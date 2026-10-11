"""Единый формат ошибок контракта: {"error": {"code", "message", "details"}} (ADR 0007, п. 3)."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
}


class ApiError(Exception):
    """Доменная ошибка с HTTP-статусом и машиночитаемым кодом."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


def unauthorized(message: str = "Требуется авторизация") -> ApiError:
    return ApiError(401, "UNAUTHORIZED", message, headers={"WWW-Authenticate": "Bearer"})


def forbidden(message: str = "Недостаточно прав") -> ApiError:
    return ApiError(403, "FORBIDDEN", message)


def rate_limited(retry_after: int, message: str = "Слишком много попыток") -> ApiError:
    retry_after = max(retry_after, 1)
    return ApiError(
        429,
        "RATE_LIMITED",
        message,
        details={"retry_after_seconds": retry_after},
        headers={"Retry-After": str(retry_after)},
    )


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            error_body(exc.code, exc.message, exc.details),
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Значения полей (телефон, код) в ответ не возвращаем — только место и тип ошибки.
        fields = [{"loc": list(e["loc"]), "type": e["type"], "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse(
            error_body("VALIDATION_ERROR", "Ошибка валидации запроса", {"fields": fields}),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = HTTP_CODES.get(exc.status_code, "ERROR")
        return JSONResponse(
            error_body(code, str(exc.detail)),
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Необработанная ошибка: %s", type(exc).__name__)
        return JSONResponse(
            jsonable_encoder(error_body("INTERNAL_ERROR", "Внутренняя ошибка сервера")),
            status_code=500,
        )
