# AGENTS

## Purpose
This repository manages ingest, publishing, and gallery generation for the media platform.
Use this file as the default execution guide for code changes and validation.

## Fast Start
```bash
make setup-python-dev
make check-changed-python
make check-fast
make check-monorepo
```

Optional:
```bash
make setup-admin-web
make pre-commit-install
make fix-changed-python
```

## Preferred Validation Order
1. `make check-changed-python` (changed Python files only)
2. `make check-fast` (full ruff + mypy when needed)
3. `make test` (when Python code is changed)
4. `make check-monorepo` (structure guard)
5. Target-specific dry-run command (`make publish-dry`, `make gallery-export`, etc.)

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
