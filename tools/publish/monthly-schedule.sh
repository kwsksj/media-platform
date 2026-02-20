#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
source "$ROOT_DIR/tools/_lib/auto-post.sh"
run_auto_post "$ROOT_DIR" post-monthly-schedule "$@"
