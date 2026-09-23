from fastapi import FastAPI

from app.core.config import settings

app = FastAPI(
    title="EV-ServiceDesk API",
    version="0.1.0",
    description="Backend-каркас, Глава 4. Контракт — см. docs/openapi.yaml (Глава 3).",
)


@app.get("/health")
def health() -> dict:
    """Проверка живости — используется CI (Глава 4) и мониторингом (Глава 26)."""
    return {"status": "ok", "environment": settings.environment}
