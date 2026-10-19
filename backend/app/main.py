from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
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
from app.core import metrics
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.headers import SecurityHeadersMiddleware
from app.core.logging import AccessLogMiddleware, configure_logging
from app.core.pubsub import PubSubHub
from app.core.storage import get_storage, require_bucket

API_PREFIX = "/v1"  # servers в docs/openapi.yaml: http://localhost:8000/v1


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    production = settings.environment == "production"

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Вне local/test без доступного бакета S3 приложение не стартует (ADR 0017 п. 11).

        Исключение при старте — uvicorn пишет причину в лог и завершается с ненулевым кодом.
        Проверяется то же хранилище, что получат маршруты (с учётом dependency_overrides);
        local/test S3 не требуют — ни при импорте, ни при старте.

        Общая подписка Redis pub/sub процесса (WebSocket событий тикета) соединяется при первом
        подписчике, а не при старте; при остановке закрывается.
        """
        storage = app.dependency_overrides.get(get_storage, get_storage)
        await run_in_threadpool(require_bucket, settings, storage)
        app.state.pubsub_hub = hub = PubSubHub.from_settings(settings)
        try:
            yield
        finally:
            await hub.aclose()

    application = FastAPI(
        title="EV-ServiceDesk API",
        version="1.17.0",  # = info.version docs/openapi.yaml
        description="Backend EV-ServiceDesk. Контракт — docs/openapi.yaml (Глава 3, ADR 0007).",
        lifespan=lifespan,
        # Swagger и схема — для разработки и staging; в production не публикуются (ADR 0029 п. 8):
        # контракт — docs/openapi.yaml в репозитории, а не карта API для сканера.
        **({"docs_url": None, "redoc_url": None, "openapi_url": None} if production else {}),
    )
    install_error_handlers(application)
    application.add_middleware(SecurityHeadersMiddleware, api_prefix=API_PREFIX)
    application.add_middleware(AccessLogMiddleware)
    configure_logging(log_format=settings.log_format)

    @application.get("/health")
    def health() -> dict:
        """Проверка живости — используется CI (Глава 4) и мониторингом (Глава 26)."""
        return {"status": "ok", "environment": settings.environment}

    @application.get("/metrics", include_in_schema=False)
    def prometheus_metrics() -> Response:
        """Метрики Prometheus (глава 26, ADR 0030 п. 13): вне /v1 и контракта; снаружи nginx
        отдаёт на этот путь 404 — читает только Prometheus из сети контейнеров."""
        body, content_type = metrics.render()
        return Response(body, media_type=content_type)

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
