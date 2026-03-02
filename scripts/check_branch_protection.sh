#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Check main branch protection status and required checks.

Usage:
  scripts/check_branch_protection.sh
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

if ! command -v jq >/dev/null 2>&1; then
  echo "jq command is required." >&2
  exit 1
fi

repo_slug="$(gh repo view --json nameWithOwner --jq '.nameWithOwner')"
required_gate_key="ai-review-gate"

echo "Repository: $repo_slug"
echo "Branch: main"

protection_json="$(gh api "repos/$repo_slug/branches/main/protection" 2>/dev/null || true)"
if [[ -z "$protection_json" ]]; then
  echo "Could not read branch protection settings."
  echo "Ensure your token/account has admin rights for this repository."
  exit 0
fi

required_status_checks="$(jq -r '.required_status_checks.checks[]?.context // empty' <<<"$protection_json")"
if [[ -z "$required_status_checks" ]]; then
  echo "No required status checks configured."
else
  echo "Required status checks:"
  echo "$required_status_checks" | sed 's/^/- /'
fi

if grep -Fiq "$required_gate_key" <<<"$required_status_checks"; then
  echo "[OK] Required check includes '$required_gate_key'."
else
  echo "[WARN] Required checks do not include '$required_gate_key'."
  echo "Recommendation: add the AI review gate job context (contains '$required_gate_key') to required checks."
fi
