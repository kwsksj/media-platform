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
make pr-merge-local PR=<number>
```

Optional:
```bash
make setup-admin-web
make pre-commit-install
make fix-changed-python
make check-markdown
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
- For local cleanup, prefer `make pr-merge-local PR=<number>` to merge and delete the local branch after merge.
- Before merge, wait for AI review signals from both Gemini and Codex:
  - Gemini: review from `gemini-code-assist[bot]` を優先。概要コメントのみの場合は猶予時間経過後に通過
  - Codex: comment/review or `+1` reaction from `chatgpt-codex-connector[bot]`
