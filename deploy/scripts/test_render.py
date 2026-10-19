"""Тесты render.py (глава 26): только ${EV_*}, ошибки и условные блоки (python3 -m unittest)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render import render  # noqa: E402


class RenderTest(unittest.TestCase):
    def test_substitutes_only_ev_variables(self) -> None:
        text = 'url: ${EV_HOST}\nsummary: "{{ $labels.env }} ${OTHER} $EV_HOST"\n'
        out = render(text, {"EV_HOST": "api.example"})
        self.assertEqual(out, 'url: api.example\nsummary: "{{ $labels.env }} ${OTHER} $EV_HOST"\n')

    def test_unknown_variable_is_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "EV_MISSING"):
            render("x: ${EV_MISSING}\n", {})

    def test_conditional_block(self) -> None:
        text = "a\n# ev:if EV_CHAT\nchat: ${EV_CHAT}\n# ev:endif\nb\n"
        self.assertEqual(render(text, {"EV_CHAT": "42"}), "a\nchat: 42\nb\n")
        self.assertEqual(render(text, {"EV_CHAT": ""}), "a\nb\n")

    def test_unbalanced_blocks(self) -> None:
        with self.assertRaises(ValueError):
            render("# ev:if EV_X\n", {"EV_X": "1"})
        with self.assertRaises(ValueError):
            render("# ev:endif\n", {})


if __name__ == "__main__":
    unittest.main()
