"""Объектное хранилище вложений: S3 API (ADR 0004, ADR 0017 п. 10–11).

Модуль скрывает boto3: домен работает с ключами объектов, presigned URL и метаданными из HEAD.
Реализации: S3ObjectStorage (MinIO локально и в CI, провайдер staging/production — глава 26)
и FakeObjectStorage — в памяти процесса, для unit-тестов. Клиент синхронный, как и сессии
SQLAlchemy: синхронные маршруты FastAPI выполняются в пуле потоков, клиент boto3 потокобезопасен.
Ключи доступа и ключи объектов в тексты ошибок не попадают.
"""

import threading
from functools import lru_cache
from typing import Any, NamedTuple, Protocol
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings, get_settings


class StorageError(Exception):
    """Хранилище ответило ошибкой или недоступно (→ 5xx, а не ошибка клиента)."""


class StorageUnavailable(StorageError):
    """Бакет недоступен: нет связи, неверные ключи или бакета нет."""


class ObjectNotFound(StorageError):
    """Исходного объекта нет (копирование)."""


class ObjectInfo(NamedTuple):
    """Метаданные объекта из HEAD — со слов S3, а не клиента (ADR 0004)."""

    size: int
    content_type: str


class ObjectStorage(Protocol):
    def presign_put(self, key: str, ttl_seconds: int) -> str:
        """URL для загрузки клиентом (PUT); MIME к подписи не привязан (ADR 0017 п. 10)."""
        ...

    def presign_get(self, key: str, ttl_seconds: int) -> str:
        """URL для скачивания (GET); публичных ссылок нет (ADR 0004)."""
        ...

    def head(self, key: str) -> ObjectInfo | None:
        """Размер и MIME объекта; None — объекта нет."""
        ...

    def copy(self, src: str, dst: str) -> None:
        """Копия внутри бакета вместе с MIME; нет src — ObjectNotFound."""
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

    def _presign(self, operation: str, key: str, ttl_seconds: int) -> str:
        return self._presigner.generate_presigned_url(
            operation, Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=ttl_seconds
        )

    def presign_put(self, key: str, ttl_seconds: int) -> str:
        return self._presign("put_object", key, ttl_seconds)

    def presign_get(self, key: str, ttl_seconds: int) -> str:
        return self._presign("get_object", key, ttl_seconds)

    def _call(self, operation: str, **params: Any) -> dict[str, Any]:
        try:
            return getattr(self._client, operation)(Bucket=self.bucket, **params)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "NoSuchBucket":
                raise StorageUnavailable(f"S3 {operation}: {_describe(exc)}") from exc
            # У HEAD нет тела ответа: «нет объекта» и «нет бакета» различимы только по коду
            # ошибки других операций; бакет проверяется при старте (check_bucket).
            if _http_status(exc) == 404:
                raise ObjectNotFound(f"S3 {operation}: объект не найден") from exc
            raise StorageError(f"S3 {operation}: {_describe(exc)}") from exc
        except BotoCoreError as exc:
            raise StorageUnavailable(f"S3 {operation}: {_describe(exc)}") from exc

    def head(self, key: str) -> ObjectInfo | None:
        # Без права s3:ListBucket S3 отвечает на HEAD отсутствующего объекта 403, а не 404 —
        # ключам backend это право нужно (глава 26).
        try:
            response = self._call("head_object", Key=key)
        except ObjectNotFound:
            return None
        return ObjectInfo(
            size=int(response["ContentLength"]), content_type=response.get("ContentType") or ""
        )

    def copy(self, src: str, dst: str) -> None:
        # MetadataDirective=COPY (по умолчанию): MIME копии — как у оригинала.
        self._call("copy_object", Key=dst, CopySource={"Bucket": self.bucket, "Key": src})

    def delete(self, key: str) -> None:
        self._call("delete_object", Key=key)

    def check_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except (ClientError, BotoCoreError) as exc:
            raise StorageUnavailable(
                f"Бакет S3 недоступен ({_describe(exc)}): проверьте S3_ENDPOINT, S3_BUCKET, "
                "S3_ACCESS_KEY/S3_SECRET_KEY"
            ) from exc


class FakeObjectStorage:
    """Хранилище в памяти процесса — для unit-тестов домена и API.

    Загрузку клиентом по presigned PUT имитирует put(); available=False — хранилище «упало»:
    HEAD, копирование, удаление и проверка бакета отвечают StorageUnavailable.
    """

    BASE_URL = "http://fake-storage.invalid/bucket"

    def __init__(self, *, available: bool = True) -> None:
        self._lock = threading.Lock()
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.available = available

    def put(self, key: str, data: bytes, content_type: str) -> None:
        with self._lock:
            self.objects[key] = (data, content_type)

    def _ensure_available(self) -> None:
        if not self.available:
            raise StorageUnavailable("Фейковое хранилище недоступно")

    def _url(self, method: str, key: str, ttl_seconds: int) -> str:
        return f"{self.BASE_URL}/{quote(key)}?X-Fake-Method={method}&X-Fake-Expires={ttl_seconds}"

    def presign_put(self, key: str, ttl_seconds: int) -> str:
        return self._url("PUT", key, ttl_seconds)

    def presign_get(self, key: str, ttl_seconds: int) -> str:
        return self._url("GET", key, ttl_seconds)

    def head(self, key: str) -> ObjectInfo | None:
        self._ensure_available()
        with self._lock:
            stored = self.objects.get(key)
        return None if stored is None else ObjectInfo(len(stored[0]), stored[1])

    def copy(self, src: str, dst: str) -> None:
        self._ensure_available()
        with self._lock:
            if src not in self.objects:
                raise ObjectNotFound("Фейковое хранилище: объект не найден")
            self.objects[dst] = self.objects[src]

    def delete(self, key: str) -> None:
        self._ensure_available()
        with self._lock:
            self.objects.pop(key, None)

    def check_bucket(self) -> None:
        self._ensure_available()


@lru_cache
def _s3_storage() -> S3ObjectStorage:
    return S3ObjectStorage.from_settings(get_settings())


def get_storage() -> ObjectStorage:
    """Зависимость FastAPI; в тестах подменяется (FakeObjectStorage или MinIO)."""
    return _s3_storage()
