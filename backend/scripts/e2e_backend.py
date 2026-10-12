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
import os
import secrets
import shlex
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from tests.support.contract import assert_contract, operation_for  # noqa: E402

MINSK = ZoneInfo("Europe/Minsk")
ZEEKR_VIN_PREFIX = "L6TZ001"  # мок-декодер VIN распознаёт как Zeekr 001 (ADR 0014)
POLICY = "e2e"
AGGREGATE = "engine_oil"
INTERVAL_KM = 10_000
MILEAGE = 9_500  # осталось 500 км ≤ 1000 — напоминание «скоро замена» (ADR 0019 п. 6)


class Failed(Exception):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise Failed(message)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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
        except AssertionError as exc:
            raise Failed(f"{operation_id}: ответ не по контракту — {exc}") from exc
        except Exception as exc:  # jsonschema.ValidationError и т. п.
            raise Failed(f"{operation_id}: тело не по схеме — {exc}".splitlines()[0]) from exc
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

    def run(self, *command: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*self.prefix, *command], input=stdin, capture_output=True, text=True, timeout=300
        )

    def ok(self, *command: str) -> str:
        result = self.run(*command)
        check(
            result.returncode == 0,
            f"{' '.join(command)}: код {result.returncode}\n" f"{result.stdout}{result.stderr}",
        )
        return result.stdout


def random_vin() -> str:
    return ZEEKR_VIN_PREFIX + "".join(secrets.choice("0123456789") for _ in range(10))


def staff_phone() -> str:
    return "+3752999" + "".join(secrets.choice("0123456789") for _ in range(5))


class Scenario:
    def __init__(self, api: Api, jobs: Jobs, phone: str, code: str) -> None:
        self.api, self.jobs, self.phone, self.code = api, jobs, phone, code
        self.today = datetime.now(MINSK).date()
        self.period = {"date_from": str(self.today), "date_to": str(self.today)}
        self.s: dict[str, Any] = {}

    # ---- шаги ----

    def health(self) -> None:
        r = self.api.http.get("/health")
        check(r.status_code == 200, f"/health → {r.status_code}")

    def admin(self) -> None:
        phone, password = staff_phone(), secrets.token_urlsafe(24)
        result = self.jobs.run(
            "python", "-m", "app.cli", "create-admin", "--phone", phone, stdin=password + "\n"
        )
        check(result.returncode == 0, f"create-admin: {result.stdout}{result.stderr}")
        body = self.api.json(
            "POST", "/auth/staff/login", json={"phone": phone, "password": password}
        )
        self.s["admin"] = bearer(body["access_token"])

    def engineer(self) -> None:
        phone, password = staff_phone(), secrets.token_urlsafe(24)
        user = self.api.json(
            "POST",
            "/users",
            201,
            headers=self.s["admin"],
            json={"phone": phone, "role": "engineer", "password": password},
        )
        check(user["role"] == "engineer" and user["is_active"], "сотрудник создан не инженером")
        body = self.api.json(
            "POST", "/auth/staff/login", json={"phone": phone, "password": password}
        )
        self.s["engineer"] = bearer(body["access_token"])
        self.s["engineer_id"] = user["id"]

    def unblock_test_client(self) -> None:
        """Повторный запуск: клиент прошлого прогона заблокирован в конце — разблокировать."""
        found = self.api.json(
            "GET",
            "/users",
            headers=self.s["admin"],
            params={"search": self.phone, "role": "client"},
        )
        for user in found["items"]:
            if user["phone"] == self.phone and not user["is_active"]:
                self.api.json(
                    "PATCH",
                    f"/users/{user['id']}",
                    headers=self.s["admin"],
                    json={"is_active": True},
                )

    def analytics_snapshot(self) -> dict[str, Any]:
        self.jobs.ok("python", "-m", "app.workers.analytics", "--once")
        admin = self.s["admin"]
        resolution = self.api.json(
            "GET", "/analytics/ticket-resolution", headers=admin, params=self.period
        )
        conversion = self.api.json(
            "GET", "/analytics/maintenance-conversion", headers=admin, params=self.period
        )
        models = self.api.json(
            "GET",
            "/analytics/problem-models",
            headers=admin,
            params=self.period | {"page_size": 100},
        )
        zeekr = next(
            (m for m in models["items"] if m["vehicle_model"]["id"] == self.s["model"]), None
        )
        return {
            "created": resolution["tickets_created"],
            "resolved": resolution["tickets_resolved"],
            "tickets": conversion["tickets_total"],
            "tickets_to": conversion["tickets_with_maintenance"],
            "recipients": conversion["notifications_recipients"],
            "opened": conversion["notifications_opened"],
            "recipients_to": conversion["recipients_with_maintenance"],
            "model_tickets": zeekr["tickets_total"] if zeekr else 0,
        }

    def regulation(self) -> None:
        models = self.api.json(
            "GET", "/vehicle-models", headers=self.s["admin"], params={"search": "Zeekr"}
        )
        check(models["items"], "модели Zeekr нет в справочнике")
        self.s["model"] = models["items"][0]["id"]
        self.api.json(
            "POST",
            "/maintenance-regulations",
            201,
            headers=self.s["admin"],
            json={
                "vehicle_model_id": self.s["model"],
                "aggregate_type_code": AGGREGATE,
                "interval_km": INTERVAL_KM,
            },
        )
        self.s["before"] = self.analytics_snapshot()

    def register_client(self) -> None:
        self.api.json("POST", "/auth/phone/request-code", json={"phone": self.phone})
        body = self.api.json(
            "POST",
            "/auth/phone/verify-code",
            json={
                "phone": self.phone,
                "code": self.code,
                "pd_policy_version": POLICY,
            },
        )
        self.s["client"] = bearer(body["access_token"])
        self.s["refresh"] = body["refresh_token"]
        self.s["client_id"] = self.api.json("GET", "/me", headers=self.s["client"])["id"]
        self.s["push"] = "e2e-fcm-" + secrets.token_hex(24)
        self.api.call(
            "POST", "/push-tokens", 201, headers=self.s["client"], json={"token": self.s["push"]}
        )

    def vehicle(self) -> None:
        car = self.api.json(
            "POST", "/vehicles", 201, headers=self.s["client"], json={"vin": random_vin()}
        )
        check(car["vehicle_model"]["brand"] == "Zeekr", "VIN не распознан как Zeekr")
        self.s["vehicle"] = vid = car["id"]
        # Базовая замена масла (администратор, без тикета) — отсчёт ресурса.
        self.api.json(
            "POST",
            f"/vehicles/{vid}/aggregate-statuses/{AGGREGATE}/replace",
            headers=self.s["admin"],
            json={"replaced_at": str(self.today - timedelta(days=60)), "mileage_at_replacement": 0},
        )
        self.api.json(
            "PATCH", f"/vehicles/{vid}/mileage", headers=self.s["client"], json={"mileage": MILEAGE}
        )
        statuses = self.api.json(
            "GET", f"/vehicles/{vid}/aggregate-statuses", headers=self.s["client"]
        )
        oil = next(s for s in statuses["items"] if s["aggregate_type_code"] == AGGREGATE)
        check(oil["status"] == "yellow", f"статус масла {oil['status']}, ожидался yellow")

    def reminder(self) -> None:
        out = self.jobs.ok("python", "-m", "app.workers.maintenance_reminders")
        check("создано: 0" not in out, f"напоминание не создано: {out.strip()}")
        feed = self.api.json("GET", "/notifications", headers=self.s["client"])
        reminder = next(
            (
                n
                for n in feed["items"]
                if n["type"] == "maintenance" and n["vehicle_id"] == self.s["vehicle"]
            ),
            None,
        )
        check(reminder is not None, "напоминания о ТО нет в ленте клиента")
        self.s["reminder"] = rid = reminder["id"]
        # Клиент нажал на push на своём устройстве: открытие и прочтение.
        self.api.call(
            "POST",
            f"/notifications/{rid}/opened",
            204,
            headers=self.s["client"],
            json={"token": self.s["push"]},
        )
        feed = self.api.json("GET", "/notifications", headers=self.s["client"])
        item = next(n for n in feed["items"] if n["id"] == rid)
        check(item["read_at"] is not None, "открытое уведомление не отмечено прочитанным")

    def ticket(self) -> None:
        ticket = self.api.json(
            "POST",
            "/tickets",
            201,
            headers=self.s["client"],
            json={
                "vehicle_id": self.s["vehicle"],
                "category": "maintenance",
                "description": "Пришло напоминание о замене масла",
            },
        )
        self.s["ticket"] = tid = ticket["id"]
        check(ticket["status"] == "new", "новый тикет не в статусе new")
        eng = self.s["engineer"]
        queue = self.api.json("GET", "/tickets", headers=eng, params={"status": "new"})
        check(any(t["id"] == tid for t in queue["items"]), "тикета нет в очереди инженера")
        card = self.api.json("GET", f"/tickets/{tid}", headers=eng)
        oil = next(
            s
            for s in card["vehicle_context"]["aggregate_statuses"]
            if s["aggregate_type_code"] == AGGREGATE
        )
        check(oil["status"] == "yellow", "vehicle_context тикета без статуса агрегата")
        self.api.json("POST", f"/tickets/{tid}/claim", headers=eng)
        self.api.json(
            "POST",
            f"/tickets/{tid}/messages",
            201,
            headers=eng,
            json={"body": "Записали вас на замену масла"},
        )
        replaced = self.api.json(
            "POST",
            f"/vehicles/{self.s['vehicle']}/aggregate-statuses/{AGGREGATE}/replace",
            headers=eng,
            json={
                "replaced_at": str(self.today),
                "mileage_at_replacement": MILEAGE,
                "description": "Замена масла по обращению",
            },
        )
        check(replaced["status"] == "green", f"после замены статус {replaced['status']}")
        self.api.json("PATCH", f"/tickets/{tid}/status", headers=eng, json={"status": "resolved"})

    def client_sees_result(self) -> None:
        client, tid = self.s["client"], self.s["ticket"]
        check(
            self.api.json("GET", f"/tickets/{tid}", headers=client)["status"] == "resolved",
            "клиент не видит решённый тикет",
        )
        messages = self.api.json("GET", f"/tickets/{tid}/messages", headers=client)
        check(len(messages["items"]) == 1, "клиент не видит ответ инженера")
        records = self.api.json(
            "GET", f"/vehicles/{self.s['vehicle']}/maintenance-records", headers=client
        )
        # Привязку работы к тикету показывает аналитика (тикет → ТО), в API истории её нет.
        check(
            any(
                r["aggregate_type_code"] == AGGREGATE and r["mileage_at_service"] == MILEAGE
                for r in records["items"]
            ),
            "замена по тикету не попала в историю ТО авто",
        )

    def analytics(self) -> None:
        after, before = self.analytics_snapshot(), self.s["before"]
        delta = {k: after[k] - before[k] for k in after}
        expected = {
            "created": 1,
            "resolved": 1,
            "tickets": 1,
            "tickets_to": 1,
            "recipients": 1,
            "opened": 1,
            "recipients_to": 1,
            "model_tickets": 1,
        }
        check(delta == expected, f"прирост показателей {delta}, ожидался {expected}")

    def integrity(self) -> None:
        self.jobs.ok("python", "-m", "app.tools.integrity")

    def block_client(self) -> None:
        self.api.json(
            "PATCH",
            f"/users/{self.s['client_id']}",
            headers=self.s["admin"],
            json={"is_active": False},
        )
        self.api.call("GET", "/me", 401, headers=self.s["client"])
        self.api.call("POST", "/auth/refresh", 401, json={"refresh_token": self.s["refresh"]})
        self.api.call("GET", f"/tickets/{self.s['ticket']}", 200, headers=self.s["admin"])


STEPS: list[tuple[str, str]] = [
    ("health", "API отвечает"),
    ("admin", "CLI создаёт администратора, вход по паролю"),
    ("engineer", "администратор создаёт инженера (Users), вход"),
    ("unblock_test_client", "тестовый клиент прошлого прогона разблокирован"),
    ("regulation", "регламент ТО модели, снимок аналитики «до»"),
    ("register_client", "регистрация клиента по SMS-коду, согласие ПД, push-токен"),
    ("vehicle", "авто по VIN, базовая замена, пробег → статус «скоро замена»"),
    ("reminder", "напоминание о ТО в ленте, открытие push"),
    ("ticket", "тикет → очередь → взят → ответ → замена по тикету → решён"),
    ("client_sees_result", "клиент видит решение, переписку и запись ТО"),
    ("analytics", "витрина обновлена: +1 тикет, решение, обе конверсии, проблемная модель"),
    ("integrity", "аудит целостности — 0 нарушений"),
    ("block_client", "блокировка клиента: 401, сессии завершены, тикет сохранён"),
    ("integrity", "аудит целостности после блокировки — 0 нарушений"),
]


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
    scenario = Scenario(api, Jobs(args.job_runner), phone, code)
    for name, title in STEPS:
        try:
            getattr(scenario, name)()
        except (Failed, httpx.HTTPError, subprocess.SubprocessError, OSError) as exc:
            print(f"FAIL  {title}: {exc}")
            return 1
        print(f"PASS  {title}")
    print(
        f"Сквозной сценарий пройден: шагов {len(STEPS)}, ответов сверено с контрактом "
        f"{api.checked}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
