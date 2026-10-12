"""Контракт ObjectStorage — одни сценарии на хранилище в памяти и на S3 API (MinIO).

Хранилище в памяти заменяет S3 в тестах домена и API, поэтому ведёт себя так же: HEAD
отсутствующего — None, копия — ровно проверенной версии с переданным MIME, исходник не
трогается, удаление идемпотентно; удалённый или перезаписанный после HEAD исходник —
CopySourceChanged (не ошибка хранилища: → 422, а не 5xx).
"""

import uuid

import pytest

from app.core.storage import CopySourceChanged, ObjectInfo, ObjectStorage, StorageError
from tests.support.storage import put_object

PHOTO = b"\xff\xd8\xff\xe0" + bytes(range(256)) * 4


@pytest.fixture(params=["memory", "minio"])
def object_storage(request: pytest.FixtureRequest) -> ObjectStorage:
    return request.getfixturevalue("fake_storage" if request.param == "memory" else "s3_storage")


def _key(prefix: str) -> str:
    return f"{prefix}/{uuid.uuid4()}.jpg"


def test_head_of_missing_object_is_none(object_storage: ObjectStorage) -> None:
    assert object_storage.head(_key("uploads/1")) is None


def test_copy_keeps_source_and_sets_given_mime(object_storage: ObjectStorage) -> None:
    upload = _key("uploads/1")
    put_object(object_storage, upload, PHOTO, "image/jpeg")
    info = object_storage.head(upload)
    assert info is not None
    assert (info.size, info.content_type) == (len(PHOTO), "image/jpeg")

    copy = _key("tickets/9")
    object_storage.copy(upload, copy, etag=info.etag, content_type="image/png")
    # MIME копии — переданный (проверенный), а не сохранённый у исходного объекта.
    assert object_storage.head(copy) == ObjectInfo(len(PHOTO), "image/png", info.etag)
    assert object_storage.head(upload) == info, "копия, а не перенос"


def test_copy_of_missing_object_raises(object_storage: ObjectStorage) -> None:
    with pytest.raises(CopySourceChanged) as exc_info:
        object_storage.copy(
            _key("uploads/1"), _key("tickets/1"), etag='"0"', content_type="image/jpeg"
        )
    assert not isinstance(exc_info.value, StorageError)


def test_copy_of_overwritten_object_raises(object_storage: ObjectStorage) -> None:
    """Клиент перезаписал загрузку после HEAD — копируется только проверенная версия."""
    upload = _key("uploads/1")
    put_object(object_storage, upload, PHOTO, "image/jpeg")
    checked = object_storage.head(upload)
    assert checked is not None
    put_object(object_storage, upload, b"<html>" * 100, "text/html")
    copy = _key("tickets/1")
    with pytest.raises(CopySourceChanged):
        object_storage.copy(upload, copy, etag=checked.etag, content_type="image/jpeg")
    assert object_storage.head(copy) is None


def test_delete_removes_object_and_is_idempotent(object_storage: ObjectStorage) -> None:
    key = _key("uploads/1")
    put_object(object_storage, key, b"x", "image/jpeg")
    object_storage.delete(key)
    assert object_storage.head(key) is None
    object_storage.delete(key)  # повторное удаление — не ошибка
