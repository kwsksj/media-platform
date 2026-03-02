# AGENTS

## Purpose
This repository manages ingest, publishing, and gallery generation for the media platform.
Use this file as the default execution guide for code changes and validation.
When available, prefer the `media-platform-dev-loop` skill and keep repository scripts as the source of truth.

## Fast Start
```bash
make setup-python-dev
make recommend-checks
make check-required
make check-required-strict
make check-changed-python
make check-fast
make check-monorepo
make check-markdown
make check-branch-protection
make pr-lifecycle PR=<number>
make pr-merge-local PR=<number>
```

Optional:
```bash
make setup-admin-web
make pre-commit-install
make fix-changed-python
make check-markdown
make pr-lifecycle PR=<number>
make pr-merge-local PR=<number>
```

## Preferred Validation Order
1. `make recommend-checks` (path-driven recommendation)
2. `make check-required` (auto-run required subset)
3. `make check-required-strict` (before merge or release)
4. `make check-changed-python` (changed Python files only)
5. `make check-fast` (full ruff + mypy when needed)
6. `make test` (when Python code is changed)
7. `make check-monorepo` (structure guard)
8. `make check-markdown` (Markdown changes only; practical rules)
9. Target-specific dry-run command (`make publish-daily-dry`, `make gallery-build-dry`, `make deploy-worker-dry`, etc.)

## Repo Map
- `src/auto_post`: Python CLI implementation
- `tools/ingest`: ingest entrypoints
- `tools/publish`: publish entrypoints
- `tools/gallery-build`: gallery export/tag scripts
- `apps/admin-web`: admin UI + smoke scripts
- `apps/gallery-web`: public gallery static assets
- `apps/worker-api`: Cloudflare Worker

## Safety Rules
- Prefer dry-run targets before operations that can post/upload.
- Never commit secrets (`.env`, tokens, keys).
- Keep changes scoped to the target responsibility area.

## PR Flow
- Prefer `--auto --squash --delete-branch` merge style for this repository.
- Use repository automation in `.github/workflows/pr-lifecycle.yml` for approval-to-merge and post-merge hooks.
- Prefer `make pr-lifecycle PR=<number>` for end-to-end operations:
  - local checks
  - AI review wait
  - auto merge
  - post-merge deploy wait
  - local branch cleanup
- For local cleanup, prefer `make pr-merge-local PR=<number>` to merge and delete the local branch after merge.
- Before merge, wait for AI review signals from Gemini, Codex, and Claude:
  - Gemini: review from `gemini-code-assist[bot]` を優先。概要コメントのみの場合は猶予時間経過後に通過
  - Codex: comment/review or `+1` reaction from `chatgpt-codex-connector[bot]`
  - Claude: `claude[bot]` の review/review-comment、または `claude-review` check 成功
- Emergency override:
  - Add PR label `override-ai-gate` only when bot checks are unavailable and human reviewers explicitly approve bypass.
  - Remove the label after use to restore normal gate behavior.
- Per-AI optional gate controls:
  - PR labels (per PR): `skip-gemini-gate`, `skip-codex-gate`, `skip-claude-gate`
  - Repository variables (default behavior):
    - `AI_GATE_REQUIRE_GEMINI` (`true`/`false`)
    - `AI_GATE_REQUIRE_CODEX` (`true`/`false`)
    - `AI_GATE_REQUIRE_CLAUDE` (`true`/`false`)
    - `AI_GATE_AUTO_SKIP_CODEX_LIMIT` (`true`/`false`)
    - `AI_GATE_AUTO_SKIP_GEMINI_UNAVAILABLE` (`true`/`false`)
    - `AI_GATE_AUTO_SKIP_CLAUDE_CHECK_FAILURE` (`true`/`false`)
  - If an AI is unavailable in your plan/time window, set that AI to optional (label or variable) and continue.
- Branch protection recommendation:
  - Configure `main` branch protection to require status checks:
    - AI review gate job context (`ai-review-gate`)
    - CI checks used by this repository (as applicable)
