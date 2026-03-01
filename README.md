# media-platform

木彫り教室の生徒作品画像を「取り込み・アップロード・公開ギャラリー生成・**Instagram / X / Threads** 投稿」まで一貫して運用するモノレポです。

CLI 名は互換性のため `auto-post` を継続しています。

## データ正本（現時点）

- 画像ファイル: `Cloudflare R2`（画像実体の正本）
- 作品メタデータ・投稿状態: `Notion`（運用台帳）
- 生徒名簿・予約状況: `Google スプレッドシート`（現行運用）

将来的に、生徒名簿・予約系データの移行先として Notion 等を検討中です。

## 責務マップ

| Path                  | Responsibility                                        |
| --------------------- | ----------------------------------------------------- |
| `apps/gallery-web`    | 公開ギャラリーUI                                      |
| `apps/admin-web`      | 管理UI（アップロード・整備）                          |
| `apps/worker-api`     | Cloudflare Worker API                                 |
| `tools/ingest`        | Takeout 取り込み・Notion 登録の入口                   |
| `tools/publish`       | SNS 自動投稿の入口                                    |
| `tools/gallery-build` | `gallery.json` / `thumbs` / `images_light` 生成の入口 |
| `src/auto_post`       | `auto-post` CLI 本体                                  |
| `docs`                | 全体構成・運用手順                                    |

統合方針と検証記録: `docs/monorepo-integration.md`

## Quick Start

```bash
git clone https://github.com/kwsksj/media-platform.git
cd media-platform
python3 -m venv venv
source venv/bin/activate
make setup-python-dev
```

```bash
make help
make recommend-checks
make check-required
make check-required-strict
make check-changed-python
make check-fast
make check-monorepo
make check-markdown
make pr-merge-local PR=<number>
```

```bash
# 任意: 管理UIの依存を入れる
make setup-admin-web

# 任意: commit前チェックを自動化
make pre-commit-install
```

`.vscode/tasks.json` を同梱しているため、VSCode では `Run Task` から
`Check Changed Python` / `Check Fast` / `Publish Daily Dry Run` を直接実行できます。
`check-required-strict` は、マージ前に cross-cutting な変更を強めに検証したいときに使います。

```bash
# 投稿 dry-run（推奨）
make publish-daily-dry

# 投稿本番
make publish-daily DATE=2026-03-01

# catch-up dry-run
make publish-catchup-dry

# catch-up 本番
make publish-catchup

# monthly schedule dry-run
make publish-monthly-schedule-dry

# monthly schedule 本番（例: next month）
make publish-monthly-schedule MONTHLY_TARGET=next

# gallery build dry-run（R2アップロードなし）
make gallery-build-dry

# gallery data deploy（gallery.json + thumbs + images_light）
make deploy-gallery-data

# gallery.html deploy
make deploy-gallery-html

# タグ再計算 dry-run
make gallery-tag-recalc-dry

# 先生専用UI deploy
make deploy-admin

# Worker deploy dry-run
make deploy-worker-dry

# Worker deploy 本番
make deploy-worker
```

詳細セットアップ: `docs/setup.md`

## Markdown Lint 方針

- 設定ファイル: `.markdownlint.jsonc`
- 対象外: `.markdownlintignore`（`venv` / `node_modules` / `archive` など）
- 実行: `make check-markdown`（Node.js + `npx` 利用。未導入時はスキップ）

## ディレクトリ構成

```text
media-platform/
├── apps/gallery-web/
├── apps/admin-web/
├── apps/worker-api/
├── tools/ingest/
├── tools/publish/
├── tools/gallery-build/
├── docs/
├── src/auto_post/
├── .github/workflows/
└── Makefile
```

## 運用コマンド

### Makefile（推奨入口）

```bash
make recommend-checks
make check-required
make check-required-strict
make check-changed-python
make fix-changed-python
make check-fast
make check-python
make check-monorepo
make check-markdown
make pr-merge-local PR=<number>
make ingest-preview TAKEOUT_DIR=./takeout-photos
make ingest-import-dry TAKEOUT_DIR=./takeout-photos
make publish-daily-dry
make publish-daily
make publish-catchup-dry
make publish-catchup
make publish-monthly-schedule-dry
make publish-monthly-schedule
make gallery-build-dry
make gallery-build
make gallery-tag-recalc-dry
make deploy-gallery
make deploy-admin
make deploy-worker-dry
make deploy-worker
make admin-smoke
```

### 責務別エントリ

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

### 直接 CLI

```bash
auto-post post --dry-run
auto-post catchup --dry-run
auto-post export-gallery-json --no-upload --no-thumbs --no-light
```

## 定期運用（GitHub Actions）

- `Daily Gallery Export` (`.github/workflows/gallery-export.yml`)
  - 毎日 16:10 JST (07:10 UTC)
- `Image Link Health Check` (`.github/workflows/image-link-health.yml`)
  - 毎週日曜 16:35 JST (07:35 UTC) に実行
- `Daily Auto Post` (`.github/workflows/schedule.yml`)
  - 毎日 16:42 JST (07:42 UTC)
- `Catch-up Post` (`.github/workflows/catchup.yml`)
  - 手動実行のみ
- `Monthly Schedule Post` (`.github/workflows/monthly-schedule.yml`)
  - 毎月25日 16:00 JST (07:00 UTC)

## PR 運用自動化（GitHub Actions）

- `PR Lifecycle Automation` (`.github/workflows/pr-lifecycle.yml`)
  - PR review が `APPROVED` になったタイミングで `--auto --squash --delete-branch` を試行
  - PR merge 後に head branch の削除をフォールバック実行
  - `apps/worker-api` / `apps/gallery-web` / `tools/gallery-build` などの変更時のみ、条件付きで後続workflowを自動起動
- `Worker Deploy` (`.github/workflows/worker-deploy.yml`)
  - 手動実行（`Run workflow`）または PR merge 後に自動起動
- `Admin Web Deploy` (`.github/workflows/admin-web-deploy.yml`)
  - `admin.html` / `admin/*` / `shared/*` と `students_index.json` / `tags_index.json` を手動実行または PR merge 後に自動デプロイ

### PR 自動化の設定項目

GitHub Repository Variables:

- `PR_AUTO_MERGE_ENABLED`: `false` のとき承認時 auto-merge 有効化を無効（既定: 有効）
- `AUTO_WORKER_DEPLOY_ON_MERGE`: `true` で merge 後に `worker-deploy.yml` を自動起動（Worker関連変更時のみ）
- `AUTO_GALLERY_EXPORT_ON_MERGE`: `true` で merge 後に `gallery-export.yml` を自動起動（Gallery関連変更時のみ）
- `AUTO_ADMIN_WEB_DEPLOY_ON_MERGE`: `true` で merge 後に `admin-web-deploy.yml` を自動起動（Admin関連変更時のみ）

GitHub Repository Secrets:

- `CLOUDFLARE_API_TOKEN`: `worker-deploy.yml` 実行に必須

### ローカルブランチ整理を含むマージ

- `make pr-merge-local PR=<number>`
  - `gh pr merge --auto --squash --delete-branch` を実行
  - マージ前に AI レビュー反応を待機
    - Gemini: `gemini-code-assist[bot]` の review を優先（概要コメントのみの場合は猶予時間経過後に通過）
    - Codex: `chatgpt-codex-connector[bot]` の comment/review または `+1` reaction
  - PR が `MERGED` になったら default branch に戻って `git branch -d` まで実施
  - 待機秒数は `PR_MERGE_WAIT_SECONDS`（既定: `600`）で調整可能
  - AI待機は `PR_AI_REVIEW_WAIT_SECONDS`（既定: `900`）で調整可能
  - Gemini の review 猶予は `PR_GEMINI_REVIEW_GRACE_SECONDS`（既定: `180`）で調整可能

### 画像リンク健全性チェックのオプション設定

GitHub Repository Variables:

- `IMAGE_LINK_CHECK_SKIP_HTTP`: `true` でHTTP疎通チェックを省略（任意）
- `IMAGE_LINK_CHECK_INCLUDE_ARCHIVED`: `true` で archived ページを含める（任意）
- `IMAGE_LINK_CHECK_MAX_DETAILS`: レポート詳細件数（任意、既定 `60`）

## ドキュメント

- 入口: `docs/README.md`
- 構成: `docs/architecture.md`
- 運用: `docs/operations.md`
- セットアップ: `docs/setup.md`
- 現行仕様: `docs/system-spec.md`
- 統合/移行記録: `docs/monorepo-integration.md`
- 旧移行計画履歴: `docs/history/monorepo-migration-plan.md`

## 補助スクリプト

```bash
# workflowが要求するSecrets名を一覧化（.envのキー存在チェック付き）
scripts/list-required-gh-secrets.sh

# .env の値から GitHub Secrets を再設定（値はGitHubからは取得不可）
scripts/push-gh-secrets-from-env.sh <owner/repo>

# 実際には更新せず、対象キーだけ確認
scripts/push-gh-secrets-from-env.sh --dry-run <owner/repo>
```

## ライセンス

Private
