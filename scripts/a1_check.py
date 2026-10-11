#!/usr/bin/env python3
"""Проверка доступа к A1 «Smart-рассылка» (Глава 10, ADR 0013). Запускает владелец.

Проверяет логин + API-ключ, разрешён ли IP этой машины и доступно ли альфа-имя.
Ключ берётся из SMS_PROVIDER_API_KEY или спрашивается скрытым вводом; он не печатается,
не пишется на диск и передаётся только в теле POST по HTTPS (не в URL и не в argv).

  python3 scripts/a1_check.py                         # проверка доступа и имён отправителя
  python3 scripts/a1_check.py --sender ETSGOMEL        # + проверка конкретного имени
  python3 scripts/a1_check.py --send +375XXXXXXXXX     # + тестовое SMS (платно, с подтверждением)

Только стандартная библиотека Python 3.9+.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("SMS_PROVIDER_URL", "https://smart-sender.a1.by/api").rstrip("/")

# Коды ошибок A1 (HTTP API 1.2.3).
HINTS = {
    3: "не переданы user/apikey",
    4: "неверный логин (msisdn) или API-ключ — проверьте «Настройки» → API key в кабинете",
    5: "доступ с этого IP не разрешён — сообщите администраторам A1 внешний IP этой машины/сервера",
    6: "учётная запись не активирована — обратитесь в A1",
    7: "превышена частота запросов (10/с) — повторите позже",
    8: "канал доставки недоступен для учётной записи",
    100: "невалидный номер получателя",
    101: "номер в пользовательском стоп-листе",
    102: "номер в глобальном стоп-листе",
    103: "номер относится к запрещённому оператору",
    104: "имя отправителя недоступно — нужно одобренное альфа-имя (раздел «Имена отправителя»)",
    106: "текст содержит стоп-слово",
}


def call(function: str, params: dict) -> dict:
    data = urllib.parse.urlencode(params).encode()
    request = urllib.request.Request(f"{API}/{function}", data=data, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read()
    except urllib.error.URLError as exc:
        sys.exit(f"FAIL  A1 недоступен: {exc.reason}")
    try:
        return json.loads(body)
    except ValueError:
        sys.exit(f"FAIL  A1 вернул не JSON (HTTP-ответ: {body[:200]!r})")


def explain(result: dict) -> str:
    error = result.get("error") or {}
    code = error.get("code")
    hint = HINTS.get(code, error.get("description", "неизвестная ошибка"))
    parameter = f", параметр {error['parameter']}" if error.get("parameter") else ""
    return f"код {code}: {hint}{parameter}"


def sender_names(result: dict) -> tuple[list[str], str | None, list[str]]:
    """SMS-имена, имя по умолчанию и Viber-имена — по схеме /senderNames (apidoc 1.2.3)."""

    def names(channel: str) -> list[dict]:
        items = result.get(channel)
        return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []

    sms = names("sms")
    sms_names = sorted({i["sender"] for i in sms if isinstance(i.get("sender"), str)})
    default = next((i.get("sender") for i in sms if i.get("is_default")), None)
    viber = sorted({i["sender"] for i in names("viber") if isinstance(i.get("sender"), str)})
    return sms_names, default, viber


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--sender", default=os.environ.get("SMS_SENDER", ""), help="альфа-имя для проверки"
    )
    parser.add_argument(
        "--send", metavar="+375...", help="отправить тестовое SMS на этот номер (платно)"
    )
    args = parser.parse_args()

    user = os.environ.get("SMS_PROVIDER_USER") or input("Логин A1 (msisdn, только цифры): ").strip()
    key = (
        os.environ.get("SMS_PROVIDER_API_KEY")
        or getpass.getpass("API key A1 (ввод скрыт): ").strip()
    )
    if not user.isdigit() or not key:
        sys.exit("FAIL  нужен логин из цифр (например 375XXXXXXXXX) и непустой API-ключ")
    auth = {"user": user, "apikey": key}

    result = call("senderNames", auth)
    if result.get("status") is not True:
        sys.exit(f"FAIL  доступ к API: {explain(result)}")
    print("PASS  логин и API-ключ приняты, IP этой машины разрешён")
    names, default, viber = sender_names(result)
    print(f"INFO  SMS-имена отправителя: {', '.join(names) if names else '(нет)'}")
    print(f"INFO  имя по умолчанию: {default or '(не задано)'}")
    if viber:
        print(f"INFO  Viber-имена (для SMS не подходят): {', '.join(viber)}")
    if args.sender:
        if args.sender in names:
            print(f"PASS  SMS-имя отправителя {args.sender} доступно")
        else:
            print(f"WARN  SMS-имени {args.sender} нет в списке — SMS вернёт ошибку 104")

    if args.send:
        phone = args.send.strip()
        if not re.fullmatch(r"\+[1-9][0-9]{7,14}", phone):
            sys.exit("FAIL  номер для теста — в формате E.164, например +375291234567")
        answer = input(f"Отправить платное тестовое SMS на {phone}? [y/N] ").strip().lower()
        if answer != "y":
            print("SKIP  тестовое SMS не отправлено")
            return
        params = auth | {
            "msisdn": phone.removeprefix("+"),
            "text": "EV-ServiceDesk: тестовое сообщение, проверка подключения.",
            "dlr_timeout": "10",
        }
        if args.sender:
            params["sender"] = args.sender
        sent = call("send/sms", params)
        if sent.get("status") is not True:
            sys.exit(f"FAIL  отправка: {explain(sent)}")
        print(
            f"PASS  SMS принято A1: message_id={sent.get('message_id')}, "
            f"частей={sent.get('parts')}, стоимость={sent.get('amount')}"
        )


if __name__ == "__main__":
    main()
