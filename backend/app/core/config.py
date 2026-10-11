from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Значения-заглушки из .env.example: в staging/production с ними приложение не стартует.
DEFAULT_JWT_SECRET = "change-me-in-every-real-environment"
DEFAULT_SMS_CODE_SECRET = "change-me-sms-code-secret"
SAFE_ENVIRONMENTS = {"local", "test"}


class Settings(BaseSettings):
    """Настройки приложения — читаются из переменных окружения (см. .env.example, Глава 4 шаг 3)."""

    # Корневой .env (запуск из backend/) и локальный; переменные окружения важнее файлов.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    environment: str = "local"
    database_url: str = "postgresql+psycopg://ev:ev@localhost:5432/ev_servicedesk"
    redis_url: str = "redis://localhost:6379/0"

    # --- JWT (Глава 10, ADR 0013) ---
    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_issuer: str = "ev-servicedesk"
    jwt_audience: str = "ev-servicedesk-api"
    access_token_ttl_seconds: int = 15 * 60
    refresh_token_ttl_days: int = 30

    # --- SMS-код (ADR 0005, 0013): в Redis только HMAC-SHA256(код, SMS_CODE_SECRET) ---
    sms_code_secret: str = DEFAULT_SMS_CODE_SECRET
    sms_code_length: int = 4
    sms_code_ttl_seconds: int = 120
    sms_code_max_attempts: int = 5

    # --- Rate limiting (N-06) ---
    sms_resend_cooldown_seconds: int = 60
    sms_requests_per_phone_hour: int = 5
    sms_requests_per_ip_hour: int = 30
    verify_failures_per_phone_day: int = 20
    staff_login_failures_per_phone_15min: int = 5
    staff_login_failures_per_ip_15min: int = 20

    # --- SMS-провайдер: fake (local/test) | a1 (A1 Smart-рассылка) ---
    sms_provider: Literal["fake", "a1"] = "fake"
    sms_provider_user: str = ""
    sms_provider_api_key: str = ""
    sms_sender: str = ""
    sms_provider_url: str = "https://smart-sender.a1.by/api"
    sms_provider_rps: float = 10.0

    @model_validator(mode="after")
    def _check_real_environment(self) -> "Settings":
        """Вне local/test заглушки секретов и фейковый SMS-провайдер запрещены."""
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
