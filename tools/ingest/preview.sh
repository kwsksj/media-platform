#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT_DIR/tools/_lib/auto-post.sh"
run_auto_post "$ROOT_DIR" preview-groups "$@"
