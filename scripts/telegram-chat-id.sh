#!/usr/bin/env bash
# chat_id для алертов (глава 26, ADR 0030 п. 14). Запускает владелец: создайте бота у @BotFather,
# напишите ему /start, затем запустите скрипт и введите токен (скрыто). Токен не попадает в argv и
# журналы: адрес запроса передаётся curl через stdin. Печатает chat_id чатов, написавших боту.
set -euo pipefail
read -r -s -p "Токен бота алертов: " token; echo
printf 'url = "https://api.telegram.org/bot%s/getUpdates"\n' "$token" | curl -fsS --config - \
  | python3 -c '
import json, sys
chats = {}
for update in json.load(sys.stdin).get("result", []):
    chat = (update.get("message") or update.get("my_chat_member") or {}).get("chat")
    if chat:
        chats[chat["id"]] = chat.get("username") or chat.get("title") or ""
if not chats:
    print("Нет сообщений боту — напишите ему /start и повторите.")
for chat_id, name in chats.items():
    print(f"chat_id {chat_id}  {name}")'
unset token
