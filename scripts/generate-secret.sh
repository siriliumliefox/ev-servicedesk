#!/usr/bin/env bash
# Генерирует криптостойкий секрет для JWT_SECRET и подобных значений.
# Использование: ./scripts/generate-secret.sh
set -euo pipefail
openssl rand -hex 32
