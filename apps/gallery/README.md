# apps/gallery

Notion + Cloudflare R2 をソースにしたギャラリーを、Googleサイトへ iframe で埋め込むための一式です。

## Module Scope

このディレクトリは `auto-post` モノレポ内で、以下を担当します。

- 公開ギャラリーUI
- 先生専用アップロード/整備UI
- Cloudflare Worker API

- アーキテクチャ: `ARCHITECTURE.md`
- 移行実績（履歴）: `docs/monorepo-migration-plan.md`
- モノレポ統合ノート（repo root）: `../../MONOREPO_INTEGRATION.md`

## 主要ファイル

- `gallery.html`: ギャラリーUI（単一HTML）
- `admin.html`: 先生専用アップロード/整備UI（Cloudflare Access 配下想定）
- `gallery.json`: 作品データ（auto-post で生成、`.gitignore` 済み）
- `gallery.sample.json`: 共有用のサンプル
- `worker/src/index.js`: ★ API + 管理API（Cloudflare Workers）
- `wrangler.toml`: Worker 設定テンプレート

## ★ API（Cloudflare Workers + KV）

1. Cloudflare で KV namespace を作成
2. `wrangler.toml` の `id` / `preview_id` を差し替え
3. `wrangler deploy` で公開
4. `gallery.html` の `data-star-api` か `window.STAR_API_BASE` に Worker のベースURLを設定

### エンドポイント

- `GET /stars?ids=<id1>,<id2>,...`
- `POST /star`（`{ id, delta }`）

## 先生専用アップロードUI（admin.html）

仕様書: `先生専用アップロードUI仕様書_v1.4.1.md`

### 前提

- `admin.html` は Cloudflare Access 配下での運用を想定しています（フロントに固定鍵は埋め込みません）。
- Notion / GitHub / R2 は Worker 経由で操作します（秘匿情報は Worker の環境変数/secret に置く）。

### admin.html の機能

- 新規登録: 画像アップロード（R2）→ Notion 作品ページ作成
- 整備モード: `整備済=false` の作品をキュー表示し、画像プレビュー付きで編集
- 画像セット操作: 分割 / 移動 / 統合（統合元は既定でアーカイブ）
- ギャラリー更新: GitHub Actions `workflow_dispatch` をトリガー

### 管理API（Worker）エンドポイント（抜粋）

- `GET /participants-index` / `GET /students-index` / `GET /tags-index`
- `POST /participants-index`（Bearer認証で `participants_index.json` をR2へ更新）
- `GET /admin/notion/schema`
- `GET /admin/notion/works?unprepared=1`
- `POST /admin/r2/upload`（multipart）
- `POST /admin/notion/work` / `PATCH /admin/notion/work`
- `POST /admin/image/split` / `POST /admin/image/move` / `POST /admin/image/merge`
- `POST /admin/trigger-gallery-update`

### Worker 設定（wrangler.toml）

- `STAR_KV`（★）
- `GALLERY_R2`（アップロード先）
- `R2_PUBLIC_BASE_URL`（Notionに保存する外部URLのベース）
- `NOTION_WORKS_DB_ID` / `NOTION_TAGS_DB_ID`
- secrets: `NOTION_TOKEN` / `GITHUB_TOKEN`
- participants push用 secret（任意）: `UPLOAD_UI_PARTICIPANTS_INDEX_PUSH_TOKEN`

### タグ一括再計算（CLI）

`scripts/tag-recalc.mjs` で「親タグ追加 + merged置換」を dry-run → apply できます。

例:

```bash
node scripts/tag-recalc.mjs --dry-run
node scripts/tag-recalc.mjs --apply
```

### students/tags インデックス生成・アップロード

`students_index.json` / `tags_index.json` は Notion から生成して R2 に配置できます。

```bash
# 生成のみ（既定: リポジトリ直下の .env を読み込む）
npm run build:admin-indexes

# 生成 + R2アップロード（既定bucket: woodcarving-photos）
npm run upload:admin-indexes
```

任意引数（直接実行時）:

```bash
bash ./scripts/upload-admin-indexes.sh <bucket> <env-file> <out-dir>
```

### 作品キュー スモークテスト

複数画像を選択したときに「作品キュー」が生成されることをヘッドレスブラウザで検証できます。

```bash
npm install
npx playwright install chromium
npm run test:upload-queue-smoke
```

結果は `test-results/upload-queue-smoke.json` と `test-results/upload-queue-smoke.png` に出力されます。

## R2 配置

- `gallery.html` / `gallery.json` / `thumbs/` を R2 にアップロード
- `gallery.html`: `Cache-Control: max-age=3600`
- `gallery.json`: `Cache-Control: max-age=300`
- `thumbs/`: `Cache-Control: max-age=31536000`

## 運用

- `auto-post export-gallery-json` で `gallery.json` と `thumbs/` を生成し R2 へ配置
- 定期実行（1日1回）+ 手動実行の運用を想定
