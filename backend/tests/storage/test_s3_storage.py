"""S3ObjectStorage на настоящем S3 API — MinIO (Глава 13, ADR 0004, ADR 0017 п. 10–11).

Путь вложения: presigned PUT → загрузка клиентом → HEAD (размер и MIME — со слов S3) →
копия в хранилище тикета → presigned GET → те же байты. Общий с хранилищем в памяти
контракт — test_object_storage_contract.py; здесь — только особенности S3.
"""

import uuid
from urllib.parse import urlsplit, urlunsplit

import httpx
import pytest

from app.core.storage import CopySourceChanged, ObjectInfo, S3ObjectStorage, StorageUnavailable

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

    info = s3_storage.head(upload)
    assert info == ObjectInfo(size=len(PHOTO), content_type="image/jpeg", etag=info.etag)
    assert info.etag.startswith('"') and len(info.etag) > 2

    attachment = _key("tickets/7")
    s3_storage.copy(upload, attachment, etag=info.etag, content_type="image/jpeg")
    assert s3_storage.head(attachment) == ObjectInfo(len(PHOTO), "image/jpeg", info.etag)

    r = httpx.get(s3_storage.presign_get(attachment, TTL, content_type="image/jpeg"))
    assert r.status_code == 200
    assert r.content == PHOTO
    assert r.headers["content-type"] == "image/jpeg"


def test_copy_pins_checked_version_and_mime(s3_storage: S3ObjectStorage) -> None:
    """Клиент перезаписал загрузку после HEAD тем же presigned PUT — копии нет (412).

    MIME копии — переданный (проверенный), presigned GET отдаёт его же, а не сохранённый.
    """
    upload = _key("uploads/1")
    url = s3_storage.presign_put(upload, TTL)
    assert httpx.put(url, content=PHOTO, headers={"Content-Type": "image/jpeg"}).is_success
    checked = s3_storage.head(upload)
    assert checked is not None

    html = b"<html><script>alert(1)</script></html>" * 100
    assert httpx.put(url, content=html, headers={"Content-Type": "text/html"}).is_success
    swapped = _key("tickets/7")
    with pytest.raises(CopySourceChanged) as exc_info:
        s3_storage.copy(upload, swapped, etag=checked.etag, content_type="image/jpeg")
    assert exc_info.value.__cause__ is None and exc_info.value.__suppress_context__
    assert s3_storage.head(swapped) is None

    current = s3_storage.head(upload)
    assert current is not None and current.content_type == "text/html"
    copied = _key("tickets/7")
    s3_storage.copy(upload, copied, etag=current.etag, content_type="image/png")
    assert s3_storage.head(copied) == ObjectInfo(len(html), "image/png", current.etag)
    r = httpx.get(s3_storage.presign_get(copied, TTL, content_type="image/png"))
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_mime_is_not_bound_to_signature(s3_storage: S3ObjectStorage) -> None:
    """MIME к подписи не привязан (ADR 0017 п. 10): его сообщает HEAD, а проверяет домен."""
    key = _key("uploads/1", ".mov")
    url = s3_storage.presign_put(key, TTL)
    assert httpx.put(url, content=b"video", headers={"Content-Type": "video/quicktime"}).is_success
    info = s3_storage.head(key)
    assert info is not None and (info.size, info.content_type) == (5, "video/quicktime")


def test_copy_missing_object_raises(s3_storage: S3ObjectStorage) -> None:
    with pytest.raises(CopySourceChanged) as exc_info:
        s3_storage.copy(_key("uploads/1"), _key("tickets/1"), etag='"0"', content_type="image/jpeg")
    # Причина (ClientError с ключом объекта в тексте) не попадает в трассировку журнала.
    assert exc_info.value.__cause__ is None and exc_info.value.__suppress_context__


def test_presigned_get_of_missing_object_is_404(s3_storage: S3ObjectStorage) -> None:
    url = s3_storage.presign_get(_key("tickets/1"), TTL, content_type="image/jpeg")
    assert httpx.get(url).status_code == 404


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
    assert httpx.get(storage.presign_get(key, TTL, content_type="image/jpeg")).content == b"x"

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
    assert exc_info.value.__cause__ is None and exc_info.value.__suppress_context__


def test_check_bucket_missing_bucket(
    s3_session: S3ObjectStorage, s3_config: dict[str, str]
) -> None:
    storage = S3ObjectStorage(**(s3_config | {"bucket": f"missing-{uuid.uuid4().hex[:12]}-test"}))
    with pytest.raises(StorageUnavailable, match="404"):
        storage.check_bucket()
