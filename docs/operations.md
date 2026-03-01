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
  - ローカル `make pr-merge-local` では AI レビュー待機を実施
    - Gemini: review from `gemini-code-assist[bot]`（概要コメントのみは未完了扱い）
    - Codex: comment/review or `+1` reaction from `chatgpt-codex-connector[bot]`

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
make pr-merge-local PR=<number>
# 例: 最大30秒だけ待機
PR_MERGE_WAIT_SECONDS=30 make pr-merge-local PR=<number>
# 例: AIレビュー待機を最大20分に延長
PR_AI_REVIEW_WAIT_SECONDS=1200 make pr-merge-local PR=<number>

# ingest dry-run
make ingest-preview TAKEOUT_DIR=./takeout-photos
make ingest-import-dry TAKEOUT_DIR=./takeout-photos

# publish (dry-run / live)
make publish-daily-dry
make publish-daily DATE=2026-03-01
make publish-catchup-dry
make publish-catchup
make publish-monthly-schedule-dry
make publish-monthly-schedule MONTHLY_TARGET=next

# gallery build (dry-run / live)
make gallery-build-dry
make gallery-build
make gallery-tag-recalc-dry

# deploy (dry-run / live)
make deploy-gallery
make deploy-admin
make deploy-worker-dry
make deploy-worker

# app smoke
make admin-smoke

# R2 backup / restore drill (rclone)
make r2-backup-dry
make r2-backup
make r2-restore-dry

# 整合性チェック（dry-run）
python scripts/check_image_links.py
python scripts/cleanup_duplicates.py
# 孤立R2画像も削除対象にする場合のみ明示指定
python scripts/cleanup_duplicates.py --delete-orphaned-r2
```

## R2 Backup Runbook

`scripts/r2_backup.sh` は `rclone` 前提の雛形です。正本はR2のまま、別リモート（例: Google Drive）をバックアップ先にします。

```bash
# 必須: rclone remote を設定済みにする
# 例: r2 remote名=r2, Drive remote名=gdrive
export R2_REMOTE_NAME=r2
export R2_BUCKET_NAME=<your-r2-bucket>
export R2_BACKUP_REMOTE=gdrive:media-platform-r2/current

# バックアップ dry-run / 実行
make r2-backup-dry
make r2-backup

# 復元リハーサル（dry-runのみ）
make r2-restore-dry
```

### 未整理アップロードが多い場合の注意

- `cleanup_duplicates.py` はデフォルトで **孤立R2画像を削除しません**（Notion未登録の保留画像を保護）。
- Notionの未整備ページと紐づく画像は従来どおり削除候補になります。
- 孤立R2画像を削除するのは、棚卸しが終わった後に `--delete-orphaned-r2` を付ける時だけにしてください。

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
