from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app.api.routes import (
    aggregates,
    analytics,
    auth,
    debug,
    knowledge,
    notifications,
    ticket_events,
    tickets,
    uploads,
    users,
    vehicles,
)
from app.core.config import SAFE_ENVIRONMENTS, Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.pubsub import PubSubHub
from app.core.storage import get_storage

API_PREFIX = "/v1"  # servers в docs/openapi.yaml: http://localhost:8000/v1


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Вне local/test без доступного бакета S3 приложение не стартует (ADR 0017 п. 11).

        Исключение при старте — uvicorn пишет причину в лог и завершается с ненулевым кодом.
        Проверяется то же хранилище, что получат маршруты (с учётом dependency_overrides);
        local/test S3 не требуют — ни при импорте, ни при старте.

        Общая подписка Redis pub/sub процесса (WebSocket событий тикета) соединяется при первом
        подписчике, а не при старте; при остановке закрывается.
        """
        if settings.environment not in SAFE_ENVIRONMENTS:
            storage = app.dependency_overrides.get(get_storage, get_storage)()
            await run_in_threadpool(storage.check_bucket)
        app.state.pubsub_hub = hub = PubSubHub.from_settings(settings)
        try:
            yield
        finally:
            await hub.aclose()

    application = FastAPI(
        title="EV-ServiceDesk API",
        version="1.7.1",  # = info.version docs/openapi.yaml
        description="Backend EV-ServiceDesk. Контракт — docs/openapi.yaml (Глава 3, ADR 0007).",
        lifespan=lifespan,
    )
    install_error_handlers(application)

    @application.get("/health")
    def health() -> dict:
        """Проверка живости — используется CI (Глава 4) и мониторингом (Глава 26)."""
        return {"status": "ok", "environment": settings.environment}

    application.include_router(auth.router, prefix=API_PREFIX)
    application.include_router(users.router, prefix=API_PREFIX)
    application.include_router(vehicles.router, prefix=API_PREFIX)
    application.include_router(aggregates.router, prefix=API_PREFIX)
    application.include_router(uploads.router, prefix=API_PREFIX)
    application.include_router(tickets.router, prefix=API_PREFIX)
    application.include_router(ticket_events.router, prefix=API_PREFIX)
    application.include_router(knowledge.router, prefix=API_PREFIX)
    application.include_router(notifications.router, prefix=API_PREFIX)
    application.include_router(analytics.router, prefix=API_PREFIX)
    # Отладочный маршрут SMS-кода — только local с фейковым провайдером (Issue #46).
    if settings.environment == "local" and settings.sms_provider == "fake":
        application.include_router(debug.router, prefix=API_PREFIX)
    return application


app = create_app()
