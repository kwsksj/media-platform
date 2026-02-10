# auto-post

木彫り教室の生徒作品写真を **Instagram / X / Threads** に自動投稿するシステム。

## 特徴

- 📅 GitHub Actions による毎日の自動投稿（16:42 JST）
- 📝 Notion データベースで作品・投稿状態を一元管理
- 🖼️ Cloudflare R2 による画像ストレージ
- 🔄 トークンの自動更新（Instagram / Threads）

## セットアップ

### 1. リポジトリのクローン

```bash
git clone https://github.com/your-repo/auto-post.git
cd auto-post
pip install -e .
```

### 2. 環境変数の設定

`.env` ファイルを作成し、以下を設定:

```bash
# Notion（TAGS_DATABASE_ID は任意）
NOTION_TOKEN=secret_xxx
NOTION_DATABASE_ID=xxx
TAGS_DATABASE_ID=xxx

# Instagram
INSTAGRAM_APP_ID=xxx
INSTAGRAM_APP_SECRET=xxx
INSTAGRAM_ACCESS_TOKEN=xxx
INSTAGRAM_BUSINESS_ACCOUNT_ID=xxx

# Threads
THREADS_APP_ID=xxx
THREADS_APP_SECRET=xxx
THREADS_ACCESS_TOKEN=xxx
THREADS_USER_ID=xxx

# Cloudflare R2
R2_ACCOUNT_ID=xxx
R2_ACCESS_KEY_ID=xxx
R2_SECRET_ACCESS_KEY=xxx
R2_BUCKET_NAME=xxx
R2_PUBLIC_URL=xxx

# X (Twitter) - オプション
X_API_KEY=xxx
X_API_KEY_SECRET=xxx
X_ACCESS_TOKEN=xxx
X_ACCESS_TOKEN_SECRET=xxx
```

> GitHub Actions で使用する場合は、リポジトリの **Settings > Secrets** に同じ変数を設定してください。

## 使い方

### 日次投稿

```bash
# 全プラットフォームに投稿
auto-post post

# 特定プラットフォームのみ
auto-post post --platform instagram
auto-post post --platform threads
auto-post post --platform x

# 投稿件数を指定
auto-post post --basic-limit 3 --catchup-limit 2

# ドライラン（テスト）
auto-post post --dry-run
```

### キャッチアップ投稿

```bash
# 他SNSで投稿済み＆当該SNS未投稿の作品を投稿
auto-post catchup
auto-post catchup --platform x --limit 3
```

> GitHub Actions の `Catch-up Post` ワークフローからも実行可能です。

### ギャラリー更新（gallery.json / thumbs / images_light）

```bash
# Notionからgallery.jsonとサムネ・軽量画像を生成し、R2へアップロード
auto-post export-gallery-json

# サムネを作らない場合
auto-post export-gallery-json --no-thumbs

# 軽量画像を作らない場合
auto-post export-gallery-json --no-light

# 既存のサムネ/軽量画像を上書き再生成する場合
auto-post export-gallery-json --overwrite-thumbs --overwrite-light
```

`export-gallery-json` は Notion の `整備済み`（checkbox または boolean を返す formula）が `true` の作品のみを書き出します。
プロパティ名が異なる場合は `NOTION_WORKS_READY_PROP` で上書きできます（checkbox / formula 対応）。

> GitHub Actions で自動実行する場合は、`.github/workflows/gallery-export.yml` を有効化し、
> Secrets に `NOTION_TOKEN`, `NOTION_DATABASE_ID`, `R2_*`, `R2_PUBLIC_URL` を設定してください。

### 確認・デバッグ

```bash
# Notion接続確認
auto-post check-notion

# 作品一覧表示
auto-post list-works
auto-post list-works --unposted
```

### 写真インポート

```bash
# フォルダから直接インポート
auto-post import-direct <folder>

# サブフォルダ単位でインポート
auto-post import-folders <folder>
```

## 投稿ロジック

各プラットフォームごとに以下の優先順位で投稿:

1. **投稿日指定** - `投稿予定日 = 今日` の作品（無制限）
2. **キャッチアップ** - 他SNS投稿済み＆当該SNS未投稿（デフォルト: 1件/日）
3. **基本投稿** - 未投稿作品を完成日順（デフォルト: 2件/日）

> 件数は `--basic-limit` / `--catchup-limit` オプションで変更可能。
> GitHub Actions の workflow_dispatch からも設定できます。

## ドキュメント

- [詳細仕様書](./CURRENT_SYSTEM.md) - Notionスキーマ、API詳細、トークン管理など

## ライセンス

Private
