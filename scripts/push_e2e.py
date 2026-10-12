#!/usr/bin/env python3
"""Проверка push на реальном iPhone — DoD главы 15 (ADR 0019 п. 18, docs/NOTIFICATIONS_E2E.md).

Backend и worker уведомлений — `docker compose --profile full` на Mac (ENVIRONMENT=local,
PUSH_PROVIDER=fcm). Телефон — в той же Wi-Fi сети, приложение запущено точкой входа
lib/main_push_debug.dart. Только стандартная библиотека Python (3.9+, как системный python3 macOS).

  python3 scripts/push_e2e.py setup --plist ~/Downloads/GoogleService-Info.plist
  python3 scripts/push_e2e.py firmware   # ① прошивка модели X: push у владельца X, у Y — нет
  python3 scripts/push_e2e.py reminder   # ② напоминание о ТО по «просроченному» агрегату
  python3 scripts/push_e2e.py news       # ③ новость: push, лента, открытие и прочтение

Пишет mobile/push_e2e.local.json (в .gitignore): ключи Firebase-приложения из plist,
адрес backend для телефона и access-токен тестового клиента. Значения ключей и токенов
не печатаются. Тестовые телефоны и пароль администратора — только локальные.
"""

from __future__ import annotations

import argparse
import base64
import json
import plistlib
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "mobile" / "push_e2e.local.json"
LOCAL_API = "http://localhost:8000"
OWNER_X = "+375290000701"  # владелец Zeekr 001 — телефон с приложением
OWNER_Y = "+375290000702"  # владелец Voyah Free — push получать не должен
ADMIN = "+375290000709"
POLICY = "2026-10"
VIN_X = "L6TZ001E2E0000701"
VIN_Y = "LSVAUE2E000000702"
WAIT_SECONDS = 120


class E2EError(Exception):
    pass


def call(
    method: str, path: str, token: str | None = None, body: dict | None = None
) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(f"{LOCAL_API}{path}", data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, json.loads(raw) if raw else {}
    except urllib.error.URLError as exc:
        raise E2EError(f"backend {LOCAL_API} недоступен: {exc.reason}") from None


def ok(status: int, body: dict, expected: int, what: str) -> dict:
    if status != expected:
        code = body.get("error", {}).get("code")
        raise E2EError(f"{what}: HTTP {status} ({code}), ожидалось {expected}")
    return body


def login_client(phone: str) -> str:
    status, body = call("POST", "/v1/auth/phone/request-code", body={"phone": phone})
    if status == 429:
        raise E2EError(
            f"лимит SMS для {phone}: подождите {body['error']['details']['retry_after_seconds']} с"
        )
    ok(status, body, 200, "запрос кода")
    code = ok(
        *call("GET", f"/v1/_debug/sms/last-code?phone=%2B{phone[1:]}"),
        200,
        "код (нужен ENVIRONMENT=local)",
    )
    verify = {"phone": phone, "code": code["code"], "pd_policy_version": POLICY}
    return ok(*call("POST", "/v1/auth/phone/verify-code", body=verify), 200, "вход")[
        "access_token"
    ]


def ensure_vehicle(token: str, vin: str, model_search: str | None = None) -> int:
    vehicles = ok(*call("GET", "/v1/vehicles", token), 200, "список авто")["items"]
    if vehicles:
        return vehicles[0]["id"]
    body: dict = {"vin": vin}
    if model_search:
        models = ok(
            *call("GET", f"/v1/vehicle-models?search={model_search}", token),
            200,
            "модели",
        )
        body["vehicle_model_id"] = models["items"][0]["id"]
    return ok(*call("POST", "/v1/vehicles", token, body), 201, "добавление авто")["id"]


def compose(*args: str, stdin: str | None = None) -> str:
    result = subprocess.run(
        ["docker", "compose", "--profile", "full", *args],
        cwd=ROOT,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise E2EError(
            f"docker compose {' '.join(args[:2])}: {result.stderr.strip()[-300:]}"
        )
    return result.stdout


def login_admin() -> str:
    """Локальный администратор: создаётся (или получает новый пароль) внутри контейнера.

    Пароль одноразовый, уходит в контейнер через stdin — не в argv и не на экран.
    """
    password = secrets.token_urlsafe(24)
    compose(
        "exec",
        "-T",
        "backend",
        "python",
        "-",
        stdin=f"""
from sqlalchemy import select
from app.core.db import get_session_scope
from app.core.security import hash_password
from app.models import AppUser
from app.models.enums import UserRole
with get_session_scope()() as db:
    user = db.scalars(select(AppUser).where(AppUser.phone == {ADMIN!r})).one_or_none()
    if user is None:
        user = AppUser(phone={ADMIN!r}, role=UserRole.ADMIN)
        db.add(user)
    user.role, user.is_active = UserRole.ADMIN, True
    user.password_hash = hash_password({password!r})
    db.commit()
""",
    )
    body = {"phone": ADMIN, "password": password}
    return ok(
        *call("POST", "/v1/auth/staff/login", body=body), 200, "вход администратора"
    )["access_token"]


def load_config() -> dict:
    if not CONFIG.exists():
        raise E2EError(
            "сначала: python3 scripts/push_e2e.py setup --plist <GoogleService-Info.plist>"
        )
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def token_ttl_hours(token: str) -> float:
    payload = token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    return (claims["exp"] - time.time()) / 3600


def mac_ip() -> str:
    for iface in ("en0", "en1"):
        result = subprocess.run(
            ["ipconfig", "getifaddr", iface], capture_output=True, text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    raise E2EError("не найден IP Mac в Wi-Fi — укажите --api http://<IP>:8000")


def setup(args: argparse.Namespace) -> None:
    plist = plistlib.loads(Path(args.plist).expanduser().read_bytes())
    token = login_client(OWNER_X)
    vehicle = ensure_vehicle(token, VIN_X)
    config = {
        "API_BASE_URL": args.api or f"http://{mac_ip()}:8000",
        "ACCESS_TOKEN": token,
        "FIREBASE_API_KEY": plist["API_KEY"],
        "FIREBASE_APP_ID": plist["GOOGLE_APP_ID"],
        "FIREBASE_SENDER_ID": plist["GCM_SENDER_ID"],
        "FIREBASE_PROJECT_ID": plist["PROJECT_ID"],
        "FIREBASE_IOS_BUNDLE_ID": plist["BUNDLE_ID"],
    }
    CONFIG.write_text(json.dumps(config, indent=2), encoding="utf-8")
    CONFIG.chmod(0o600)
    print(f"OK  клиент X {OWNER_X}, авто {vehicle} (Zeekr 001)")
    print(
        f"OK  {CONFIG.relative_to(ROOT)}: backend для телефона {config['API_BASE_URL']}"
    )
    hours = token_ttl_hours(token)
    if hours < 2:
        print(
            f"!!  access-токен живёт {hours * 60:.0f} мин — задайте ACCESS_TOKEN_TTL_SECONDS=86400 в .env"
        )
    print(
        "Далее: cd mobile && flutter run -t lib/main_push_debug.dart --dart-define-from-file=push_e2e.local.json"
    )


def wait_stats(admin: str, notification_id: int, field: str, at_least: int = 1) -> dict:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        items = ok(
            *call("GET", "/v1/notifications/published?page_size=100", admin),
            200,
            "лента публикаций",
        )
        stats = next(
            (i["stats"] for i in items["items"] if i["id"] == notification_id), None
        )
        if stats and stats[field] >= at_least:
            return stats
        time.sleep(0.5)
    raise E2EError(
        f"за {WAIT_SECONDS} с не дождались {field} ≥ {at_least} у уведомления {notification_id}"
    )


def feed_ids(token: str) -> list[int]:
    return [
        n["id"]
        for n in ok(*call("GET", "/v1/notifications", token), 200, "лента")["items"]
    ]


def firmware(_: argparse.Namespace) -> None:
    x = load_config()["ACCESS_TOKEN"]
    admin = login_admin()
    y = login_client(OWNER_Y)
    ensure_vehicle(y, VIN_Y, "Voyah")
    models = ok(*call("GET", "/v1/vehicle-models?search=Zeekr", admin), 200, "модели")
    version = f"e2e-{datetime.now():%m%d.%H%M%S}"
    started = datetime.now(timezone.utc)
    body = {
        "vehicle_model_id": models["items"][0]["id"],
        "version": version,
        "released_at": str(date.today()),
    }
    release = ok(
        *call("POST", "/v1/firmware-releases", admin, body), 201, "релиз прошивки"
    )
    notification = next(
        n
        for n in ok(*call("GET", "/v1/notifications", x), 200, "лента X")["items"]
        if n["firmware_release_id"] == release["id"]
    )
    stats = wait_stats(admin, notification["id"], "delivered")
    accepted = (datetime.now(timezone.utc) - started).total_seconds()
    leaked = [n for n in feed_ids(y) if n == notification["id"]]
    print(
        f"OK  ① релиз {version}: опубликован {started.isoformat(timespec='milliseconds')}"
    )
    print(
        f"OK     FCM принял за {accepted:.2f} с; доставок {stats['delivered']}, ошибок {stats['failed']}"
    )
    print(
        f"{'OK' if not leaked else 'FAIL'}     владелец Y (Voyah) уведомление {'не получил' if not leaked else 'ПОЛУЧИЛ'}"
    )
    print("→  на iPhone: push «Новая прошивка», задержка на отладочном экране < 10 с")
    if leaked:
        raise E2EError("таргетинг нарушен")


def reminder(_: argparse.Namespace) -> None:
    x = load_config()["ACCESS_TOKEN"]
    admin = login_admin()
    vehicle = ok(*call("GET", "/v1/vehicles", x), 200, "авто X")["items"][0]
    models = ok(*call("GET", "/v1/vehicle-models?search=Zeekr", admin), 200, "модели")
    regulation = {
        "vehicle_model_id": models["items"][0]["id"],
        "aggregate_type_code": "cabin_filter",
        "interval_km": 10_000,
    }
    ok(
        *call("POST", "/v1/maintenance-regulations", admin, regulation),
        201,
        "регламент",
    )
    # Новый цикл замены салонного фильтра на текущем пробеге, затем «искусственный» пробег:
    # 10 500 км после замены — 105 %, красный («просрочено»).
    replaced_km = vehicle["mileage"]
    replace = {"replaced_at": str(date.today()), "mileage_at_replacement": replaced_km}
    path = f"/v1/vehicles/{vehicle['id']}/aggregate-statuses/cabin_filter/replace"
    ok(*call("POST", path, admin, replace), 200, "замена агрегата")
    mileage = {"mileage": replaced_km + 10_500}
    ok(
        *call("PATCH", f"/v1/vehicles/{vehicle['id']}/mileage", x, mileage),
        200,
        "пробег",
    )
    before = set(feed_ids(x))
    started = datetime.now(timezone.utc)
    out = compose(
        "exec",
        "-T",
        "notifications-worker",
        "python",
        "-m",
        "app.workers.maintenance_reminders",
    )
    print(f"OK  ② {out.strip()}")
    new = [
        n
        for n in ok(*call("GET", "/v1/notifications", x), 200, "лента X")["items"]
        if n["id"] not in before and n["type"] == "maintenance"
    ]
    if not new:
        raise E2EError("напоминание о ТО не создано")
    print(
        f"OK     «{new[0]['message']}» (запуск {started.isoformat(timespec='milliseconds')})"
    )
    print(
        "→  на iPhone: push «Пора на ТО» < 10 с; отладочный экран — vehicle_id и aggregate_type_id"
    )


def news(_: argparse.Namespace) -> None:
    x = load_config()["ACCESS_TOKEN"]
    admin = login_admin()
    models = ok(*call("GET", "/v1/vehicle-models?search=Zeekr", admin), 200, "модели")
    body = {
        "type": "news",
        "target_vehicle_model_id": models["items"][0]["id"],
        "message": f"Проверка push {datetime.now():%H:%M:%S}: откройте это уведомление",
    }
    preview = ok(
        *call("POST", "/v1/notifications/audience-preview", admin, body),
        200,
        "аудитория",
    )
    print(
        f"OK  ③ аудитория: клиентов {preview['recipients']}, устройств {preview['devices']}"
    )
    started = datetime.now(timezone.utc)
    notification = ok(
        *call("POST", "/v1/notifications", admin, body), 201, "публикация"
    )
    stats = wait_stats(admin, notification["id"], "delivered")
    print(
        f"OK     FCM принял за {(datetime.now(timezone.utc) - started).total_seconds():.2f} с; в ленте X: "
        f"{'да' if notification['id'] in feed_ids(x) else 'НЕТ'}"
    )
    print(f"…  нажмите на push на iPhone (ждём до {WAIT_SECONDS} с)")
    stats = wait_stats(admin, notification["id"], "opened")
    print(
        f"OK     открытие и прочтение записаны: opened {stats['opened']}, read {stats['read']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("setup", help="тестовый клиент и mobile/push_e2e.local.json")
    p.add_argument(
        "--plist",
        required=True,
        help="GoogleService-Info.plist iOS-приложения из Firebase",
    )
    p.add_argument(
        "--api",
        help="адрес backend для телефона (по умолчанию — IP Mac в Wi-Fi, порт 8000)",
    )
    p.set_defaults(run=setup)
    for name, run in (("firmware", firmware), ("reminder", reminder), ("news", news)):
        sub.add_parser(name).set_defaults(run=run)
    args = parser.parse_args()
    try:
        args.run(args)
    except E2EError as exc:
        print(f"FAIL  {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
