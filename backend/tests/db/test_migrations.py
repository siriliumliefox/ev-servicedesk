"""Миграции: полный цикл up/down/up, соответствие ORM ↔ БД, объекты вне autogenerate."""

from sqlalchemy import CheckConstraint, Engine, create_engine, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from app.models import Base
from app.models.enums import PG_ENUMS
from tests.db.conftest import alembic_config

EXPECTED_TABLES = set(Base.metadata.tables)
EXPECTED_FUNCTIONS = {
    "vehicle_guard",
    "set_updated_at",
    "mileage_correction_before_insert",
    "mileage_correction_after_insert",
    "append_only_guard",
    "pd_consent_guard",
}


def _snapshot(engine: Engine) -> dict[str, set[str]]:
    with engine.connect() as c:
        tables = set(inspect(c).get_table_names()) - {"alembic_version"}
        enums = set(
            c.execute(
                text(
                    "SELECT t.typname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace "
                    "WHERE n.nspname = 'public' AND t.typtype = 'e'"
                )
            ).scalars()
        )
        functions = set(
            c.execute(
                text(
                    "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE n.nspname = 'public'"
                )
            ).scalars()
        )
    return {"tables": tables, "enums": enums, "functions": functions}


def test_upgrade_downgrade_upgrade(migrated_engine: Engine, db_url: URL) -> None:
    cfg = alembic_config(db_url)
    head = ScriptDirectory.from_config(cfg).get_current_head()
    assert head == "0004"

    command.downgrade(cfg, "base")
    empty = _snapshot(migrated_engine)
    assert empty == {"tables": set(), "enums": set(), "functions": set()}

    command.upgrade(cfg, "head")
    full = _snapshot(migrated_engine)
    assert full["tables"] == EXPECTED_TABLES
    assert full["enums"] == set(PG_ENUMS)
    assert full["functions"] == EXPECTED_FUNCTIONS
    with migrated_engine.connect() as c:
        assert MigrationContext.configure(c).get_current_revision() == head


def test_downgrade_seed_only(migrated_engine: Engine, db_url: URL) -> None:
    cfg = alembic_config(db_url)
    command.downgrade(cfg, "0001")
    with migrated_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM aggregate_type")).scalar_one() == 0
    command.upgrade(cfg, "head")
    with migrated_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM aggregate_type")).scalar_one() == 6


def test_orm_matches_migrations(migrated_engine: Engine) -> None:
    """Аналог `alembic revision --autogenerate` без diff."""
    with migrated_engine.connect() as c:
        ctx = MigrationContext.configure(c, opts={"compare_type": True})
        diff = compare_metadata(ctx, Base.metadata)
    assert diff == []


def test_enum_values_match_orm(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as c:
        for name, enum_cls in PG_ENUMS.items():
            values = list(
                c.execute(
                    text(
                        "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                        "WHERE t.typname = :n ORDER BY e.enumsortorder"
                    ),
                    {"n": name},
                ).scalars()
            )
            assert values == [m.value for m in enum_cls], name


def test_check_constraints_match_orm(migrated_engine: Engine) -> None:
    """autogenerate не сравнивает CHECK — сверяем имена явно."""
    expected = {
        str(c.name)
        for t in Base.metadata.tables.values()
        for c in t.constraints
        if isinstance(c, CheckConstraint)
    }
    with migrated_engine.connect() as c:
        actual = set(
            c.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE contype = 'c' AND connamespace = 'public'::regnamespace"
                )
            ).scalars()
        )
    assert actual == expected


def test_foreign_keys_have_explicit_on_delete(migrated_engine: Engine) -> None:
    """ADR 0003: ни один FK не остаётся с неявным NO ACTION."""
    with migrated_engine.connect() as c:
        implicit = list(
            c.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE contype = 'f' "
                    "AND confdeltype = 'a' AND connamespace = 'public'::regnamespace"
                )
            ).scalars()
        )
    assert implicit == []


def test_foreign_key_columns_are_indexed(migrated_engine: Engine) -> None:
    """Первая колонка каждого FK — ведущая колонка какого-либо индекса (RESTRICT, JOIN)."""
    insp_engine = create_engine(migrated_engine.url, poolclass=NullPool)
    missing = []
    with insp_engine.connect() as c:
        insp = inspect(c)
        for table in insp.get_table_names():
            # Частичные индексы (WHERE ...) не покрывают все строки и не считаются.
            prefixes = [
                tuple(i["column_names"])
                for i in insp.get_indexes(table)
                if not i.get("dialect_options", {}).get("postgresql_where")
            ]
            prefixes += [tuple(u["column_names"]) for u in insp.get_unique_constraints(table)]
            prefixes.append(tuple(insp.get_pk_constraint(table)["constrained_columns"]))
            for fk in insp.get_foreign_keys(table):
                cols = tuple(fk["constrained_columns"])
                if not any(p[:1] == cols[:1] for p in prefixes):
                    missing.append(f"{table}{cols}")
    insp_engine.dispose()
    assert missing == []
