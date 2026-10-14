#!/usr/bin/env python3
"""Данные межролевых E2E на стеке (глава 23, ADR 0027 п. 8, 15: E2E-08, E2E-11, E2E-15, E2E-16).

На работающем стеке (scripts/integration_stack.sh — окружение команды после «--»):

  seed --out FILE [--sets N]
    Администратор и инженер (входы в админ-панель и кабинет инженера); клиент X
    (E2E_SYSTEM_PHONE) с N авто Zeekr 001 — по одному на браузер: у каждого воздушный и масляный
    фильтры по регламенту 15 000 км выработаны на 106 % («требуется замена»); клиент Y
    (E2E_SYSTEM_PHONE_Y) с авто другой модели — для таргетинга прошивки. У обоих клиентов
    зарегистрирован push-токен. В FILE (0600) — входы сотрудников и токены клиентов; пароли и
    токены на экран не выводятся.

  cd backend && poetry run python scripts/e2e_system.py seed --out /tmp/system-seed.json --sets 3

Окружение: API_BASE_URL, E2E_JOB_RUNNER (CLI администратора в контейнере стека), E2E_SYSTEM_PHONE,
E2E_SYSTEM_PHONE_Y и E2E_CODE (тестовые номера стека). Каждый ответ сверяется с docs/openapi.yaml.
"""

import argparse
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

from e2e_admin import bootstrap_admin_account, staff_account
from e2e_backend import (
    ZEEKR_VIN_PREFIX,
    Api,
    Client,
    Failed,
    Headers,
    Jobs,
    check,
    digits,
    register_client,
    write_private,
    zeekr_regulation,
)

# Агрегаты сценариев: замена из карточки тикета (E2E-08) и главный сценарий (E2E-16) — на разных
# агрегатах одного авто, поэтому сценарии не зависят от порядка запуска.
AGGREGATES = {"replace": "air_filter", "golden": "oil_filter"}
INTERVAL_KM = 15_000
MILEAGE = 16_000  # 106 % интервала — «требуется замена»
OTHER_MODEL = "Li Auto"  # VIN не распознаётся мок-декодером — модель выбирается вручную (ADR 0014)


def regulations(api: Api, admin: Headers) -> int:
    """Регламенты обоих агрегатов сценариев у Zeekr 001; возвращает id модели."""
    model_ids = {zeekr_regulation(api, admin, code, INTERVAL_KM) for code in AGGREGATES.values()}
    return model_ids.pop()


def worn_car(api: Api, admin: Headers, client: Client) -> dict[str, Any]:
    """Авто Zeekr: оба фильтра заменены при 0 км, пробег 16 000 — оба «требуется замена»."""
    vin = ZEEKR_VIN_PREFIX + digits(10)
    car = api.json("POST", "/vehicles", 201, headers=client.headers, json={"vin": vin})
    for code in AGGREGATES.values():
        path = f"/vehicles/{car['id']}/aggregate-statuses/{code}/replace"
        body = {"replaced_at": str(date.today()), "mileage_at_replacement": 0}
        api.json("POST", path, headers=admin, json=body)
    path = f"/vehicles/{car['id']}/mileage"
    api.json("PATCH", path, headers=client.headers, json={"mileage": MILEAGE})
    statuses = api.json("GET", f"/vehicles/{car['id']}/aggregate-statuses", headers=client.headers)
    worn = {s["aggregate_type_code"]: s for s in statuses["items"]}
    names = {}
    for key, code in AGGREGATES.items():
        check(worn.get(code, {}).get("status") == "red", f"{code}: ожидался red, получено {worn}")
        names[key] = worn[code]["aggregate_type_name"]
    return {"id": car["id"], "aggregates": AGGREGATES, "aggregate_names": names}


def other_model_car(api: Api, client: Client) -> dict[str, Any]:
    models = api.json(
        "GET", "/vehicle-models", headers=client.headers, params={"search": OTHER_MODEL}
    )
    check(models["items"], f"модели {OTHER_MODEL} нет в справочнике")
    model = models["items"][0]
    body = {"vin": "LLX" + digits(14), "vehicle_model_id": model["id"]}
    car = api.json("POST", "/vehicles", 201, headers=client.headers, json=body)
    return {"id": car["id"], "model_id": model["id"]}


def client_data(client: Client, phone: str, code: str) -> dict[str, Any]:
    return {
        "phone": phone,
        # Код тестового номера стека — вход клиента в мобильном приложении при ручном прогоне.
        "sms_code": code,
        "access_token": client.headers["Authorization"].removeprefix("Bearer "),
        "user_id": client.user_id,
    }


def seed(api: Api, jobs: Jobs, phone_x: str, phone_y: str, code: str, sets: int) -> dict[str, Any]:
    admin_headers, admin = bootstrap_admin_account(api, jobs)
    engineer = staff_account(api, admin_headers, "engineer")
    model_id = regulations(api, admin_headers)
    owner_x = register_client(api, phone_x, code)
    cars = [worn_car(api, admin_headers, owner_x) for _ in range(sets)]
    owner_y = register_client(api, phone_y, code)
    car_y = other_model_car(api, owner_y)
    check(car_y["model_id"] != model_id, "у клиента Y должна быть другая модель")
    print(
        f"PASS  администратор, инженер, клиент X с авто {[c['id'] for c in cars]} (Zeekr 001), "
        f"клиент Y с авто №{car_y['id']} ({OTHER_MODEL})"
    )
    return {
        "admin": admin,
        "engineer": engineer,
        "client_x": {**client_data(owner_x, phone_x, code), "model_id": model_id, "cars": cars},
        "client_y": {**client_data(owner_y, phone_y, code), **car_y},
        "model_label": "Zeekr 001",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    seed_args = sub.add_parser("seed")
    seed_args.add_argument("--out", type=Path, required=True)
    seed_args.add_argument(
        "--sets", type=int, default=1, help="авто клиента X — по одному на браузер"
    )
    args = parser.parse_args(argv)

    env = os.environ
    names = ("API_BASE_URL", "E2E_JOB_RUNNER", "E2E_SYSTEM_PHONE", "E2E_SYSTEM_PHONE_Y", "E2E_CODE")
    missing = [n for n in names if not env.get(n)]
    if missing:
        print(f"Нужны {', '.join(missing)} — запускается из scripts/integration_stack.sh")
        return 2
    api = Api(env["API_BASE_URL"])
    try:
        data = seed(
            api,
            Jobs(env["E2E_JOB_RUNNER"]),
            env["E2E_SYSTEM_PHONE"],
            env["E2E_SYSTEM_PHONE_Y"],
            env["E2E_CODE"],
            args.sets,
        )
    except Failed as exc:
        print(f"FAIL  {exc}")
        return 1
    write_private(args.out, data)
    print(f"PASS  данные для входа — {args.out} (0600)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
