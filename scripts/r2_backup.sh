#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
R2 backup/restore helper (rclone required).

Usage:
  scripts/r2_backup.sh backup [--source SRC] [--dest DST] [-- <extra rclone args>]
  scripts/r2_backup.sh backup-dry-run [--source SRC] [--dest DST] [-- <extra rclone args>]
  scripts/r2_backup.sh restore-dry-run [--source SRC] [--dest DST] [-- <extra rclone args>]

Defaults:
  source (backup):      ${R2_REMOTE_NAME:-r2}:${R2_BUCKET_NAME}
  destination (backup): ${R2_BACKUP_REMOTE:-gdrive:media-platform-r2/current}
  source (restore):     ${R2_BACKUP_REMOTE:-gdrive:media-platform-r2/current}
  destination (restore):${R2_REMOTE_NAME:-r2}:${R2_BUCKET_NAME}

Notes:
  - backup mode uses "rclone copy" (non-destructive on destination).
  - restore is dry-run only by design to prevent accidental overwrite.
EOF
}

if ! command -v rclone >/dev/null 2>&1; then
  echo "rclone is required but not installed." >&2
  exit 1
fi

MODE="${1:-backup}"
if [[ "$#" -gt 0 ]]; then
  shift
fi

SOURCE_OVERRIDE=""
DEST_OVERRIDE=""
EXTRA_ARGS=()

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --source)
      NEXT_VALUE="${2:-}"
      if [[ -z "$NEXT_VALUE" || "${NEXT_VALUE:0:1}" == "-" ]]; then
        echo "Error: --source requires a value." >&2
        exit 1
      fi
      SOURCE_OVERRIDE="$NEXT_VALUE"
      shift 2
      ;;
    --dest)
      NEXT_VALUE="${2:-}"
      if [[ -z "$NEXT_VALUE" || "${NEXT_VALUE:0:1}" == "-" ]]; then
        echo "Error: --dest requires a value." >&2
        exit 1
      fi
      DEST_OVERRIDE="$NEXT_VALUE"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --)
      shift
      EXTRA_ARGS+=("$@")
      break
      ;;
    *)
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

R2_REMOTE_NAME="${R2_REMOTE_NAME:-r2}"
R2_BUCKET_NAME="${R2_BUCKET_NAME:-}"
R2_BACKUP_REMOTE="${R2_BACKUP_REMOTE:-gdrive:media-platform-r2/current}"

# Allow running via "make r2-backup*" without manual export.
if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

R2_PATH="${R2_REMOTE_NAME}:${R2_BUCKET_NAME}"

SOURCE=""
DEST=""
DRY_RUN=false
USES_DEFAULT_R2_PATH=false

case "$MODE" in
  backup)
    if [[ -n "$SOURCE_OVERRIDE" ]]; then
      SOURCE="$SOURCE_OVERRIDE"
    else
      SOURCE="$R2_PATH"
      USES_DEFAULT_R2_PATH=true
    fi
    DEST="${DEST_OVERRIDE:-$R2_BACKUP_REMOTE}"
    ;;
  backup-dry-run)
    if [[ -n "$SOURCE_OVERRIDE" ]]; then
      SOURCE="$SOURCE_OVERRIDE"
    else
      SOURCE="$R2_PATH"
      USES_DEFAULT_R2_PATH=true
    fi
    DEST="${DEST_OVERRIDE:-$R2_BACKUP_REMOTE}"
    DRY_RUN=true
    ;;
  restore-dry-run)
    SOURCE="${SOURCE_OVERRIDE:-$R2_BACKUP_REMOTE}"
    if [[ -n "$DEST_OVERRIDE" ]]; then
      DEST="$DEST_OVERRIDE"
    else
      DEST="$R2_PATH"
      USES_DEFAULT_R2_PATH=true
    fi
    DRY_RUN=true
    ;;
  *)
    echo "Unknown mode: $MODE" >&2
    usage
    exit 1
    ;;
esac

if [[ "$USES_DEFAULT_R2_PATH" == "true" && -z "$R2_BUCKET_NAME" ]]; then
  echo "R2_BUCKET_NAME is required unless the default R2 endpoint is fully overridden." >&2
  exit 1
fi

RCLONE_ARGS=(
  copy
  "$SOURCE"
  "$DEST"
  --fast-list
  --checkers=16
  --transfers=8
  --metadata
)

if [[ "$DRY_RUN" == "true" ]]; then
  RCLONE_ARGS+=(--dry-run)
fi

if [[ "${#EXTRA_ARGS[@]}" -gt 0 ]]; then
  RCLONE_ARGS+=("${EXTRA_ARGS[@]}")
fi

echo "Mode: $MODE"
echo "Source: $SOURCE"
echo "Destination: $DEST"
if [[ "$DRY_RUN" == "true" ]]; then
  echo "Dry-run: true"
fi

rclone "${RCLONE_ARGS[@]}"
