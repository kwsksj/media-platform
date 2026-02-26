#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Run local required checks and show GitHub PR check status.

Usage:
  scripts/gh_pr_ready.sh [PR_NUMBER]

Behavior:
  1) make recommend-checks
  2) make check-required
  3) gh pr checks <PR>
USAGE
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
pr_number="${1:-}"
if [[ -z "$pr_number" ]]; then
  pr_number="$(gh pr view --repo "$repo_slug" --json number --jq '.number')"
fi

echo "Repository: $repo_slug"
echo "PR: #$pr_number"

echo "==> make recommend-checks"
make recommend-checks

echo "==> make check-required"
make check-required

echo "==> gh pr checks #$pr_number"
gh pr checks "$pr_number" --repo "$repo_slug"
