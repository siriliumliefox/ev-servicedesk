"""Заголовки безопасности ответов API (Глава 25, ADR 0029 п. 8, OWASP A02).

API отдаёт только JSON: браузеру запрещено угадывать тип (nosniff), встраивать ответ во фрейм
и передавать адрес API в Referer; ответы `/v1` с данными пользователей не кэшируются
(`no-store`: общие прокси и кэш браузера). HSTS и CSP заголовком ставит nginx (глава 26).
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
}


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, api_prefix: str = "/v1") -> None:
        self.app = app
        self.api_prefix = api_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        api = scope["path"].startswith(self.api_prefix + "/")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in HEADERS.items():
                    headers.setdefault(name, value)
                if api:
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_with_headers)
