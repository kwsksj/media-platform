# Architecture Overview

## Current Architecture (as of 2026-02-13)

`auto-post` が canonical repository であり、gallery 関連は `apps/gallery` に集約されています。

```text
auto-post/
  apps/gallery/
  shared/
  docs/
```

## Responsibility Boundaries

- `apps/gallery`
  - public gallery UI (`gallery.html`)
  - admin upload/curation UI (`admin.html`, `admin/`)
  - worker API for admin + stars (`worker/`, `wrangler.toml`)
- monorepo root (`auto-post`)
  - batch/automation tooling: ingest, publish, export
  - scheduled workflows and repository secrets

## Operation Rule

- gallery 機能の改修はこの `apps/gallery` 配下で行う
- スケジュール運用・Secrets 管理は monorepo root 側で管理する
