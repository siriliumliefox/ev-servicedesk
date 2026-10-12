"""Хранилище в памяти: только его особенности (URL, «упавшее» хранилище).

Общий с S3 контракт ObjectStorage — test_object_storage_contract.py.
"""

import pytest

from app.core.storage import StorageUnavailable
from tests.support.storage import FakeObjectStorage


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
