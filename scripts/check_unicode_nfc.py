#!/usr/bin/env python3
"""Проверка: текстовые файлы под git записаны в Unicode NFC.

NFD («и» + U+0306 вместо «й») появляется после копирования через macOS и незаметен
глазом, но ломает сравнение строк, поиск и данные, которые уходят в БД и API.

Использование:
    python3 scripts/check_unicode_nfc.py         # exit 1 и список файлов, если есть NFD
    python3 scripts/check_unicode_nfc.py --fix   # нормализовать файлы к NFC
"""
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTENSIONS = {
    ".py", ".sql", ".yaml", ".yml", ".md", ".ts", ".tsx", ".mts",
    ".dart", ".json", ".sh", ".html", ".mermaid",
}
# Lock-файлы генерируются менеджерами пакетов — не проверяются.
SKIP_NAMES = {"package-lock.json", "poetry.lock"}
# Применённая seed-миграция 0002 записала названия агрегатов в NFD; менять её строки
# нельзя (исправляет data-миграция 0007), а DDL рендерится из миграций и повторяет их.
ALLOWED_NFD = {
    "backend/alembic/versions/0002_seed_aggregate_types.py",
    "docs/EV_ServiceDesk_Glava2_DDL.sql",
}


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode("utf-8")
    return [
        path for path in out.split("\0")
        if Path(path).suffix in EXTENSIONS
        and Path(path).name not in SKIP_NAMES
        and path not in ALLOWED_NFD
    ]


def main() -> int:
    fix = "--fix" in sys.argv
    bad = []
    for path in tracked_files():
        file = ROOT / path
        if not file.is_file():
            continue
        text = file.read_text(encoding="utf-8")
        normalized = unicodedata.normalize("NFC", text)
        if text != normalized:
            bad.append(path)
            if fix:
                file.write_bytes(normalized.encode("utf-8"))
    if not bad:
        print("All text files are Unicode NFC")
        return 0
    if fix:
        print(f"Normalized to NFC ({len(bad)}):", *bad, sep="\n  ")
        return 0
    print(f"ERROR: files not in Unicode NFC ({len(bad)}):", *bad, sep="\n  ")
    print("Run: python3 scripts/check_unicode_nfc.py --fix")
    return 1


if __name__ == "__main__":
    sys.exit(main())
