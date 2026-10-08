"""docs/EV_ServiceDesk_Glava2_DDL.sql должен совпадать с offline-рендером миграций (без БД)."""

from scripts.export_ddl import DDL_PATH, render


def test_ddl_file_in_sync_with_migrations() -> None:
    assert (
        DDL_PATH.read_text(encoding="utf-8") == render()
    ), "DDL устарел: cd backend && poetry run python scripts/export_ddl.py"
