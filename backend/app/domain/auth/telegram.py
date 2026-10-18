"""Владение аккаунтом Telegram — подпись Telegram Login Widget (Глава 25, ADR 0029 п. 16).

Строка проверки — все полученные от виджета поля, кроме `hash`, в виде `ключ=значение`,
отсортированные по ключу и разделённые переводом строки; подпись — HMAC-SHA256 строки с ключом
SHA-256(токен бота). Без токена бота привязка недоступна (503); неверная подпись или устаревший
`auth_date` (старше TELEGRAM_AUTH_MAX_AGE_SECONDS) — 422.
"""

import hashlib
import hmac
from collections.abc import Mapping
from datetime import UTC, datetime

from app.core.config import Settings
from app.core.errors import ApiError, field_error

CLOCK_SKEW_SECONDS = 60


def verify_widget(settings: Settings, fields: Mapping[str, str], signature: str | None) -> str:
    """id аккаунта Telegram из подписанных полей виджета (`id`, `auth_date`, …)."""
    if not settings.telegram_bot_token:
        raise ApiError(503, "TELEGRAM_UNAVAILABLE", "Привязка Telegram временно недоступна")
    invalid = field_error("hash", "TELEGRAM_AUTH_INVALID", "Подпись Telegram недействительна")
    if signature is None or "auth_date" not in fields:
        raise invalid
    check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hashlib.sha256(settings.telegram_bot_token.encode()).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    age = datetime.now(UTC).timestamp() - int(fields["auth_date"])
    fresh = -CLOCK_SKEW_SECONDS <= age <= settings.telegram_auth_max_age_seconds
    if not (hmac.compare_digest(expected, signature) and fresh):
        raise invalid
    return fields["id"]
