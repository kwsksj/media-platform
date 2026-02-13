# Architecture

## Current Layout

```text
media-platform/
├── apps/gallery-web/      # 公開ギャラリーUI
├── apps/admin-web/        # 管理UI
├── apps/worker-api/       # Cloudflare Worker API
├── tools/ingest/          # ingest系エントリ
├── tools/publish/         # publish系エントリ
├── tools/gallery-build/   # gallery build系エントリ
├── src/auto_post/         # CLI本体
├── .github/workflows/     # 定期運用・手動運用
├── docs/                  # 構成/運用ドキュメント
└── Makefile               # 日常運用入口
```

## Responsibility Boundaries

- `apps/gallery-web`
  - 公開ギャラリーUI（`gallery.html`）
- `apps/admin-web`
  - 先生向け管理UI（`admin.html`）
  - 管理画面ロジック（`admin/`, `shared/`）
  - 管理運用スクリプト（`scripts/`）
- `apps/worker-api`
  - Cloudflare Worker API（`worker/src/index.js`）
  - Worker 設定（`wrangler.toml`）
- `tools/*`
  - 運用入口スクリプト。`auto-post` / node スクリプトへの薄いラッパー
- `src/auto_post`
  - SNS投稿・取り込み・gallery export のコア実装
- `.github/workflows`
  - 定期運用（投稿・gallery export）と手動運用（catch-up）

## Operation Rules

- 日常運用の入口は `Makefile` を優先する
- UI 改修は `apps/gallery-web` / `apps/admin-web` に分離して実施する
- API 改修は `apps/worker-api` に集約する
- 投稿・取り込み・gallery build の CLI 導線は `tools/*` で維持する
- 定期実行と Secrets 管理は monorepo root 側で管理する
