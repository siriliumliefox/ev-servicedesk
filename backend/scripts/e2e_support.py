#!/usr/bin/env python3
"""Данные и действия персонала для клиентского сценария главы 20 (ADR 0024 п. 1, 12).

Таблица — docs/specs/support_flow.json. На работающем стеке (scripts/integration_stack.sh —
окружение команды после «--») от имени персонала:

  seed     — статья «Обучения» и статья «Устранения неполадок» с деревом решений, обе опубликованы;
  publish  — новость и акция для всех моделей (аудитория — клиенты на момент публикации);
  reply    — ответ инженера в чат тикета: взять в работу (или переназначить) и написать;
             --status resolved — затем решить тикет (push «Статус обращения»);
  answer   — для UI E2E (mobile/scripts/e2e_ui.sh): дождаться нового тикета из дерева решений,
             ответить в чат и опубликовать новость и акцию (клиент к этому времени уже есть).

  cd backend && poetry run python scripts/e2e_support.py seed
  cd backend && poetry run python scripts/e2e_support.py reply --ticket 12

Окружение: API_BASE_URL, E2E_JOB_RUNNER (префикс разовой задачи в контейнере стека — CLI
администратора). Каждый ответ сверяется с docs/openapi.yaml (как e2e_backend.py).
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from e2e_backend import Api, Failed, Headers, Jobs, bootstrap_admin, check, create_engineer

TABLE = Path(__file__).resolve().parents[2] / "docs" / "specs" / "support_flow.json"


def load_table() -> dict[str, Any]:
    return json.loads(TABLE.read_text(encoding="utf-8"))


def create_article(api: Api, admin: Headers, body: dict[str, Any]) -> int:
    article = api.json("POST", "/knowledge-articles", 201, headers=admin, json=body)
    return int(article["id"])


def publish_article(api: Api, admin: Headers, article_id: int) -> None:
    body = {"is_published": True}
    api.json("PATCH", f"/knowledge-articles/{article_id}", headers=admin, json=body)


def create_tree(api: Api, admin: Headers, article_id: int, nodes: dict[str, Any]) -> None:
    """Узлы — от листьев к корню: вариант ответа ссылается на уже созданный узел."""
    ids: dict[str, int] = {}
    pending = dict(nodes)
    while pending:
        ready = [
            key for key, node in pending.items() if all(o["next"] in ids for o in node["options"])
        ]
        check(bool(ready), f"в дереве цикл или ссылка на несуществующий узел: {sorted(pending)}")
        for key in ready:
            node = pending.pop(key)
            body = {
                "question_text": node["question"],
                "is_root": node.get("is_root", False),
                "is_escalation": node.get("is_escalation", False),
                "options": [
                    {"label": o["label"], "next_node_id": ids[o["next"]]} for o in node["options"]
                ],
            }
            path = f"/knowledge-articles/{article_id}/decision-tree"
            ids[key] = int(api.json("POST", path, 201, headers=admin, json=body)["id"])
    validate = f"/knowledge-articles/{article_id}/decision-tree/validate"
    validation = api.json("GET", validate, headers=admin)
    check(validation["is_valid"], f"дерево не прошло проверку: {validation['issues']}")


def seed(api: Api, admin: Headers, table: dict[str, Any]) -> None:
    guide = table["guide"]
    guide_id = create_article(
        api, admin, {"article_type": "guide", "title": guide["title"], "content": guide["content"]}
    )
    publish_article(api, admin, guide_id)
    trouble = table["troubleshooting"]
    body = {
        "article_type": "troubleshooting",
        "category": trouble["category"],
        "title": trouble["title"],
        "content": trouble["content"],
    }
    trouble_id = create_article(api, admin, body)
    create_tree(api, admin, trouble_id, trouble["nodes"])
    publish_article(api, admin, trouble_id)
    print(f"PASS  статьи опубликованы: «{guide['title']}», «{trouble['title']}» (дерево решений)")


def publish(api: Api, admin: Headers, table: dict[str, Any]) -> None:
    created = []
    for item in table["publications"]:
        body = {"type": item["type"], "message": item["message"], "target_vehicle_model_id": None}
        notification = api.json("POST", "/notifications", 201, headers=admin, json=body)
        created.append(f"{item['type']} №{notification['id']}")
    print(f"PASS  опубликовано: {', '.join(created)}")


def reply(api: Api, admin: Headers, ticket_id: int, text: str, status: str | None) -> None:
    """Новый инженер: тикет из очереди — claim, уже назначенный — переназначает администратор."""
    engineer = create_engineer(api, admin)
    engineer_id = api.json("GET", "/me", headers=engineer)["id"]
    ticket = api.json("GET", f"/tickets/{ticket_id}", headers=admin)
    if ticket["status"] == "new":
        api.json("POST", f"/tickets/{ticket_id}/claim", headers=engineer)
    else:
        body = {"assigned_engineer_id": engineer_id}
        api.json("PATCH", f"/tickets/{ticket_id}/assign", headers=admin, json=body)
    path = f"/tickets/{ticket_id}/messages"
    api.json("POST", path, 201, headers=engineer, json={"body": text})
    if status:
        body = {"status": status}
        api.json("PATCH", f"/tickets/{ticket_id}/status", headers=engineer, json=body)
    suffix = f", статус {status}" if status else ""
    print(f"PASS  ответ инженера в тикет №{ticket_id}{suffix}")


def answer(api: Api, admin: Headers, table: dict[str, Any], timeout: int) -> None:
    title = table["troubleshooting"]["title"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        queue = api.json("GET", "/tickets", headers=admin, params={"status": "new"})["items"]
        found = [t for t in queue if t["summary"].startswith(title)]
        if found:
            reply(api, admin, found[0]["id"], table["engineer_reply"], None)
            publish(api, admin, table)
            return
        time.sleep(2)
    check(False, f"за {timeout} с не появился тикет «{title}…»")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed")
    sub.add_parser("publish")
    reply_args = sub.add_parser("reply")
    reply_args.add_argument("--ticket", type=int, required=True)
    reply_args.add_argument("--text")
    reply_args.add_argument("--status", choices=["in_progress", "waiting_vendor", "resolved"])
    answer_args = sub.add_parser("answer")
    answer_args.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args(argv)

    env = os.environ
    missing = [n for n in ("API_BASE_URL", "E2E_JOB_RUNNER") if not env.get(n)]
    if missing:
        print(f"Нужны {', '.join(missing)} — запускается из scripts/integration_stack.sh")
        return 2
    api = Api(env["API_BASE_URL"])
    table = load_table()
    try:
        admin = bootstrap_admin(api, Jobs(env["E2E_JOB_RUNNER"]))
        if args.command == "seed":
            seed(api, admin, table)
        elif args.command == "publish":
            publish(api, admin, table)
        elif args.command == "answer":
            answer(api, admin, table, args.timeout)
        else:
            text = args.text or table["engineer_reply"]
            reply(api, admin, args.ticket, text, args.status)
    except Failed as exc:
        print(f"FAIL  {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
