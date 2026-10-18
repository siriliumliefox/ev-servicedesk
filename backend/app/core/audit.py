"""События безопасности (глава 26, ADR 0030 п. 15): логгер `app.security`.

Вход и выход, повтор refresh-токена, пароли, учётные записи сотрудников, согласие и анонимизация,
публикации и регламенты администратора. В записи — событие, исход, id пользователя и роль, IP
(источник входа) и id объекта; телефона, текстов и токенов нет (первая линия; `PiiFilter` —
вторая). Loki хранит поток `app.security` 365 дней — требование к журналам ИБ класса 3-ин
(приказ ОАЦ № 66), остальное — 30.
"""

import logging
from typing import Literal

security_logger = logging.getLogger("app.security")

Outcome = Literal["success", "failure", "denied"]


def security_event(
    event: str,
    *,
    outcome: Outcome = "success",
    user_id: int | None = None,
    role: str | None = None,
    ip: str | None = None,
    target_user_id: int | None = None,
    target: str | None = None,
) -> None:
    """`event` — точечное имя (`auth.staff_login`); `target` — объект без ПД (`notification:12`)."""
    fields = {
        "event": event,
        "outcome": outcome,
        "user_id": user_id,
        "role": role,
        "ip": ip,
        "target_user_id": target_user_id,
        "target": target,
    }
    text = " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
    level = logging.INFO if outcome == "success" else logging.WARNING
    security_logger.log(level, text, extra=fields)
