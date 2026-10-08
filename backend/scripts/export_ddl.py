"""Генерация docs/EV_ServiceDesk_Glava2_DDL.sql из миграций Alembic (offline, без БД).

Источник истины схемы — backend/alembic/versions (ADR 0003); DDL — артефакт для диплома
и ревью. Запуск: cd backend && poetry run python scripts/export_ddl.py [--check]
"""

import argparse
import io
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DDL_PATH = BACKEND.parent / "docs" / "EV_ServiceDesk_Glava2_DDL.sql"

HEADER = """\
-- EV-ServiceDesk — DDL (PostgreSQL 16)
-- СГЕНЕРИРОВАНО из миграций Alembic: cd backend && poetry run python scripts/export_ddl.py
-- Не редактировать вручную: источник истины — backend/alembic/versions (ADR 0003).
-- Синхронность проверяет backend/tests/db/test_ddl_export.py.
"""


def render() -> str:
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from alembic import command
    from alembic.config import Config

    buf = io.StringIO()
    cfg = Config(str(BACKEND / "alembic.ini"), output_buffer=buf)
    # Offline-режиму нужен только диалект; подключения не будет.
    cfg.attributes["database_url"] = "postgresql+psycopg://offline@localhost/offline"
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head", sql=True)
    return HEADER + "\n" + buf.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="только проверить синхронность")
    args = parser.parse_args()
    ddl = render()
    if args.check:
        if DDL_PATH.read_text(encoding="utf-8") != ddl:
            print(f"{DDL_PATH.name} устарел: запустите scripts/export_ddl.py", file=sys.stderr)
            return 1
        print(f"{DDL_PATH.name} in sync with Alembic migrations")
        return 0
    DDL_PATH.write_text(ddl, encoding="utf-8")
    print(f"written {DDL_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
