from fastapi import FastAPI

from app.api.routes import auth, debug, users
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers

API_PREFIX = "/v1"  # servers в docs/openapi.yaml: http://localhost:8000/v1


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    application = FastAPI(
        title="EV-ServiceDesk API",
        version="0.2.0",
        description="Backend EV-ServiceDesk. Контракт — docs/openapi.yaml (Глава 3, ADR 0007).",
    )
    install_error_handlers(application)

    @application.get("/health")
    def health() -> dict:
        """Проверка живости — используется CI (Глава 4) и мониторингом (Глава 26)."""
        return {"status": "ok", "environment": settings.environment}

    application.include_router(auth.router, prefix=API_PREFIX)
    application.include_router(users.router, prefix=API_PREFIX)
    if settings.environment == "local":
        application.include_router(debug.router, prefix=API_PREFIX)
    return application


app = create_app()
