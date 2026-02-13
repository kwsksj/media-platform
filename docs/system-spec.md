# media-platform 生徒作品画像運用システム 現状仕様書

## 概要

木彫り教室の生徒作品画像を、取り込み・アップロード・公開ギャラリー生成・**Instagram / X / Threads** 投稿まで一貫運用するシステム。

## データ正本（現時点）

- 画像ファイル: `Cloudflare R2`（画像実体の正本）
- 作品メタデータ・投稿状態: `Notion`（運用台帳）
- 生徒名簿・予約状況: `Google スプレッドシート`（現行運用）

将来的に、生徒名簿・予約系データの移行先として Notion 等を検討中。

### 当初仕様からの主な変更点

| 項目                 | 当初仕様                | 現状                            |
| -------------------- | ----------------------- | ------------------------------- |
| 作品管理台帳         | Google スプレッドシート | **Notion データベース**         |
| 生徒名簿・予約状況   | Google スプレッドシート | **Google スプレッドシート（現行）** |
| 画像ストレージ       | Google Drive            | **Cloudflare R2**               |
| 対応プラットフォーム | Instagram, X            | **Instagram, X, Threads**       |
| 実行方式             | GAS 定期実行            | **GitHub Actions + Python CLI** |
| トークン管理         | 手動更新                | **R2保存 + 自動更新（60日）**   |

---

## システム構成

```
media-platform (monorepo)
├─ GitHub Actions
│  ├─ schedule.yml       (毎日 16:42 JST)
│  ├─ gallery-export.yml (毎日 16:10 JST)
│  └─ catchup.yml        (手動実行)
├─ auto-post CLI (src/auto_post)
│  ├→ Instagram Graph API
│  ├→ X (Twitter) API v2
│  └→ Threads API
└─ apps/
   ├─ gallery-web (gallery.html)
   ├─ admin-web (admin.html + admin/shared)
   └─ worker-api (Cloudflare Workers)
```

---

## 運用導線

- 日常運用 runbook: `operations.md`
- 初期セットアップ: `setup.md`
- 全体概要と責務マップ: `../README.md`

CLI は `auto-post` を中心に運用し、日常実行は `Makefile` を優先します。  
主要カテゴリは以下です。

- 投稿系: `post`, `catchup`
- 取り込み系: `preview-groups`, `import-direct`, `import-folders`, `export-groups`, `import-groups`
- gallery build 系: `export-gallery-json`
- 管理系: `check-notion`, `list-works`, `refresh-token`

---

## 環境変数

### 必須

| 変数名                          | 説明                             |
| ------------------------------- | -------------------------------- |
| `NOTION_TOKEN`                  | Notion API トークン              |
| `NOTION_DATABASE_ID`            | 作品管理DBのID                   |
| `INSTAGRAM_APP_ID`              | Meta App ID                      |
| `INSTAGRAM_APP_SECRET`          | Meta App Secret                  |
| `INSTAGRAM_ACCESS_TOKEN`        | 長期アクセストークン             |
| `INSTAGRAM_BUSINESS_ACCOUNT_ID` | ビジネスアカウントID             |
| `THREADS_APP_ID`                | Threads用 App ID（通常IGと同じ） |
| `THREADS_APP_SECRET`            | Threads用 App Secret             |
| `THREADS_ACCESS_TOKEN`          | Threads長期トークン              |
| `THREADS_USER_ID`               | Threads ユーザーID               |
| `R2_ACCOUNT_ID`                 | Cloudflare Account ID            |
| `R2_ACCESS_KEY_ID`              | R2 Access Key                    |
| `R2_SECRET_ACCESS_KEY`          | R2 Secret Key                    |
| `R2_BUCKET_NAME`                | バケット名                       |

### オプション

| 変数名                  | 説明                     | デフォルト |
| ----------------------- | ------------------------ | ---------- |
| `R2_PUBLIC_URL`         | 公開URL                  | なし       |
| `X_API_KEY`             | X API Key (Consumer Key) | なし       |
| `X_API_KEY_SECRET`      | X API Key Secret         | なし       |
| `X_ACCESS_TOKEN`        | X Access Token           | なし       |
| `X_ACCESS_TOKEN_SECRET` | X Access Token Secret    | なし       |

---

## Notion データベース構造

このセクションは「作品メタデータ・投稿状態」を管理する Notion DB の仕様です。  
生徒名簿・予約状況の正本は現時点では Google スプレッドシート運用です。

### 必須プロパティ

| プロパティ名    | タイプ   | 説明                   |
| --------------- | -------- | ---------------------- |
| 作品名          | Title    | 作品のタイトル         |
| 画像            | Files    | 投稿する画像（複数可） |
| Instagram投稿済 | Checkbox | IG投稿完了フラグ       |
| X投稿済         | Checkbox | X投稿完了フラグ        |
| Threads投稿済   | Checkbox | Threads投稿完了フラグ  |
| スキップ        | Checkbox | 投稿対象外フラグ       |

### オプションプロパティ

| プロパティ名      | タイプ                | 説明                                             |
| ----------------- | --------------------- | ------------------------------------------------ |
| 作者              | Relation（生徒DB）    | 生徒（Relation。Select運用は非推奨）             |
| 教室              | Select                | 教室（正規値。例：東京教室/つくば教室/沼津教室） |
| 会場              | Select                | 会場（正規値。例：浅草橋/東池袋）                |
| 完成日            | Date                  | 作品完成日（初期値は写真撮影日）                 |
| 投稿予定日        | Date                  | 優先投稿日                                       |
| Instagram投稿日時 | Date                  | Instagram投稿日時（JST）                         |
| X投稿日時         | Date                  | X投稿日時（JST）                                 |
| Threads投稿日時   | Date                  | Threads投稿日時（JST）                           |
| キャプション      | Rich Text             | カスタムキャプション                             |
| タグ              | Relation/Multi-select | 分類用タグ（投稿には使用しない）                 |
| Instagram投稿ID   | Rich Text             | 投稿後に自動記録                                 |
| X投稿ID           | Rich Text             | 投稿後に自動記録                                 |
| Threads投稿ID     | Rich Text             | 投稿後に自動記録                                 |
| エラーログ        | Rich Text             | エラー発生時に記録                               |

補足：教室（Select）は `東京教室 / つくば教室 / 沼津教室` のように「〇〇教室」で**正規化**して運用し（予約UIの都合で `東京` のような短縮表記が混在しても保存前に正規化する）、会場（浅草橋など）は `会場`（Select）に分けると、後からデータが濁りません。公開ギャラリー側の `studio` には表示都合で教室名を短縮（末尾の「教室」を除去）して出す前提でOKです。会場は Notion に保持しますが、現状の公開JSON（gallery.json）には含めません（互換性維持）。

---

## 投稿ロジック

### 投稿対象の選定

各プラットフォーム（Instagram, X, Threads）ごとに独立して以下の優先順位で選定します。

1. **Priority 1: 投稿日指定**
    - `投稿予定日 = 今日` の作品（無制限）
2. **Priority 2: キャッチアップ投稿**
    - 「他SNSで投稿済み」かつ「当該SNSで未投稿」の作品
    - 1日最大 1件
3. **Priority 3: 基本投稿**
    - 「当該SNSで未投稿」の作品（完成日順）
    - 1日最大 2件（既定値。`--basic-limit` で変更可能）
    - ※ X (Basic Tier) は1ツイートにつき画像1枚のみ（Notionの画像リストの先頭を使用）

※ 画像処理は全プラットフォームの選定作品をまとめて行うため効率的です。

### プラットフォーム別投稿

`--platform` オプション指定時:

- 指定プラットフォームの未投稿チェックのみで作品を選定
- 指定プラットフォームにのみ投稿

例: `--platform threads` → Threads未投稿の作品を拾い、Threadsのみ投稿

### キャプション生成

```
{作品名} の木彫りです！
{キャプション}
完成日: {YYYY年MM月DD日}
{デフォルトタグ}
#{教室名}
```

---

## トークン管理

### Instagram / Threads

- 長期トークン（60日有効）を R2 に保存
- 有効期限20日前から自動更新
- 更新エンドポイント:
  - IG: `graph.facebook.com/oauth/access_token` + `fb_exchange_token`
  - Threads: `graph.threads.net/refresh_access_token` + `th_refresh_token`

### X (Twitter)

- OAuth 1.0a トークン（無期限）
- **Read and Write** 権限が必要
- 更新不要

---

## GitHub Actions

### ワークフロー: `schedule.yml`（Daily Auto Post）

- **スケジュール**: 毎日 16:42 JST (07:42 UTC)
- **手動実行オプション**:
  - `date`: 対象日指定
  - `platform`: プラットフォーム選択 (all/instagram/x/threads)
  - `basic_limit`: 基本投稿件数
  - `catchup_limit`: キャッチアップ件数
  - `dry_run`: dry-run 実行

### ワークフロー: `gallery-export.yml`（Daily Gallery Export）

- **スケジュール**: 毎日 16:10 JST (07:10 UTC)
- **手動実行オプション**:
  - `no_thumbs` / `no_light`
  - `overwrite_thumbs` / `overwrite_light`
  - `thumb_width` / `light_max_size` / `light_quality`

### ワークフロー: `catchup.yml`（Catch-up Post）

- **スケジュール**: なし（手動実行のみ）
- **手動実行オプション**:
  - `limit`: キャッチアップ件数
  - `platform`: プラットフォーム選択 (all/instagram/x/threads)
  - `dry_run`: dry-run 実行

### 必要な Secrets

GitHub リポジトリの Settings > Secrets に設定:

- 上記「環境変数 - 必須」の全項目

---

## ファイル構成

```text
media-platform/
├── apps/gallery-web/
│   ├── gallery.html        # 公開ギャラリーUI
│   ├── gallery-ui-spec.md
│   └── scripts/upload-gallery-html.sh
├── apps/admin-web/
│   ├── admin.html          # 先生専用UI
│   ├── admin/              # 管理画面スクリプト/CSS
│   ├── admin-upload-ui-spec.md
│   ├── docs/               # 管理UI関連ドキュメント
│   ├── shared/             # UI共通モジュール
│   └── scripts/            # index生成・upload・smoke test
├── apps/worker-api/
│   ├── worker/src/index.js # Cloudflare Worker API
│   └── wrangler.toml
├── tools/ingest/          # ingest エントリーポイント
├── tools/publish/         # publish エントリーポイント
├── tools/gallery-build/   # gallery build エントリーポイント
├── docs/
│   ├── README.md
│   ├── architecture.md
│   ├── operations.md
│   ├── setup.md
│   ├── system-spec.md
│   ├── monorepo-integration.md
│   └── history/
├── .github/workflows/
│   ├── schedule.yml       # Daily Auto Post
│   ├── catchup.yml        # Catch-up Post
│   └── gallery-export.yml # Daily Gallery Export
├── src/auto_post/
│   ├── cli.py           # CLIエントリーポイント
│   ├── config.py        # 設定クラス
│   ├── poster.py        # 投稿オーケストレーター
│   ├── notion_db.py     # Notion API クライアント
│   ├── instagram.py     # Instagram API クライアント
│   ├── threads.py       # Threads API クライアント
│   ├── x_twitter.py     # X API クライアント
│   ├── r2_storage.py    # R2 ストレージ
│   ├── token_manager.py # トークン管理
│   ├── importer.py      # 写真インポート
│   ├── grouping.py      # グルーピング処理
│   └── gps_utils.py     # GPS/教室判定
├── scripts/              # 補助運用スクリプト
├── tests/
├── Makefile
├── pyproject.toml
└── README.md
```
