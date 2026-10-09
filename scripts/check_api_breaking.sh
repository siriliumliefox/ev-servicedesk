#!/bin/sh
# Ломающие изменения docs/openapi.yaml относительно базовой ветки (ADR 0007).
# Базовая версия — релиз (X.Y.Z): ломающее изменение = ошибка.
# Базовая версия — пререлиз (X.Y.Z-rcN): только отчёт (до заморозки v1).
# Использование: scripts/check_api_breaking.sh [base-ref]   (по умолчанию origin/develop)
set -eu

BASE_REF="${1:-origin/develop}"
OASDIFF_IMAGE="tufin/oasdiff:v1.32.1"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if ! git show "$BASE_REF:docs/openapi.yaml" > "$TMP/base.yaml" 2>/dev/null; then
    echo "В $BASE_REF нет docs/openapi.yaml — сравнивать не с чем."
    exit 0
fi
cp docs/openapi.yaml "$TMP/head.yaml"

BASE_VERSION="$(sed -n 's/^  version: "\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' "$TMP/base.yaml" | head -n 1)"
echo "Базовый контракт: $BASE_REF, версия $BASE_VERSION"

run_oasdiff() {
    docker run --rm -v "$TMP:/specs:ro" "$OASDIFF_IMAGE" breaking /specs/base.yaml /specs/head.yaml "$@"
}

case "$BASE_VERSION" in
    *-*)
        echo "Базовая версия — пререлиз: ломающие изменения допустимы до заморозки v1 (отчёт ниже)."
        run_oasdiff --format singleline
        ;;
    *)
        run_oasdiff --format singleline --fail-on ERR
        echo "Ломающих изменений нет."
        ;;
esac
