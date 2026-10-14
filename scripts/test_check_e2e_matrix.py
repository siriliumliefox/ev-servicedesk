"""Тесты стража матрицы E2E (scripts/check_e2e_matrix.py, ADR 0027 п. 1): каждое правило ловит нарушение.

Запуск: python3 -m unittest scripts/test_check_e2e_matrix.py
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_e2e_matrix import backlog, check_matrix  # noqa: E402

BACKLOG = """| ID | Функция | Приоритет |
|---|---|---|
| C-01 | Вход | Must |
| C-12 | Несколько авто | Should |
"""

SPEC = """test('вход по SMS → карточка', async () => {})
testWidgets('схема — 1 тап', (tester) async {})
"""

PYTEST = """def test_login_rate_limit(client):
    step("регистрация клиента", register)
"""


class CheckMatrixTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / "BACKLOG.md").write_text(BACKLOG, encoding="utf-8")
        (self.root / "app.spec.ts").write_text(SPEC, encoding="utf-8")
        (self.root / "test_api.py").write_text(PYTEST, encoding="utf-8")
        self.requirements = backlog(self.root / "BACKLOG.md")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def scenario(self, **override: object) -> dict:
        base = {
            "id": "E2E-01",
            "title": "Вход",
            "roles": ["client"],
            "priority": "P0",
            "requirements": ["C-01"],
            "tests": [{"level": "web", "ref": "app.spec.ts::вход по SMS"}],
        }
        return {**base, **override}

    def errors(self, *scenarios: dict) -> list[str]:
        return check_matrix({"scenarios": list(scenarios)}, self.requirements, self.root)

    def test_backlog_parses_ids_and_moscow(self) -> None:
        self.assertEqual(self.requirements, {"C-01": "Must", "C-12": "Should"})

    def test_valid_matrix_passes(self) -> None:
        pytest_ref = {"level": "unit", "ref": "test_api.py::test_login_rate_limit"}
        step_ref = {"level": "backend", "ref": "test_api.py::регистрация клиента"}
        widget_ref = {"level": "widget", "ref": "app.spec.ts::схема — 1 тап"}
        self.assertEqual(self.errors(self.scenario(tests=[pytest_ref, step_ref, widget_ref])), [])

    def test_missing_test_name_or_file(self) -> None:
        wrong_name = self.scenario(tests=[{"level": "web", "ref": "app.spec.ts::выход"}])
        self.assertIn("E2E-01: в app.spec.ts нет теста «выход»", self.errors(wrong_name))
        wrong_file = self.scenario(tests=[{"level": "web", "ref": "nope.spec.ts::вход"}])
        self.assertIn("E2E-01: файла теста нет: nope.spec.ts", self.errors(wrong_file))
        outside = self.scenario(tests=[{"level": "web", "ref": "../etc/passwd::root"}])
        self.assertIn("E2E-01: файла теста нет: ../etc/passwd", self.errors(outside))

    def test_uncovered_must(self) -> None:
        other = self.scenario(requirements=["C-12"], priority="P1")
        self.assertIn("Must-требование C-01 не покрыто ни одним сценарием", self.errors(other))

    def test_p0_needs_must_and_e2e_level(self) -> None:
        should = self.scenario(requirements=["C-01", "C-12"])
        self.assertIn("E2E-01: P0 — только Must, а C-12 — Should", self.errors(should))
        unit_only = self.scenario(tests=[{"level": "unit", "ref": "test_api.py::test_login_rate_limit"}])
        self.assertTrue(any("у P0 нет теста уровня E2E" in e for e in self.errors(unit_only)))

    def test_ids_roles_priority_check(self) -> None:
        duplicate = self.errors(self.scenario(), self.scenario())
        self.assertIn("E2E-01: id повторяется", duplicate)
        bad = self.errors(self.scenario(id="X-1", roles=["guest"], priority="P9", requirements=["Z-99"]))
        self.assertIn("X-1: id должен быть E2E-NN", bad)
        self.assertTrue(any("роли" in e for e in bad))
        self.assertTrue(any("приоритет" in e for e in bad))
        self.assertIn("X-1: требования Z-99 нет в бэклоге", bad)
        no_tests = self.scenario(priority="P2", requirements=["C-12"], tests=[])
        self.assertIn("E2E-01: нет тестов и не указано, как проверяется (check)", self.errors(self.scenario(id="E2E-02"), no_tests))
        allowed = self.scenario(priority="P2", requirements=["C-12"], tests=[], check="chapter-27")
        self.assertEqual(self.errors(self.scenario(id="E2E-02"), allowed), [])


if __name__ == "__main__":
    unittest.main()
