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
pip install -e .
```

```bash
make help
make check-monorepo
```

```bash
# 投稿 dry-run
make publish-dry

# catch-up dry-run
make publish-catchup-dry

# monthly schedule dry-run
make publish-monthly-schedule-dry

# gallery export dry-run（R2アップロードなし）
make gallery-export

# タグ再計算 dry-run
make gallery-tag-recalc-dry

# Worker deploy dry-run
make worker-dry
```

詳細セットアップ: `docs/setup.md`

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
make check-monorepo
make ingest-preview TAKEOUT_DIR=./takeout-photos
make ingest-import-dry TAKEOUT_DIR=./takeout-photos
make publish-dry
make publish-catchup-dry
make publish-monthly-schedule-dry
make gallery-export
make gallery-tag-recalc-dry
make admin-smoke
make worker-dry
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
- `Daily Auto Post` (`.github/workflows/schedule.yml`)
  - 毎日 16:42 JST (07:42 UTC)
- `Catch-up Post` (`.github/workflows/catchup.yml`)
  - 手動実行のみ
- `Monthly Schedule Post` (`.github/workflows/monthly-schedule.yml`)
  - 毎月25日 16:00 JST (07:00 UTC)

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
