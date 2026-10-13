#!/usr/bin/env python3
"""Данные веб-кабинета инженера на стеке (глава 21, ADR 0025 п. 14, 15).

Таблица — docs/specs/engineer_web_flow.json. На работающем стеке (scripts/integration_stack.sh —
окружение команды после «--»):

  seed --out FILE  — два инженера (пароли случайные), клиент E2E_WEB_PHONE с авто, опубликованная
                     статья для быстрого ответа, тикеты клиента разных категорий для доски
                     (--board-tickets, по умолчанию все из таблицы) и наборы тикетов Playwright
                     (--e2e-sets: по набору из 3 тикетов на браузер). В FILE (0600) — входы
                     инженеров, токены клиента, id авто и тикетов, заголовок статьи; на экран
                     пароли и токены не выводятся. Клиент создаёт не больше 10 тикетов в час
                     (ticket_create_per_user_hour) — тикеты заводятся здесь, а не в тестах.

  cd backend && poetry run python scripts/e2e_engineer.py seed --out /tmp/seed.json --e2e-sets 1

Окружение: API_BASE_URL, E2E_JOB_RUNNER (CLI администратора в контейнере стека), E2E_WEB_PHONE и
E2E_CODE (тестовый номер стека, SMS не отправляется). Каждый ответ сверяется с docs/openapi.yaml.
"""

import argparse
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any

from e2e_backend import (
    ZEEKR_VIN_PREFIX,
    Api,
    Failed,
    Headers,
    Jobs,
    bootstrap_admin,
    check,
    digits,
    register_client,
    staff_login,
)

TABLE = Path(__file__).resolve().parents[2] / "docs" / "specs" / "engineer_web_flow.json"
ENGINEERS = 2


def create_engineer_account(api: Api, admin: Headers) -> dict[str, str]:
    phone, password = "+3752999" + digits(5), secrets.token_urlsafe(18)
    body = {"phone": phone, "role": "engineer", "password": password}
    user = api.json("POST", "/users", 201, headers=admin, json=body)
    check(user["role"] == "engineer" and user["is_active"], "сотрудник создан не инженером")
    staff_login(api, phone, password)  # вход проверен до передачи в тесты
    return {"phone": phone, "password": password}


def publish_quick_reply(api: Api, admin: Headers, article: dict[str, str]) -> None:
    body = {"article_type": "guide", "title": article["title"], "content": article["content"]}
    created = api.json("POST", "/knowledge-articles", 201, headers=admin, json=body)
    body = {"is_published": True}
    api.json("PATCH", f"/knowledge-articles/{created['id']}", headers=admin, json=body)


def e2e_set(api: Api, client: Headers, vehicle_id: int, texts: dict[str, str]) -> dict[str, int]:
    """Тикеты одного браузера: сценарий E2E и две гонки (кнопкой и перетаскиванием)."""
    tickets = {
        "flow": texts["flow_description"],
        "race_button": f"{texts['race_description']} Кнопка.",
        "race_drag": f"{texts['race_description']} Перетаскивание.",
    }
    return {
        key: api.json(
            "POST",
            "/tickets",
            201,
            headers=client,
            json={"vehicle_id": vehicle_id, "category": "navigation", "description": text},
        )["id"]
        for key, text in tickets.items()
    }


def seed(
    api: Api,
    admin: Headers,
    table: dict[str, Any],
    phone: str,
    code: str,
    board_tickets: int,
    e2e_sets: int,
) -> dict[str, Any]:
    engineers = [create_engineer_account(api, admin) for _ in range(ENGINEERS)]
    publish_quick_reply(api, admin, table["quick_reply"])
    client = register_client(api, phone, code)
    vin = ZEEKR_VIN_PREFIX + digits(10)
    car = api.json("POST", "/vehicles", 201, headers=client.headers, json={"vin": vin})
    tickets = []
    for item in table["tickets"][:board_tickets]:
        body = {"vehicle_id": car["id"], **item}
        tickets.append(api.json("POST", "/tickets", 201, headers=client.headers, json=body)["id"])
    sets = [e2e_set(api, client.headers, car["id"], table["e2e"]) for _ in range(e2e_sets)]
    print(
        f"PASS  инженеров: {len(engineers)}, клиент с авто №{car['id']}, тикеты доски {tickets}, "
        f"наборов E2E: {len(sets)}, статья «{table['quick_reply']['title']}»"
    )
    return {
        "engineers": engineers,
        "client": {
            "phone": phone,
            "access_token": client.headers["Authorization"].removeprefix("Bearer "),
            "refresh_token": client.refresh_token,
            "vehicle_id": car["id"],
        },
        "quick_reply_title": table["quick_reply"]["title"],
        "tickets": tickets,
        "e2e_sets": sets,
    }


def write_private(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.chmod(path, 0o600)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    seed_args = sub.add_parser("seed")
    seed_args.add_argument("--out", type=Path, required=True)
    seed_args.add_argument("--board-tickets", type=int, default=None)
    seed_args.add_argument("--e2e-sets", type=int, default=0)
    args = parser.parse_args(argv)

    env = os.environ
    names = ("API_BASE_URL", "E2E_JOB_RUNNER", "E2E_WEB_PHONE", "E2E_CODE")
    missing = [n for n in names if not env.get(n)]
    if missing:
        print(f"Нужны {', '.join(missing)} — запускается из scripts/integration_stack.sh")
        return 2
    api = Api(env["API_BASE_URL"])
    table = json.loads(TABLE.read_text(encoding="utf-8"))
    try:
        admin = bootstrap_admin(api, Jobs(env["E2E_JOB_RUNNER"]))
        board = len(table["tickets"]) if args.board_tickets is None else args.board_tickets
        data = seed(api, admin, table, env["E2E_WEB_PHONE"], env["E2E_CODE"], board, args.e2e_sets)
    except Failed as exc:
        print(f"FAIL  {exc}")
        return 1
    write_private(args.out, data)
    print(f"PASS  данные для входа — {args.out} (0600)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
