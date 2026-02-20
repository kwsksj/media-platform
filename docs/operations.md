# Operations

## データソース（現時点）

- 画像ファイル: `Cloudflare R2`
- 作品メタデータ・投稿状態: `Notion`
- 生徒名簿・予約状況: `Google スプレッドシート`

## Daily Scheduled Jobs

- `Daily Gallery Export` (`.github/workflows/gallery-export.yml`)
  - Schedule: 毎日 16:10 JST (07:10 UTC)
- `Daily Auto Post` (`.github/workflows/schedule.yml`)
  - Schedule: 毎日 16:42 JST (07:42 UTC)
- `Monthly Schedule Post` (`.github/workflows/monthly-schedule.yml`)
  - Schedule: 毎月25日 16:00 JST (07:00 UTC)

## Manual Jobs

- `Catch-up Post` (`.github/workflows/catchup.yml`)
- `Daily Gallery Export` の手動再実行
- `Daily Auto Post` の手動再実行
- `Monthly Schedule Post` の手動再実行

## Local Runbook (Make)

```bash
# 構成チェック
make check-monorepo

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
