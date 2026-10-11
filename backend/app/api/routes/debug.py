"""Отладка для ENVIRONMENT=local (решение владельца, Issue #46).

Фейковый SMS-провайдер не пишет код в логи (ADR 0005), поэтому локально код можно
получить только здесь. Роутер подключается исключительно при ENVIRONMENT=local и
не входит в OpenAPI; в staging/production маршрута не существует (404).
"""

import re

from fastapi import APIRouter, Query

from app.core.errors import ApiError
from app.domain.auth.sms import fake_provider

router = APIRouter(prefix="/_debug", include_in_schema=False)

_CODE = re.compile(r"\b(\d{4,8})\b")


@router.get("/sms/last-code")
def last_sms_code(phone: str = Query(pattern=r"^\+[1-9][0-9]{7,14}$")) -> dict:
    text = fake_provider().last_text(phone)
    match = _CODE.search(text or "")
    if match is None:
        raise ApiError(404, "NOT_FOUND", "SMS на этот номер не отправлялось")
    return {"phone": phone, "code": match.group(1)}
