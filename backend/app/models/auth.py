"""Auth: пользователи и refresh-токены (C-01, A-04, X-04, N-07, ADR 0005)."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, TimestampMixin
from app.models.enums import UserRole, pg_enum


class AppUser(IdMixin, TimestampMixin, Base):
    """Таблица app_user: `user` — зарезервированное слово PostgreSQL (ADR 0003)."""

    __tablename__ = "app_user"
    __table_args__ = (
        CheckConstraint(r"phone ~ '^\+[1-9][0-9]{7,14}$'", name="phone_e164"),
        CheckConstraint("phone IS NOT NULL OR anonymized_at IS NOT NULL", name="phone_required"),
        CheckConstraint("role = 'client' OR password_hash IS NOT NULL", name="staff_password"),
        CheckConstraint(
            "(pd_consent_at IS NULL) = (pd_policy_version IS NULL)", name="pd_consent_pair"
        ),
    )

    # E.164; UNIQUE-индекс одновременно служит индексом поиска по телефону.
    # NULL допустим только у анонимизированного пользователя (N-07).
    phone: Mapped[str | None] = mapped_column(String(16), unique=True)
    role: Mapped[UserRole] = mapped_column(pg_enum(UserRole, "user_role"), nullable=False)
    telegram_id: Mapped[str | None] = mapped_column(String(50), unique=True)
    # bcrypt/argon2 (N-08); обязателен для engineer/admin (staff login).
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"), nullable=False)
    pd_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pd_policy_version: Mapped[str | None] = mapped_column(String(20))
    anonymized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshToken(IdMixin, CreatedAtMixin, Base):
    """Хранится только SHA-256 токена; сам токен в БД не попадает (ADR 0005)."""

    __tablename__ = "refresh_token"
    __table_args__ = (CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash_sha256"),)

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
