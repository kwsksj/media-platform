# auto-post システム 現状仕様書

## 概要

木彫り教室の生徒作品写真を **Instagram / X / Threads** に自動投稿するシステム。

### 当初仕様からの主な変更点

| 項目                 | 当初仕様                | 現状                            |
| -------------------- | ----------------------- | ------------------------------- |
| 管理台帳             | Google スプレッドシート | **Notion データベース**         |
| 画像ストレージ       | Google Drive            | **Cloudflare R2**               |
| 対応プラットフォーム | Instagram, X            | **Instagram, X, Threads**       |
| 実行方式             | GAS 定期実行            | **GitHub Actions + Python CLI** |
| トークン管理         | 手動更新                | **R2保存 + 自動更新（60日）**   |

---

## システム構成

```
Notion データベース（投稿管理）
    ↓
GitHub Actions (毎日 12:00 JST)
    ↓
auto-post CLI (Python)
    ├→ Instagram Graph API
    ├→ X (Twitter) API v2
    └→ Threads API
    ↓
Notion 更新（投稿済みフラグ）
```

---

## CLI コマンド一覧

### 投稿系

```bash
# 日次投稿（3件まで）
auto-post post

# 特定プラットフォームのみ
auto-post post --platform threads
auto-post post --platform instagram
auto-post post --platform x

# ドライラン（実際には投稿しない）
auto-post post --dry-run

# 特定日付を対象
auto-post post --date 2026-01-23

# 組み合わせ
auto-post post --platform threads --dry-run
```

### トークン管理

```bash
# トークン更新
auto-post refresh-token
```

### 確認・デバッグ

```bash
# Notion接続・スキーマ確認
auto-post check-notion

# 作品一覧表示
auto-post list-works
auto-post list-works --student "生徒名"
auto-post list-works --unposted
```

### インポート系

```bash
# フォルダから直接インポート
auto-post import-direct <folder>

# サブフォルダ単位でインポート
auto-post import-folders <folder>

# グルーピングプレビュー
auto-post preview-groups <folder>

# JSON編集後インポート
auto-post export-groups <folder> output.json
auto-post import-groups output.json
```

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
| `X_API_KEY`                     | X API Key                        |
| `X_API_KEY_SECRET`              | X API Key Secret                 |
| `X_ACCESS_TOKEN`                | X Access Token                   |
| `X_ACCESS_TOKEN_SECRET`         | X Access Token Secret            |
| `R2_ACCOUNT_ID`                 | Cloudflare Account ID            |
| `R2_ACCESS_KEY_ID`              | R2 Access Key                    |
| `R2_SECRET_ACCESS_KEY`          | R2 Secret Key                    |
| `R2_BUCKET_NAME`                | バケット名                       |

### オプション

| 変数名          | 説明               | デフォルト |
| --------------- | ------------------ | ---------- |
| `R2_PUBLIC_URL` | 公開URL            | なし       |
| `DEFAULT_TAGS`  | 投稿に追加するタグ | なし       |

---

## Notion データベース構造

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

| プロパティ名    | タイプ                | 説明                             |
| --------------- | --------------------- | -------------------------------- |
| 作者            | Select                | 生徒名                           |
| 教室            | Select                | 教室名                           |
| 完成日          | Date                  | 作品完成日（キャプションに表示） |
| 投稿予定日      | Date                  | 優先投稿日                       |
| 投稿日          | Date                  | 実際の投稿日                     |
| キャプション    | Rich Text             | カスタムキャプション             |
| タグ            | Relation/Multi-select | ハッシュタグ                     |
| Instagram投稿ID | Rich Text             | 投稿後に自動記録                 |
| X投稿ID         | Rich Text             | 投稿後に自動記録                 |
| Threads投稿ID   | Rich Text             | 投稿後に自動記録                 |
| エラーログ      | Rich Text             | エラー発生時に記録               |

---

## 投稿ロジック

### 投稿対象の選定

1. **Priority 1**: `投稿予定日 = 今日` の作品
2. **Priority 2**: 予定日未設定 + 3プラットフォーム全て未投稿 の作品（完成日順）

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

{カスタムタグ}
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
- 更新不要

---

## GitHub Actions

### ワークフロー: `schedule.yml`

- **スケジュール**: 毎日 12:00 JST (03:00 UTC)
- **手動実行オプション**:
  - `date`: 対象日指定
  - `platform`: プラットフォーム選択 (all/instagram/x/threads)

### 必要な Secrets

GitHub リポジトリの Settings > Secrets に設定:

- 上記「環境変数 - 必須」の全項目

---

## ファイル構成

```
auto-post/
├── .github/workflows/schedule.yml  # GitHub Actions
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
├── pyproject.toml
├── .env                 # ローカル環境変数
└── README.md
```
