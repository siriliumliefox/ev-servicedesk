"""Проверка перед стартом API (глава 24, ADR 0028 п. 18): fail closed при WEB_CONCURRENCY > 1."""

import pytest

from app import preflight
from app.core.config import Settings
from app.core.storage import StorageUnavailable


class _NoBucket:
    def __init__(self) -> None:
        self.checked = False

    def check_bucket(self) -> None:
        self.checked = True
        raise StorageUnavailable("Бакет S3 недоступен (HTTP 404)")


def _patch(monkeypatch: pytest.MonkeyPatch, settings: Settings, storage: _NoBucket) -> None:
    monkeypatch.setattr(preflight, "get_settings", lambda: settings)
    monkeypatch.setattr(preflight, "get_storage", lambda: storage)


def test_staging_without_bucket_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    staging = Settings(
        _env_file=None,
        environment="staging",
        jwt_secret="j" * 40,
        sms_code_secret="s" * 40,
        s3_endpoint="http://minio:9000",
        s3_bucket="b",
        s3_access_key="key",
        s3_secret_key="secret",
    )
    storage = _NoBucket()
    _patch(monkeypatch, staging, storage)
    with pytest.raises(StorageUnavailable, match="HTTP 404"):
        preflight.main()
    assert storage.checked


def test_local_and_test_do_not_need_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = _NoBucket()
    _patch(monkeypatch, Settings(_env_file=None, environment="test"), storage)
    assert preflight.main() == 0
    assert not storage.checked
