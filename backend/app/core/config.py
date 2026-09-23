from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения — читаются из переменных окружения (см. .env.example, Глава 4 шаг 3)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "local"
    database_url: str = "postgresql+psycopg://ev:ev@localhost:5432/ev_servicedesk"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "change-me-in-every-real-environment"


settings = Settings()
