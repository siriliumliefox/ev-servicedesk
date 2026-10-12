"""Данные миграций-сидов для тестов: модули alembic/versions — не пакет, загружаются по пути."""

import importlib.util
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Заголовки сценариев «Устранение неполадок» миграции 0011 (ADR 0018 п. 12).
SEED_TITLES: list[str] = _load("0011_seed_troubleshooting_scenarios").TITLES
