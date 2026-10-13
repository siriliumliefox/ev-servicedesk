"""Миграции: полный цикл up/down/up, соответствие ORM ↔ БД, объекты вне autogenerate."""

import pytest
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
from tests.db.factories import make_ticket
from tests.db.seeds import SEED_TITLES

EXPECTED_TABLES = set(Base.metadata.tables)
EXPECTED_FUNCTIONS = {
    "vehicle_guard",
    "set_updated_at",
    "mileage_correction_before_insert",
    "mileage_correction_after_insert",
    "append_only_guard",
    "pd_consent_guard",
    "singleton_row_guard",
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
    assert head == "0014"

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


def test_downgrade_sla_policy_keeps_ticket_category(migrated_engine: Engine, db_url: URL) -> None:
    """0008 удаляет только свою таблицу: тип ticket_category нужен ticket.category (0001)."""
    cfg = alembic_config(db_url)
    command.downgrade(cfg, "0007")
    snapshot = _snapshot(migrated_engine)
    assert "ticket_sla_policy" not in snapshot["tables"]
    assert "ticket_category" in snapshot["enums"]
    command.upgrade(cfg, "head")
    with migrated_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM ticket_sla_policy")).scalar_one() == 5


def test_downgrade_knowledge_base(migrated_engine: Engine, db_url: URL) -> None:
    """0011 удаляет только свои сценарии, 0010 — свои колонки и таблицу версий (ADR 0018)."""
    cfg = alembic_config(db_url)
    count = "SELECT count(*) FROM knowledge_article WHERE article_type = 'troubleshooting'"
    with migrated_engine.begin() as c:
        assert c.execute(text(count)).scalar_one() == 5
        # Сценарий переименован администратором — всё равно сценарий миграции.
        c.execute(
            text("UPDATE knowledge_article SET title = 'Переименован' WHERE title = :t"),
            {"t": SEED_TITLES[0]},
        )
    with migrated_engine.begin() as c:
        # Статья администратора с заголовком сценария (копия) — не сценарий миграции.
        copy = c.execute(
            text(
                "INSERT INTO knowledge_article (article_type, category, title, is_published) "
                "VALUES ('troubleshooting', 'audio', :t, true) RETURNING id"
            ),
            {"t": SEED_TITLES[1]},
        ).scalar_one()
        c.execute(
            text(
                "INSERT INTO knowledge_article_revision (article_id, version, title, content) "
                "VALUES (:a, 1, :t, '')"
            ),
            {"a": copy, "t": SEED_TITLES[1]},
        )
    command.downgrade(cfg, "0010")
    with migrated_engine.connect() as c:
        left = c.execute(text("SELECT id FROM knowledge_article")).scalars().all()
        assert left == [copy], "удалены ровно 5 сценариев, копия осталась"
        assert c.execute(text("SELECT count(*) FROM decision_tree_node")).scalar_one() == 0
    with migrated_engine.begin() as c:
        c.execute(text("DELETE FROM knowledge_article WHERE id = :a"), {"a": copy})
    command.downgrade(cfg, "0009")
    snapshot = _snapshot(migrated_engine)
    assert "knowledge_article_revision" not in snapshot["tables"]
    assert "ticket_category" in snapshot["enums"], "тип нужен ticket.category (0001)"
    command.upgrade(cfg, "head")
    with migrated_engine.connect() as c:
        assert c.execute(text(count)).scalar_one() == 5
        assert c.execute(text("SELECT count(*) FROM knowledge_article_revision")).scalar_one() == 5


def test_downgrade_scenarios_refuses_when_tickets_reference_them(
    migrated_engine: Engine, db_url: URL
) -> None:
    """Тикет с «пометкой» сценария — откат 0011 останавливается, данные не теряются молча."""
    cfg = alembic_config(db_url)
    with migrated_engine.begin() as c:
        article = c.execute(
            text("SELECT id FROM knowledge_article ORDER BY id LIMIT 1")
        ).scalar_one()
        ticket = make_ticket(c, source_article_id=article, source_article_version=1)
    try:
        with pytest.raises(Exception, match="ссылаются тикеты"):
            command.downgrade(cfg, "0010")
        with migrated_engine.connect() as c:
            # Откат идёт одной транзакцией: отказ 0011 оставляет схему на head.
            head = ScriptDirectory.from_config(cfg).get_current_head()
            assert MigrationContext.configure(c).get_current_revision() == head
    finally:
        with migrated_engine.begin() as c:
            vehicle = c.execute(
                text("DELETE FROM ticket WHERE id = :t RETURNING vehicle_id"), {"t": ticket}
            ).scalar_one()
            user, model = c.execute(
                text("DELETE FROM vehicle WHERE id = :v RETURNING user_id, vehicle_model_id"),
                {"v": vehicle},
            ).one()
            c.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": user})
            c.execute(text("DELETE FROM vehicle_model WHERE id = :m"), {"m": model})


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
    """ADR 0003: ни один FK не остаётся с неявным NO ACTION."""
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
