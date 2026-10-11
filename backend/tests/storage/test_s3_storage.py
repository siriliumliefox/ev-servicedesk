"""S3ObjectStorage на настоящем S3 API — MinIO (Глава 13, ADR 0004, ADR 0017 п. 10–11).

Путь вложения: presigned PUT → загрузка клиентом → HEAD (размер и MIME — со слов S3) →
копия в хранилище тикета → presigned GET → те же байты.
"""

import uuid
from urllib.parse import urlsplit, urlunsplit

import httpx
import pytest

from app.core.storage import ObjectInfo, ObjectNotFound, S3ObjectStorage, StorageUnavailable

TTL = 15 * 60
PHOTO = b"\xff\xd8\xff\xe0" + bytes(range(256)) * 64  # «JPEG» 16 КБ


def _key(prefix: str, ext: str = ".jpg") -> str:
    return f"{prefix}/{uuid.uuid4()}{ext}"


def test_presigned_upload_head_copy_download(s3_storage: S3ObjectStorage) -> None:
    upload = _key("uploads/1")
    r = httpx.put(
        s3_storage.presign_put(upload, TTL), content=PHOTO, headers={"Content-Type": "image/jpeg"}
    )
    assert r.status_code == 200, r.text

    assert s3_storage.head(upload) == ObjectInfo(size=len(PHOTO), content_type="image/jpeg")

    attachment = _key("tickets/7")
    s3_storage.copy(upload, attachment)
    assert s3_storage.head(attachment) == ObjectInfo(len(PHOTO), "image/jpeg")

    r = httpx.get(s3_storage.presign_get(attachment, TTL))
    assert r.status_code == 200
    assert r.content == PHOTO
    assert r.headers["content-type"] == "image/jpeg"


def test_mime_is_not_bound_to_signature(s3_storage: S3ObjectStorage) -> None:
    """MIME к подписи не привязан (ADR 0017 п. 10): его сообщает HEAD, а проверяет домен."""
    key = _key("uploads/1", ".mov")
    url = s3_storage.presign_put(key, TTL)
    assert httpx.put(url, content=b"video", headers={"Content-Type": "video/quicktime"}).is_success
    assert s3_storage.head(key) == ObjectInfo(5, "video/quicktime")


def test_head_missing_object_is_none(s3_storage: S3ObjectStorage) -> None:
    assert s3_storage.head(_key("uploads/1")) is None


def test_copy_missing_object_raises(s3_storage: S3ObjectStorage) -> None:
    with pytest.raises(ObjectNotFound):
        s3_storage.copy(_key("uploads/1"), _key("tickets/1"))


def test_delete_removes_object_and_is_idempotent(s3_storage: S3ObjectStorage) -> None:
    key = _key("uploads/1")
    assert httpx.put(s3_storage.presign_put(key, TTL), content=b"x").is_success
    s3_storage.delete(key)
    assert s3_storage.head(key) is None
    s3_storage.delete(key)


def test_presigned_get_of_missing_object_is_404(s3_storage: S3ObjectStorage) -> None:
    assert httpx.get(s3_storage.presign_get(_key("tickets/1"), TTL)).status_code == 404


def test_tampered_presigned_url_is_rejected(s3_storage: S3ObjectStorage) -> None:
    """Подпись покрывает ключ: по URL на один объект нельзя загрузить другой."""
    key = _key("uploads/1")
    url = s3_storage.presign_put(key, TTL).replace(key, _key("uploads/2"))
    assert httpx.put(url, content=b"x").status_code == 403


def _swap_loopback(endpoint: str) -> str:
    """Тот же сервер под другим именем хоста: localhost ↔ 127.0.0.1."""
    parts = urlsplit(endpoint)
    other = "127.0.0.1" if parts.hostname == "localhost" else "localhost"
    netloc = other + (f":{parts.port}" if parts.port else "")
    return urlunsplit(parts._replace(netloc=netloc))


def test_presigned_urls_are_signed_for_public_endpoint(
    s3_storage: S3ObjectStorage, s3_config: dict[str, str]
) -> None:
    """Операции — на endpoint, presigned URL — на public_endpoint; подпись включает хост."""
    host = urlsplit(s3_config["endpoint"]).hostname
    if host not in ("localhost", "127.0.0.1"):
        pytest.skip("Нужен MinIO на loopback: тот же сервер доступен под двумя именами")
    public = _swap_loopback(s3_config["endpoint"])
    storage = S3ObjectStorage(**s3_config, public_endpoint=public)
    key = _key("uploads/1")

    url = storage.presign_put(key, TTL)
    assert urlsplit(url).netloc == urlsplit(public).netloc
    assert httpx.put(url, content=b"x").is_success
    info = storage.head(key)  # HEAD — по внутреннему адресу
    assert info is not None and info.size == 1
    assert httpx.get(storage.presign_get(key, TTL)).content == b"x"

    # Тот же URL с внутренним хостом не принимается: подпись привязана к хосту.
    internal_url = url.replace(urlsplit(public).netloc, urlsplit(s3_config["endpoint"]).netloc, 1)
    assert httpx.put(internal_url, content=b"y").status_code == 403


def test_check_bucket_ok(s3_storage: S3ObjectStorage) -> None:
    s3_storage.check_bucket()


def test_check_bucket_wrong_credentials(
    s3_session: S3ObjectStorage, s3_config: dict[str, str]
) -> None:
    secret = "wrong-secret-" + uuid.uuid4().hex
    storage = S3ObjectStorage(**(s3_config | {"secret_key": secret}))
    with pytest.raises(StorageUnavailable) as exc_info:
        storage.check_bucket()
    assert secret not in str(exc_info.value)
    assert "403" in str(exc_info.value)


def test_check_bucket_missing_bucket(
    s3_session: S3ObjectStorage, s3_config: dict[str, str]
) -> None:
    storage = S3ObjectStorage(**(s3_config | {"bucket": f"missing-{uuid.uuid4().hex[:12]}-test"}))
    with pytest.raises(StorageUnavailable, match="404"):
        storage.check_bucket()
