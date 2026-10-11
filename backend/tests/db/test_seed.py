"""Seed справочника агрегатов — утверждённые коды baseline v1 (ADR 0002)."""

import unicodedata

from sqlalchemy import Connection, text

APPROVED_CODES = {
    "engine_oil",
    "oil_filter",
    "air_filter",
    "cabin_filter",
    "gearbox_oil",
    "ac_refrigerant",
}


def test_seed_contains_exactly_approved_codes(conn: Connection) -> None:
    rows = conn.execute(text("SELECT code, name FROM aggregate_type")).all()
    assert {r.code for r in rows} == APPROVED_CODES
    assert all(r.name.strip() for r in rows)
    # Миграция 0007: seed 0002 содержал NFD («и» + U+0306 вместо «й»).
    assert all(r.name == unicodedata.normalize("NFC", r.name) for r in rows)
    assert ("cabin_filter", "Салонный фильтр") in {(r.code, r.name) for r in rows}


def test_seed_contains_serviced_vehicle_models(conn: Connection) -> None:
    """Справочник моделей (Глава 11, ADR 0014): модели, которые обслуживает ETS AUTO."""
    rows = conn.execute(text("SELECT brand, model, trim FROM vehicle_model")).all()
    assert {(r.brand, r.model, r.trim) for r in rows} >= {
        ("Zeekr", "001", ""),
        ("Voyah", "Free", ""),
        ("Li Auto", "L7", ""),
    }
