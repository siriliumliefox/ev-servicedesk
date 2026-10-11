"""VIN: проверка формата и декодер марки/модели (Глава 11, ADR 0014).

Формат — как CHECK vin_format в БД и шаблон контракта: 17 символов, цифры и латиница
без I, O, Q. Контрольная цифра (9-й символ) не проверяется: она обязательна в США и Китае,
но не в Европе — проверка отклонила бы настоящие VIN авто, ввезённых из ЕС.
"""

import re
from dataclasses import dataclass
from typing import Protocol

VIN_LENGTH = 17
VIN_PATTERN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
_FORBIDDEN = frozenset("IOQ")


class InvalidVinError(ValueError):
    """VIN не соответствует формату; сообщение — для поля details ответа 422."""


def validate_vin(vin: str) -> str:
    """Возвращает VIN без изменений или поднимает InvalidVinError с причиной."""
    if len(vin) != VIN_LENGTH:
        raise InvalidVinError(f"VIN должен содержать {VIN_LENGTH} символов, получено {len(vin)}")
    forbidden = sorted({ch for ch in vin if ch in _FORBIDDEN})
    if forbidden:
        raise InvalidVinError(f"VIN не может содержать буквы {', '.join(forbidden)}")
    if not VIN_PATTERN.fullmatch(vin):
        raise InvalidVinError("VIN содержит недопустимые символы: только A–Z (кроме I, O, Q) и 0–9")
    return vin


@dataclass(frozen=True)
class DecodedVehicle:
    brand: str
    model: str
    trim: str = ""  # '' — без комплектации, как vehicle_model.trim


class VinDecoder(Protocol):
    def decode(self, vin: str) -> DecodedVehicle | None:
        """Марка/модель по VIN или None, если VIN не распознан."""
        ...


# Префикс VIN → модель. WMI (символы 1–3) Zeekr — L6T: письмо Zeekr в NHTSA по 49 CFR 565
# (2026). Символы 4–8 (VDS) — демонстрационные, не из реестра производителя (ADR 0014).
# Коды Li Auto и Voyah в открытых источниках не подтверждены: такие VIN декодер не
# распознаёт, и клиент выбирает модель вручную (GET /vehicle-models).
MOCK_TABLE: dict[str, DecodedVehicle] = {
    "L6TZ001": DecodedVehicle(brand="Zeekr", model="001"),
}


class MockVinDecoder:
    """Мок вместо внешнего API: VIN — ПД (ADR 0005), за пределы системы не передаётся."""

    def __init__(self, table: dict[str, DecodedVehicle] | None = None) -> None:
        self._table = MOCK_TABLE if table is None else table
        # Самый длинный совпавший префикс — точнее.
        self._prefixes = sorted(self._table, key=len, reverse=True)

    def decode(self, vin: str) -> DecodedVehicle | None:
        for prefix in self._prefixes:
            if vin.startswith(prefix):
                return self._table[prefix]
        return None
