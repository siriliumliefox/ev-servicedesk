"""Пары токенов (ADR 0005, 0013): access — JWT, refresh — случайная строка, в БД только SHA-256.

Refresh одноразовый: при обновлении старый отзывается и выдаётся новый (ротация).
Повторное предъявление отозванного токена считается кражей — отзываются все токены
пользователя (reuse detection).

Порядок блокировок там, где сценарии пересекаются (ротация, отзыв всех токенов, вход по
коду, отзыв согласия): сначала строка app_user (lock_user), затем его refresh_token и
pd_consent. Так параллельная ротация и обнаружение повторного использования сериализуются
по пользователю и не оставляют «пропущенный» новый токен.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.audit import security_event
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


def lock_user(db: Session, user_id: int) -> None:
    """FOR NO KEY UPDATE на app_user: не мешает вставкам с FK, но сериализует сценарии."""
    db.execute(select(AppUser.id).where(AppUser.id == user_id).with_for_update(key_share=True))


def revoke_all(db: Session, user_id: int) -> None:
    """Все сессии пользователя: refresh-токены и выданные access-токены (`sessions_revoked_at`,
    ADR 0029 п. 12) — одной транзакцией вызывающего."""
    now = datetime.now(UTC)
    lock_user(db, user_id)
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    db.execute(update(AppUser).where(AppUser.id == user_id).values(sessions_revoked_at=now))


def rotate(db: Session, refresh_token: str, settings: Settings) -> TokenPair:
    """POST /auth/refresh. Строка блокируется (FOR UPDATE): параллельная ротация — одна."""
    now = datetime.now(UTC)
    token_hash = hash_refresh_token(refresh_token)
    user_id = db.scalar(select(RefreshToken.user_id).where(RefreshToken.token_hash == token_hash))
    if user_id is None:
        raise unauthorized("Недействительный refresh-токен")
    lock_user(db, user_id)
    row = db.scalars(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
    ).one_or_none()
    if row is None:  # удалён между поиском и блокировкой (например, вместе с пользователем)
        raise unauthorized("Недействительный refresh-токен")
    if row.revoked_at is not None:
        revoke_all(db, row.user_id)
        db.commit()
        security_event("auth.refresh_reuse", outcome="denied", user_id=row.user_id)
        raise unauthorized("Refresh-токен уже использован; все сессии завершены")
    if row.expires_at <= now:
        raise unauthorized("Refresh-токен истёк")

    user = db.get(AppUser, row.user_id)
    if user is None or not user.is_available:
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
