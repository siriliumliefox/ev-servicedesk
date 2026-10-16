"""Объектное хранилище вложений: S3 API (ADR 0004, ADR 0017 п. 10–11).

Модуль скрывает boto3: домен работает с ключами объектов, presigned URL и метаданными из HEAD.
Реализация — S3ObjectStorage (MinIO локально и в CI, провайдер staging/production — глава 26);
тестовый двойник в памяти — в tests/. Клиент синхронный, как и сессии SQLAlchemy: синхронные
маршруты FastAPI выполняются в пуле потоков, клиент boto3 потокобезопасен.
Ключи доступа и ключи объектов в тексты ошибок и цепочку их причин не попадают.
"""

from collections.abc import Callable
from functools import lru_cache
from typing import Any, NamedTuple, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import SAFE_ENVIRONMENTS, Settings, get_settings


class StorageError(Exception):
    """Хранилище ответило ошибкой или недоступно (→ 5xx, а не ошибка клиента)."""


class StorageUnavailable(StorageError):
    """Бакет недоступен: нет связи, неверные ключи или бакета нет."""


class CopySourceChanged(Exception):
    """Проверенной версии src больше нет (удалён или перезаписан после HEAD) — копии нет.

    Не StorageError: причина — действия клиента с загрузкой, а не сбой хранилища.
    """


class ObjectInfo(NamedTuple):
    """Метаданные объекта из HEAD — со слов S3, а не клиента (ADR 0004).

    etag — версия содержимого: копируется ровно проверенная версия (`ObjectStorage.copy`).
    """

    size: int
    content_type: str
    etag: str


class ObjectStorage(Protocol):
    def presign_put(self, key: str, ttl_seconds: int) -> str:
        """URL для загрузки клиентом (PUT); MIME к подписи не привязан (ADR 0017 п. 10)."""
        ...

    def presign_get(self, key: str, ttl_seconds: int, *, content_type: str) -> str:
        """URL для скачивания (GET); публичных ссылок нет (ADR 0004).

        content_type — Content-Type ответа по подписи (проверенный MIME), а не сохранённый
        у объекта.
        """
        ...

    def head(self, key: str) -> ObjectInfo | None:
        """Размер, MIME и ETag объекта; None — объекта нет."""
        ...

    def copy(self, src: str, dst: str, *, etag: str, content_type: str) -> None:
        """Копия внутри бакета версии `etag` объекта src с MIME `content_type`.

        Нет src или он перезаписан после HEAD — CopySourceChanged: между проверкой и
        копированием клиент мог удалить загрузку или загрузить в тот же ключ другой файл.
        """
        ...

    def delete(self, key: str) -> None:
        """Удаление; отсутствующий ключ — не ошибка."""
        ...

    def check_bucket(self) -> None:
        """Бакет доступен с текущими ключами, иначе StorageUnavailable (проверка при старте)."""
        ...


# Path-style (http://host/bucket/key): MinIO без настройки доменов поддерживает только его.
# Контрольные суммы — только когда их требует операция: новые CRC по умолчанию в botocore
# поддерживают не все S3-совместимые хранилища.
_BOTO_CONFIG = Config(
    signature_version="s3v4",
    s3={"addressing_style": "path"},
    connect_timeout=3,
    read_timeout=30,
    retries={"max_attempts": 3, "mode": "standard"},
    request_checksum_calculation="when_required",
    response_checksum_validation="when_required",
)


class _Missing(StorageError):
    """Ответ 404 на операцию с объектом: HEAD переводит его в None, копирование — в
    CopySourceChanged; у удаления (S3 отвечает 204) — обычная ошибка хранилища."""


def _http_status(exc: ClientError) -> int | None:
    return exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")


def _describe(exc: Exception) -> str:
    """Код ошибки без деталей запроса (в них бывают ключ объекта и адрес)."""
    if isinstance(exc, ClientError):
        status = str(_http_status(exc))
        code = exc.response.get("Error", {}).get("Code") or status
        # У HEAD нет тела: кодом ошибки boto3 подставляет сам HTTP-статус.
        return f"HTTP {status}" if code == status else f"HTTP {status}, {code}"
    return type(exc).__name__


class S3ObjectStorage:
    """S3 через boto3. Операции идут на endpoint, presigned URL подписываются для public_endpoint.

    Подпись SigV4 включает хост: URL, подписанный для внутреннего адреса (http://minio:9000),
    по публичному адресу не примется. Подпись presigned URL выполняется локально, без запроса в S3.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str,
        public_endpoint: str = "",
    ) -> None:
        self.bucket = bucket
        session = boto3.Session(
            aws_access_key_id=access_key, aws_secret_access_key=secret_key, region_name=region
        )
        self._client = session.client("s3", endpoint_url=endpoint, config=_BOTO_CONFIG)
        self._presigner = session.client(
            "s3", endpoint_url=public_endpoint or endpoint, config=_BOTO_CONFIG
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "S3ObjectStorage":
        return cls(
            endpoint=settings.s3_endpoint,
            public_endpoint=settings.s3_public_endpoint,
            bucket=settings.s3_bucket,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            region=settings.s3_region,
        )

    def _presign(self, operation: str, key: str, ttl_seconds: int, **params: str) -> str:
        return self._presigner.generate_presigned_url(
            operation,
            Params={"Bucket": self.bucket, "Key": key, **params},
            ExpiresIn=ttl_seconds,
        )

    def presign_put(self, key: str, ttl_seconds: int) -> str:
        return self._presign("put_object", key, ttl_seconds)

    def presign_get(self, key: str, ttl_seconds: int, *, content_type: str) -> str:
        # response-content-type входит в подпись: заменить его в URL нельзя.
        return self._presign("get_object", key, ttl_seconds, ResponseContentType=content_type)

    def _call(self, operation: str, **params: Any) -> dict[str, Any]:
        # Исключения boto3 — `from None`: в их тексте URL запроса с ключом объекта, а цепочка
        # причин попала бы в трассировку журнала (обработчик 500). Остаётся код ошибки.
        try:
            return getattr(self._client, operation)(Bucket=self.bucket, **params)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "NoSuchBucket":
                raise StorageUnavailable(f"S3 {operation}: {_describe(exc)}") from None
            # У HEAD нет тела ответа: «нет объекта» и «нет бакета» различимы только по коду
            # ошибки других операций; бакет проверяется при старте (check_bucket).
            if _http_status(exc) == 404:
                raise _Missing(f"S3 {operation}: объект не найден") from None
            if _http_status(exc) == 412:  # CopySourceIfMatch не выполнен
                raise CopySourceChanged(f"S3 {operation}: объект изменён") from None
            raise StorageError(f"S3 {operation}: {_describe(exc)}") from None
        except BotoCoreError as exc:
            raise StorageUnavailable(f"S3 {operation}: {_describe(exc)}") from None

    def head(self, key: str) -> ObjectInfo | None:
        # Без права s3:ListBucket S3 отвечает на HEAD отсутствующего объекта 403, а не 404 —
        # ключам backend это право нужно (глава 26).
        try:
            response = self._call("head_object", Key=key)
        except _Missing:
            return None
        return ObjectInfo(
            size=int(response["ContentLength"]),
            content_type=response.get("ContentType") or "",
            etag=response.get("ETag") or "",
        )

    def copy(self, src: str, dst: str, *, etag: str, content_type: str) -> None:
        # CopySourceIfMatch: S3 копирует только версию с этим ETag, иначе 412.
        # MetadataDirective=REPLACE: MIME копии — проверенный, а не тот, что прислал клиент.
        try:
            self._call(
                "copy_object",
                Key=dst,
                CopySource={"Bucket": self.bucket, "Key": src},
                CopySourceIfMatch=etag,
                MetadataDirective="REPLACE",
                ContentType=content_type,
            )
        except _Missing:
            raise CopySourceChanged("S3 copy_object: объект не найден") from None

    def delete(self, key: str) -> None:
        self._call("delete_object", Key=key)

    def check_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except (ClientError, BotoCoreError) as exc:
            raise StorageUnavailable(
                f"Бакет S3 недоступен ({_describe(exc)}): проверьте S3_ENDPOINT, S3_BUCKET, "
                "S3_ACCESS_KEY/S3_SECRET_KEY"
            ) from None


@lru_cache
def _s3_storage() -> S3ObjectStorage:
    return S3ObjectStorage.from_settings(get_settings())


def get_storage() -> ObjectStorage:
    """Зависимость FastAPI; в тестах подменяется (хранилище в памяти или MinIO)."""
    return _s3_storage()


def require_bucket(settings: Settings, storage: Callable[[], ObjectStorage]) -> None:
    """Вне local/test без доступного бакета приложение не стартует (ADR 0017 п. 11);
    local/test S3 не требуют. Хранилище создаётся только когда нужно (`storage` — фабрика).
    Вызывают: `app.preflight` до запуска uvicorn и lifespan каждого процесса."""
    if settings.environment not in SAFE_ENVIRONMENTS:
        storage().check_bucket()
