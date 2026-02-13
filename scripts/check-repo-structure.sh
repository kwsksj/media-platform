#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

required_dirs=(
  "apps/gallery-web"
  "apps/admin-web"
  "apps/worker-api"
  "tools/ingest"
  "tools/publish"
  "tools/gallery-build"
  "docs"
)

required_files=(
  "apps/gallery-web/gallery.html"
  "apps/admin-web/admin.html"
  "apps/admin-web/admin/admin.js"
  "apps/admin-web/shared/gallery-core.js"
  "apps/worker-api/worker/src/index.js"
  "apps/worker-api/wrangler.toml"
)

echo "Checking repository structure..."

for d in "${required_dirs[@]}"; do
  if [[ ! -d "$ROOT_DIR/$d" ]]; then
    echo "ERROR: missing directory: $d" >&2
    exit 1
  fi
  echo "OK dir: $d"
done

for f in "${required_files[@]}"; do
  if [[ ! -f "$ROOT_DIR/$f" ]]; then
    echo "ERROR: missing file: $f" >&2
    exit 1
  fi
  echo "OK file: $f"
done

echo "Repository structure check passed."
