"""Логи без ПД (99-З п. 2, ADR 0005 п. 4, ADR 0029 п. 17).

Первая линия — код не пишет ПД в сообщения (телефон — `mask_phone`, тексты и имена файлов не
логируются, SQL — `hide_parameters`). Вторая линия — здесь:
- `PiiFilter` на обработчиках маскирует в любом сообщении и трассировке телефоны E.164, VIN и
  JWT — на случай, если ПД попадут в лог через библиотеку или исключение;
- журнал доступа uvicorn выключен (`--no-access-log`: он пишет путь со строкой запроса —
  `GET /users?search=<телефон>`, `DELETE /push-tokens/<токен>`); `AccessLogMiddleware` пишет
  метод, шаблон маршрута (`/v1/push-tokens/{token}`), статус и длительность; он же считает
  метрики запросов (`app.core.metrics`, глава 26).

Формат (глава 26, ADR 0030 п. 15): `text` — локально и в CI, `json` — staging/production: одна
строка JSON на запись (`ts`, `level`, `logger`, `msg`, `exc` и поля из `extra` — списком
`JSON_FIELDS`), её разбирает Loki. Маскирование одинаково в обоих форматах.
"""

import json
import logging
import re
import sys
import time
from datetime import UTC, datetime

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import metrics

FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
# Поля `extra`, которые JSON-журнал выносит отдельно: журнал доступа и события безопасности
# (`app.core.audit`). Только они — случайный `extra` с ПД в журнал не попадёт.
JSON_FIELDS = (
    "method",
    "route",
    "status",
    "duration_ms",
    "event",
    "outcome",
    "user_id",
    "role",
    "ip",
    "target_user_id",
    "target",
)

_PHONE = re.compile(r"\+?\b375\d{9}\b|\+[1-9]\d{7,14}\b")
_VIN = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")
_JWT = re.compile(r"\beyJ[\w-]{5,}\.[\w-]{5,}\.[\w-]{5,}")


def _mask_phone(match: re.Match[str]) -> str:
    value = match.group(0)
    return value[:4] + "*" * max(len(value) - 6, 0) + value[-2:]


def mask_pii(text: str) -> str:
    text = _JWT.sub("<jwt>", text)
    text = _VIN.sub(lambda m: m.group(0)[:3] + "*" * 14, text)
    return _PHONE.sub(_mask_phone, text)


class PiiFilter(logging.Filter):
    """Маскирует ПД в готовом сообщении и тексте исключения записи."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        masked = mask_pii(message)
        if masked != message:
            record.msg, record.args = masked, None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = mask_pii(record.exc_text)
        return True


class JsonFormatter(logging.Formatter):
    """Одна строка JSON на запись; сообщение и трассировка уже замаскированы `PiiFilter`."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for field in JSON_FIELDS:
            value = record.__dict__.get(field)
            if value is not None:
                entry[field] = value
        if record.exc_text:
            entry["exc"] = record.exc_text
        return json.dumps(entry, ensure_ascii=False, default=str)


class PiiStdoutHandler(logging.StreamHandler):
    """stdout с `PiiFilter`. Поток берётся при каждой записи: под pytest это перехваченный
    stdout теста, а не терминал."""

    def __init__(self, log_format: str = "text") -> None:
        super().__init__()
        self.setFormatter(JsonFormatter() if log_format == "json" else logging.Formatter(FORMAT))
        self.addFilter(PiiFilter())

    @property
    def stream(self):  # type: ignore[override]
        return sys.stdout

    @stream.setter
    def stream(self, _value) -> None:
        pass


def configure_logging(level: int = logging.INFO, log_format: str = "text") -> None:
    """Корневой обработчик `PiiStdoutHandler`; `PiiFilter` — и у обработчиков uvicorn.

    Повторный вызов не добавляет обработчиков. API (create_app) и worker'ы вызывают при старте:
    без него INFO приложения терялись бы, а предупреждения шли бы мимо фильтра. Формат —
    `Settings.log_format`; журнал uvicorn в JSON не переводится (свой журнал доступа — наш).
    """
    root = logging.getLogger()
    if not any(isinstance(h, PiiStdoutHandler) for h in root.handlers):
        root.addHandler(PiiStdoutHandler(log_format))
    root.setLevel(level)
    # httpx пишет на INFO полный URL запроса (A1, FCM): URL без ПД, но и без пользы в журнале.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            if not any(isinstance(f, PiiFilter) for f in handler.filters):
                handler.addFilter(PiiFilter())


access_logger = logging.getLogger("app.access")
# Пробы живости (healthcheck Docker раз в 5 с, blackbox) и сбор метрик — в метриках, но не в
# журнале: иначе тысячи одинаковых строк в сутки.
QUIET_ROUTES = frozenset({"/health", "/metrics"})


class AccessLogMiddleware:
    """Журнал запросов без строки запроса и значений параметров пути (ADR 0029 п. 17)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500

        async def send_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_status)
        finally:
            route = scope.get("route")
            # Без найденного маршрута путь не пишется: в нём может быть что угодно (404).
            path = getattr(route, "path", None) or "<unmatched>"
            seconds = time.perf_counter() - started
            method = scope["method"]
            metrics.observe_request(method, path, status, seconds)
            elapsed = round(seconds * 1000, 1)
            if path not in QUIET_ROUTES:
                access_logger.info(
                    "%s %s %d %.1fms",
                    method,
                    path,
                    status,
                    elapsed,
                    extra={
                        "method": method,
                        "route": path,
                        "status": status,
                        "duration_ms": elapsed,
                    },
                )
