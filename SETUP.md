# Instagram/X/Threads 自動投稿システム セットアップ手順書

## 前提条件

- Python 3.10以上
- Instagram Business または Creator アカウント（Facebookページと連携済み）
- Threads アカウント（Instagram アカウントと連携）
- X（Twitter）アカウント
- Cloudflare アカウント
- Notion アカウント
- GitHub アカウント

---

## システム構成

```
ローカル写真 → R2（パブリック読み取り）→ Instagram / X / Threads
                    ↓
              Notion DB（管理台帳 + 画像プレビュー）
```

**Google Cloud は不要です！**

---

## Step 1: Notion データベースの作成

### 1.1 新規データベースを作成

Notion で新しいページを作成し、「データベース - フルページ」を選択。

### 1.2 プロパティを設定

以下のプロパティを追加:

| プロパティ名    | 種類              | 説明                 |
| --------------- | ----------------- | -------------------- |
| 作品名          | タイトル          | 作品の名前（必須）   |
| 画像            | ファイル&メディア | R2の画像URL          |
| 生徒名          | セレクト          | フィルタ用           |
| 投稿予定日      | 日付              | 投稿スケジュール     |
| スキップ        | チェックボックス  | 投稿をスキップ       |
| キャプション    | テキスト          | カスタムキャプション |
| タグ            | テキスト          | ハッシュタグ         |
| Instagram投稿済 | チェックボックス  | 投稿状態             |
| Instagram投稿ID | テキスト          | 投稿後のID           |
| X投稿済         | チェックボックス  | 投稿状態             |
| X投稿ID         | テキスト          | 投稿後のID           |
| Threads投稿済   | チェックボックス  | 投稿状態             |
| Threads投稿ID   | テキスト          | 投稿後のID           |
| エラーログ      | テキスト          | エラー記録           |

### 1.3 Notion Integration を作成

1. [Notion Integrations](https://www.notion.so/my-integrations) にアクセス
2. 「New integration」をクリック
3. 名前を入力（例: 「自動投稿システム」）
4. 「Submit」→ **Internal Integration Token** を控える
5. データベースページで「...」→「コネクト」→ 作成した Integration を追加

### 1.4 データベースIDを取得

データベースのURLから取得:

```
https://www.notion.so/xxxxxxxx?v=yyyyyyyy
                    ^^^^^^^^
                    これがデータベースID
```

---

## Step 2: Cloudflare R2 のセットアップ

### 2.1 バケット作成

1. [Cloudflare Dashboard](https://dash.cloudflare.com/) → R2
2. 「Create bucket」→ 名前: `woodcarving-photos`

### 2.2 パブリックアクセスを有効化

1. バケット → 「Settings」
2. 「Public access」→ 「Allow Access」
3. カスタムドメインまたは R2.dev サブドメインを設定
4. **Public URL** を控える（例: `https://pub-xxxxx.r2.dev`）

### 2.3 API Token を作成

1. R2 → 「Manage R2 API Tokens」→「Create API token」
2. 権限: **Admin Read & Write**
3. 控える:
   - **Access Key ID**
   - **Secret Access Key**
   - **Account ID**（ダッシュボード右側）

---

## Step 3: Instagram Graph API

### 3.1 Facebook Developer 設定

1. [Facebook Developers](https://developers.facebook.com/) → 「マイアプリ」→「アプリを作成」
2. アプリタイプ: 「ビジネス」
3. 「Instagram Graph API」を追加
4. 控える: **App ID**, **App Secret**

### 3.2 アクセストークン取得

1. [Graph API Explorer](https://developers.facebook.com/tools/explorer/)
2. 権限を追加: `instagram_basic`, `instagram_content_publish`
3. 「Generate Access Token」→ 短期トークンを取得

### 3.3 長期トークンに変換

```
https://graph.facebook.com/v18.0/oauth/access_token?grant_type=fb_exchange_token&client_id={APP_ID}&client_secret={APP_SECRET}&fb_exchange_token={短期トークン}
```

---

## Step 4: X (Twitter) API

1. [X Developer Portal](https://developer.twitter.com/)
2. Project & App を作成
3. 「Keys and tokens」から取得:
   - **API Key / API Key Secret**
   - **Access Token / Access Token Secret**
4. 権限を **Read and write** に設定

---

## Step 4.5: Threads API

### 4.5.1 Threads Developer 設定

1. [Meta for Developers](https://developers.facebook.com/) → Step 3 で作成したアプリを使用
2. 「Threads API」を追加
3. 控える: **App ID**, **App Secret**（Instagram と共通）

### 4.5.2 アクセストークン取得

1. [Threads API Explorer](https://developers.facebook.com/tools/explorer/) または Graph API Explorer を使用
2. 権限を追加: `threads_basic`, `threads_content_publish`
3. 「Generate Access Token」→ 短期トークンを取得

### 4.5.3 長期トークンに変換

```text
https://graph.threads.net/access_token?grant_type=th_exchange_token&client_id={APP_ID}&client_secret={APP_SECRET}&access_token={短期トークン}
```

### 4.5.4 User ID を取得

```bash
curl "https://graph.threads.net/v1.0/me?access_token={ACCESS_TOKEN}"
```

レスポンスの `id` を控える。

---

## Step 5: ローカル環境セットアップ

### 5.1 クローン & インストール

```bash
git clone https://github.com/kwsksj/auto-post.git
cd auto-post
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -e ".[dev]"
```

### 5.2 環境変数設定

```bash
cp .env.example .env
# .env を編集して認証情報を入力
```

### 5.3 接続テスト

```bash
# Notion 接続確認
auto-post check-notion

# 作品一覧表示
auto-post list-works
```

---

## Step 6: 画像のアップロードとNotionへの登録

### 6.1 R2 に画像をアップロード

Cloudflare Dashboard または rclone/aws cli で画像をアップロード:

```bash
# rclone の例
rclone copy ./photos r2:woodcarving-photos/
```

### 6.2 Notion に作品を登録

1. Notion データベースで「新規」
2. 作品名を入力
3. 「画像」プロパティに R2 の URL を追加
   - 例: `https://pub-xxxxx.r2.dev/photo1.jpg`
4. 投稿予定日を設定
5. 生徒名を選択（オプション）

**ギャラリービューを使うと画像一覧が見やすい！**

---

## Step 7: GitHub Actions 設定

### 7.1 Secrets を追加

GitHub リポジトリ → Settings → Secrets and variables → Actions

| Secret名                        | 値                              |
| ------------------------------- | ------------------------------- |
| `INSTAGRAM_APP_ID`              | Facebook App ID                 |
| `INSTAGRAM_APP_SECRET`          | Facebook App Secret             |
| `INSTAGRAM_ACCESS_TOKEN`        | 長期アクセストークン            |
| `INSTAGRAM_BUSINESS_ACCOUNT_ID` | Instagram Business Account ID   |
| `THREADS_APP_ID`                | Threads App ID（※）            |
| `THREADS_APP_SECRET`            | Threads App Secret（※）        |
| `THREADS_ACCESS_TOKEN`          | Threads 長期アクセストークン    |
| `THREADS_USER_ID`               | Threads User ID                 |
| `X_API_KEY`                     | X API Key                       |
| `X_API_KEY_SECRET`              | X API Key Secret                |
| `X_ACCESS_TOKEN`                | X Access Token                  |
| `X_ACCESS_TOKEN_SECRET`         | X Access Token Secret           |
| `R2_ACCOUNT_ID`                 | Cloudflare Account ID           |
| `R2_ACCESS_KEY_ID`              | R2 Access Key ID                |
| `R2_SECRET_ACCESS_KEY`          | R2 Secret Access Key            |
| `R2_BUCKET_NAME`                | バケット名                      |
| `R2_PUBLIC_URL`                 | パブリックURL                   |
| `NOTION_TOKEN`                  | Notion Integration Token        |
| `NOTION_DATABASE_ID`            | データベースID                  |

※ Threads App ID/Secret は Instagram と同じ Meta アプリを使用する場合、`INSTAGRAM_APP_ID`/`INSTAGRAM_APP_SECRET` と同じ値になります。

### 7.2 自動実行

- 毎日 12:00 JST に自動実行
- 手動実行: Actions → Daily Post → Run workflow

---

## CLI コマンド一覧

```bash
# 今日の投稿を実行
auto-post post

# 特定日の投稿を実行
auto-post post --date 2025-01-20

# 作品一覧表示
auto-post list-works
auto-post list-works --student "山田"
auto-post list-works --unposted

# Notion 接続確認
auto-post check-notion

# テスト投稿
auto-post test-post PAGE_ID --platform instagram

# トークン更新
auto-post refresh-token

# デバッグモード
auto-post --debug post
```

---

## Step 8: 写真のインポート（グループ化機能）

Google Takeout からエクスポートした写真を、撮影時刻に基づいて自動的に作品ごとにグループ化してインポートできます。

### 8.1 グループ化のプレビュー

まずはどのようにグループ化されるか確認:

```bash
# 10分の間隔でグループ化（デフォルト）
auto-post preview-groups ./takeout-photos

# 5分の間隔でより細かくグループ化
auto-post preview-groups ./takeout-photos --threshold 5

# 15分の間隔でより大きくグループ化
auto-post preview-groups ./takeout-photos --threshold 15
```

### 8.2 手動調整用にエクスポート

グループ化結果をJSONファイルに出力して手動編集:

```bash
auto-post export-groups ./takeout-photos grouping.json --threshold 10
```

`grouping.json` を編集して以下を調整できます:

- `work_name`: 作品名を編集
- `student_name`: 生徒名を追加
- `photos`: 写真をグループ間で移動

### 8.3 編集したグループ化ファイルからインポート

```bash
# ドライラン（確認のみ）
auto-post import-groups grouping.json --dry-run

# 実際にインポート
auto-post import-groups grouping.json --student "山田太郎" --start-date 2025-02-01

# --start-date を指定すると、グループごとに1日ずつ増加してスケジュール
```

### 8.4 直接インポート（手動調整なし）

時間がない場合は、手動調整なしで直接インポートも可能:

```bash
# ドライラン
auto-post import-direct ./takeout-photos --dry-run

# 実際にインポート
auto-post import-direct ./takeout-photos --student "山田太郎" --start-date 2025-02-01
```

### インポートコマンド一覧

```bash
# グループ化プレビュー
auto-post preview-groups FOLDER [--threshold 10] [--max-per-group 10]

# JSONにエクスポート（手動編集用）
auto-post export-groups FOLDER OUTPUT.json [--threshold 10]

# JSONからインポート
auto-post import-groups FILE.json [--student NAME] [--start-date DATE] [--dry-run]

# 直接インポート
auto-post import-direct FOLDER [--threshold 10] [--student NAME] [--start-date DATE] [--dry-run]
```

---

## 運用フロー

1. **写真撮影** → ローカルに保存
2. **R2 にアップロード** → パブリックURLを取得
3. **Notion に登録** → 作品名、画像URL、投稿予定日を設定
4. **自動投稿** → 毎日 12:00 に GitHub Actions が実行

---

## トラブルシューティング

### Notion 接続エラー

- Integration Token が正しいか確認
- データベースに Integration を接続したか確認

### 画像が表示されない

- R2 のパブリックアクセスが有効か確認
- URL が正しいか確認

### Instagram 投稿失敗

- トークンの有効期限を確認（60日で失効）
- `auto-post refresh-token` で更新
