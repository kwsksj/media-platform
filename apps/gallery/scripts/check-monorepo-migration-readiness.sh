#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GALLERY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Resolve canonical auto-post repo path:
# 1) explicit AUTO_POST_DIR, if provided
# 2) monorepo layout: <auto-post>/apps/gallery
# 3) split-repo layout: <parent>/auto-post
if [[ -n "${AUTO_POST_DIR:-}" ]]; then
  AUTO_POST_DIR="${AUTO_POST_DIR}"
else
  MONOREPO_CANDIDATE="$(cd "${GALLERY_DIR}/../.." && pwd)"
  SPLIT_REPO_CANDIDATE="$(cd "${GALLERY_DIR}/.." && pwd)/auto-post"

  if [[ -d "${MONOREPO_CANDIDATE}/.git" && -d "${MONOREPO_CANDIDATE}/.github/workflows" ]]; then
    AUTO_POST_DIR="${MONOREPO_CANDIDATE}"
  else
    AUTO_POST_DIR="${SPLIT_REPO_CANDIDATE}"
  fi
fi

ALREADY_IMPORTED=0
if [[ -d "${AUTO_POST_DIR}/apps/gallery" ]]; then
  IMPORTED_DIR_REAL="$(cd "${AUTO_POST_DIR}/apps/gallery" && pwd)"
  GALLERY_DIR_REAL="$(cd "${GALLERY_DIR}" && pwd)"
  if [[ "${IMPORTED_DIR_REAL}" == "${GALLERY_DIR_REAL}" ]]; then
    ALREADY_IMPORTED=1
  fi
fi

echo "[1/4] Checking gallery repo path"
IS_GALLERY_GIT_REPO=0
if [[ -d "${GALLERY_DIR}/.git" ]]; then
  IS_GALLERY_GIT_REPO=1
  echo "OK: standalone gallery repo at ${GALLERY_DIR}"
elif [[ -f "${GALLERY_DIR}/admin.html" && -f "${GALLERY_DIR}/worker/src/index.js" ]]; then
  echo "OK: gallery module directory at ${GALLERY_DIR}"
else
  echo "ERROR: gallery directory is invalid: ${GALLERY_DIR}" >&2
  exit 1
fi

echo "[2/4] Checking auto-post repo path"
if [[ ! -d "${AUTO_POST_DIR}/.git" ]]; then
  echo "ERROR: auto-post git repo not found at ${AUTO_POST_DIR}" >&2
  echo "Hint: set AUTO_POST_DIR=/path/to/auto-post and rerun." >&2
  exit 1
fi
echo "OK: ${AUTO_POST_DIR}"

echo "[3/4] Checking clean working trees"
auto_post_dirty="$(git -C "${AUTO_POST_DIR}" status --porcelain)"
gallery_dirty=""
if [[ "${IS_GALLERY_GIT_REPO}" -eq 1 ]]; then
  gallery_dirty="$(git -C "${GALLERY_DIR}" status --porcelain)"
  if [[ -n "${gallery_dirty}" && "${ALLOW_GALLERY_DIRTY:-0}" != "1" ]]; then
    echo "ERROR: gallery repo has uncommitted changes." >&2
    echo "Hint: commit/stash changes or run with ALLOW_GALLERY_DIRTY=1." >&2
    exit 1
  fi
fi
if [[ -n "${auto_post_dirty}" ]]; then
  echo "ERROR: auto-post repo has uncommitted changes." >&2
  exit 1
fi
if [[ "${IS_GALLERY_GIT_REPO}" -eq 1 && -n "${gallery_dirty}" ]]; then
  echo "WARN: gallery repo is dirty, but ALLOW_GALLERY_DIRTY=1 is set."
else
  if [[ "${IS_GALLERY_GIT_REPO}" -eq 1 ]]; then
    echo "OK: both repos are clean"
  else
    echo "OK: auto-post repo is clean (gallery is module directory)"
  fi
fi

if [[ "${ALREADY_IMPORTED}" -eq 1 ]]; then
  cat <<EOF

Gallery is already imported into canonical repo.
No import action is needed.

Recommended next checks:
  cd "${AUTO_POST_DIR}"
  auto-post post --dry-run --date \$(date +%Y-%m-%d)
  auto-post export-gallery-json --no-upload --no-thumbs --no-light
  cd "${AUTO_POST_DIR}/apps/gallery" && npx wrangler deploy --dry-run

Docs:
  - ${AUTO_POST_DIR}/MONOREPO_INTEGRATION.md
  - ${AUTO_POST_DIR}/apps/gallery/docs/monorepo-migration-plan.md
EOF
  exit 0
fi

echo "[4/4] Checking subtree support"
IMPORT_MODE="subtree"
if ! git -C "${AUTO_POST_DIR}" subtree --help >/dev/null 2>&1; then
  IMPORT_MODE="rsync"
  echo "WARN: git subtree is not available. Falling back to rsync import instructions."
else
  echo "OK: git subtree is available"
fi

cat <<EOF

Migration is ready.

Recommended next commands:
EOF

if [[ "${IMPORT_MODE}" == "subtree" ]]; then
cat <<EOF
History-preserving import (auto-post is canonical):
  git -C "${AUTO_POST_DIR}" checkout -b codex/monorepo-bootstrap
  git -C "${AUTO_POST_DIR}" remote add gallery-local "${GALLERY_DIR}"
  git -C "${AUTO_POST_DIR}" fetch gallery-local
  git -C "${AUTO_POST_DIR}" subtree add --prefix apps/gallery gallery-local main
EOF
else
cat <<EOF
Copy import (no history, auto-post is canonical):
  git -C "${AUTO_POST_DIR}" checkout -b codex/monorepo-bootstrap
  mkdir -p "${AUTO_POST_DIR}/apps/gallery"
  rsync -a --exclude .git "${GALLERY_DIR}/" "${AUTO_POST_DIR}/apps/gallery/"
  git -C "${AUTO_POST_DIR}" add apps/gallery
  git -C "${AUTO_POST_DIR}" commit -m "Import gallery into apps/gallery (no history)"
EOF
fi

cat <<EOF
Docs:
  - ${AUTO_POST_DIR}/MONOREPO_INTEGRATION.md
  - ${GALLERY_DIR}/docs/monorepo-migration-plan.md
EOF
