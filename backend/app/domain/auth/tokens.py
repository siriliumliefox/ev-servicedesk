"""Пары токенов (ADR 0005, 0013): access — JWT, refresh — случайная строка, в БД только SHA-256.

Refresh одноразовый: при обновлении старый отзывается и выдаётся новый (ротация).
Повторное предъявление отозванного токена считается кражей — отзываются все токены
пользователя (reuse detection).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import unauthorized
from app.core.security import create_access_token, hash_refresh_token, new_refresh_token
from app.models import AppUser, RefreshToken


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


def issue_pair(db: Session, user: AppUser, settings: Settings) -> TokenPair:
    """Добавляет refresh-токен в сессию; commit — на стороне вызывающего."""
    now = datetime.now(UTC)
    refresh = new_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh),
            expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    return TokenPair(
        access_token=create_access_token(user.id, user.role.value, settings, now),
        refresh_token=refresh,
        expires_in=settings.access_token_ttl_seconds,
    )


def revoke_all(db: Session, user_id: int) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


def rotate(db: Session, refresh_token: str, settings: Settings) -> TokenPair:
    """POST /auth/refresh. Строка блокируется (FOR UPDATE): параллельная ротация — одна."""
    now = datetime.now(UTC)
    row = db.scalars(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_refresh_token(refresh_token))
        .with_for_update()
    ).one_or_none()
    if row is None:
        raise unauthorized("Недействительный refresh-токен")
    if row.revoked_at is not None:
        revoke_all(db, row.user_id)
        db.commit()
        raise unauthorized("Refresh-токен уже использован; все сессии завершены")
    if row.expires_at <= now:
        raise unauthorized("Refresh-токен истёк")

    user = db.get(AppUser, row.user_id)
    if user is None or not user.is_active or user.anonymized_at is not None:
        raise unauthorized("Учётная запись недоступна")

    row.revoked_at = now
    pair = issue_pair(db, user, settings)
    db.commit()
    return pair


def revoke(db: Session, refresh_token: str, user_id: int) -> None:
    """POST /auth/logout: отзывает токен, только если он принадлежит текущему пользователю.

    Чужой или неизвестный токен молча игнорируется — ответ не раскрывает его существование.
    """
    db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == hash_refresh_token(refresh_token),
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    db.commit()
