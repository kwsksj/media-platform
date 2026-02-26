# Operations

## データソース（現時点）

- 画像ファイル: `Cloudflare R2`
- 作品メタデータ・投稿状態: `Notion`
- 生徒名簿・予約状況: `Google スプレッドシート`

## Daily Scheduled Jobs

- `Daily Gallery Export` (`.github/workflows/gallery-export.yml`)
  - Schedule: 毎日 16:10 JST (07:10 UTC)
- `Image Link Health Check` (`.github/workflows/image-link-health.yml`)
  - Schedule: 毎週日曜 16:35 JST (07:35 UTC)
- `Daily Auto Post` (`.github/workflows/schedule.yml`)
  - Schedule: 毎日 16:42 JST (07:42 UTC)
- `Monthly Schedule Post` (`.github/workflows/monthly-schedule.yml`)
  - Schedule: 毎月25日 16:00 JST (07:00 UTC)

## Manual Jobs

- `Catch-up Post` (`.github/workflows/catchup.yml`)
- `Daily Gallery Export` の手動再実行
- `Image Link Health Check` の手動再実行
- `Daily Auto Post` の手動再実行
- `Monthly Schedule Post` の手動再実行
- `Worker Deploy` (`.github/workflows/worker-deploy.yml`)
- `Admin Web Deploy` (`.github/workflows/admin-web-deploy.yml`)
  - `admin.html` / `admin/*` / `shared/*` と管理用 index JSON をデプロイ

## PR Lifecycle Automation

- `PR Lifecycle Automation` (`.github/workflows/pr-lifecycle.yml`)
  - Approved review を契機に auto-merge を有効化（`--auto --squash --delete-branch`）
  - merge 後に head branch 削除をフォールバック実行
  - Worker/Gallery/Admin 関連変更時のみ `Worker Deploy` / `Daily Gallery Export` / `Admin Web Deploy` を merge 後に自動起動

Repository Variables:

- `PR_AUTO_MERGE_ENABLED` (`false` で auto-merge 有効化を停止)
- `AUTO_WORKER_DEPLOY_ON_MERGE` (`true` で `worker-deploy.yml` を merge 後に起動、Worker関連変更時のみ)
- `AUTO_GALLERY_EXPORT_ON_MERGE` (`true` で `gallery-export.yml` を merge 後に起動、Gallery関連変更時のみ)
- `AUTO_ADMIN_WEB_DEPLOY_ON_MERGE` (`true` で `admin-web-deploy.yml` を merge 後に起動、Admin関連変更時のみ)

## Image Link Health Check Optional Settings

GitHub Repository Variables:

- `IMAGE_LINK_CHECK_SKIP_HTTP`: `true` でHTTPチェック省略（optional）
- `IMAGE_LINK_CHECK_INCLUDE_ARCHIVED`: `true` でarchivedページを含める（optional）
- `IMAGE_LINK_CHECK_MAX_DETAILS`: 出力詳細件数（default: `60`）

## Local Runbook (Make)

```bash
# 構成チェック
make check-monorepo

# Markdown チェック（実務向け）
make check-markdown

# PRマージ + ローカルブランチ整理
make pr-merge-local PR=16

# ingest dry-run
make ingest-preview TAKEOUT_DIR=./takeout-photos
make ingest-import-dry TAKEOUT_DIR=./takeout-photos

# publish dry-run
make publish-dry
make publish-catchup-dry
make publish-monthly-schedule-dry

# gallery build dry-run
make gallery-export
make gallery-tag-recalc-dry

# app smoke / deploy dry-run
make admin-smoke
make worker-dry
```

## Tool Entrypoints

```bash
# ingest
./tools/ingest/preview.sh ./takeout-photos --threshold 10 --max-per-group 10
./tools/ingest/import-direct.sh ./takeout-photos --dry-run

# publish
./tools/publish/post.sh --dry-run
./tools/publish/catchup.sh --dry-run
./tools/publish/monthly-schedule.sh --dry-run

# gallery build
./tools/gallery-build/export.sh --no-upload --no-thumbs --no-light
./tools/gallery-build/tag-recalc.sh --dry-run
```

## App Directories

- `apps/gallery-web`: 公開ギャラリーUI
- `apps/admin-web`: 管理UI（アップロード・整備）
- `apps/worker-api`: Cloudflare Worker API
