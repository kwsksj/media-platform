#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WRANGLER_CONFIG="${WRANGLER_CONFIG:-${APP_DIR}/../worker-api/wrangler.toml}"

BUCKET="${1:-woodcarving-photos}"
FILE="${2:-${APP_DIR}/gallery.html}"

if [[ ! -f "$FILE" ]]; then
  CANDIDATE="${APP_DIR}/$FILE"
  if [[ -f "$CANDIDATE" ]]; then
    FILE="$CANDIDATE"
  else
    echo "ファイルが見つかりません: $FILE" >&2
    exit 1
  fi
fi

OBJECT_NAME="$(basename "$FILE")"

npx wrangler r2 object put "${BUCKET}/${OBJECT_NAME}" \
  --config="${WRANGLER_CONFIG}" \
  --file="$FILE" \
  --content-type="text/html" \
  --cache-control="max-age=3600" \
  --remote
