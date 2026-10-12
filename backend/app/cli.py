"""Эксплуатационные команды образа (Глава 17, ADR 0021 п. 7).

`python -m app.cli create-admin --phone +375291234567` — первый администратор чистой среды
(дальше сотрудников создаёт администратор через POST /users). Пароль читается из stdin
(первая строка): не попадает в аргументы процесса, историю оболочки и окружение.
"""

import argparse
import sys

from pydantic import ValidationError

from app.api.schemas.auth import StaffUserCreateRequest
from app.core.db import get_session_scope
from app.core.errors import ApiError
from app.domain.users import service
from app.models.enums import UserRole


def create_admin(phone: str, password: str) -> int:
    try:
        request = StaffUserCreateRequest(phone=phone, role=UserRole.ADMIN, password=password)
    except ValidationError as exc:
        fields = ", ".join(str(e["loc"][0]) for e in exc.errors())
        print(f"Неверные данные: {fields} (телефон E.164, пароль 12–128 символов)")
        return 2
    with get_session_scope()() as db:
        try:
            user = service.create_admin(db, request.phone, request.password)
        except ApiError as exc:
            print(exc.message)
            return 1
    print(f"Администратор создан: id {user.id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin", help="первый администратор; пароль — из stdin")
    admin.add_argument("--phone", required=True)
    args = parser.parse_args(argv)
    if args.command == "create-admin":
        password = sys.stdin.readline().rstrip("\r\n")
        return create_admin(args.phone, password)
    return 2  # pragma: no cover — argparse не пропускает неизвестную команду


if __name__ == "__main__":
    sys.exit(main())
