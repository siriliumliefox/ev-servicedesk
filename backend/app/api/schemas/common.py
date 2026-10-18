"""Общие проверки строк для схем запросов (ADR 0007)."""

import re

from pydantic import AfterValidator

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def no_control_chars(value: str) -> str:
    # PostgreSQL не хранит NUL в text: без проверки — 500 вместо 422.
    if _CONTROL.search(value):
        raise ValueError("управляющие символы недопустимы")
    return value


def optional_no_control_chars(value: str | None) -> str | None:
    """Для необязательных параметров запроса (поиск, фильтры): None пропускается."""
    return None if value is None else no_control_chars(value)


# Параметры пути и строки запроса — те же правила, что у тел (ZAP-1, глава 25): `?search=%00`
# давал 500 (NUL в запросе PostgreSQL) вместо 422.
SafeText = AfterValidator(no_control_chars)
SafeOptionalText = AfterValidator(optional_no_control_chars)


# Многострочный текст (описания, сообщения, статьи): табуляция и переводы строк разрешены,
# прочие управляющие символы Unicode Cc (C0, DEL и C1) — нет: NUL PostgreSQL в text не хранит,
# C1 (например, CSI U+009B) управляет терминалами.
_MULTILINE_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def no_control_chars_multiline(value: str) -> str:
    if _MULTILINE_CONTROL.search(value):
        raise ValueError("управляющие символы недопустимы")
    return value
