"""Общие проверки строк для схем запросов (ADR 0007)."""

import re

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def no_control_chars(value: str) -> str:
    # PostgreSQL не хранит NUL в text: без проверки — 500 вместо 422.
    if _CONTROL.search(value):
        raise ValueError("управляющие символы недопустимы")
    return value
