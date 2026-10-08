"""Генерация docs/ERD_EV_ServiceDesk_Glava2.mermaid из ORM-метаданных (app.models).

Запуск: cd backend && poetry run python scripts/export_erd.py [--check]
Синхронность ORM ↔ миграции проверяет tests/db/test_migrations.py, ERD ↔ ORM — test_erd_export.py.
"""

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ERD_PATH = BACKEND.parent / "docs" / "ERD_EV_ServiceDesk_Glava2.mermaid"

HEADER = """\
%% EV-ServiceDesk — ER-диаграмма (Глава 2)
%% СГЕНЕРИРОВАНО из backend/app/models: cd backend && poetry run python scripts/export_erd.py
%% Не редактировать вручную. ||--o{ — обязательный FK, |o--o{ — необязательный.
"""


def _type(column) -> str:
    from sqlalchemy import Enum
    from sqlalchemy.dialects import postgresql

    if isinstance(column.type, Enum):
        return column.type.name
    rendered = column.type.compile(dialect=postgresql.dialect()).lower()
    rendered = rendered.replace("timestamp with time zone", "timestamptz")
    return rendered.replace(" ", "_").replace("(", "_").replace(")", "")


def render() -> str:
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

    from app.models import Base

    lines = ["erDiagram", HEADER.rstrip("\n")]
    relations: list[str] = []
    for table in sorted(Base.metadata.tables.values(), key=lambda t: t.name):
        single_unique = {
            next(iter(c.columns)).name
            for c in table.constraints
            if isinstance(c, UniqueConstraint) and len(c.columns) == 1
        }
        partial_unique = {}
        for index in table.indexes:
            where = index.dialect_options["postgresql"].get("where")
            if not index.unique:
                continue
            if where is None and len(index.columns) == 1:
                single_unique.add(next(iter(index.columns)).name)
            elif where is not None:
                cols = ", ".join(c.name for c in index.columns)
                partial_unique[next(iter(index.columns)).name] = f"unique ({cols}) where {where}"
        fk_columns = {col.name for fk in table.foreign_key_constraints for col in fk.columns}
        lines.append(f"    {table.name} {{")
        for column in table.columns:
            keys = [
                k for k, on in (("PK", column.primary_key), ("FK", column.name in fk_columns)) if on
            ]
            if column.name in single_unique:
                keys.append("UK")
            key = f" {','.join(keys)}" if keys else ""
            notes = []
            if column.nullable and not column.primary_key:
                notes.append("nullable")
            if column.name in partial_unique:
                notes.append(partial_unique[column.name])
            note = f' "{"; ".join(notes)}"' if notes else ""
            lines.append(f"        {_type(column)} {column.name}{key}{note}")
        lines.append("    }")
        for fk in sorted(table.foreign_key_constraints, key=lambda c: str(c.name)):
            assert isinstance(fk, ForeignKeyConstraint)
            parent = fk.referred_table.name
            optional = any(col.nullable for col in fk.columns)
            left = "|o" if optional else "||"
            label = ", ".join(col.name for col in fk.columns)
            ondelete = (fk.ondelete or "NO ACTION").upper()
            relations.append(f'    {parent} {left}--o{{ {table.name} : "{label} ({ondelete})"')
    lines.append("")
    lines.extend(relations)
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="только проверить синхронность")
    args = parser.parse_args()
    erd = render()
    if args.check:
        if ERD_PATH.read_text(encoding="utf-8") != erd:
            print(f"{ERD_PATH.name} устарел: запустите scripts/export_erd.py", file=sys.stderr)
            return 1
        print(f"{ERD_PATH.name} in sync with ORM models")
        return 0
    ERD_PATH.write_text(erd, encoding="utf-8")
    print(f"written {ERD_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
