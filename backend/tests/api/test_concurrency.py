"""Регрессия гонок Auth (ревизия PR #47): лимиты и reuse detection под параллельной нагрузкой.

Реальные Redis и PostgreSQL: атомарность Lua/MULTI и блокировки строк проверяются на
настоящих серверах. Без исправлений эти тесты падали.
"""

import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from redis import Redis
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import hash_refresh_token
from app.domain.auth import codes, service, tokens
from app.domain.auth.sms import FakeSmsProvider
from app.models import AppUser, PdConsent, RefreshToken
from app.models.enums import UserRole
from tests.api.conftest import api_settings, code_from

PHONE = "+375296660001"


def storm(n: int, fn: Callable[[], object]) -> list[object]:
    """n потоков стартуют одновременно; результат — значение или исключение."""
    barrier = threading.Barrier(n)
    results: list[object] = [None] * n

    def run(i: int) -> None:
        barrier.wait()
        try:
            results[i] = fn()
        except Exception as exc:  # noqa: BLE001 — исход каждого запроса нужен тесту
            results[i] = exc

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


@pytest.fixture
def compare_counter(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Считает фактические сравнения кода (то, что ограничивают лимиты)."""
    calls: list[int] = []
    lock = threading.Lock()
    original = codes.sms_code_matches

    def counting(*args, **kwargs):
        with lock:
            calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(codes, "sms_code_matches", counting)
    return calls


def wrong_for(code: str) -> str:
    return "0000" if code != "0000" else "1111"


def test_parallel_guesses_cannot_exceed_attempts_per_code(real_redis: Redis, compare_counter):
    settings = api_settings()
    sms = FakeSmsProvider()
    codes.request_code(real_redis, sms, settings, PHONE, "10.1.0.1")
    code = code_from(sms, PHONE)

    results = storm(40, lambda: codes.check_code(real_redis, settings, PHONE, wrong_for(code)))
    assert len(compare_counter) <= settings.sms_code_max_attempts
    wrong = [
        r for r in results if isinstance(r, codes.CodeResult) and r.status is codes.CodeCheck.WRONG
    ]
    assert len(wrong) <= settings.sms_code_max_attempts - 1
    assert any(isinstance(r, ApiError) and r.status_code == 429 for r in results)
    # Код сгорел: даже верный больше не принимается.
    assert codes.check_code(real_redis, settings, PHONE, code).status is codes.CodeCheck.MISSING


def test_parallel_guesses_cannot_exceed_daily_limit(real_redis: Redis, compare_counter):
    settings = api_settings(sms_code_max_attempts=10, verify_failures_per_phone_day=3)
    sms = FakeSmsProvider()
    codes.request_code(real_redis, sms, settings, PHONE, "10.1.0.2")
    code = code_from(sms, PHONE)

    storm(30, lambda: codes.check_code(real_redis, settings, PHONE, wrong_for(code)))
    assert len(compare_counter) <= settings.verify_failures_per_phone_day
    with pytest.raises(ApiError) as exc:
        codes.check_code(real_redis, settings, PHONE, code)
    assert exc.value.status_code == 429


class _NoUserDb:
    """Сессия-заглушка: пользователя нет — проверяются только лимиты (без БД)."""

    def scalars(self, *_args, **_kwargs):
        return self

    def one_or_none(self):
        return None


def test_parallel_staff_logins_cannot_exceed_failure_limit(
    real_redis: Redis, monkeypatch: pytest.MonkeyPatch
):
    settings = api_settings()
    checks: list[int] = []
    lock = threading.Lock()

    def counting_verify(password: str, password_hash: str | None) -> bool:
        with lock:
            checks.append(1)
        return False

    monkeypatch.setattr(service, "verify_password", counting_verify)
    results = storm(
        30,
        lambda: service.staff_login(
            _NoUserDb(), real_redis, settings, "+375295557777", "guess", "10.2.0.1"
        ),
    )
    assert len(checks) <= settings.staff_login_failures_per_phone_15min
    statuses = sorted(r.status_code for r in results if isinstance(r, ApiError))
    assert statuses.count(401) == len(checks) and statuses.count(429) == 30 - len(checks)


def test_reuse_detection_revokes_token_issued_by_concurrent_rotation(migrated_engine: Engine):
    """Вор ротирует T3→T4, жертва одновременно предъявляет старый T2: T4 тоже отзывается."""
    settings = api_settings()
    now = datetime.now(UTC)
    with Session(migrated_engine) as setup:
        user = AppUser(phone="+375296660099", role=UserRole.CLIENT)
        setup.add(user)
        setup.flush()
        old, current = "old-token-T2", "current-token-T3"
        setup.add_all(
            [
                RefreshToken(
                    user_id=user.id,
                    token_hash=hash_refresh_token(old),
                    expires_at=now + timedelta(days=1),
                    revoked_at=now,
                ),
                RefreshToken(
                    user_id=user.id,
                    token_hash=hash_refresh_token(current),
                    expires_at=now + timedelta(days=1),
                ),
            ]
        )
        setup.commit()
        user_id = user.id

    thief_at_commit, release_thief = threading.Event(), threading.Event()
    outcome: dict[str, object] = {}

    def thief() -> None:
        with Session(migrated_engine) as s:
            original_commit = s.commit

            def paused_commit() -> None:
                thief_at_commit.set()
                release_thief.wait(5)
                original_commit()

            s.commit = paused_commit  # type: ignore[method-assign]
            outcome["thief"] = tokens.rotate(s, current, settings)

    def victim() -> None:
        with Session(migrated_engine) as s:
            try:
                tokens.rotate(s, old, settings)
            except ApiError as exc:
                outcome["victim"] = exc.status_code

    try:
        t1 = threading.Thread(target=thief)
        t1.start()
        assert thief_at_commit.wait(5)
        t2 = threading.Thread(target=victim)
        t2.start()
        t2.join(0.5)  # жертва должна ждать блокировку пользователя
        release_thief.set()
        t1.join(5)
        t2.join(5)
        assert outcome.get("victim") == 401
        with Session(migrated_engine) as check:
            active = check.scalar(
                select(func.count())
                .select_from(RefreshToken)
                .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            )
        assert active == 0, "токен, выданный параллельной ротацией, пережил reuse detection"
    finally:
        release_thief.set()
        with Session(migrated_engine) as cleanup:
            cleanup.execute(delete(AppUser).where(AppUser.id == user_id))
            cleanup.commit()


@pytest.mark.parametrize("policy", [None, "2027-01"], ids=["same-consent", "new-policy"])
def test_withdraw_serializes_with_verify_code(
    migrated_engine: Engine, real_redis: Redis, monkeypatch: pytest.MonkeyPatch, policy
):
    """Отзыв согласия во время входа по коду: после обоих — ни согласия, ни живых сессий."""
    settings = api_settings()
    phone = "+37529666010" + ("1" if policy is None else "2")
    with Session(migrated_engine) as setup:
        user = AppUser(phone=phone, role=UserRole.CLIENT)
        setup.add(user)
        setup.flush()
        setup.add(PdConsent(user_id=user.id, policy_version="2026-01"))
        setup.commit()
        user_id = user.id
    sms = FakeSmsProvider()
    codes.request_code(real_redis, sms, settings, phone, "10.3.0.1")
    code = code_from(sms, phone)

    read_done, proceed = threading.Event(), threading.Event()
    original = service._active_consent

    def paused_read(db, uid):
        consent = original(db, uid)
        if not read_done.is_set():
            read_done.set()
            proceed.wait(5)
        return consent

    monkeypatch.setattr(service, "_active_consent", paused_read)
    outcome: dict[str, object] = {}

    def verify() -> None:
        with Session(migrated_engine) as s:
            try:
                outcome["verify"] = service.verify_phone_code(
                    s, real_redis, settings, phone, code, policy
                )
            except ApiError as exc:
                outcome["verify"] = exc.status_code

    def withdraw() -> None:
        with Session(migrated_engine) as s:
            try:
                service.withdraw_pd_consent(s, s.get(AppUser, user_id))
                outcome["withdraw"] = "ok"
            except ApiError as exc:
                outcome["withdraw"] = exc.status_code

    t1 = threading.Thread(target=verify)
    t1.start()
    try:
        assert read_done.wait(5)
        t2 = threading.Thread(target=withdraw)
        t2.start()
        t2.join(0.5)
        assert t2.is_alive(), "отзыв не ждёт блокировку пользователя, захваченную входом"
    finally:
        proceed.set()
        t1.join(5)
        t2.join(5)

    assert isinstance(outcome.get("verify"), service.LoginResult)
    assert outcome.get("withdraw") == "ok"
    with Session(migrated_engine) as check:
        active_consents = check.scalar(
            select(func.count())
            .select_from(PdConsent)
            .where(PdConsent.user_id == user_id, PdConsent.withdrawn_at.is_(None))
        )
        live_tokens = check.scalar(
            select(func.count())
            .select_from(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        )
    assert active_consents == 0
    assert live_tokens == 0, "сессия, выданная во время отзыва согласия, осталась живой"
