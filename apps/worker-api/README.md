# worker-api

Cloudflare Worker API（★機能 + 管理API）です。

## Main Files

- `worker/src/index.js`: Worker 実装
- `wrangler.toml`: Worker 設定

## Deploy

```bash
npx wrangler deploy
npx wrangler deploy --dry-run
```

## Required Bindings / Vars

- `STAR_KV`
- `GALLERY_R2`
- `R2_PUBLIC_BASE_URL`
- `NOTION_WORKS_DB_ID`
- `NOTION_TAGS_DB_ID`
- `NOTION_STUDENTS_DB_ID`（任意）

## Required Secrets

- `NOTION_TOKEN`
- `GITHUB_TOKEN`
- `ADMIN_API_TOKEN`（管理API保護用、任意だが推奨）

## Optional: Upload Notification Mail

`POST /admin/notion/work` では通知対象をキューへ積み、`gallery.json` 更新完了後に
`POST /admin/notify/students-after-gallery-update` で同一生徒を1通に集約して通知できます。

- Vars
  - `UPLOAD_NOTIFY_ENABLED`（`false` のとき通知無効）
  - `UPLOAD_NOTIFY_FROM_EMAIL`
  - `UPLOAD_NOTIFY_FROM_NAME`（任意）
  - `UPLOAD_NOTIFY_REPLY_TO`（任意）
  - `UPLOAD_NOTIFY_BCC`（任意・カンマ区切り）
  - `UPLOAD_NOTIFY_SUBJECT`（任意）
  - `UPLOAD_NOTIFY_RESERVATION_APP_URL`（任意。設定時はメール本文の導線URLとして最優先）
  - `UPLOAD_NOTIFY_GALLERY_URL`（任意）
  - `NOTION_STUDENTS_EMAIL_PROP`（任意。既定はメール系プロパティを自動探索）
  - `NOTION_STUDENTS_NOTIFY_OPT_IN_PROP`（任意。指定した場合のみ false 相当を通知除外に利用。未指定時は全員通知）
- Secret
  - `UPLOAD_NOTIFY_RESEND_API_KEY`（Resend API key）

GitHub Actions から自動送信する場合は、リポジトリ Secrets に以下も設定します。
- `WORKER_ADMIN_BASE_URL`（例: `https://<worker>.workers.dev`）
- `ADMIN_API_TOKEN`（Worker 側 `ADMIN_API_TOKEN` と同じ値）
