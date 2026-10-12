"""CLI образа `python -m app.cli create-admin` (Глава 17, ADR 0021 п. 7)."""

import io
from contextlib import contextmanager

import pytest
from sqlalchemy import select

from app import cli
from app.core.security import verify_password
from app.models import AppUser
from app.models.enums import UserRole

PHONE = "+375296700001"
PASSWORD = "Bootstrap-pass-1"


@pytest.fixture
def run(db, monkeypatch):
    @contextmanager
    def scope():
        yield db

    monkeypatch.setattr(cli, "get_session_scope", lambda: scope)

    def _run(argv: list[str], stdin: str) -> int:
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
        return cli.main(argv)

    return _run


def test_create_admin_from_stdin(run, db, capsys):
    assert run(["create-admin", "--phone", PHONE], PASSWORD + "\n") == 0
    user = db.scalars(select(AppUser).where(AppUser.phone == PHONE)).one()
    assert user.role is UserRole.ADMIN and user.is_active
    assert verify_password(PASSWORD, user.password_hash)
    out = capsys.readouterr().out
    assert f"id {user.id}" in out and PASSWORD not in out


def test_create_admin_twice_fails(run, capsys):
    assert run(["create-admin", "--phone", PHONE], PASSWORD) == 0
    assert run(["create-admin", "--phone", PHONE], PASSWORD) == 1
    assert "уже зарегистрирован" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("phone", "password"),
    [(PHONE, "short"), ("375296700001", PASSWORD), (PHONE, "")],
)
def test_create_admin_rejects_bad_input(run, db, phone, password, capsys):
    assert run(["create-admin", "--phone", phone], password) == 2
    assert password not in capsys.readouterr().out or not password
    assert db.scalars(select(AppUser).where(AppUser.role == UserRole.ADMIN)).all() == []
