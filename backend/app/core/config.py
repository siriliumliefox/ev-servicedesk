from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Значения-заглушки из .env.example: в staging/production с ними приложение не стартует.
DEFAULT_JWT_SECRET = "change-me-in-every-real-environment"
DEFAULT_SMS_CODE_SECRET = "change-me-sms-code-secret"
# Учётные данные MinIO из docker-compose.yml (только local): известны всем, кто видит репозиторий.
DEFAULT_S3_ACCESS_KEY = "ev_local"
DEFAULT_S3_SECRET_KEY = "ev_local_only"
SAFE_ENVIRONMENTS = {"local", "test"}


class Settings(BaseSettings):
    """Настройки приложения — читаются из переменных окружения (см. .env.example, Глава 4 шаг 3)."""

    # Корневой .env (запуск из backend/) и локальный; переменные окружения важнее файлов.
    # hide_input_in_errors: ошибка валидации не печатает значения (секреты) в лог старта.
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"), extra="ignore", hide_input_in_errors=True
    )

    # Опечатка («prod») — ошибка старта, а не тихий local. Образ задаёт production (Dockerfile).
    environment: Literal["local", "test", "staging", "production"] = "local"
    database_url: str = "postgresql+psycopg://ev:ev@localhost:5432/ev_servicedesk"
    redis_url: str = "redis://localhost:6379/0"

    # --- JWT (Глава 10, ADR 0013) ---
    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_issuer: str = "ev-servicedesk"
    jwt_audience: str = "ev-servicedesk-api"
    access_token_ttl_seconds: int = Field(15 * 60, ge=60, le=24 * 3600)
    refresh_token_ttl_days: int = Field(30, ge=1, le=365)

    # --- SMS-код (ADR 0005, 0013): в Redis только HMAC-SHA256(код, SMS_CODE_SECRET) ---
    sms_code_secret: str = DEFAULT_SMS_CODE_SECRET
    sms_code_length: int = Field(4, ge=4, le=8)  # как в VerifyCodeRequest.code
    sms_code_ttl_seconds: int = Field(120, ge=30, le=900)
    sms_code_max_attempts: int = Field(5, ge=1, le=10)

    # --- Rate limiting (N-06) ---
    sms_resend_cooldown_seconds: int = Field(60, ge=1)
    sms_requests_per_phone_hour: int = Field(5, ge=1)
    sms_requests_per_ip_hour: int = Field(30, ge=1)
    verify_failures_per_phone_day: int = Field(20, ge=1)
    staff_login_failures_per_phone_15min: int = Field(5, ge=1)
    staff_login_failures_per_ip_15min: int = Field(20, ge=1)
    # Попытки POST /vehicles: 409 отвечает «VIN уже зарегистрирован» — защита от перебора VIN
    # (ПД, ADR 0005, ADR 0014).
    vehicle_create_per_user_hour: int = Field(10, ge=1)

    # --- SMS-провайдер: fake (local/test) | a1 (A1 Smart-рассылка) ---
    sms_provider: Literal["fake", "a1"] = "fake"
    sms_provider_user: str = ""
    sms_provider_api_key: str = ""
    sms_sender: str = Field("", max_length=11)  # альфа-имя A1 — до 11 символов
    sms_provider_url: str = "https://smart-sender.a1.by/api"
    sms_provider_rps: float = Field(10.0, gt=0, le=10)  # лимит A1 — 10 запросов/с

    # --- Объектное хранилище S3 (Глава 13, ADR 0004, ADR 0017 п. 10–11) ---
    # Локально и в CI — MinIO; провайдер staging/production — глава 26.
    s3_endpoint: str = "http://localhost:9000"  # адрес, по которому S3 видит backend
    # Адрес для клиентов: подпись presigned URL включает хост, поэтому URL подписываются для
    # публичного адреса (backend в docker compose ходит в http://minio:9000, а телефон и браузер —
    # нет). Пусто — совпадает с s3_endpoint.
    s3_public_endpoint: str = ""
    s3_region: str = "us-east-1"
    s3_bucket: str = "ev-servicedesk-local"
    s3_access_key: str = DEFAULT_S3_ACCESS_KEY
    s3_secret_key: str = DEFAULT_S3_SECRET_KEY

    # --- Tickets и вложения (Глава 13, ADR 0017 п. 7–10) ---
    ticket_create_per_user_hour: int = Field(10, ge=1)
    ticket_message_per_user_minute: int = Field(30, ge=1)
    upload_presign_per_user_hour: int = Field(60, ge=1)
    # Срок presigned URL: PUT — загрузка клиентом, GET — file_url вложения при чтении.
    # Подпись SigV4 действует не дольше 7 суток.
    presign_put_ttl_seconds: int = Field(15 * 60, ge=60, le=7 * 24 * 3600)
    presign_get_ttl_seconds: int = Field(15 * 60, ge=60, le=7 * 24 * 3600)
    max_attachments: int = Field(10, ge=1)  # на тикет или сообщение
    attachment_photo_max_bytes: int = Field(20 * 1024 * 1024, ge=1)
    attachment_video_max_bytes: int = Field(200 * 1024 * 1024, ge=1)
    # MIME сверяется с ответом HEAD из S3, а не со словами клиента (ADR 0004).
    attachment_photo_mime_types: tuple[str, ...] = (
        "image/jpeg",
        "image/png",
        "image/heic",
        "image/webp",
    )
    attachment_video_mime_types: tuple[str, ...] = ("video/mp4", "video/quicktime")
    # WebSocket чата: первое сообщение {"type": "auth"} — не позже, иначе закрытие 4401.
    ws_auth_timeout_seconds: float = Field(5, gt=0, le=60)

    # --- WebSocket событий тикета (ADR 0017 п. 9, docs/asyncapi.yaml) ---
    # Каналы Redis pub/sub не зависят от номера БД Redis: стенды на одном сервере Redis
    # разделяются префиксом каналов. Пусто — `ev-servicedesk:<environment>`.
    redis_channel_prefix: str = ""
    # Подключения процесса к Redis pub/sub — одно общее соединение (app.core.pubsub.PubSubHub).
    # Тишина дольше интервала — PING; нет ответа за тот же срок — связь потеряна, подключения
    # закрываются 1011 (клиент переподключается и догружает пропущенное).
    redis_pubsub_ping_seconds: float = Field(10, gt=0, le=60)
    # Кадров в очереди одного подключения; не успевающий получатель закрывается 1013.
    ws_event_queue_size: int = Field(100, ge=1)
    ws_max_sockets_per_user: int = Field(10, ge=1)  # одновременно, на процесс; сверх — 4429
    ws_connects_per_ip_minute: int = Field(60, ge=1)  # попыток подключения; сверх — 4429

    # --- Push и worker уведомлений (Глава 15, ADR 0019) ---
    # fake — local/test/staging без Firebase-проекта; fcm — FCM HTTP v1 по сервисному аккаунту.
    push_provider: Literal["fake", "fcm"] = "fake"
    # Содержимое JSON-ключа сервисного аккаунта Firebase (не путь к файлу); вводит владелец.
    fcm_service_account_json: str = ""
    fcm_timeout_seconds: float = Field(10, gt=0, le=60)
    # Worker: опрос очереди, если сигнал Redis потерян; размер пачки; повторы (ADR 0019 п. 9).
    notifications_poll_seconds: float = Field(5, gt=0, le=300)
    notifications_batch_size: int = Field(100, ge=1, le=1000)
    push_max_attempts: int = Field(5, ge=1, le=20)
    push_retry_base_seconds: float = Field(10, gt=0, le=3600)
    # Напоминания о ТО — раз в сутки, час по Europe/Minsk (ADR 0019 п. 7).
    maintenance_reminder_hour: int = Field(10, ge=0, le=23)

    @model_validator(mode="after")
    def _default_channel_prefix(self) -> "Settings":
        if not self.redis_channel_prefix:
            self.redis_channel_prefix = f"ev-servicedesk:{self.environment}"
        return self

    @model_validator(mode="after")
    def _check_real_environment(self) -> "Settings":
        """Вне local/test заглушки секретов, фейковые SMS и push в production, S3 без ключей
        и FCM без ключа запрещены.

        Доступность бакета проверяется при старте приложения (app.main, ADR 0017 п. 11).
        """
        if self.environment in SAFE_ENVIRONMENTS:
            return self
        problems = []
        if self.jwt_secret == DEFAULT_JWT_SECRET or len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET")
        if self.sms_code_secret == DEFAULT_SMS_CODE_SECRET or len(self.sms_code_secret) < 32:
            problems.append("SMS_CODE_SECRET")
        if self.sms_provider == "a1" and not (self.sms_provider_user and self.sms_provider_api_key):
            problems.append("SMS_PROVIDER_USER/SMS_PROVIDER_API_KEY")
        if self.environment == "production" and self.sms_provider == "fake":
            problems.append("SMS_PROVIDER=fake")
        if not (self.s3_endpoint and self.s3_bucket):
            problems.append("S3_ENDPOINT/S3_BUCKET")
        if self.s3_access_key in ("", DEFAULT_S3_ACCESS_KEY) or self.s3_secret_key in (
            "",
            DEFAULT_S3_SECRET_KEY,
        ):
            problems.append("S3_ACCESS_KEY/S3_SECRET_KEY")
        if self.push_provider == "fcm" and not self.fcm_service_account_json:
            problems.append("FCM_SERVICE_ACCOUNT_JSON")
        if self.environment == "production" and self.push_provider == "fake":
            problems.append("PUSH_PROVIDER=fake")
        if problems:
            raise ValueError(
                f"Недопустимые настройки для ENVIRONMENT={self.environment}: {', '.join(problems)}"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Зависимость FastAPI; в тестах подменяется через app.dependency_overrides."""
    return Settings()


settings = get_settings()
