"""Логи без ПД (99-З п. 2, ADR 0005 п. 4, ADR 0029 п. 17).

Первая линия — код не пишет ПД в сообщения (телефон — `mask_phone`, тексты и имена файлов не
логируются, SQL — `hide_parameters`). Вторая линия — здесь:
- `PiiFilter` на обработчиках маскирует в любом сообщении и трассировке телефоны E.164, VIN и
  JWT — на случай, если ПД попадут в лог через библиотеку или исключение;
- журнал доступа uvicorn выключен (`--no-access-log`: он пишет путь со строкой запроса —
  `GET /users?search=<телефон>`, `DELETE /push-tokens/<токен>`); `AccessLogMiddleware` пишет
  метод, шаблон маршрута (`/v1/push-tokens/{token}`), статус и длительность.
"""

import logging
import re
import sys
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

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


def configure_logging(level: int = logging.INFO) -> None:
    """Корневой обработчик (stdout) с `PiiFilter`; фильтр — и у обработчиков uvicorn.

    Повторный вызов не добавляет обработчиков. API (create_app вне тестов) и worker'ы вызывают
    при старте: без него INFO приложения терялись бы, а предупреждения шли бы мимо фильтра.
    """
    root = logging.getLogger()
    if not any(getattr(h, "_ev_pii", False) for h in root.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(FORMAT))
        handler.addFilter(PiiFilter())
        handler._ev_pii = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    root.setLevel(level)
    # httpx пишет на INFO полный URL запроса (A1, FCM): URL без ПД, но и без пользы в журнале.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            if not any(isinstance(f, PiiFilter) for f in handler.filters):
                handler.addFilter(PiiFilter())


access_logger = logging.getLogger("app.access")


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
            elapsed = (time.perf_counter() - started) * 1000
            access_logger.info("%s %s %d %.1fms", scope["method"], path, status, elapsed)
