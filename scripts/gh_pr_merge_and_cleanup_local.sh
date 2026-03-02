#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Merge a PR with GitHub CLI, verify post-merge deploy workflows, and clean up the local branch.

Usage:
  scripts/gh_pr_merge_and_cleanup_local.sh [PR_NUMBER]

Behavior:
  1) Wait for AI review signals (enabled by default)
     - Gemini: review from gemini-code-assist[bot]
     - Codex: comment/review/review-comment OR +1 reaction from chatgpt-codex-connector[bot]
     - Claude: review/review-comment from claude[bot]
       or successful check run named "claude-review"
     - Block merge while required AI review threads remain unresolved
  2) gh pr merge --auto --squash --delete-branch
  3) Wait for merge completion (default: 600s, configurable by PR_MERGE_WAIT_SECONDS)
  4) Optionally wait for post-merge automation/deploy workflows:
     - PR Lifecycle Automation (pull_request closed event)
     - Worker Deploy / Daily Gallery Export / Admin Web Deploy (when dispatched)
  5) If PR state is MERGED:
     - switch to default branch
     - fast-forward pull
     - delete the original local branch (force-delete fallback for squash/rebase merge)

Environment variables:
  PR_REQUIRE_AI_REVIEW=true|false     (default: true)
  PR_AI_OVERRIDE_LABEL=...            (default: override-ai-gate)
  PR_REQUIRE_GEMINI_REVIEW=true|false (default: true)
  PR_REQUIRE_CODEX_REVIEW=true|false  (default: true)
  PR_REQUIRE_CLAUDE_REVIEW=true|false (default: true)
  PR_AUTO_SKIP_CODEX_LIMIT=true|false (default: true)
  PR_AUTO_SKIP_GEMINI_UNAVAILABLE=true|false (default: false)
  PR_AUTO_SKIP_CLAUDE_CHECK_FAILURE=true|false (default: true)
  PR_REQUIRE_AI_REVIEW_RESOLUTION=true|false (default: true)
  PR_REVIEW_RESOLUTION_OVERRIDE_LABEL=... (default: override-ai-review-resolution)
  PR_SKIP_GEMINI_LABEL=...            (default: skip-gemini-gate)
  PR_SKIP_CODEX_LABEL=...             (default: skip-codex-gate)
  PR_SKIP_CLAUDE_LABEL=...            (default: skip-claude-gate)
  PR_AI_REVIEW_WAIT_SECONDS=900       (default timeout)
  PR_AI_REVIEW_POLL_SECONDS=10        (default poll interval)
  PR_GEMINI_BOT_LOGIN=...             (default: gemini-code-assist[bot])
  PR_CODEX_BOT_LOGIN=...              (default: chatgpt-codex-connector[bot])
  PR_CLAUDE_BOT_LOGIN=...             (default: claude[bot])
  PR_CLAUDE_CHECK_NAME=...            (default: claude-review)
  PR_WAIT_POST_MERGE_DEPLOYS=true|false (default: true)
  PR_DEPLOY_WAIT_SECONDS=1800         (default timeout)
  PR_DEPLOY_POLL_SECONDS=15           (default poll interval)
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

if ! command -v jq >/dev/null 2>&1; then
  echo "jq command is required." >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree is not clean. Commit or stash changes first." >&2
  exit 1
fi

normalize_bool() {
  if [[ "$(echo "${1:-false}" | tr '[:upper:]' '[:lower:]' | xargs)" == "true" ]]; then
    printf "true"
  else
    printf "false"
  fi
}

start_branch="$(git rev-parse --abbrev-ref HEAD)"
repo_slug="$(gh repo view --json nameWithOwner --jq '.nameWithOwner')"
repo_owner="${repo_slug%/*}"
repo_name="${repo_slug#*/}"
default_branch="$(gh repo view --json defaultBranchRef --jq '.defaultBranchRef.name')"
require_ai_review="$(normalize_bool "${PR_REQUIRE_AI_REVIEW:-true}")"
ai_override_label="${PR_AI_OVERRIDE_LABEL:-override-ai-gate}"
ai_review_resolution_override_label="${PR_REVIEW_RESOLUTION_OVERRIDE_LABEL:-override-ai-review-resolution}"
require_gemini_review="$(normalize_bool "${PR_REQUIRE_GEMINI_REVIEW:-true}")"
require_codex_review="$(normalize_bool "${PR_REQUIRE_CODEX_REVIEW:-true}")"
require_claude_review="$(normalize_bool "${PR_REQUIRE_CLAUDE_REVIEW:-true}")"
auto_skip_codex_limit="$(normalize_bool "${PR_AUTO_SKIP_CODEX_LIMIT:-true}")"
auto_skip_gemini_unavailable="$(normalize_bool "${PR_AUTO_SKIP_GEMINI_UNAVAILABLE:-false}")"
auto_skip_claude_check_failure="$(normalize_bool "${PR_AUTO_SKIP_CLAUDE_CHECK_FAILURE:-true}")"
require_ai_review_resolution="$(normalize_bool "${PR_REQUIRE_AI_REVIEW_RESOLUTION:-true}")"
skip_gemini_label="${PR_SKIP_GEMINI_LABEL:-skip-gemini-gate}"
skip_codex_label="${PR_SKIP_CODEX_LABEL:-skip-codex-gate}"
skip_claude_label="${PR_SKIP_CLAUDE_LABEL:-skip-claude-gate}"
gemini_bot_login="${PR_GEMINI_BOT_LOGIN:-gemini-code-assist[bot]}"
codex_bot_login="${PR_CODEX_BOT_LOGIN:-chatgpt-codex-connector[bot]}"
claude_bot_login="${PR_CLAUDE_BOT_LOGIN:-claude[bot]}"
claude_check_name="${PR_CLAUDE_CHECK_NAME:-claude-review}"
codex_unavailable_pattern="${PR_CODEX_UNAVAILABLE_PATTERN:-reached your codex usage limits|usage limits for code reviews|add credits|upgrade your account|上限}"
gemini_unavailable_pattern="${PR_GEMINI_UNAVAILABLE_PATTERN:-i'm unable to|i am unable to|i can't|i cannot|temporarily unavailable|limit reached|上限に達}"
wait_post_merge_deploys="$(normalize_bool "${PR_WAIT_POST_MERGE_DEPLOYS:-true}")"

sanitize_non_negative_int() {
  local value="$1"
  local fallback="$2"
  if [[ "$value" =~ ^[0-9]+$ ]]; then
    printf "%s" "$value"
  else
    printf "%s" "$fallback"
  fi
}

validate_pr_number() {
  local value="$1"
  if [[ "$value" =~ ^[0-9]+$ ]]; then
    return 0
  fi
  echo "Invalid PR number: '$value' (must be numeric)." >&2
  exit 1
}

wait_seconds="$(sanitize_non_negative_int "${PR_MERGE_WAIT_SECONDS:-600}" "600")"
ai_wait_seconds="$(sanitize_non_negative_int "${PR_AI_REVIEW_WAIT_SECONDS:-900}" "900")"
ai_poll_seconds="$(sanitize_non_negative_int "${PR_AI_REVIEW_POLL_SECONDS:-10}" "10")"
deploy_wait_seconds="$(sanitize_non_negative_int "${PR_DEPLOY_WAIT_SECONDS:-1800}" "1800")"
deploy_poll_seconds="$(sanitize_non_negative_int "${PR_DEPLOY_POLL_SECONDS:-15}" "15")"

pr_number="${1:-${PR:-}}"
if [[ -n "$pr_number" ]]; then
  validate_pr_number "$pr_number"
fi
if [[ -z "$pr_number" ]]; then
  pr_number="$(gh pr view --repo "$repo_slug" --json number --jq '.number')"
  validate_pr_number "$pr_number"
fi

echo "Repository: $repo_slug"
echo "PR: #$pr_number"
echo "Current branch: $start_branch"
echo "Default branch: $default_branch"
echo "Wait timeout (seconds): $wait_seconds"
echo "Require AI review signals: $require_ai_review"
echo "AI override label: $ai_override_label"
echo "Require Gemini signal: $require_gemini_review"
echo "Require Codex signal: $require_codex_review"
echo "Require Claude signal: $require_claude_review"
echo "Auto skip Codex limit: $auto_skip_codex_limit"
echo "Auto skip Gemini unavailable: $auto_skip_gemini_unavailable"
echo "Auto skip Claude check failure: $auto_skip_claude_check_failure"
echo "Require AI review thread resolution: $require_ai_review_resolution"
echo "AI review resolution override label: $ai_review_resolution_override_label"
echo "Wait post-merge deploy workflows: $wait_post_merge_deploys"

table_has_actor() {
  local actor="$1"
  local table="$2"
  awk -F'\t' -v actor="$actor" '$1 == actor {found=1; exit} END {exit found ? 0 : 1}' <<<"$table"
}

table_has_actor_content() {
  local actor="$1"
  local content="$2"
  local table="$3"
  awk -F'\t' -v actor="$actor" -v content="$content" '$1 == actor && $2 == content {found=1; exit} END {exit found ? 0 : 1}' <<<"$table"
}

table_has_successful_check() {
  local check_name="$1"
  local table="$2"
  awk -F'\t' -v check_name="$check_name" '$1 == check_name && $2 == "COMPLETED" && $3 == "SUCCESS" {found=1; exit} END {exit found ? 0 : 1}' <<<"$table"
}

table_has_failed_check() {
  local check_name="$1"
  local table="$2"
  awk -F'\t' -v check_name="$check_name" '
    $1 == check_name && $2 == "COMPLETED" && ($3 == "FAILURE" || $3 == "TIMED_OUT" || $3 == "CANCELLED" || $3 == "ACTION_REQUIRED") {found=1; exit}
    END {exit found ? 0 : 1}
  ' <<<"$table"
}

table_actor_body_matches() {
  local actor="$1"
  local pattern="$2"
  local table="$3"
  awk -F'\t' -v actor="$actor" -v pattern="$pattern" '
    tolower($1) == tolower(actor) && tolower($2) ~ pattern {found=1; exit}
    END {exit found ? 0 : 1}
  ' <<<"$table"
}

get_repo_var() {
  local var_name="$1"
  gh variable get "$var_name" --repo "$repo_slug" --json value --jq '.value' 2>/dev/null || true
}

wait_for_workflow_run() {
  local workflow_name="$1"
  local expected_event="$2"
  local earliest_created_at="$3"
  local expected_head_sha="$4"
  local display_name="$5"

  local deadline=$((SECONDS + deploy_wait_seconds))
  local run_json=""
  local run_id=""
  local run_status=""
  local run_conclusion=""
  local run_url=""

  while true; do
    local runs_json
    runs_json="$(
      gh run list \
        --repo "$repo_slug" \
        --workflow "$workflow_name" \
        --limit 50 \
        --json databaseId,event,status,conclusion,createdAt,headSha,url 2>/dev/null || echo '[]'
    )"

    run_json="$(
      jq -c \
        --arg expected_event "$expected_event" \
        --arg earliest_created_at "$earliest_created_at" \
        --arg expected_head_sha "$expected_head_sha" \
        '
          [
            .[]
            | select(.event == $expected_event)
            | select(.createdAt >= $earliest_created_at)
            | if ($expected_head_sha | length) > 0
              then select(.headSha == $expected_head_sha)
              else .
              end
          ]
          | sort_by(.createdAt)
          | last // empty
        ' <<<"$runs_json"
    )"

    if [[ -n "$run_json" ]]; then
      run_id="$(jq -r '.databaseId' <<<"$run_json")"
      run_status="$(jq -r '.status' <<<"$run_json")"
      run_conclusion="$(jq -r '.conclusion // ""' <<<"$run_json")"
      run_url="$(jq -r '.url // ""' <<<"$run_json")"

      if [[ "$run_status" == "completed" ]]; then
        if [[ "$run_conclusion" == "success" ]]; then
          echo "[OK] $display_name completed successfully: $run_url"
          return 0
        fi

        echo "[FAIL] $display_name concluded with '$run_conclusion': $run_url" >&2
        echo "==> Failed job logs for $display_name (run $run_id)" >&2
        gh run view "$run_id" --repo "$repo_slug" --log-failed || true
        return 1
      fi

      echo "Waiting for $display_name to complete (status=$run_status): $run_url"
    else
      echo "Waiting for $display_name to start..."
    fi

    if [[ "$deploy_wait_seconds" -le 0 || "$SECONDS" -ge "$deadline" ]]; then
      echo "Timed out waiting for $display_name completion." >&2
      if [[ -n "$run_url" ]]; then
        echo "Last observed run: $run_url" >&2
      fi
      return 1
    fi

    sleep "$deploy_poll_seconds"
  done
}

wait_for_deploy_if_needed() {
  local changed="$1"
  local auto="$2"
  local workflow_name="$3"
  local display_name="$4"
  local merged_at="$5"
  local merge_commit_sha="$6"

  if [[ "$changed" == "true" && "$auto" == "true" ]]; then
    wait_for_workflow_run \
      "$workflow_name" \
      "workflow_dispatch" \
      "$merged_at" \
      "$merge_commit_sha" \
      "$display_name"
  else
    echo "Skip $display_name wait: gate not satisfied."
  fi
}

wait_for_post_merge_deploys_fn() {
  local pr_meta_json
  pr_meta_json="$(
    gh pr view "$pr_number" --repo "$repo_slug" \
      --json mergedAt,title,headRefOid,mergeCommit
  )"

  local merged_at
  local pr_title
  local pr_head_sha
  local merge_commit_sha
  merged_at="$(jq -r '.mergedAt // ""' <<<"$pr_meta_json")"
  pr_title="$(jq -r '.title // ""' <<<"$pr_meta_json")"
  pr_head_sha="$(jq -r '.headRefOid // ""' <<<"$pr_meta_json")"
  merge_commit_sha="$(jq -r '.mergeCommit.oid // ""' <<<"$pr_meta_json")"

  if [[ -z "$merged_at" ]]; then
    echo "Skip post-merge deploy wait: PR is not merged yet."
    return 0
  fi

  if [[ "$deploy_poll_seconds" -lt 1 ]]; then
    deploy_poll_seconds=1
  fi

  echo "Waiting for post-merge workflows for PR #$pr_number..."
  echo "- Title: $pr_title"
  echo "- mergedAt: $merged_at"
  echo "- PR head SHA: $pr_head_sha"
  echo "- merge commit SHA: $merge_commit_sha"
  echo "- Timeout (seconds): $deploy_wait_seconds"

  wait_for_workflow_run \
    "PR Lifecycle Automation" \
    "pull_request" \
    "$merged_at" \
    "$pr_head_sha" \
    "PR Lifecycle Automation"

  local changed_files
  changed_files="$(
    gh api "repos/$repo_slug/pulls/$pr_number/files" --paginate \
      --jq '.[].filename' 2>/dev/null || true
  )"

  local worker_changed=false
  local gallery_changed=false
  local admin_changed=false

  if grep -Eq '^apps/worker-api/|^\.github/workflows/worker-deploy\.yml$|^\.github/workflows/pr-lifecycle\.yml$' <<<"$changed_files"; then
    worker_changed=true
  fi
  if grep -Eq '^apps/gallery-web/|^tools/gallery-build/|^\.github/workflows/gallery-export\.yml$|^\.github/workflows/pr-lifecycle\.yml$' <<<"$changed_files"; then
    gallery_changed=true
  fi
  if grep -Eq '^apps/admin-web/|^apps/worker-api/wrangler\.toml$|^\.github/workflows/admin-web-deploy\.yml$|^\.github/workflows/pr-lifecycle\.yml$' <<<"$changed_files"; then
    admin_changed=true
  fi

  local worker_auto
  local gallery_auto
  local admin_auto
  worker_auto="$(normalize_bool "$(get_repo_var AUTO_WORKER_DEPLOY_ON_MERGE)")"
  gallery_auto="$(normalize_bool "$(get_repo_var AUTO_GALLERY_EXPORT_ON_MERGE)")"
  admin_auto="$(normalize_bool "$(get_repo_var AUTO_ADMIN_WEB_DEPLOY_ON_MERGE)")"

  echo "Post-merge deploy gates:"
  echo "- Worker: changed=$worker_changed auto=$worker_auto"
  echo "- Gallery: changed=$gallery_changed auto=$gallery_auto"
  echo "- Admin: changed=$admin_changed auto=$admin_auto"

  wait_for_deploy_if_needed \
    "$worker_changed" \
    "$worker_auto" \
    "Worker Deploy" \
    "Worker Deploy" \
    "$merged_at" \
    "$merge_commit_sha"

  wait_for_deploy_if_needed \
    "$gallery_changed" \
    "$gallery_auto" \
    "Daily Gallery Export" \
    "Daily Gallery Export" \
    "$merged_at" \
    "$merge_commit_sha"

  wait_for_deploy_if_needed \
    "$admin_changed" \
    "$admin_auto" \
    "Admin Web Deploy" \
    "Admin Web Deploy" \
    "$merged_at" \
    "$merge_commit_sha"
}

ensure_ai_review_feedback_resolved() {
  if [[ "$require_ai_review_resolution" != "true" ]]; then
    return
  fi

  if [[ "$require_gemini_review" != "true" \
    && "$require_codex_review" != "true" \
    && "$require_claude_review" != "true" ]]; then
    echo "Skip AI review resolution gate: no AI review gates are required."
    return
  fi

  local current_labels
  current_labels="$(gh pr view "$pr_number" --repo "$repo_slug" --json labels --jq '.labels[].name' 2>/dev/null || true)"
  if grep -Fxq "$ai_override_label" <<<"$current_labels"; then
    echo "AI review resolution gate is bypassed because label '$ai_override_label' is present."
    return
  fi
  if grep -Fxq "$ai_review_resolution_override_label" <<<"$current_labels"; then
    echo "AI review resolution gate is bypassed because label '$ai_review_resolution_override_label' is present."
    return
  fi

  local changes_requested_awk
  changes_requested_awk="$(cat <<'AWK'
$2 == "CHANGES_REQUESTED" && (
  (rg == "true" && $1 == g) ||
  (rc == "true" && $1 == c) ||
  (ra == "true" && $1 == a)
) {print $0}
AWK
)"

  local changes_requested
  changes_requested="$(
    gh api "repos/$repo_slug/pulls/$pr_number/reviews" --paginate \
      --jq '.[] | [.user.login, .state, .submitted_at] | @tsv' 2>/dev/null \
      | awk -F'\t' -v g="$gemini_bot_login" -v c="$codex_bot_login" -v a="$claude_bot_login" \
          -v rg="$require_gemini_review" -v rc="$require_codex_review" -v ra="$require_claude_review" \
          "$changes_requested_awk" || true
  )"
  if [[ -n "$changes_requested" ]]; then
    echo "Merge blocked: required AI reviewers have CHANGES_REQUESTED reviews." >&2
    echo "$changes_requested" >&2
    echo "Address the feedback and push updates, then re-run merge." >&2
    exit 1
  fi

  local review_threads_query
  review_threads_query="$(cat <<'GRAPHQL'
query($owner:String!, $repo:String!, $number:Int!, $endCursor:String){
  repository(owner:$owner,name:$repo){
    pullRequest(number:$number){
      reviewThreads(first:100, after:$endCursor){
        nodes {
          isResolved
          isOutdated
          path
          line
          startLine
          originalLine
          comments(first:100){
            totalCount
            nodes{author{login}}
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
GRAPHQL
)"

  local review_threads
  review_threads="$(
    gh api graphql --paginate \
      -F owner="$repo_owner" \
      -F repo="$repo_name" \
      -F number="$pr_number" \
      -f query="$review_threads_query" \
      --jq '.data.repository.pullRequest.reviewThreads.nodes[]' 2>/dev/null \
      | jq -s '.' || echo '[]'
  )"

  local unresolved_ai_filter
  unresolved_ai_filter="$(cat <<'JQ'
.[]
| select((.isResolved | not) and ((.isOutdated // false) | not))
| .authors = ([.comments.nodes[]?.author.login] | unique)
| select(
    (($rg == "true") and (.authors | index($g) != null))
    or (($rc == "true") and (.authors | index($c) != null))
    or (($ra == "true") and (.authors | index($a) != null))
  )
| [(.path // "(unknown path)"), ((.line // .startLine // .originalLine // 0) | tostring), (.authors | join(","))]
| @tsv
JQ
)"

  local unresolved_ai_threads
  unresolved_ai_threads="$(
    jq -r \
      --arg g "$gemini_bot_login" \
      --arg c "$codex_bot_login" \
      --arg a "$claude_bot_login" \
      --arg rg "$require_gemini_review" \
      --arg rc "$require_codex_review" \
      --arg ra "$require_claude_review" \
      "$unresolved_ai_filter" <<<"$review_threads"
  )"

  local truncated_unresolved_threads
  truncated_unresolved_threads="$(
    jq -r '
      .[]
      | select((.isResolved | not) and ((.isOutdated // false) | not))
      | select((.comments.totalCount // 0) > ((.comments.nodes // []) | length))
      | [(.path // "(unknown path)"), ((.line // .startLine // .originalLine // 0) | tostring), ((.comments.totalCount // 0) | tostring)]
      | @tsv
    ' <<<"$review_threads"
  )"
  if [[ -n "$truncated_unresolved_threads" ]]; then
    echo "Merge blocked: unresolved review threads have more than 100 comments, and author coverage is incomplete." >&2
    echo "$truncated_unresolved_threads" | head -n 10 >&2
    echo "Resolve those threads manually (or use '$ai_review_resolution_override_label' only for emergency bypass), then re-run merge." >&2
    exit 1
  fi

  if [[ -n "$unresolved_ai_threads" ]]; then
    echo "Merge blocked: unresolved AI review threads remain." >&2
    echo "$unresolved_ai_threads" | head -n 10 >&2
    echo "Resolve the review threads (or add '$ai_review_resolution_override_label' only for emergency bypass), then re-run merge." >&2
    exit 1
  fi
}

if [[ "$require_ai_review" == "true" ]]; then
  codex_unavailable_pattern="$(echo "$codex_unavailable_pattern" | tr '[:upper:]' '[:lower:]')"
  gemini_unavailable_pattern="$(echo "$gemini_unavailable_pattern" | tr '[:upper:]' '[:lower:]')"

  pr_labels="$(gh pr view "$pr_number" --repo "$repo_slug" --json labels --jq '.labels[].name' 2>/dev/null || true)"
  if grep -Fxq "$ai_override_label" <<<"$pr_labels"; then
    echo "AI review wait is bypassed because label '$ai_override_label' is present."
    require_ai_review="false"
  fi

  if [[ "$require_ai_review" == "true" ]]; then
    if grep -Fxq "$skip_gemini_label" <<<"$pr_labels"; then
      echo "Gemini gate is bypassed because label '$skip_gemini_label' is present."
      require_gemini_review="false"
    fi
    if grep -Fxq "$skip_codex_label" <<<"$pr_labels"; then
      echo "Codex gate is bypassed because label '$skip_codex_label' is present."
      require_codex_review="false"
    fi
    if grep -Fxq "$skip_claude_label" <<<"$pr_labels"; then
      echo "Claude gate is bypassed because label '$skip_claude_label' is present."
      require_claude_review="false"
    fi
  fi

  if [[ "$require_ai_review" == "true" \
    && "$require_gemini_review" != "true" \
    && "$require_codex_review" != "true" \
    && "$require_claude_review" != "true" ]]; then
    echo "All AI gates are optional for this PR. Skipping AI wait."
    require_ai_review="false"
  fi
fi

if [[ "$require_ai_review" == "true" ]]; then
  if [[ "$ai_poll_seconds" -lt 1 ]]; then
    ai_poll_seconds=1
  fi

  echo "Waiting for AI review signals before merge..."
  echo "- Gemini actor: $gemini_bot_login"
  echo "- Codex actor:  $codex_bot_login"
  echo "- Claude actor: $claude_bot_login"
  echo "- Claude check: $claude_check_name"
  echo "- Gemini required: $require_gemini_review"
  echo "- Codex required:  $require_codex_review"
  echo "- Claude required: $require_claude_review"
  echo "- Timeout (seconds): $ai_wait_seconds"

  ai_deadline=$((SECONDS + ai_wait_seconds))
  gemini_ready=false
  codex_ready=false
  claude_ready=false

  while true; do
    issue_data="$(
      gh api "repos/$repo_slug/issues/$pr_number/comments" --paginate \
        --jq '.[] | [.user.login, .created_at, (.body // "" | gsub("[\\r\\n\\t]"; " "))] | @tsv' || true
    )"
    issue_comments="$(cut -f1,2 <<<"$issue_data")"
    issue_comment_bodies="$(cut -f1,3 <<<"$issue_data")"

    review_comment_data="$(
      gh api "repos/$repo_slug/pulls/$pr_number/comments" --paginate \
        --jq '.[] | [.user.login, .created_at, (.body // "" | gsub("[\\r\\n\\t]"; " "))] | @tsv' || true
    )"
    review_comments="$(cut -f1,2 <<<"$review_comment_data")"
    review_comment_bodies="$(cut -f1,3 <<<"$review_comment_data")"

    review_data="$(
      gh api "repos/$repo_slug/pulls/$pr_number/reviews" --paginate \
        --jq '.[] | [.user.login, .state, .submitted_at, (.body // "" | gsub("[\\r\\n\\t]"; " "))] | @tsv' || true
    )"
    reviews="$(cut -f1,2,3 <<<"$review_data")"
    review_bodies="$(cut -f1,4 <<<"$review_data")"
    reactions="$(
      gh api "repos/$repo_slug/issues/$pr_number/reactions" --paginate \
        -H "Accept: application/vnd.github+json" \
        --jq '.[] | [.user.login, .content, .created_at] | @tsv' || true
    )"
    checks="$(
      gh pr view "$pr_number" --repo "$repo_slug" --json statusCheckRollup \
        --jq '.statusCheckRollup[]? | [.name, .status, .conclusion] | @tsv' || true
    )"

    if [[ "$require_codex_review" == "true" && "$auto_skip_codex_limit" == "true" ]] && {
      table_actor_body_matches "$codex_bot_login" "$codex_unavailable_pattern" "$issue_comment_bodies" \
      || table_actor_body_matches "$codex_bot_login" "$codex_unavailable_pattern" "$review_comment_bodies" \
      || table_actor_body_matches "$codex_bot_login" "$codex_unavailable_pattern" "$review_bodies";
    }; then
      echo "Codex appears unavailable (limit/unavailable message detected). Skipping Codex gate."
      require_codex_review="false"
    fi

    if [[ "$require_gemini_review" == "true" && "$auto_skip_gemini_unavailable" == "true" ]] && {
      table_actor_body_matches "$gemini_bot_login" "$gemini_unavailable_pattern" "$issue_comment_bodies" \
      || table_actor_body_matches "$gemini_bot_login" "$gemini_unavailable_pattern" "$review_comment_bodies" \
      || table_actor_body_matches "$gemini_bot_login" "$gemini_unavailable_pattern" "$review_bodies";
    }; then
      echo "Gemini appears unavailable (unavailable/limit message detected). Skipping Gemini gate."
      require_gemini_review="false"
    fi

    if [[ "$require_claude_review" == "true" && "$auto_skip_claude_check_failure" == "true" ]] \
      && table_has_failed_check "$claude_check_name" "$checks"; then
      echo "Claude review check is failing. Skipping Claude gate."
      require_claude_review="false"
    fi

    gemini_ready=false
    codex_ready=false
    claude_ready=false
    if [[ "$require_gemini_review" != "true" ]]; then
      gemini_ready=true
    fi
    if [[ "$require_codex_review" != "true" ]]; then
      codex_ready=true
    fi
    if [[ "$require_claude_review" != "true" ]]; then
      claude_ready=true
    fi

    if [[ "$require_gemini_review" != "true" \
      && "$require_codex_review" != "true" \
      && "$require_claude_review" != "true" ]]; then
      echo "All AI gates are optional or unavailable for this PR. Skipping remaining AI wait."
      break
    fi

    if [[ "$require_gemini_review" == "true" ]] && { table_has_actor "$gemini_bot_login" "$reviews" \
      || table_has_actor "$gemini_bot_login" "$review_comments"; }; then
      gemini_ready=true
    fi

    if [[ "$require_codex_review" == "true" ]] && { table_has_actor "$codex_bot_login" "$issue_comments" \
      || table_has_actor "$codex_bot_login" "$review_comments" \
      || table_has_actor "$codex_bot_login" "$reviews" \
      || table_has_actor_content "$codex_bot_login" "+1" "$reactions"; }; then
      codex_ready=true
    fi

    # Claude: review, review-comment, or successful Claude check run.
    if [[ "$require_claude_review" == "true" ]] && { table_has_actor "$claude_bot_login" "$reviews" \
      || table_has_actor "$claude_bot_login" "$review_comments" \
      || table_has_successful_check "$claude_check_name" "$checks"; }; then
      claude_ready=true
    fi

    if [[ "$gemini_ready" == "true" && "$codex_ready" == "true" && "$claude_ready" == "true" ]]; then
      echo "AI review signals received (Gemini + Codex + Claude)."
      break
    fi

    if [[ "$ai_wait_seconds" -le 0 || "$SECONDS" -ge "$ai_deadline" ]]; then
      echo "Timed out waiting for AI review signals." >&2
      if [[ "$require_gemini_review" == "true" && "$gemini_ready" != "true" ]]; then
        echo "- Missing Gemini signal (review/review-comment) from: $gemini_bot_login" >&2
      fi
      if [[ "$require_codex_review" == "true" && "$codex_ready" != "true" ]]; then
        echo "- Missing Codex signal (+1/comment/review/review-comment) from: $codex_bot_login" >&2
      fi
      if [[ "$require_claude_review" == "true" && "$claude_ready" != "true" ]]; then
        echo "- Missing Claude signal (review/review-comment from $claude_bot_login or successful check: $claude_check_name)" >&2
      fi
      echo "Merge aborted. Re-run after AI feedback arrives, set PR_REQUIRE_AI_REVIEW=false, add '$ai_override_label', or add one of: '$skip_gemini_label' '$skip_codex_label' '$skip_claude_label'." >&2
      exit 1
    fi

    echo "Waiting... Gemini=${gemini_ready} Codex=${codex_ready} Claude=${claude_ready}"
    sleep "$ai_poll_seconds"
  done
fi

ensure_ai_review_feedback_resolved

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

if [[ "$wait_post_merge_deploys" == "true" ]]; then
  wait_for_post_merge_deploys_fn
fi

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
