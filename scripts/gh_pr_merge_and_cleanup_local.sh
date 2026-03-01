#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Merge a PR with GitHub CLI and clean up the current local branch after merge.

Usage:
  scripts/gh_pr_merge_and_cleanup_local.sh [PR_NUMBER]

Behavior:
  1) Wait for AI review signals (enabled by default)
     - Gemini: review from gemini-code-assist[bot]
     - Codex: comment/review OR +1 reaction from chatgpt-codex-connector[bot]
  2) gh pr merge --auto --squash --delete-branch
  3) Wait for merge completion (default: 600s, configurable by PR_MERGE_WAIT_SECONDS)
  4) If PR state is MERGED:
     - switch to default branch
     - fast-forward pull
     - delete the original local branch (force-delete fallback for squash/rebase merge)

Environment variables:
  PR_REQUIRE_AI_REVIEW=true|false     (default: true)
  PR_AI_REVIEW_WAIT_SECONDS=900       (default timeout)
  PR_AI_REVIEW_POLL_SECONDS=10        (default poll interval)
  PR_GEMINI_BOT_LOGIN=...             (default: gemini-code-assist[bot])
  PR_CODEX_BOT_LOGIN=...              (default: chatgpt-codex-connector[bot])
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

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree is not clean. Commit or stash changes first." >&2
  exit 1
fi

start_branch="$(git rev-parse --abbrev-ref HEAD)"
repo_slug="$(gh repo view --json nameWithOwner --jq '.nameWithOwner')"
default_branch="$(gh repo view --json defaultBranchRef --jq '.defaultBranchRef.name')"
wait_seconds="${PR_MERGE_WAIT_SECONDS:-600}"
require_ai_review="$(echo "${PR_REQUIRE_AI_REVIEW:-true}" | tr '[:upper:]' '[:lower:]' | xargs)"
ai_wait_seconds="${PR_AI_REVIEW_WAIT_SECONDS:-900}"
ai_poll_seconds="${PR_AI_REVIEW_POLL_SECONDS:-10}"
gemini_bot_login="${PR_GEMINI_BOT_LOGIN:-gemini-code-assist[bot]}"
codex_bot_login="${PR_CODEX_BOT_LOGIN:-chatgpt-codex-connector[bot]}"

pr_number="${1:-}"
if [[ -z "$pr_number" ]]; then
  pr_number="$(gh pr view --repo "$repo_slug" --json number --jq '.number')"
fi

echo "Repository: $repo_slug"
echo "PR: #$pr_number"
echo "Current branch: $start_branch"
echo "Default branch: $default_branch"
echo "Wait timeout (seconds): $wait_seconds"
echo "Require AI review signals: $require_ai_review"

table_has_actor() {
  local actor="$1"
  local table="$2"
  awk -F'\t' -v actor="$actor" '$1 == actor {found=1} END {exit found ? 0 : 1}' <<<"$table"
}

table_has_actor_content() {
  local actor="$1"
  local content="$2"
  local table="$3"
  awk -F'\t' -v actor="$actor" -v content="$content" '$1 == actor && $2 == content {found=1} END {exit found ? 0 : 1}' <<<"$table"
}

if [[ "$require_ai_review" == "true" ]]; then
  if [[ "$ai_wait_seconds" -lt 0 ]]; then
    ai_wait_seconds=0
  fi
  if [[ "$ai_poll_seconds" -lt 1 ]]; then
    ai_poll_seconds=1
  fi

  echo "Waiting for AI review signals before merge..."
  echo "- Gemini actor: $gemini_bot_login"
  echo "- Codex actor:  $codex_bot_login"
  echo "- Timeout (seconds): $ai_wait_seconds"

  ai_deadline=$((SECONDS + ai_wait_seconds))
  gemini_ready=false
  codex_ready=false

  while true; do
    issue_comments="$(
      gh api "repos/$repo_slug/issues/$pr_number/comments" --paginate \
        --jq '.[] | [.user.login, .created_at] | @tsv' 2>/dev/null || true
    )"
    reviews="$(
      gh api "repos/$repo_slug/pulls/$pr_number/reviews" --paginate \
        --jq '.[] | [.user.login, .state, .submitted_at] | @tsv' 2>/dev/null || true
    )"
    reactions="$(
      gh api "repos/$repo_slug/issues/$pr_number/reactions" --paginate \
        -H "Accept: application/vnd.github+json" \
        --jq '.[] | [.user.login, .content, .created_at] | @tsv' 2>/dev/null || true
    )"

    gemini_ready=false
    codex_ready=false

    # Gemini posts a summary issue comment first, then a review.
    # Require the review event so we do not merge after summary only.
    if table_has_actor "$gemini_bot_login" "$reviews"; then
      gemini_ready=true
    fi

    if table_has_actor "$codex_bot_login" "$issue_comments" \
      || table_has_actor "$codex_bot_login" "$reviews" \
      || table_has_actor_content "$codex_bot_login" "+1" "$reactions"; then
      codex_ready=true
    fi

    if [[ "$gemini_ready" == "true" && "$codex_ready" == "true" ]]; then
      echo "AI review signals received (Gemini + Codex)."
      break
    fi

    if [[ "$ai_wait_seconds" -le 0 || "$SECONDS" -ge "$ai_deadline" ]]; then
      echo "Timed out waiting for AI review signals." >&2
      if [[ "$gemini_ready" != "true" ]]; then
        echo "- Missing Gemini review from: $gemini_bot_login" >&2
      fi
      if [[ "$codex_ready" != "true" ]]; then
        echo "- Missing Codex signal (+1/comment/review) from: $codex_bot_login" >&2
      fi
      echo "Merge aborted. Re-run after AI feedback arrives, or set PR_REQUIRE_AI_REVIEW=false to override." >&2
      exit 1
    fi

    echo "Waiting... Gemini=${gemini_ready} Codex=${codex_ready}"
    sleep "$ai_poll_seconds"
  done
fi

gh pr merge "$pr_number" \
  --repo "$repo_slug" \
  --auto \
  --squash \
  --delete-branch

deadline=$((SECONDS + wait_seconds))
pr_state=""
while true; do
  pr_state="$(gh pr view "$pr_number" --repo "$repo_slug" --json state --jq '.state')"
  if [[ "$pr_state" == "MERGED" ]]; then
    break
  fi

  if [[ "$wait_seconds" -le 0 || "$SECONDS" -ge "$deadline" ]]; then
    echo "PR is not merged yet (state=$pr_state)."
    echo "Local branch cleanup is skipped for now."
    echo "Run this command again later to clean up the local branch."
    exit 0
  fi

  sleep 5
done

if [[ "$start_branch" == "$default_branch" ]]; then
  echo "Already on default branch. Local cleanup is not required."
  exit 0
fi

git switch "$default_branch"
git pull --ff-only

if git branch -d "$start_branch" >/dev/null 2>&1; then
  echo "Deleted local branch: $start_branch"
else
  echo "Local branch is not a direct ancestor after merge (likely squash/rebase)." >&2
  echo "Force deleting local branch: $start_branch" >&2
  git branch -D "$start_branch" >/dev/null
  echo "Deleted local branch (forced): $start_branch"
fi
