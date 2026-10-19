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


def field_error(field: str, code: str, message: str, location: str = "body") -> ApiError:
    """422 с указанием поля (`details.fields[].loc`), как ошибки валидации схемы."""
    return ApiError(422, code, message, details={"fields": [{"loc": [location, field]}]})


def rate_limited(retry_after: int, message: str = "Слишком много попыток") -> ApiError:
    retry_after = max(retry_after, 1)
    return ApiError(
        429,
        "RATE_LIMITED",
        message,
        details={"retry_after_seconds": retry_after},
        headers={"Retry-After": str(retry_after)},
    )


# Тексты ошибок валидации схемы по типу ошибки Pydantic (#105, №15): вместо английских «Input should
# be…» и «Field required». В тексте — только ограничения схемы (ctx), не введённое значение.
_VALIDATION_TEXTS: dict[str, str] = {
    "missing": "Обязательное поле",
    "extra_forbidden": "Лишнее поле",
    "greater_than_equal": "Не меньше {ge}",
    "greater_than": "Больше {gt}",
    "less_than_equal": "Не больше {le}",
    "less_than": "Меньше {lt}",
    "string_too_short": "Не короче {min_length} символов",
    "string_too_long": "Не длиннее {max_length} символов",
    "too_short": "Не меньше {min_length} элементов",
    "too_long": "Не больше {max_length} элементов",
    "string_pattern_mismatch": "Неверный формат",
    "string_type": "Нужна строка",
    "int_type": "Нужно целое число",
    "int_parsing": "Нужно целое число",
    "int_from_float": "Нужно целое число",
    "float_type": "Нужно число",
    "float_parsing": "Нужно число",
    "bool_type": "Нужно true или false",
    "bool_parsing": "Нужно true или false",
    "enum": "Допустимые значения: {expected}",
    "literal_error": "Допустимые значения: {expected}",
    "uuid_type": "Нужен UUID",
    "uuid_parsing": "Нужен UUID",
    "date_type": "Нужна дата ГГГГ-ММ-ДД",
    "date_parsing": "Нужна дата ГГГГ-ММ-ДД",
    "date_from_datetime_parsing": "Нужна дата ГГГГ-ММ-ДД",
    "datetime_type": "Нужны дата и время ISO 8601",
    "datetime_parsing": "Нужны дата и время ISO 8601",
    "datetime_from_date_parsing": "Нужны дата и время ISO 8601",
    "list_type": "Нужен список",
    "dict_type": "Нужен объект",
    "model_type": "Нужен объект",
    "model_attributes_type": "Нужен объект",
    "json_invalid": "Некорректный JSON",
    "json_type": "Некорректный JSON",
}
# Свои проверки (field_validator / model_validator) уже пишут по-русски — без префикса Pydantic.
_OWN_PREFIXES = ("Value error, ", "Assertion failed, ")


def validation_message(error: dict[str, Any]) -> str:
    """Русский текст ошибки валидации схемы: по типу Pydantic, у своих проверок — их текст."""
    for prefix in _OWN_PREFIXES:
        if error["msg"].startswith(prefix):
            return error["msg"].removeprefix(prefix)
    template = _VALIDATION_TEXTS.get(error["type"], "Недопустимое значение")
    ctx = dict(error.get("ctx") or {})
    if isinstance(ctx.get("expected"), str):  # «'a', 'b' or 'c'» — без английского «or»
        ctx["expected"] = ctx["expected"].replace(" or ", ", ")
    try:
        return template.format(**ctx)
    except (KeyError, IndexError):
        return "Недопустимое значение"


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
        fields = [
            {"loc": list(e["loc"]), "type": e["type"], "msg": validation_message(e)}
            for e in exc.errors()
        ]
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
