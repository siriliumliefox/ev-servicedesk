"""Unit-тесты VIN (Глава 11): формат 17 символов, алфавит без I/O/Q, мок-декодер."""

import re

import pytest
from pydantic import ValidationError

from app.api.vehicle_schemas import VehicleCreateRequest
from app.domain.vehicles.vin import (
    VIN_PATTERN,
    DecodedVehicle,
    InvalidVinError,
    MockVinDecoder,
    validate_vin,
)
from tests.api.conftest import contract

VALID = [
    "L6TZ0010000000001",
    "LSVAU2183R2100001",  # пример из контракта
    "WVWZZZ1KZAW000001",  # VIN из ЕС: 9-й символ не контрольная цифра — принимается
    "12345678901234567",
    "ABCDEFGHJKLMNPRST",
]


@pytest.mark.parametrize("vin", VALID)
def test_valid_vin_accepted(vin: str) -> None:
    assert validate_vin(vin) == vin


@pytest.mark.parametrize(
    ("vin", "reason"),
    [
        ("", "17 символов, получено 0"),
        ("L6TZ001000000000", "получено 16"),  # 16 — граница снизу
        ("L6TZ00100000000012", "получено 18"),  # 18 — граница сверху
        ("L6TZ00100000000I1", "буквы I"),
        ("L6TZ00100000000O1", "буквы O"),
        ("L6TZ00100000000Q1", "буквы Q"),
        ("IOQZ0010000000001", "буквы I, O, Q"),
        ("l6tz0010000000001", "недопустимые символы"),  # строчные — 422 по контракту (Q9)
        ("L6TZ00100000000-1", "недопустимые символы"),
        ("L6TZ00100000000 1", "недопустимые символы"),
        ("L6TZ00100000000Ж1", "недопустимые символы"),
    ],
)
def test_invalid_vin_rejected_with_reason(vin: str, reason: str) -> None:
    with pytest.raises(InvalidVinError, match=reason):
        validate_vin(vin)


def test_pattern_matches_contract_and_db() -> None:
    schema = contract()["components"]["schemas"]["VehicleCreateRequest"]["properties"]["vin"]
    assert VIN_PATTERN.pattern == schema["pattern"]
    # Тот же шаблон в CHECK vin_format (docs/EV_ServiceDesk_Glava2_DDL.sql).
    from tests.api.conftest import DOCS

    ddl = (DOCS / "EV_ServiceDesk_Glava2_DDL.sql").read_text(encoding="utf-8")
    assert re.search(re.escape(f"vin ~ '{VIN_PATTERN.pattern}'"), ddl)


def test_request_schema_reports_reason() -> None:
    with pytest.raises(ValidationError, match="буквы O"):
        VehicleCreateRequest(vin="L6TZ00100000000O1")
    with pytest.raises(ValidationError):
        VehicleCreateRequest(vin=12345678901234567)  # не строка


def test_mock_decoder_recognizes_zeekr_prefix() -> None:
    assert MockVinDecoder().decode("L6TZ0010000000001") == DecodedVehicle("Zeekr", "001")


def test_mock_decoder_unknown_vin_is_none() -> None:
    assert MockVinDecoder().decode("LSVAU2183R2100001") is None
    # Только WMI Zeekr без известного VDS — модель не угадывается.
    assert MockVinDecoder().decode("L6TX9990000000001") is None


def test_mock_decoder_prefers_longest_prefix() -> None:
    decoder = MockVinDecoder(
        {"L6T": DecodedVehicle("Zeekr", "generic"), "L6TZ001": DecodedVehicle("Zeekr", "001")}
    )
    assert decoder.decode("L6TZ0010000000001").model == "001"
    assert decoder.decode("L6TX0010000000001").model == "generic"
