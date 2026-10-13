#!/usr/bin/env python3
"""Данные админ-панели на стеке (глава 22, ADR 0026 п. 13–15).

На работающем стеке (scripts/integration_stack.sh — окружение команды после «--»):

  seed --out FILE  — администратор (вход в админ-панель), два инженера (у первого — тикет в работе),
                     клиент E2E_ADMIN_PHONE с Zeekr 001 и регламентом салонного фильтра 20 000 км
                     (замена при 0 км, пробег 10 000 — статус «зелёный»), контрольный набор
                     аналитики (март 2026, docs/ANALYTICS_CONTROL.md) и обновлённая витрина.
                     В FILE (0600) — входы сотрудников и токен клиента; на экран пароли и токены
                     не выводятся.

  cd backend && poetry run python scripts/e2e_admin.py seed --out /tmp/admin-seed.json

Окружение: API_BASE_URL, E2E_JOB_RUNNER (задачи в контейнере API), E2E_COMPOSE (префикс docker
compose стека — разовый контейнер с каталогом tests для контрольного набора), E2E_ADMIN_PHONE и
E2E_CODE (тестовый номер стека). Каждый ответ сверяется с docs/openapi.yaml.
"""

import argparse
import os
import secrets
import shlex
import sys
from datetime import date
from pathlib import Path
from typing import Any

from e2e_backend import (
    ZEEKR_VIN_PREFIX,
    Api,
    Failed,
    Headers,
    Jobs,
    check,
    digits,
    register_client,
    staff_login,
)
from e2e_engineer import write_private

BACKEND = Path(__file__).resolve().parents[1]
AGGREGATE = "cabin_filter"
INTERVAL_KM = 20_000
MILEAGE = 10_000  # 50 % износа — зелёный; пересмотр в админ-панели меняет статус


def staff_account(api: Api, admin: Headers, role: str) -> dict[str, Any]:
    phone, password = "+3752998" + digits(5), secrets.token_urlsafe(18)
    body = {"phone": phone, "role": role, "password": password}
    user = api.json("POST", "/users", 201, headers=admin, json=body)
    staff_login(api, phone, password)  # вход проверен до передачи в тесты
    return {"id": user["id"], "phone": phone, "password": password}


def bootstrap_admin_account(api: Api, jobs: Jobs) -> tuple[Headers, dict[str, Any]]:
    """Первый администратор — CLI образа; пароль нужен тестам для входа в админ-панель."""
    phone, password = "+3752997" + digits(5), secrets.token_urlsafe(24)
    jobs.run("python", "-m", "app.cli", "create-admin", "--phone", phone, stdin=password + "\n")
    headers = staff_login(api, phone, password)
    me = api.json("GET", "/me", headers=headers)
    return headers, {"id": me["id"], "phone": phone, "password": password}


def client_car(api: Api, admin: Headers, phone: str, code: str) -> dict[str, Any]:
    """Клиент с Zeekr 001: регламент салонного фильтра, замена при 0 км, пробег 10 000 — зелёный."""
    client = register_client(api, phone, code)
    car = api.json(
        "POST",
        "/vehicles",
        201,
        headers=client.headers,
        json={"vin": ZEEKR_VIN_PREFIX + digits(10)},
    )
    model = car["vehicle_model"]
    check(model["brand"] == "Zeekr", "VIN не распознан как Zeekr")
    body = {
        "vehicle_model_id": car["vehicle_model_id"],
        "aggregate_type_code": AGGREGATE,
        "interval_km": INTERVAL_KM,
    }
    api.json("POST", "/maintenance-regulations", 201, headers=admin, json=body)
    replace = f"/vehicles/{car['id']}/aggregate-statuses/{AGGREGATE}/replace"
    api.json(
        "POST",
        replace,
        headers=admin,
        json={"replaced_at": str(date.today()), "mileage_at_replacement": 0},
    )
    api.json(
        "PATCH", f"/vehicles/{car['id']}/mileage", headers=client.headers, json={"mileage": MILEAGE}
    )
    statuses = api.json("GET", f"/vehicles/{car['id']}/aggregate-statuses", headers=client.headers)[
        "items"
    ]
    status = [s["status"] for s in statuses if s["aggregate_type_code"] == AGGREGATE]
    check(status == ["green"], f"статус салонного фильтра {status}, ожидался green")
    return {
        "access_token": client.headers["Authorization"].removeprefix("Bearer "),
        "vehicle_id": car["id"],
        "model_id": car["vehicle_model_id"],
        "model_label": f"{model['brand']} {model['model']}",
        "aggregate": AGGREGATE,
        "interval_km": INTERVAL_KM,
        "mileage": MILEAGE,
        "headers": client.headers,
    }


def engineer_ticket(api: Api, client: Headers, vehicle_id: int, engineer: dict[str, Any]) -> int:
    """Тикет клиента в работе у первого инженера — его переназначают в карточке инженера."""
    body = {
        "vehicle_id": vehicle_id,
        "category": "audio",
        "description": "E2E админ-панели: нет звука.",
    }
    ticket = api.json("POST", "/tickets", 201, headers=client, json=body)
    headers = staff_login(api, engineer["phone"], engineer["password"])
    claimed = api.json("POST", f"/tickets/{ticket['id']}/claim", headers=headers)
    check(claimed["assigned_engineer_id"] == engineer["id"], "тикет не взят инженером")
    return ticket["id"]


def analytics_control(jobs: Jobs, compose: str) -> None:
    """Контрольный набор главы 16 в разовом контейнере с каталогом tests и обновление витрины."""
    os.environ["CONTROL_ADMIN_PASSWORD"] = secrets.token_urlsafe(
        24
    )  # администратор набора не нужен тестам
    tests = BACKEND / "tests"
    volume = shlex.quote(f"{tests}:/app/tests:ro")
    control = Jobs(f"{compose} run --rm -T --no-deps -v {volume} -e CONTROL_ADMIN_PASSWORD backend")
    control.run("python", "-m", "tests.support.analytics_control", "load")
    jobs.run("python", "-m", "app.workers.analytics", "--once")


def seed(api: Api, jobs: Jobs, compose: str, phone: str, code: str) -> dict[str, Any]:
    admin_headers, admin = bootstrap_admin_account(api, jobs)
    engineers = [staff_account(api, admin_headers, "engineer") for _ in range(2)]
    client = client_car(api, admin_headers, phone, code)
    ticket = engineer_ticket(api, client.pop("headers"), client["vehicle_id"], engineers[0])
    analytics_control(jobs, compose)
    print(
        f"PASS  администратор, инженеров: {len(engineers)}, клиент с авто №{client['vehicle_id']} "
        f"({client['model_label']}), тикет №{ticket} у инженера, контрольный набор загружен"
    )
    return {"admin": admin, "engineers": engineers, "client": client, "ticket_id": ticket}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    seed_args = sub.add_parser("seed")
    seed_args.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    env = os.environ
    names = ("API_BASE_URL", "E2E_JOB_RUNNER", "E2E_COMPOSE", "E2E_ADMIN_PHONE", "E2E_CODE")
    missing = [n for n in names if not env.get(n)]
    if missing:
        print(f"Нужны {', '.join(missing)} — запускается из scripts/integration_stack.sh")
        return 2
    api = Api(env["API_BASE_URL"])
    try:
        data = seed(
            api,
            Jobs(env["E2E_JOB_RUNNER"]),
            env["E2E_COMPOSE"],
            env["E2E_ADMIN_PHONE"],
            env["E2E_CODE"],
        )
    except Failed as exc:
        print(f"FAIL  {exc}")
        return 1
    write_private(args.out, data)
    print(f"PASS  данные для входа — {args.out} (0600)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
