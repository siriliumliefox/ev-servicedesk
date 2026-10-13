#!/usr/bin/env python3
"""5 тестовых авто для сверки схемы агрегатов с backend (Глава 19, ADR 0023 п. 7).

Таблица — docs/specs/scheme_test_vehicles.json: регламенты моделей, авто клиента, замены и
ожидаемые статусы «светофора» (пороги по умолчанию 70/100, глава 5). Скрипт на работающем стеке
(scripts/integration_stack.sh — окружение команды после «--») заводит регламенты от имени
администратора, регистрирует клиента тестовым номером, добавляет ему авто, фиксирует замены и
сверяет статусы API с таблицей. Каждый ответ сверяется с docs/openapi.yaml (как e2e_backend.py).

  cd backend && poetry run python scripts/seed_scheme_vehicles.py

Окружение: API_BASE_URL, E2E_CODE, E2E_SCHEME_PHONE (тестовый номер клиента схемы),
E2E_JOB_RUNNER (префикс разовой задачи в контейнере стека — для CLI администратора).
Стек одноразовый: повторный запуск на той же среде не предусмотрен (VIN из таблицы уже заняты).
"""

import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from e2e_backend import Api, Failed, Headers, Jobs, bearer, bootstrap_admin, check

TABLE = Path(__file__).resolve().parents[2] / "docs" / "specs" / "scheme_test_vehicles.json"
POLICY = "2026-10"  # редакция политики ПД, которую принимает приложение (ADR 0022 п. 11)
MINSK = ZoneInfo("Europe/Minsk")


def load_table() -> dict[str, Any]:
    return json.loads(TABLE.read_text(encoding="utf-8"))


def model_ids(api: Api, headers: Headers) -> dict[str, int]:
    body = api.json("GET", "/vehicle-models", headers=headers, params={"page_size": 100})
    return {f"{m['brand']} {m['model']}": m["id"] for m in body["items"]}


def seed_regulations(
    api: Api, admin: Headers, table: dict[str, Any], models: dict[str, int]
) -> None:
    thresholds = api.json("GET", "/aggregate-status-thresholds", headers=admin)
    expected = table["thresholds"]
    check(
        all(thresholds[k] == v for k, v in expected.items()),
        f"пороги стека {thresholds} — не значения по умолчанию {expected}",
    )
    for model, aggregates in table["regulations"].items():
        for code, interval in aggregates.items():
            body = {"vehicle_model_id": models[model], "aggregate_type_code": code, **interval}
            api.json("POST", "/maintenance-regulations", 201, headers=admin, json=body)


def register_client(api: Api, phone: str, code: str) -> Headers:
    api.json("POST", "/auth/phone/request-code", json={"phone": phone})
    body = {"phone": phone, "code": code, "pd_policy_version": POLICY}
    return bearer(api.json("POST", "/auth/phone/verify-code", json=body)["access_token"])


def seed_vehicle(
    api: Api, admin: Headers, client: Headers, car: dict[str, Any], model_id: int, today: date
) -> int:
    body = {"vin": car["vin"], "vehicle_model_id": model_id}
    vid = api.json("POST", "/vehicles", 201, headers=client, json=body)["id"]
    if car["mileage"]:
        api.json(
            "PATCH", f"/vehicles/{vid}/mileage", headers=client, json={"mileage": car["mileage"]}
        )
    for code, agg in car["aggregates"].items():
        if "replaced_mileage" not in agg:
            continue
        replacement = {
            "replaced_at": str(today - timedelta(days=agg["replaced_days_ago"])),
            "mileage_at_replacement": agg["replaced_mileage"],
        }
        path = f"/vehicles/{vid}/aggregate-statuses/{code}/replace"
        api.json("POST", path, headers=admin, json=replacement)
    return vid


def verify(api: Api, client: Headers, car: dict[str, Any], vid: int) -> list[str]:
    """Статусы API против таблицы; возвращает расхождения."""
    path = f"/vehicles/{vid}/aggregate-statuses"
    actual = {
        s["aggregate_type_code"]: s
        for s in api.json("GET", path, headers=client, params={"page_size": 100})["items"]
    }
    problems = []
    if set(actual) != set(car["aggregates"]):
        problems.append(f"агрегаты {sorted(actual)} ≠ {sorted(car['aggregates'])}")
    for code, agg in car["aggregates"].items():
        got = actual.get(code)
        if got is None:
            continue
        if got["status"] != agg["status"]:
            problems.append(f"{code}: статус {got['status']} ≠ {agg['status']}")
        if "percentage" in agg and got["percentage"] != agg["percentage"]:
            problems.append(f"{code}: {got['percentage']} % ≠ {agg['percentage']} %")
    return problems


def main() -> int:
    env = os.environ
    names = ("API_BASE_URL", "E2E_CODE", "E2E_SCHEME_PHONE", "E2E_JOB_RUNNER")
    missing = [n for n in names if not env.get(n)]
    if missing:
        print(f"Нужны {', '.join(missing)} — запускается из scripts/integration_stack.sh")
        return 2
    api = Api(env["API_BASE_URL"])
    table = load_table()
    today = datetime.now(MINSK).date()  # дата замены — по Минску, как проверяет backend
    try:
        admin = bootstrap_admin(api, Jobs(env["E2E_JOB_RUNNER"]))
        models = model_ids(api, admin)
        seed_regulations(api, admin, table, models)
        client = register_client(api, env["E2E_SCHEME_PHONE"], env["E2E_CODE"])
        failed = False
        for car in table["vehicles"]:
            vid = seed_vehicle(api, admin, client, car, models[car["model"]], today)
            problems = verify(api, client, car, vid)
            statuses = ", ".join(f"{c} {a['status']}" for c, a in car["aggregates"].items())
            print(
                f"{'FAIL' if problems else 'PASS'}  авто {car['title']} ({car['vin']}): {statuses}"
            )
            for p in problems:
                print(f"      {p}")
            failed = failed or bool(problems)
    except Failed as exc:
        print(f"FAIL  {exc}")
        return 1
    if failed:
        return 1
    print(f"5 тестовых авто: статусы API совпали с таблицей, ответов сверено: {api.checked}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
