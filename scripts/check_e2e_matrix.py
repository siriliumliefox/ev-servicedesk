#!/usr/bin/env python3
"""Страж матрицы сценариев E2E (глава 23, ADR 0027 п. 1): docs/specs/e2e_matrix.yaml сверяется с бэклогом
и тестами репозитория.

Проверки:
- id сценариев — E2E-NN, без повторов; роли, приоритет, уровни тестов и `check` — из допустимых;
- требования сценария есть в docs/requirements/BACKLOG.md, каждое Must покрыто хотя бы одним сценарием;
- P0 — только Must-требования и хотя бы один тест уровня E2E (backend, mobile-api, mobile-ui, web, system);
- тест — «файл::имя»: файл есть, имя — подстрока объявления теста в нём (test('…'), testWidgets('…'),
  it('…'), group('…'), def test_…, шаг step("…") сценария backend);
- у сценария без тестов есть `check` (как он проверяется).

Нужен PyYAML. Запуск: python3 scripts/check_e2e_matrix.py [--matrix FILE] [--root DIR]
"""

import argparse
import re
import sys
from pathlib import Path

import yaml

ROLES = {"client", "engineer", "admin"}
PRIORITIES = {"P0", "P1", "P2"}
E2E_LEVELS = {"backend", "mobile-api", "mobile-ui", "web", "system"}
LEVELS = E2E_LEVELS | {"unit", "widget", "tokens"}
CHECKS = {"exploratory", "manual", "not-implemented"}
CHECK_CHAPTER = re.compile(r"^chapter-\d{2}$")
ID = re.compile(r"^E2E-\d{2}$")
BACKLOG_ROW = re.compile(r"^\|\s*([A-Z]-\d{2})\s*\|.*\|\s*(Must|Should|Could|Won't)\s*\|\s*$")
# Объявление теста: имя теста — строковый литерал вызова или имя функции pytest.
DECLARATION = re.compile(
    r"""(?:\b(?:test|testWidgets|it|group|describe|step)\s*\(\s*(?P<q>['"`])(?P<name>.*?)(?P=q))"""
    r"""|(?:^\s*def\s+(?P<func>test_\w+))""",
    re.MULTILINE | re.DOTALL,
)


def backlog(path: Path) -> dict[str, str]:
    """ID требования → приоритет MoSCoW."""
    rows = (BACKLOG_ROW.match(line) for line in path.read_text(encoding="utf-8").splitlines())
    return {m.group(1): m.group(2) for m in rows if m}


def declarations(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [m.group("name") or m.group("func") for m in DECLARATION.finditer(text)]


def check_matrix(matrix: dict, requirements: dict[str, str], root: Path) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    covered: set[str] = set()
    cache: dict[Path, list[str]] = {}

    for index, scenario in enumerate(matrix.get("scenarios") or []):
        sid = str(scenario.get("id", f"#{index + 1}"))
        where = f"{sid}:"
        if not ID.match(sid):
            errors.append(f"{where} id должен быть E2E-NN")
        if sid in seen:
            errors.append(f"{where} id повторяется")
        seen.add(sid)
        if not str(scenario.get("title", "")).strip():
            errors.append(f"{where} нет названия")
        roles = scenario.get("roles") or []
        if not roles or set(roles) - ROLES:
            errors.append(f"{where} роли — непустой список из {sorted(ROLES)}, получено {roles}")
        priority = scenario.get("priority")
        if priority not in PRIORITIES:
            errors.append(f"{where} приоритет — один из {sorted(PRIORITIES)}, получено {priority!r}")

        reqs = scenario.get("requirements") or []
        if not reqs:
            errors.append(f"{where} нет требований")
        for req in reqs:
            if req not in requirements:
                errors.append(f"{where} требования {req} нет в бэклоге")
            elif priority == "P0" and requirements[req] != "Must":
                errors.append(f"{where} P0 — только Must, а {req} — {requirements[req]}")
        covered.update(reqs)

        tests = scenario.get("tests") or []
        check = scenario.get("check")
        if check is not None and check not in CHECKS and not CHECK_CHAPTER.match(str(check)):
            errors.append(f"{where} check — один из {sorted(CHECKS)} или chapter-NN, получено {check!r}")
        if not tests and check is None:
            errors.append(f"{where} нет тестов и не указано, как проверяется (check)")
        if priority == "P0" and not any(t.get("level") in E2E_LEVELS for t in tests):
            errors.append(f"{where} у P0 нет теста уровня E2E ({', '.join(sorted(E2E_LEVELS))})")

        for test in tests:
            level, ref = test.get("level"), str(test.get("ref", ""))
            if level not in LEVELS:
                errors.append(f"{where} уровень теста {level!r} не из {sorted(LEVELS)}")
            file, sep, name = ref.partition("::")
            if not sep or not file or not name:
                errors.append(f"{where} ссылка на тест — «файл::имя», получено {ref!r}")
                continue
            path = (root / file).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                errors.append(f"{where} файла теста нет: {file}")
                continue
            names = cache.setdefault(path, declarations(path))
            if not any(name in declared for declared in names):
                errors.append(f"{where} в {file} нет теста «{name}»")

    for req, moscow in sorted(requirements.items()):
        if moscow == "Must" and req not in covered:
            errors.append(f"Must-требование {req} не покрыто ни одним сценарием")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    root_default = Path(__file__).resolve().parents[1]
    parser.add_argument("--root", type=Path, default=root_default)
    parser.add_argument("--matrix", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    matrix_path = args.matrix or root / "docs/specs/e2e_matrix.yaml"

    matrix = yaml.safe_load(matrix_path.read_text(encoding="utf-8")) or {}
    requirements = backlog(root / "docs/requirements/BACKLOG.md")
    errors = check_matrix(matrix, requirements, root)
    scenarios = matrix.get("scenarios") or []
    p0 = sum(1 for s in scenarios if s.get("priority") == "P0")
    if errors:
        for error in errors:
            print(f"FAIL  {error}")
        return 1
    must = sum(1 for m in requirements.values() if m == "Must")
    print(f"PASS  сценариев: {len(scenarios)}, P0: {p0}, Must-требований покрыто: {must}/{must}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
