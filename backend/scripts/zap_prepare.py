"""Подготовка сканирования OWASP ZAP на интеграционном стеке (Глава 25, ADR 0029 п. 7).

Создаёт участников и данные, которые сканер будет атаковать, и пишет в каталог `--out`:
- `tokens.json` (права 600) — access-токены client, engineer, admin (каталог временный, вне
  отчётов);
- `openapi-<роль>.yaml` — контракт только с операциями роли, без операций, завершающих сессию
  сканера (выход, отзыв согласия, смена и сброс пароля, блокировка): иначе ZAP на середине
  прохода разлогинил бы сам себя и сканировал бы одни 401;
- `openapi-anonymous.yaml` — все операции: проход без токена (публичные операции и отказы 401).

Окружение (scripts/integration_stack.sh): API_BASE_URL, E2E_CODE, E2E_JOB_RUNNER, E2E_ZAP_PHONE.
Только стандартная библиотека и PyYAML (dev-зависимость backend).
"""

import argparse
import copy
import json
import os
import secrets
import shlex
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
POLICY = "2026-10"
# Завершают сессию предъявителя или чужую — не для прохода с токеном (сканируются без токена).
SESSION_ENDING = {
    "logout",
    "withdrawPdConsent",
    "changeStaffPassword",
    "updateUser",
    "resetUserPassword",
}


def call(base: str, method: str, path: str, body: dict | None = None, token: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{base}{path}", data=data, method=method)  # noqa: S310
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        # Адрес — API_BASE_URL стенда (http), не пользовательский ввод.
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{method} {path}: {exc.code} {exc.read()[:300]!r}") from exc
    return json.loads(raw) if raw else None


def staff_login(base: str, phone: str, password: str) -> str:
    body = {"phone": phone, "password": password}
    return call(base, "POST", "/auth/staff/login", body)["access_token"]


def prepare(base: str, code: str, runner: str, client_phone: str) -> dict[str, str]:
    call(base, "POST", "/auth/phone/request-code", {"phone": client_phone})
    verify = {"phone": client_phone, "code": code, "pd_policy_version": POLICY}
    client = call(base, "POST", "/auth/phone/verify-code", verify)["access_token"]

    admin_phone = "+3752990" + f"{secrets.randbelow(10**5):05d}"
    admin_password = secrets.token_urlsafe(24)
    subprocess.run(  # noqa: S603 — префикс задачи стека, без shell
        [*shlex.split(runner), "python", "-m", "app.cli", "create-admin", "--phone", admin_phone],
        input=admin_password + "\n",
        text=True,
        check=True,
        capture_output=True,
    )
    admin = staff_login(base, admin_phone, admin_password)

    engineer_phone = "+3752991" + f"{secrets.randbelow(10**5):05d}"
    engineer_password = secrets.token_urlsafe(24)
    body = {"phone": engineer_phone, "role": "engineer", "password": engineer_password}
    call(base, "POST", "/users", body, admin)
    engineer = staff_login(base, engineer_phone, engineer_password)

    # Данные для атак по id: авто, тикет в работе у инженера, сообщение в чате.
    vin = "L6TZ001" + f"{secrets.randbelow(10**10):010d}"
    vehicle = call(base, "POST", "/vehicles", {"vin": vin}, client)
    ticket = call(
        base,
        "POST",
        "/tickets",
        {"vehicle_id": vehicle["id"], "category": "sim", "description": "Сканирование ZAP"},
        client,
    )
    call(base, "POST", f"/tickets/{ticket['id']}/claim", None, engineer)
    call(base, "POST", f"/tickets/{ticket['id']}/messages", {"body": "Сообщение ZAP"}, engineer)
    return {"client": client, "engineer": engineer, "admin": admin}


def role_specs(out: Path) -> None:
    spec = yaml.safe_load((ROOT / "docs" / "openapi.yaml").read_text(encoding="utf-8"))
    (out / "openapi-anonymous.yaml").write_text(yaml.safe_dump(spec, allow_unicode=True))
    for role in ("client", "engineer", "admin"):
        scoped = copy.deepcopy(spec)
        for path, item in list(scoped["paths"].items()):
            for method, op in list(item.items()):
                if not isinstance(op, dict) or "operationId" not in op:
                    continue
                roles = op.get("x-required-roles")
                if not roles or role not in roles or op["operationId"] in SESSION_ENDING:
                    del item[method]
            if not any(isinstance(v, dict) and "operationId" in v for v in item.values()):
                del scoped["paths"][path]
        (out / f"openapi-{role}.yaml").write_text(yaml.safe_dump(scoped, allow_unicode=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    base = os.environ["API_BASE_URL"].rstrip("/") + "/v1"
    tokens = prepare(
        base, os.environ["E2E_CODE"], os.environ["E2E_JOB_RUNNER"], os.environ["E2E_ZAP_PHONE"]
    )
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "tokens.json"
    path.touch(mode=0o600)
    path.write_text(json.dumps(tokens))
    role_specs(args.out)
    print("PASS  ZAP: участники, данные и контракты ролей готовы")


if __name__ == "__main__":
    main()
