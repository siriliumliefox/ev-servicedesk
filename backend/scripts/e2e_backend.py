#!/usr/bin/env python3
"""Сквозной сценарий backend одним скриптом (Глава 17, ADR 0021 п. 9).

Регистрация → авто → уведомление → тикет → аналитика на работающем стеке (интеграционный
стек scripts/integration_stack.sh, позже — staging главы 26). Каждый ответ сверяется с
docs/openapi.yaml (tests/support/contract.py). Разовые задачи (CLI администратора, напоминания
о ТО, обновление витрины, аудит целостности) выполняются командой `--job-runner` — в CI это
`docker compose ... exec -T backend`.

  cd backend && poetry run python scripts/e2e_backend.py --base-url http://127.0.0.1:18080 \\
      --job-runner "docker compose -p ev-integration ... exec -T backend"

Окружение: E2E_PHONE и E2E_CODE — тестовый номер и код (SMS_TEST_PHONES/SMS_TEST_CODE стека).
Повторный запуск на той же среде допустим: новые авто и сотрудник, клиент разблокируется,
показатели аналитики сравниваются как прирост. Пароли генерируются и не печатаются.
"""

import argparse
import json
import os
import secrets
import shlex
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from jsonschema.exceptions import ValidationError

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from tests.support.contract import assert_contract, operation_for  # noqa: E402

MINSK = ZoneInfo("Europe/Minsk")
ZEEKR_VIN_PREFIX = "L6TZ001"  # мок-декодер VIN распознаёт как Zeekr 001 (ADR 0014)
POLICY = "e2e"
# Zeekr 001 — электромобиль без ДВС: обслуживается масло редуктора, а не масло двигателя (замечание
# владельца к главе 18). Интервал — реалистичный для редуктора.
AGGREGATE = "gearbox_oil"
INTERVAL_KM = 60_000
MILEAGE = 59_500  # осталось 500 км ≤ 1000 — напоминание «скоро замена» (ADR 0019 п. 6)

Headers = dict[str, str]


class Failed(Exception):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise Failed(message)


def bearer(token: str) -> Headers:
    return {"Authorization": f"Bearer {token}"}


def digits(n: int) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(n))


class Api:
    """HTTP-клиент: каждый ответ операции контракта сверяется с docs/openapi.yaml."""

    def __init__(self, base_url: str) -> None:
        self.http = httpx.Client(base_url=base_url, timeout=30)
        self.checked = 0

    def call(self, method: str, path: str, expect: int, **kwargs: Any) -> httpx.Response:
        response = self.http.request(method, f"/v1{path}", **kwargs)
        operation_id = operation_for(method, response.request.url.path)
        check(operation_id is not None, f"{method} {path}: операции нет в контракте")
        try:
            assert_contract(response, operation_id)
        except (AssertionError, ValidationError) as exc:
            raise Failed(f"{operation_id}: ответ не по контракту — {exc}".splitlines()[0]) from exc
        self.checked += 1
        check(
            response.status_code == expect,
            f"{operation_id}: ожидался {expect}, получен {response.status_code} "
            f"{response.text[:300]}",
        )
        return response

    def json(self, method: str, path: str, expect: int = 200, **kwargs: Any) -> Any:
        return self.call(method, path, expect, **kwargs).json()


class Jobs:
    """Разовые задачи в контейнере стека (тот же образ и окружение, что у API)."""

    def __init__(self, runner: str) -> None:
        self.prefix = shlex.split(runner)

    def run(self, *command: str, stdin: str | None = None) -> str:
        # Команда — из кода сценария, префикс — из переменной окружения CI, без shell.
        result = subprocess.run(  # noqa: S603
            [*self.prefix, *command], input=stdin, capture_output=True, text=True, timeout=300
        )
        check(
            result.returncode == 0,
            f"{' '.join(command)}: код {result.returncode}\n{result.stdout}{result.stderr}",
        )
        return result.stdout


@dataclass(frozen=True)
class Client:
    headers: Headers
    refresh_token: str
    user_id: int
    push_token: str


def write_private(path: Path, data: dict[str, Any]) -> None:
    """Данные E2E с паролями и токенами — файл 0600 (на экран не выводятся)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.chmod(path, 0o600)


# ---------- Шаги сценария: явные входы и результаты ----------


def check_health(api: Api) -> None:
    r = api.http.get("/health")
    check(r.status_code == 200, f"/health → {r.status_code}")


def staff_login(api: Api, phone: str, password: str) -> Headers:
    body = api.json("POST", "/auth/staff/login", json={"phone": phone, "password": password})
    return bearer(body["access_token"])


def bootstrap_admin(api: Api, jobs: Jobs) -> Headers:
    phone, password = "+3752999" + digits(5), secrets.token_urlsafe(24)
    jobs.run("python", "-m", "app.cli", "create-admin", "--phone", phone, stdin=password + "\n")
    return staff_login(api, phone, password)


def create_engineer(api: Api, admin: Headers) -> Headers:
    phone, password = "+3752999" + digits(5), secrets.token_urlsafe(24)
    body = {"phone": phone, "role": "engineer", "password": password}
    user = api.json("POST", "/users", 201, headers=admin, json=body)
    check(user["role"] == "engineer" and user["is_active"], "сотрудник создан не инженером")
    return staff_login(api, phone, password)


def unblock_test_client(api: Api, admin: Headers, phone: str) -> None:
    """Повторный запуск: клиент прошлого прогона заблокирован в конце — разблокировать."""
    params = {"search": phone, "role": "client"}
    for user in api.json("GET", "/users", headers=admin, params=params)["items"]:
        if user["phone"] == phone and not user["is_active"]:
            api.json("PATCH", f"/users/{user['id']}", headers=admin, json={"is_active": True})


def zeekr_regulation(
    api: Api, admin: Headers, code: str = AGGREGATE, interval_km: int = INTERVAL_KM
) -> int:
    """Регламент агрегата модели Zeekr 001 (пересмотр — новая версия); возвращает id модели."""
    models = api.json("GET", "/vehicle-models", headers=admin, params={"search": "Zeekr"})
    check(models["items"], "модели Zeekr нет в справочнике")
    model_id = models["items"][0]["id"]
    body = {"vehicle_model_id": model_id, "aggregate_type_code": code, "interval_km": interval_km}
    api.json("POST", "/maintenance-regulations", 201, headers=admin, json=body)
    return model_id


def analytics(api: Api, jobs: Jobs, admin: Headers, model_id: int, day: date) -> dict[str, int]:
    """Показатели за день после обновления витрины (сравниваются как прирост)."""
    jobs.run("python", "-m", "app.workers.analytics", "--once")
    period = {"date_from": str(day), "date_to": str(day)}
    resolution = api.json("GET", "/analytics/ticket-resolution", headers=admin, params=period)
    conversion = api.json("GET", "/analytics/maintenance-conversion", headers=admin, params=period)
    models = api.json(
        "GET", "/analytics/problem-models", headers=admin, params=period | {"page_size": 100}
    )
    zeekr = [m["tickets_total"] for m in models["items"] if m["vehicle_model"]["id"] == model_id]
    return {
        "tickets_created": resolution["tickets_created"],
        "tickets_resolved": resolution["tickets_resolved"],
        "tickets_total": conversion["tickets_total"],
        "tickets_with_maintenance": conversion["tickets_with_maintenance"],
        "notifications_recipients": conversion["notifications_recipients"],
        "notifications_opened": conversion["notifications_opened"],
        "recipients_with_maintenance": conversion["recipients_with_maintenance"],
        "problem_model_tickets": sum(zeekr),
    }


def register_client(api: Api, phone: str, code: str) -> Client:
    api.json("POST", "/auth/phone/request-code", json={"phone": phone})
    body = {"phone": phone, "code": code, "pd_policy_version": POLICY}
    tokens = api.json("POST", "/auth/phone/verify-code", json=body)
    headers = bearer(tokens["access_token"])
    push_token = "e2e-fcm-" + secrets.token_hex(24)
    api.call("POST", "/push-tokens", 201, headers=headers, json={"token": push_token})
    user_id = api.json("GET", "/me", headers=headers)["id"]
    return Client(headers, tokens["refresh_token"], user_id, push_token)


def due_soon_vehicle(api: Api, admin: Headers, client: Client, today: date) -> int:
    """Авто с базовой заменой масла редуктора и пробегом до «скоро замена»; возвращает id авто."""
    body = {"vin": ZEEKR_VIN_PREFIX + digits(10)}
    car = api.json("POST", "/vehicles", 201, headers=client.headers, json=body)
    check(car["vehicle_model"]["brand"] == "Zeekr", "VIN не распознан как Zeekr")
    vid = car["id"]
    baseline = {"replaced_at": str(today - timedelta(days=60)), "mileage_at_replacement": 0}
    replace_path = f"/vehicles/{vid}/aggregate-statuses/{AGGREGATE}/replace"
    api.json("POST", replace_path, headers=admin, json=baseline)
    api.json("PATCH", f"/vehicles/{vid}/mileage", headers=client.headers, json={"mileage": MILEAGE})
    statuses = api.json("GET", f"/vehicles/{vid}/aggregate-statuses", headers=client.headers)
    oil = [s["status"] for s in statuses["items"] if s["aggregate_type_code"] == AGGREGATE]
    check(oil == ["yellow"], f"статус масла {oil}, ожидался yellow")
    return vid


def open_reminder(api: Api, jobs: Jobs, client: Client, vid: int) -> None:
    out = jobs.run("python", "-m", "app.workers.maintenance_reminders")
    check("создано: 0" not in out, f"напоминание не создано: {out.strip()}")
    feed = api.json("GET", "/notifications", headers=client.headers)["items"]
    reminders = [n["id"] for n in feed if n["type"] == "maintenance" and n["vehicle_id"] == vid]
    check(len(reminders) == 1, "напоминания о ТО нет в ленте клиента")
    rid = reminders[0]
    # Клиент нажал на push на своём устройстве: открытие и прочтение.
    body = {"token": client.push_token}
    api.call("POST", f"/notifications/{rid}/opened", 204, headers=client.headers, json=body)
    feed = api.json("GET", "/notifications", headers=client.headers)["items"]
    read = [n["read_at"] for n in feed if n["id"] == rid]
    check(read != [None], "открытое уведомление не отмечено прочитанным")


def resolve_ticket(api: Api, client: Client, engineer: Headers, vid: int, today: date) -> int:
    """Тикет клиента → очередь → взят → ответ → замена по тикету → решён; возвращает id."""
    body = {
        "vehicle_id": vid,
        "category": "maintenance",
        "description": "Пришло напоминание о замене масла",
    }
    ticket = api.json("POST", "/tickets", 201, headers=client.headers, json=body)
    tid = ticket["id"]
    check(ticket["status"] == "new", "новый тикет не в статусе new")
    queue = api.json("GET", "/tickets", headers=engineer, params={"status": "new"})["items"]
    check(any(t["id"] == tid for t in queue), "тикета нет в очереди инженера")
    context = api.json("GET", f"/tickets/{tid}", headers=engineer)["vehicle_context"]
    check(
        any(
            s["aggregate_type_code"] == AGGREGATE and s["status"] == "yellow"
            for s in context["aggregate_statuses"]
        ),
        "vehicle_context тикета без статуса агрегата",
    )
    api.json("POST", f"/tickets/{tid}/claim", headers=engineer)
    message = {"body": "Записали вас на замену масла"}
    api.json("POST", f"/tickets/{tid}/messages", 201, headers=engineer, json=message)
    replacement = {
        "replaced_at": str(today),
        "mileage_at_replacement": MILEAGE,
        "description": "Замена масла по обращению",
    }
    replace_path = f"/vehicles/{vid}/aggregate-statuses/{AGGREGATE}/replace"
    replaced = api.json("POST", replace_path, headers=engineer, json=replacement)
    check(replaced["status"] == "green", f"после замены статус {replaced['status']}")
    api.json("PATCH", f"/tickets/{tid}/status", headers=engineer, json={"status": "resolved"})
    return tid


def client_sees_result(api: Api, client: Client, vid: int, tid: int) -> None:
    ticket = api.json("GET", f"/tickets/{tid}", headers=client.headers)
    check(ticket["status"] == "resolved", "клиент не видит решённый тикет")
    messages = api.json("GET", f"/tickets/{tid}/messages", headers=client.headers)["items"]
    check(len(messages) == 1, "клиент не видит ответ инженера")
    records = api.json("GET", f"/vehicles/{vid}/maintenance-records", headers=client.headers)
    # Привязку работы к тикету показывает аналитика (тикет → ТО), в API истории её нет.
    check(
        any(
            r["aggregate_type_code"] == AGGREGATE and r["mileage_at_service"] == MILEAGE
            for r in records["items"]
        ),
        "замена по тикету не попала в историю ТО авто",
    )


def analytics_grew(before: dict[str, int], after: dict[str, int]) -> None:
    delta = {k: after[k] - before[k] for k in after}
    check(set(delta.values()) == {1}, f"прирост показателей {delta}, у каждого ожидался +1")


def integrity(jobs: Jobs) -> None:
    jobs.run("python", "-m", "app.tools.integrity")


def block_client(api: Api, admin: Headers, client: Client, tid: int) -> None:
    api.json("PATCH", f"/users/{client.user_id}", headers=admin, json={"is_active": False})
    api.call("GET", "/me", 401, headers=client.headers)
    api.call("POST", "/auth/refresh", 401, json={"refresh_token": client.refresh_token})
    api.call("GET", f"/tickets/{tid}", 200, headers=admin)


# ---------- Запуск ----------


class StepFailed(Exception):
    pass


def step[T](title: str, run: Callable[..., T], *args: Any) -> T:
    """Шаг сценария: PASS — и результат дальше по цепочке; любая ошибка — FAIL и стоп."""
    try:
        result = run(*args)
    except (Failed, httpx.HTTPError, subprocess.SubprocessError, OSError) as exc:
        raise StepFailed(f"FAIL  {title}: {exc}") from exc
    print(f"PASS  {title}")
    return result


def scenario(api: Api, jobs: Jobs, phone: str, code: str) -> None:
    today = datetime.now(MINSK).date()
    step("API отвечает", check_health, api)
    admin = step("CLI создаёт администратора, вход по паролю", bootstrap_admin, api, jobs)
    engineer = step("администратор создаёт инженера (Users), вход", create_engineer, api, admin)
    step("тестовый клиент прошлого прогона разблокирован", unblock_test_client, api, admin, phone)
    model_id = step("регламент ТО модели", zeekr_regulation, api, admin)
    before = step("снимок аналитики «до»", analytics, api, jobs, admin, model_id, today)
    client = step(
        "регистрация клиента по SMS-коду, согласие ПД, push-токен",
        register_client,
        api,
        phone,
        code,
    )
    vid = step(
        "авто по VIN, базовая замена, пробег → статус «скоро замена»",
        due_soon_vehicle,
        api,
        admin,
        client,
        today,
    )
    step("напоминание о ТО в ленте, открытие push", open_reminder, api, jobs, client, vid)
    tid = step(
        "тикет → очередь → взят → ответ → замена по тикету → решён",
        resolve_ticket,
        api,
        client,
        engineer,
        vid,
        today,
    )
    step("клиент видит решение, переписку и запись ТО", client_sees_result, api, client, vid, tid)
    after = step("витрина обновлена", analytics, api, jobs, admin, model_id, today)
    step("+1: тикет, решение, обе конверсии, проблемная модель", analytics_grew, before, after)
    step("аудит целостности — 0 нарушений", integrity, jobs)
    step(
        "блокировка клиента: 401, сессии завершены, тикет сохранён",
        block_client,
        api,
        admin,
        client,
        tid,
    )
    step("аудит целостности после блокировки — 0 нарушений", integrity, jobs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument(
        "--job-runner",
        required=True,
        help="префикс команды разовой задачи, напр. «docker compose ... exec -T backend»",
    )
    args = parser.parse_args(argv)
    phone, code = os.environ.get("E2E_PHONE", ""), os.environ.get("E2E_CODE", "")
    if not (phone and code):
        print("Нужны E2E_PHONE и E2E_CODE (тестовый номер и код стека)")
        return 2
    api = Api(args.base_url)
    try:
        scenario(api, Jobs(args.job_runner), phone, code)
    except StepFailed as exc:
        print(exc)
        return 1
    print(f"Сквозной сценарий пройден, ответов сверено с контрактом: {api.checked}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
