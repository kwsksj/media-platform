# AGENTS

## Purpose
This repository manages ingest, publishing, and gallery generation for the media platform.
Use this file as the default execution guide for code changes and validation.

## Fast Start
```bash
make setup-python-dev
make check-fast
make check-monorepo
```

Optional:
```bash
make setup-admin-web
make pre-commit-install
```

## Preferred Validation Order
1. `make check-fast` (ruff + mypy)
2. `make test` (when Python code is changed)
3. `make check-monorepo` (structure guard)
4. Target-specific dry-run command (`make publish-dry`, `make gallery-export`, etc.)

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
