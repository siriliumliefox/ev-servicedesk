"""Настройки S3 и проверка бакета при старте: вне local/test — fail closed (ADR 0017 п. 11)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import DEFAULT_S3_ACCESS_KEY, DEFAULT_S3_SECRET_KEY, Settings
from app.core.storage import ObjectStorage, S3ObjectStorage, StorageUnavailable, get_storage
from app.main import create_app
from tests.support.storage import FakeObjectStorage

STRONG = "z" * 40
S3_REAL = {"s3_access_key": "staging-access-key", "s3_secret_key": "staging-secret-" + "k" * 24}


def _settings(environment: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": environment,
        "jwt_secret": STRONG,
        "sms_code_secret": STRONG,
        "sms_provider": "a1",
        "sms_provider_user": "375290000000",
        "sms_provider_api_key": "k",
        # В production фейковый push запрещён (ADR 0019); ключ разбирает worker при старте.
        "push_provider": "fcm",
        "fcm_service_account_json": "{}",
    }
    return Settings(_env_file=None, **(values | overrides))


@pytest.mark.parametrize(
    "s3",
    [
        {},  # заглушки local из docker-compose.yml
        {"s3_access_key": "", "s3_secret_key": ""},
        {"s3_access_key": "real-key", "s3_secret_key": DEFAULT_S3_SECRET_KEY},
        {"s3_access_key": DEFAULT_S3_ACCESS_KEY, "s3_secret_key": "real-secret-" + "s" * 20},
    ],
    ids=["defaults", "empty", "default-secret", "default-access-key"],
)
@pytest.mark.parametrize("environment", ["staging", "production"])
def test_real_environment_requires_s3_credentials(environment: str, s3: dict) -> None:
    with pytest.raises(ValidationError, match="S3_ACCESS_KEY/S3_SECRET_KEY") as exc_info:
        _settings(environment, **s3)
    for value in s3.values():
        if value:
            assert value not in str(exc_info.value)


@pytest.mark.parametrize("empty", ["s3_bucket", "s3_endpoint"])
def test_real_environment_requires_bucket_and_endpoint(empty: str) -> None:
    with pytest.raises(ValidationError, match="S3_ENDPOINT/S3_BUCKET"):
        _settings("staging", **S3_REAL, **{empty: ""})


def test_real_environment_with_s3_credentials_ok() -> None:
    settings = _settings("production", **S3_REAL)
    assert settings.s3_access_key == S3_REAL["s3_access_key"]


@pytest.mark.parametrize("environment", ["local", "test"])
def test_safe_environments_do_not_require_s3(environment: str) -> None:
    settings = Settings(_env_file=None, environment=environment, s3_access_key="", s3_bucket="")
    assert settings.s3_bucket == ""


def test_ticket_settings_defaults() -> None:
    """Значения ADR 0017 п. 7–10 — их читает Tickets Service."""
    s = Settings(_env_file=None, environment="test")
    assert (
        s.ticket_create_per_user_hour,
        s.ticket_message_per_user_minute,
        s.upload_presign_per_user_hour,
    ) == (10, 30, 60)
    assert s.presign_put_ttl_seconds == s.presign_get_ttl_seconds == 15 * 60
    assert s.max_attachments == 10
    assert s.attachment_photo_max_bytes == 20 * 1024 * 1024
    assert s.attachment_video_max_bytes == 200 * 1024 * 1024
    assert s.attachment_photo_mime_types == ("image/jpeg", "image/png", "image/heic", "image/webp")
    assert s.attachment_video_mime_types == ("video/mp4", "video/quicktime")
    assert s.ws_auth_timeout_seconds == 5


def test_s3_storage_built_from_settings_without_network() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        s3_endpoint="http://minio:9000",
        s3_public_endpoint="https://files.example.test",
        s3_bucket="b-test",
    )
    storage = S3ObjectStorage.from_settings(settings)
    url = storage.presign_put("uploads/1/a.jpg", 900)
    assert url.startswith("https://files.example.test/b-test/uploads/1/a.jpg?")
    assert "X-Amz-Expires=900" in url and "X-Amz-Signature=" in url


def test_unreachable_endpoint_is_unavailable() -> None:
    storage = S3ObjectStorage(
        endpoint="http://127.0.0.1:9",
        bucket="b-test",
        access_key="a",
        secret_key="s" * 8,
        region="us-east-1",
    )
    with pytest.raises(StorageUnavailable, match="S3_ENDPOINT"):
        storage.check_bucket()


# --- Старт приложения ------------------------------------------------------------------------


def _start(settings: Settings, storage: ObjectStorage) -> TestClient:
    app = create_app(settings)
    app.dependency_overrides[get_storage] = lambda: storage
    return TestClient(app)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_startup_refused_without_bucket(environment: str) -> None:
    with (
        pytest.raises(StorageUnavailable),
        _start(_settings(environment, **S3_REAL), FakeObjectStorage(available=False)),
    ):
        pass


def test_startup_with_available_bucket() -> None:
    with _start(_settings("staging", **S3_REAL), FakeObjectStorage()) as client:
        assert client.get("/health").json()["environment"] == "staging"


@pytest.mark.parametrize("environment", ["local", "test"])
def test_safe_environments_start_without_s3(environment: str) -> None:
    settings = Settings(_env_file=None, environment=environment)
    with _start(settings, FakeObjectStorage(available=False)) as client:
        assert client.get("/health").status_code == 200


def test_startup_against_real_bucket(s3_session: S3ObjectStorage) -> None:
    with _start(_settings("staging", **S3_REAL), s3_session) as client:
        assert client.get("/health").status_code == 200
