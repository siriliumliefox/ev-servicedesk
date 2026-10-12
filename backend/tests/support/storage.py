"""Хранилище вложений в памяти процесса — двойник ObjectStorage для тестов (ADR 0017 п. 10).

Контракт с S3ObjectStorage общий: tests/storage/test_object_storage_contract.py прогоняет
одни и те же сценарии на обоих.
"""

import hashlib
import threading
import urllib.request
from urllib.parse import quote

from app.core.config import Settings
from app.core.storage import CopySourceChanged, ObjectInfo, ObjectStorage, StorageUnavailable

PUT_TTL_SECONDS: int = Settings.model_fields["presign_put_ttl_seconds"].default


class FakeObjectStorage:
    """Хранилище в памяти процесса — для тестов домена и API.

    Загрузку клиентом по presigned PUT имитирует put(); available=False — хранилище «упало»:
    HEAD, копирование, удаление и проверка бакета отвечают StorageUnavailable. ETag — MD5
    содержимого в кавычках, как у S3 для загрузки одним PUT.
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

    def presign_get(self, key: str, ttl_seconds: int, *, content_type: str) -> str:
        url = self._url("GET", key, ttl_seconds)
        return f"{url}&X-Fake-Content-Type={quote(content_type, safe='')}"

    @staticmethod
    def etag(data: bytes) -> str:
        return f'"{hashlib.md5(data, usedforsecurity=False).hexdigest()}"'

    def head(self, key: str) -> ObjectInfo | None:
        self._ensure_available()
        with self._lock:
            stored = self.objects.get(key)
        if stored is None:
            return None
        return ObjectInfo(len(stored[0]), stored[1], self.etag(stored[0]))

    def copy(self, src: str, dst: str, *, etag: str, content_type: str) -> None:
        self._ensure_available()
        with self._lock:
            stored = self.objects.get(src)
            if stored is None:
                raise CopySourceChanged("Фейковое хранилище: объект не найден")
            if self.etag(stored[0]) != etag:
                raise CopySourceChanged("Фейковое хранилище: объект изменён")
            self.objects[dst] = (stored[0], content_type)

    def delete(self, key: str) -> None:
        self._ensure_available()
        with self._lock:
            self.objects.pop(key, None)

    def check_bucket(self) -> None:
        self._ensure_available()


def put_object(
    storage: ObjectStorage,
    key: str,
    data: bytes,
    content_type: str,
    upload_url: str | None = None,
) -> None:
    """Загрузка клиентом по presigned PUT: в памяти — put(), в S3 — PUT по URL.

    upload_url — URL, выданный API (createPresignedUpload); без него — подписанный здесь.
    """
    if isinstance(storage, FakeObjectStorage):
        storage.put(key, data, content_type)
        return
    url = upload_url or storage.presign_put(key, PUT_TTL_SECONDS)
    # urllib, а не httpx: httpx сам пишет URL запроса (с ключом) в лог — это лог теста.
    request = urllib.request.Request(
        url, data=data, method="PUT", headers={"Content-Type": content_type}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 200
