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
