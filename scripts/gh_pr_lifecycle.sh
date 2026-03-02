#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Run end-to-end PR lifecycle for this repository.

Usage:
  scripts/gh_pr_lifecycle.sh [PR_NUMBER]

Behavior:
  1) make recommend-checks
  2) make check-required
  3) gh pr checks <PR>
  4) scripts/gh_pr_merge_and_cleanup_local.sh <PR>

Environment variables:
  PR_LIFECYCLE_SKIP_LOCAL_CHECKS=true|false  (default: false)
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "gh command is required." >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "gh is not authenticated. Run: gh auth login" >&2
  exit 1
fi

repo_slug="$(gh repo view --json nameWithOwner --jq '.nameWithOwner')"
pr_number="${1:-${PR:-}}"
if [[ -z "$pr_number" ]]; then
  pr_number="$(gh pr view --repo "$repo_slug" --json number --jq '.number' 2>/dev/null || true)"
  if [[ ! "$pr_number" =~ ^[0-9]+$ ]]; then
    echo "Could not auto-detect a valid PR number. Run from a PR branch or specify PR=<number>." >&2
    exit 1
  fi
elif [[ ! "$pr_number" =~ ^[0-9]+$ ]]; then
  echo "Invalid PR number: '$pr_number' (must be numeric)." >&2
  exit 1
fi

skip_local_checks="$(echo "${PR_LIFECYCLE_SKIP_LOCAL_CHECKS:-false}" | tr '[:upper:]' '[:lower:]' | xargs)"

echo "Repository: $repo_slug"
echo "PR: #$pr_number"
echo "Skip local checks: $skip_local_checks"

if [[ "$skip_local_checks" != "true" ]]; then
  echo "==> make recommend-checks"
  make recommend-checks

  echo "==> make check-required"
  make check-required
fi

echo "==> gh pr checks #$pr_number"
gh pr checks "$pr_number" --repo "$repo_slug" || true

echo "==> scripts/gh_pr_merge_and_cleanup_local.sh #$pr_number"
./scripts/gh_pr_merge_and_cleanup_local.sh "$pr_number"
