"""Политика паролей сотрудников (Глава 25, ADR 0029 п. 13, #102 B1 №5).

Длина 12–128 проверяет схема запроса; здесь — стойкость: оценка zxcvbn не ниже 3 из 4
(перебор онлайн и офлайн с медленным хэшем не окупается). Номер телефона — известные данные:
пароль из цифр своего номера слабый. Слабый пароль — 422 VALIDATION_ERROR с полем, как ошибки
схемы; схема контракта не меняется.
"""

from zxcvbn import zxcvbn

from app.core.errors import field_error

MIN_SCORE = 3
MAX_LENGTH = 128  # как у схем запроса; по умолчанию zxcvbn отказывает длиннее 72


def ensure_strong(password: str, phone: str | None, field: str = "password") -> None:
    known = [phone, phone.lstrip("+")] if phone else []
    if zxcvbn(password, user_inputs=known, max_length=MAX_LENGTH)["score"] < MIN_SCORE:
        raise field_error(
            field,
            "VALIDATION_ERROR",
            "Пароль слишком простой: используйте фразу из нескольких слов или случайный набор",
        )
