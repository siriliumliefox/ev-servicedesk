"""FakeObjectStorage — тот же контракт ObjectStorage, что и у S3 (unit, без сети)."""

import pytest

from app.core.storage import (
    FakeObjectStorage,
    ObjectChanged,
    ObjectInfo,
    ObjectNotFound,
    ObjectStorage,
    StorageUnavailable,
)

JPEG_ETAG = '"ab4f3ccba74857c5f2ba0d5b7dbf65e1"'  # MD5 b"jpeg" — как ETag S3 для одного PUT


def test_put_head_copy_delete(fake_storage: FakeObjectStorage) -> None:
    storage: ObjectStorage = fake_storage
    assert storage.head("uploads/1/a.jpg") is None

    fake_storage.put("uploads/1/a.jpg", b"jpeg", "image/jpeg")  # загрузка клиентом
    info = storage.head("uploads/1/a.jpg")
    assert info == ObjectInfo(size=4, content_type="image/jpeg", etag=JPEG_ETAG)

    # MIME копии — переданный (проверенный), а не сохранённый у исходного объекта.
    storage.copy("uploads/1/a.jpg", "tickets/9/a.jpg", etag=info.etag, content_type="image/png")
    assert storage.head("tickets/9/a.jpg") == ObjectInfo(4, "image/png", JPEG_ETAG)
    assert storage.head("uploads/1/a.jpg") == info  # копия, а не перенос

    storage.delete("tickets/9/a.jpg")
    assert storage.head("tickets/9/a.jpg") is None
    storage.delete("tickets/9/a.jpg")  # повторное удаление — не ошибка


def test_copy_missing_object_raises(fake_storage: FakeObjectStorage) -> None:
    with pytest.raises(ObjectNotFound):
        fake_storage.copy(
            "uploads/1/none.jpg", "tickets/1/none.jpg", etag=JPEG_ETAG, content_type="image/jpeg"
        )


def test_copy_of_overwritten_object_raises(fake_storage: FakeObjectStorage) -> None:
    """Клиент перезаписал загрузку после HEAD — копируется только проверенная версия."""
    fake_storage.put("uploads/1/a.jpg", b"jpeg", "image/jpeg")
    checked = fake_storage.head("uploads/1/a.jpg")
    fake_storage.put("uploads/1/a.jpg", b"<html>" * 100, "text/html")
    with pytest.raises(ObjectChanged):
        fake_storage.copy(
            "uploads/1/a.jpg", "tickets/1/a.jpg", etag=checked.etag, content_type="image/jpeg"
        )
    assert fake_storage.head("tickets/1/a.jpg") is None


def test_presigned_urls_carry_key_method_and_ttl(fake_storage: FakeObjectStorage) -> None:
    put_url = fake_storage.presign_put("uploads/1/a b.jpg", 900)
    get_url = fake_storage.presign_get("tickets/2/c.mp4", 60, content_type="video/mp4")
    assert put_url.startswith(FakeObjectStorage.BASE_URL + "/uploads/1/a%20b.jpg?")
    assert "X-Fake-Method=PUT" in put_url and "X-Fake-Expires=900" in put_url
    assert "/tickets/2/c.mp4?" in get_url and "X-Fake-Method=GET" in get_url
    assert "X-Fake-Content-Type=video%2Fmp4" in get_url
    fake_storage.check_bucket()


def test_unavailable_storage_fails_network_operations() -> None:
    storage = FakeObjectStorage(available=False)
    storage.put("uploads/1/a.jpg", b"x", "image/jpeg")
    # presigned URL подписываются локально, без запроса в S3 — как у S3ObjectStorage.
    assert storage.presign_put("uploads/1/b.jpg", 900)
    for call in (
        storage.check_bucket,
        lambda: storage.head("uploads/1/a.jpg"),
        lambda: storage.copy("uploads/1/a.jpg", "tickets/1/a.jpg", etag="", content_type=""),
        lambda: storage.delete("uploads/1/a.jpg"),
    ):
        with pytest.raises(StorageUnavailable):
            call()
