#!/usr/bin/env bash
set -euo pipefail

resolve_auto_post_bin() {
  local root_dir="$1"
  local candidate="${AUTO_POST_BIN:-$root_dir/venv/bin/auto-post}"

  if [[ -x "$candidate" ]] && "$candidate" --help >/dev/null 2>&1; then
    printf "%s" "$candidate"
    return 0
  fi

  if command -v auto-post >/dev/null 2>&1; then
    local path_bin
    path_bin="$(command -v auto-post)"
    if "$path_bin" --help >/dev/null 2>&1; then
      printf "%s" "$path_bin"
      return 0
    fi
  fi

  return 1
}

run_auto_post() {
  local root_dir="$1"
  local subcommand="$2"
  shift 2

  local bin=""
  if bin="$(resolve_auto_post_bin "$root_dir")"; then
    exec "$bin" "$subcommand" "$@"
  fi

  # Last-resort fallback for local dev when entrypoint scripts are not installed.
  exec env PYTHONPATH="$root_dir/src${PYTHONPATH:+:$PYTHONPATH}" \
    python3 -m auto_post.cli "$subcommand" "$@"
}
