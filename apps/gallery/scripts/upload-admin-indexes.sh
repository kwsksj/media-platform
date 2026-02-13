#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MONOREPO_ROOT="$(cd "$REPO_ROOT/../.." && pwd)"

BUCKET="${1:-woodcarving-photos}"
ENV_FILE="${2:-$MONOREPO_ROOT/.env}"
OUT_DIR="${3:-$(mktemp -d)}"

cleanup() {
  if [[ "${3:-}" == "" ]] && [[ -d "$OUT_DIR" ]]; then
    rm -rf "$OUT_DIR"
  fi
}
trap cleanup EXIT

cd "$REPO_ROOT"

echo "[1/3] Build students_index.json and tags_index.json"
node ./scripts/build-admin-indexes.mjs --env-file "$ENV_FILE" --out-dir "$OUT_DIR"

echo "[2/3] Upload students_index.json to R2 ($BUCKET)"
npx wrangler r2 object put "${BUCKET}/students_index.json" \
  --file="${OUT_DIR}/students_index.json" \
  --content-type="application/json; charset=utf-8" \
  --cache-control="max-age=300" \
  --remote

echo "[3/3] Upload tags_index.json to R2 ($BUCKET)"
npx wrangler r2 object put "${BUCKET}/tags_index.json" \
  --file="${OUT_DIR}/tags_index.json" \
  --content-type="application/json; charset=utf-8" \
  --cache-control="max-age=300" \
  --remote

echo "Done. Uploaded:"
echo "  - students_index.json"
echo "  - tags_index.json"
