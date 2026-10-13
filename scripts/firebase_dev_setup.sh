#!/usr/bin/env bash
# Локальная настройка Firebase для проверки push на Android-эмуляторе (Глава 20, ADR 0024 п. 5).
# Запускает ВЛАДЕЛЕЦ после создания бесплатного проекта Firebase (Spark) с Android-приложением
# com.etsavtogomel.evServicedesk. Пути к скачанным файлам вводятся с клавиатуры; значения ключей
# нигде не печатаются и в git не попадают:
#   - google-services.json → mobile/firebase.local.json (в .gitignore) — для
#     `flutter run --dart-define-from-file=firebase.local.json`;
#   - JSON-ключ сервисного аккаунта → ~/.config/ev-servicedesk/fcm-service-account.json (0600) —
#     его берёт scripts/integration_stack.sh при FCM_SERVICE_ACCOUNT_FILE (PUSH_PROVIDER=fcm).
# После запуска оба скачанных файла удалите из «Загрузок».
# Запуск:  ./scripts/firebase_dev_setup.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PACKAGE="com.etsavtogomel.evServicedesk"
OUT_DEFINES="$ROOT/mobile/firebase.local.json"
OUT_KEY_DIR="$HOME/.config/ev-servicedesk"
OUT_KEY="$OUT_KEY_DIR/fcm-service-account.json"

read -r -p "Путь к google-services.json (Android-приложение $PACKAGE): " gs_path
gs_path="${gs_path/#\~/$HOME}"
[ -f "$gs_path" ] || { echo "Файл не найден"; exit 1; }
read -r -p "Путь к JSON-ключу сервисного аккаунта (Service accounts → Generate new private key): " sa_path
sa_path="${sa_path/#\~/$HOME}"
[ -f "$sa_path" ] || { echo "Файл не найден"; exit 1; }

umask 077
mkdir -p "$OUT_KEY_DIR"
python3 - "$gs_path" "$sa_path" "$OUT_DEFINES" "$OUT_KEY" "$PACKAGE" <<'PY'
import json, sys

gs_path, sa_path, out_defines, out_key, package = sys.argv[1:]
gs = json.load(open(gs_path, encoding="utf-8"))
client = next((c for c in gs.get("client", [])
               if c.get("client_info", {}).get("android_client_info", {}).get("package_name") == package),
              None)
if client is None:
    sys.exit(f"В google-services.json нет Android-приложения {package}")
info = gs["project_info"]
defines = {
    "FIREBASE_API_KEY": client["api_key"][0]["current_key"],
    "FIREBASE_APP_ID": client["client_info"]["mobilesdk_app_id"],
    "FIREBASE_SENDER_ID": info["project_number"],
    "FIREBASE_PROJECT_ID": info["project_id"],
}
sa = json.load(open(sa_path, encoding="utf-8"))
missing = [k for k in ("project_id", "client_email", "private_key") if not sa.get(k)]
if sa.get("type") != "service_account" or missing:
    sys.exit("Это не ключ сервисного аккаунта Firebase (нет: " + ", ".join(missing or ["type"]) + ")")
if sa["project_id"] != info["project_id"]:
    sys.exit("Ключ сервисного аккаунта и google-services.json — из разных проектов Firebase")
with open(out_defines, "w", encoding="utf-8") as f:
    json.dump(defines, f, indent=2)
with open(out_key, "w", encoding="utf-8") as f:
    json.dump(sa, f, separators=(",", ":"))
print(f"→ проект Firebase {info['project_id']}: конфигурация приложения и ключ записаны")
PY
chmod 600 "$OUT_KEY" "$OUT_DEFINES"
echo "→ $OUT_DEFINES (в .gitignore)"
echo "→ $OUT_KEY"
echo "Удалите скачанные файлы из «Загрузок»."
