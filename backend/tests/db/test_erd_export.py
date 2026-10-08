"""docs/ERD_EV_ServiceDesk_Glava2.mermaid должен совпадать с рендером ORM-метаданных (без БД)."""

from scripts.export_erd import ERD_PATH, render


def test_erd_file_in_sync_with_models() -> None:
    assert (
        ERD_PATH.read_text(encoding="utf-8") == render()
    ), "ERD устарел: cd backend && poetry run python scripts/export_erd.py"
