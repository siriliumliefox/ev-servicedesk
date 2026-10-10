"""Алгоритм «светофор» на сценариях Главы 5 (docs/specs/aggregate_status_scenarios.yaml).

Тот же YAML — источник ожиданий для модульных тестов сервиса Главы 12; таблицы §5
спецификации обязаны совпадать с ним (test_spec_tables_match_yaml).
"""

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from app.domain.aggregates import (
    Regulation,
    Replacement,
    Thresholds,
    TrafficLight,
    add_months,
    becomes_current,
    compute_status,
)

SPECS = Path(__file__).resolve().parents[3] / "docs" / "specs"
SCENARIOS = yaml.safe_load((SPECS / "aggregate_status_scenarios.yaml").read_text(encoding="utf-8"))
SPEC_MD = (SPECS / "AGGREGATE_STATUS_ALGORITHM.md").read_text(encoding="utf-8")
DEFAULTS = SCENARIOS["defaults"]


def _replacement(raw: dict | None) -> Replacement | None:
    return None if raw is None else Replacement(raw.get("replaced_at"), raw.get("mileage"))


def _run(case: dict):
    regulation = case["regulation"]
    return compute_status(
        regulation=None if regulation is None else Regulation(**regulation),
        last=_replacement(case["last"]),
        current_mileage=case["current_mileage"],
        today=case.get("today", DEFAULTS["today"]),
        thresholds=Thresholds(**case.get("thresholds", DEFAULTS["thresholds"])),
    )


@pytest.mark.parametrize("case", SCENARIOS["status"], ids=lambda c: c["id"])
def test_status_scenario(case: dict) -> None:
    result = _run(case)
    expect = case["expect"]
    if expect is None:
        assert result is None
        return
    assert result is not None
    assert result.status is TrafficLight(expect["status"])
    percentage = expect["percentage"]
    assert result.percentage == (None if percentage is None else Decimal(percentage))
    assert result.remaining_km == expect["remaining_km"]
    assert result.remaining_days == expect["remaining_days"]


@pytest.mark.parametrize("case", SCENARIOS["replacement"], ids=lambda c: c["id"])
def test_replacement_scenario(case: dict) -> None:
    current = _replacement(case["current"])
    assert becomes_current(current, case["new"]["replaced_at"]) is case["becomes_current"]


def test_scenarios_cover_checklist_boundaries() -> None:
    """MASTER_CHECKLIST, Глава 5: границы 69/70/100/101% и «нет данных о замене»."""
    percents = {c["expect"]["percentage"] for c in SCENARIOS["status"] if c["expect"]}
    assert {"69.0", "70.0", "100.0", "101.0"} <= percents
    assert any(
        c["last"] is None and c["expect"]["status"] == "unknown" for c in SCENARIOS["status"]
    )


# --- Синхронность спецификации и YAML ---------------------------------------------------


def _md_rows(prefix: str) -> dict[str, list[str]]:
    rows = {}
    for line in SPEC_MD.splitlines():
        if re.match(rf"^\| {prefix}\d\d \|", line):
            cells = [c.strip() for c in line.strip("|").split("|")]
            rows[cells[0]] = cells
    return rows


def _md_value(token: str) -> str | int | None:
    token = token.strip().replace("−", "-")
    if token == "—":
        return None
    return int(token) if re.fullmatch(r"-?\d+", token) else token


def test_spec_tables_match_yaml() -> None:
    status_rows = _md_rows("S")
    assert sorted(status_rows) == [c["id"] for c in SCENARIOS["status"]]
    for case in SCENARIOS["status"]:
        expectation = re.sub(r"\s*\(.*\)$", "", status_rows[case["id"]][-1])
        if case["expect"] is None:
            assert expectation.startswith("не возвращается"), case["id"]
            continue
        status, percentage, remaining_km, remaining_days = map(_md_value, expectation.split("/"))
        expect = case["expect"]
        assert (status, percentage, remaining_km, remaining_days) == (
            expect["status"],
            expect["percentage"],
            expect["remaining_km"],
            expect["remaining_days"],
        ), case["id"]

    replacement_rows = _md_rows("R")
    assert sorted(replacement_rows) == [c["id"] for c in SCENARIOS["replacement"]]
    for case in SCENARIOS["replacement"]:
        expectation = replacement_rows[case["id"]][-1]
        assert expectation.startswith("становится текущей") is case["becomes_current"], case["id"]


# --- Отдельные правила ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (date(2026, 1, 31), 1, date(2026, 2, 28)),
        (date(2028, 1, 31), 1, date(2028, 2, 29)),
        (date(2026, 3, 31), 1, date(2026, 4, 30)),
        (date(2026, 11, 15), 3, date(2027, 2, 15)),
        (date(2026, 10, 10), 24, date(2028, 10, 10)),
    ],
)
def test_add_months(start: date, months: int, expected: date) -> None:
    assert add_months(start, months) == expected


def test_exact_boundary_not_affected_by_float() -> None:
    """7 000 / 10 000 и 1/3 интервала: сравнение в дробях, без ошибок float."""
    regulation = Regulation(interval_km=3)
    result = compute_status(regulation, Replacement(mileage=0), 1, date(2026, 1, 1), Thresholds())
    assert result is not None and result.status is TrafficLight.GREEN
    assert result.percentage == Decimal("33.3")


def test_unknown_when_regulation_has_no_matching_history() -> None:
    result = compute_status(
        Regulation(interval_months=12),
        Replacement(mileage=1000),
        5000,
        date(2026, 1, 1),
        Thresholds(),
    )
    assert result is not None and result.status is TrafficLight.UNKNOWN
