#!/usr/bin/env python3
"""Рендер конфигураций с переменными окружения (глава 26, ADR 0030 п. 5).

    render.py <шаблон> <результат>

Подставляет только `${EV_ИМЯ}` — `$labels`, `{{ ... }}` и прочие `$` в правилах Prometheus и
шаблонах Alertmanager остаются как есть (envsubst заменил бы и их). Неизвестная переменная —
ошибка (без тихих пустых адресов). Блок строк между `# ev:if EV_ИМЯ` и `# ev:endif` остаётся,
только если переменная непуста (например, получатель Telegram — когда задан chat_id).
Только стандартная библиотека: работает на ВМ (Ubuntu 24.04) и на Mac стенда.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

VAR = re.compile(r"\$\{(EV_[A-Z0-9_]+)\}")
IF = re.compile(r"^\s*# ev:if (EV_[A-Z0-9_]+)\s*$")
ENDIF = re.compile(r"^\s*# ev:endif\s*$")


def render(text: str, env: dict[str, str]) -> str:
    out: list[str] = []
    keep: bool | None = None
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        if m := IF.match(line):
            if keep is not None:
                raise ValueError(f"строка {number}: вложенный ev:if")
            keep = bool(env.get(m.group(1)))
            continue
        if ENDIF.match(line):
            if keep is None:
                raise ValueError(f"строка {number}: ev:endif без ev:if")
            keep = None
            continue
        if keep is False:
            continue

        def substitute(match: re.Match[str], number: int = number) -> str:
            name = match.group(1)
            if name not in env:
                raise ValueError(f"строка {number}: не задана переменная {name}")
            return env[name]

        out.append(VAR.sub(substitute, line))
    if keep is not None:
        raise ValueError("ev:if без ev:endif")
    return "".join(out)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        result = render(Path(argv[1]).read_text(encoding="utf-8"), dict(os.environ))
    except ValueError as exc:
        print(f"render.py {argv[1]}: {exc}", file=sys.stderr)
        return 1
    target = Path(argv[2])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(result, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
