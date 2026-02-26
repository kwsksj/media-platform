#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Merge a PR with GitHub CLI and clean up the current local branch after merge.

Usage:
  scripts/gh_pr_merge_and_cleanup_local.sh [PR_NUMBER]

Behavior:
  1) gh pr merge --auto --squash --delete-branch
  2) If PR state is MERGED:
     - switch to default branch
     - fast-forward pull
     - delete the original local branch
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

if ! command -v git >/dev/null 2>&1; then
  echo "git command is required." >&2
  exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Working tree is not clean. Commit or stash changes first." >&2
  exit 1
fi

start_branch="$(git rev-parse --abbrev-ref HEAD)"
repo_slug="$(gh repo view --json nameWithOwner --jq '.nameWithOwner')"
default_branch="$(gh repo view --json defaultBranchRef --jq '.defaultBranchRef.name')"

pr_number="${1:-}"
if [[ -z "$pr_number" ]]; then
  pr_number="$(gh pr view --repo "$repo_slug" --json number --jq '.number')"
fi

echo "Repository: $repo_slug"
echo "PR: #$pr_number"
echo "Current branch: $start_branch"
echo "Default branch: $default_branch"

gh pr merge "$pr_number" \
  --repo "$repo_slug" \
  --auto \
  --squash \
  --delete-branch

pr_state="$(gh pr view "$pr_number" --repo "$repo_slug" --json state --jq '.state')"
if [[ "$pr_state" != "MERGED" ]]; then
  echo "PR is not merged yet (state=$pr_state). Local branch cleanup is skipped for now."
  echo "Run this command again after merge to clean up the local branch."
  exit 0
fi

if [[ "$start_branch" == "$default_branch" ]]; then
  echo "Already on default branch. Local cleanup is not required."
  exit 0
fi

git switch "$default_branch"
git pull --ff-only

if git branch -d "$start_branch"; then
  echo "Deleted local branch: $start_branch"
else
  echo "Failed to delete local branch with -d. Check branch status manually." >&2
  exit 1
fi
