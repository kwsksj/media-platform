# Instagram/X 自動投稿システム 仕様書

## 概要

木彫り教室の生徒作品写真（Google Photos に蓄積）を、Instagram および X に自動投稿するシステム。

### 背景と目的

- 約350枚の写真が未投稿のまま蓄積
- 1作品につき複数枚（複数アングル）で撮影されている
- 作品単位でカルーセル投稿（Instagram）/ 複数画像投稿（X）したい
- 手作業での投稿は現実的でないため自動化する

---

## システム構成

```
[Phase 1: 初期処理]
Google Photos（元データ）
    ↓ Google Takeout で一括エクスポート
ローカル or Cloud Storage（一時置き場）
    ↓ EXIF撮影日時でグルーピング
Google Drive（フォルダ＝作品単位）
    ↓
スプレッドシート（管理台帳を自動生成）

[Phase 2: 定期投稿]
スプレッドシート（投稿スケジュール管理）
    ↓ 定期実行スクリプト（1日1回）
    ├→ Instagram Graph API（カルーセル投稿）
    └→ X API v2（複数画像投稿）

[Phase 3: 継続運用]
Google Drive 監視（新規フォルダ検知）
    ↓ 自動でスプレッドシートに追加
    ↓ 定期投稿フローへ
```

---

## Phase 1: 初期データ処理

### 1.1 写真のエクスポート

**手動作業**

1. Google Takeout（<https://takeout.google.com>）で対象アルバムをエクスポート
2. ZIPをダウンロード・展開

**出力**: JPEGファイル群 + メタデータJSON（Takeout形式）

### 1.2 グルーピング処理

**入力**: 展開された写真ファイル群 + Takeout付属の `.json` ファイル
**処理**:

- **撮影日時の取得**: Google Takeoutの `.json` ファイルから `photoTakenTime` を読み取る
  - GASでのEXIF解析は標準ライブラリがなく複雑なため、Takeout JSONを優先
  - JSONが欠損している場合のみ、ファイルの更新日時をフォールバックとして使用
- 撮影日時でソート
- 前の写真から N分以上間隔が空いたら別グループとみなす
- グループごとに連番フォルダを作成

**グルーピング閾値の設定**:

- 初期値: 10分（推奨範囲: 5〜15分）
- スプレッドシートの「設定」シートにセルとして保持し、後から調整可能にする
- 閾値を変えて再グルーピングしたい場合は、Phase 1を再実行

**出力**: Google Drive上のフォルダ構造

```
📁 Instagram投稿用/
    📁 001/
        🖼 photo1.jpg
        🖼 photo2.jpg
    📁 002/
        🖼 photo3.jpg
        🖼 photo4.jpg
        🖼 photo5.jpg
    ...
```

**フォルダ命名規則**: 3桁連番（001, 002, ...）

- シンプルさ優先。日時情報はスプレッドシート側で保持

**注意事項**:

- 1フォルダ内の画像順序は撮影日時順を維持
- Instagramカルーセルは最大10枚

**11枚以上の作品の扱い**:

- 自動で「作品名 (1/2)」「作品名 (2/2)」のように分割し、スプレッドシートに2行として登録
- 分割単位: 10枚ごと（11〜20枚→2行、21〜30枚→3行）
- scheduled_date は連日に自動設定（例: 1/2が1月20日なら、2/2は1月21日）
- 手動で1フォルダにまとめ直したい場合は、Drive上で10枚に絞ってから再スキャン

### 1.2.1 グルーピング修正機能

自動グルーピングは完璧ではないため、手動修正の手段を用意する。

**修正シナリオと対応方法**:

| シナリオ                         | 操作                      | システムの挙動                                                           |
| -------------------------------- | ------------------------- | ------------------------------------------------------------------------ |
| 1つの作品が2フォルダに分割された | 2つのフォルダを統合したい | 統合先フォルダに画像を移動 → 空フォルダ削除 → スプレッドシート再スキャン |
| 2つの作品が1フォルダに混在       | フォルダを分割したい      | 新規フォルダ作成 → 該当画像を移動 → スプレッドシート再スキャン           |
| 画像の順序がおかしい             | 順序を変えたい            | ファイル名をリネーム（01*, 02* 等のプレフィックス）                      |
| 不要な画像がある                 | 削除したい                | Drive上で削除 → 自動的に投稿対象外                                       |

**スプレッドシート再スキャン機能**:

- 手動実行可能なスクリプト（ボタン or メニュー）
- Driveのフォルダ構造を再スキャン
- 新規フォルダ → 行追加
- 削除されたフォルダ → 行削除（または削除フラグ）
- 既存フォルダの画像枚数変更 → image_count 更新
- 既に入力済みの caption, work_name, scheduled_date は保持

**運用上の推奨フロー**:

1. 自動グルーピング実行
2. スプレッドシートの folder_link をクリックして目視確認
3. 問題があれば Drive 上でフォルダ操作
4. 再スキャン実行
5. 確認完了後、投稿スケジュールを設定

### 1.3 スプレッドシート生成

**処理**: フォルダ構造を走査し、管理台帳を自動生成

**シート構成**:

- **メインシート**: 作品一覧（下記の列構造）
- **設定シート**: システム設定値を保持
  - グルーピング閾値（分）
  - デフォルトタグ
  - Instagram Access Token / 有効期限
  - X API認証情報
  - 通知先（メールアドレス等）

**メインシート列構造**:

| 列  | 内容              | 備考                                                   |
| --- | ----------------- | ------------------------------------------------------ |
| A   | folder_id         | Google DriveのフォルダID                               |
| B   | folder_name       | フォルダ名（001, 002, ...）※識別子のみ、意味は持たない |
| C   | folder_link       | フォルダへのハイパーリンク                             |
| D   | image_count       | フォルダ内の画像枚数                                   |
| E   | first_photo_date  | 最初の写真の撮影日時                                   |
| F   | work_name         | 作品名（ユーザーが入力）                               |
| G   | scheduled_date    | 投稿予定日（初期値: 空欄）                             |
| H   | skip              | 投稿スキップフラグ（TRUE で投稿しない）                |
| I   | caption           | 自動生成（work_name から生成、直接編集も可）           |
| J   | tags              | ハッシュタグ（デフォルト値あり、編集可）               |
| K   | instagram_posted  | Instagram投稿済フラグ                                  |
| L   | instagram_post_id | 投稿後のID（エラー追跡用）                             |
| M   | x_posted          | X投稿済フラグ                                          |
| N   | x_post_id         | 投稿後のID                                             |
| O   | error_log         | エラーログ（追記型: timestamp \| service \| message）  |

**folder_name について**:

- 連番（001, 002, ...）は単なる識別子であり、意味を持たない
- 作品の表示名・説明は全て `work_name` に集約する
- 番号が飛んでも、順序が入れ替わっても問題ない

**skip フラグについて**:

- `TRUE` にすると、scheduled_date に関係なく投稿されない
- 失敗作、ぼやけ写真、後で見返したい作品などに使用
- 空欄または `FALSE` は投稿対象

**error_log の形式**:

- 追記型（上書きしない）
- 形式: `2025-01-17 12:00 | Instagram | Container creation failed: invalid image`
- 改行区切りで複数エラーを記録可能

**キャプション生成ルール**:

- work_name が入力されている場合: `{work_name}の木彫りです！`
- work_name が空欄の場合: キャプションなし（タグのみ）
- caption 列を直接編集した場合はそちらを優先

**デフォルトタグ**:

```
#木彫り教室生徒作品 #木彫り #woodcarving #彫刻 #handcarved #woodart #ハンドメイド #手仕事
```

※ 既存運用タグ `#木彫り教室生徒作品` を筆頭に、発見性を高める一般的なタグを付与

### 1.4 投稿スケジュール設定

**処理**: scheduled_date 列に日付を自動割り当て

**ロジック**:

- 開始日を指定（例: 2025-01-20）
- 1日1投稿ペースで連番フォルダ順に割り当て
- 土日も投稿 or 平日のみ、は設定可能に

---

## Phase 2: 定期投稿処理

### 2.1 トリガー

- 毎日1回、指定時刻に実行（例: 12:00 JST）
- GASのTime-driven trigger または GitHub Actions cron

### 2.2 投稿対象の抽出

```
WHERE scheduled_date = TODAY()
  AND (skip IS NULL OR skip != TRUE)
  AND instagram_posted != TRUE
```

### 2.3 Instagram投稿処理

**Instagram Graph API カルーセル投稿フロー**:

1. **画像の一時ホスティング**:
   - Google Driveからファイルを取得（Blob）
   - Cloudflare R2 または GCS にアップロード
   - 署名付きURL（有効期限: 1時間）を生成
   - ※詳細は「補足: 画像ホスティングの設計判断」参照

2. **子コンテナ作成**: 各画像に対して

   ```
   POST /{ig-user-id}/media
   {
     "image_url": "{署名付きURL}",
     "is_carousel_item": true
   }
   ```

   → creation_id を取得

3. **カルーセルコンテナ作成**:

   ```
   POST /{ig-user-id}/media
   {
     "media_type": "CAROUSEL",
     "children": ["{creation_id_1}", "{creation_id_2}", ...],
     "caption": "{キャプション}\n{タグ}"
   }
   ```

   → carousel_creation_id を取得

4. **公開**:

   ```
   POST /{ig-user-id}/media_publish
   {
     "creation_id": "{carousel_creation_id}"
   }
   ```

**エラーハンドリング**:

- 画像URL取得失敗 → error_log に記録、スキップ
- API Rate Limit → リトライ or 翌日に延期
- 投稿失敗 → error_log に記録、instagram_posted は FALSE のまま

**重要: 非同期処理への対応**

Instagram Graph APIのメディア作成は非同期で処理される。`creation_id` 取得後、即座に次のステップに進むと失敗する。

```
1. POST /{ig-user-id}/media → creation_id 取得
2. GET /{creation_id}?fields=status_code でステータス確認
3. status_code が "FINISHED" になるまでポーリング（2〜3秒間隔、最大60秒）
4. "FINISHED" 確認後、次のステップへ
5. "ERROR" の場合は error_log に記録してスキップ
```

カルーセルの場合、子コンテナ全てが FINISHED になってからカルーセルコンテナを作成する。

### 2.4 X投稿処理

**X API v2 複数画像投稿フロー**:

1. **画像アップロード**: 各画像に対して（media upload endpoint）

   ```
   POST https://upload.twitter.com/1.1/media/upload.json
   ```

   → media_id を取得

2. **ツイート投稿**:

   ```
   POST /2/tweets
   {
     "text": "{キャプション}\n{タグ}",
     "media": {
       "media_ids": ["{media_id_1}", "{media_id_2}", ...]
     }
   }
   ```

**注意事項**:

- Xは1ツイート最大4画像
- X Free tier はレート制限がきつめ
- 5枚以上の場合の対応:
  - **Phase 1〜3（初期運用）**: 最初の4枚を代表として投稿
  - **Phase 4以降（安定後）**: スレッド化を検討
    - 1ツイート目: 画像1〜4枚目 + キャプション + タグ
    - 2ツイート目（リプライ）: 画像5〜8枚目
    - 3ツイート目（リプライ）: 画像9〜10枚目
  - スレッド化は連続APIコールが必要でレート制限に引っかかりやすいため、運用安定後に実装

### 2.5 投稿後処理

- スプレッドシートの posted フラグを TRUE に更新
- post_id を記録
- エラーがあれば error_log に記録

**エラー通知（推奨）**:

- error_log への書き込みと同時に、外部通知を送信
- 通知手段の候補:
  - **メール**: GASの `MailApp.sendEmail()` で自分宛に送信（最もシンプル）
  - **LINE Notify**: 無料でLINEに通知可能
  - **Slack Webhook**: 業務用途向け
- 通知すべきイベント:
  - 投稿失敗（API エラー）
  - トークン更新失敗（緊急度高）
  - 予期せぬ例外

---

## Phase 3: 継続運用

### 3.1 新規作品の追加フロー

**想定運用**:

1. 教室で作品を撮影
2. 写真を Google Drive の「Instagram投稿用」フォルダ内に新規フォルダとして追加
3. システムが新規フォルダを検知

### 3.2 新規フォルダ検知

**方式A: 定期スキャン（シンプル）**

- 1日1回、フォルダ構造をスキャン
- スプレッドシートに存在しない folder_id を検知
- 新規行として追加、scheduled_date は「最後の予定日 + 1日」を自動設定

**方式B: Google Drive Push通知（リアルタイム）**

- Drive API の変更通知を受信
- 新規フォルダ作成を即時検知
- より複雑だが、即座にスプレッドシート反映される

**推奨**: 1日1投稿ペースなら方式Aで十分

### 3.3 キャプション入力（オプション）

- スプレッドシートを開き、caption 列に直接入力
- 空欄の場合はタグのみで投稿
- 投稿前日までに入力すれば反映される

---

## 投稿先アカウント

### Instagram

- URL: <https://www.instagram.com/kibori_class/>
- Instagram Business Account ID: `17841422021372550`
- アカウント種別: プロアカウント（確認済み）

### X (Twitter)

- URL: <https://x.com/kibori_class>

### Meta ビジネス構成（API連携用）

```
ビジネスポートフォリオ: Seiji Kawasaki
    ビジネスポートフォリオID: 2389558487727608
    │
    ├── Facebookページ: 川崎 誠二 木彫り教室
    │   ページID: 937676102768175
    │
    └── Instagram: @kibori_class
        Instagram Business Account ID: 17841422021372550
```

---

## API認証情報

### Instagram Graph API

**必要なもの**:

- Facebook Developer アカウント
- Facebook ページ（Instagram Businessアカウントと連携済み）
- Instagram Business または Creator アカウント
- アプリ作成 + instagram_basic, instagram_content_publish 権限

**取得する認証情報**:

- App ID
- App Secret
- Long-lived Access Token（60日有効）
- Instagram Business Account ID

**重要: トークン自動更新の実装**

Long-lived Access Token は60日で失効する。これを忘れると「ある日突然投稿が止まる」。

```
実装方針:
1. トークンの有効期限をスプレッドシートの「設定」シートに記録
2. 毎日の投稿処理時に残り日数をチェック
3. 残り15日を切ったら自動更新APIを呼び出し
   GET /oauth/access_token
     ?grant_type=fb_exchange_token
     &client_id={app-id}
     &client_secret={app-secret}
     &fb_exchange_token={current-token}
4. 新しいトークンと有効期限をスプレッドシートに保存
5. 更新失敗時はエラー通知（後述）
```

この処理は Phase 2（定期投稿機能）に含める。

### X API v2

**必要なもの**:

- X Developer アカウント（Free tier で可）
- Project & App 作成

**取得する認証情報**:

- API Key
- API Key Secret
- Access Token
- Access Token Secret

---

## 技術選定

### 推奨構成: Google Apps Script（初期）

**理由**:

- Google Drive / スプレッドシートとの連携がネイティブ
- 定期実行トリガーが組み込み
- サーバー不要
- 初期構築が速い

**懸念点と対策**:

| 制約                         | 対策                                                |
| ---------------------------- | --------------------------------------------------- |
| 実行時間制限（6分）          | 1日1投稿なら問題なし。大量処理は分割実行            |
| メモリ制限（約100MB）        | 画像は1枚ずつ処理し、都度メモリ解放                 |
| R2へのS3署名（V4 Signature） | 既存ライブラリ（S3-for-Google-Apps-Script等）を活用 |
| EXIF解析ライブラリなし       | Takeout付属の.jsonファイルから撮影日時を取得        |

### 将来の移行先候補: Python + GitHub Actions

運用が安定し、以下のような要求が出てきた場合に検討：

- より複雑なリトライ制御
- 画像の前処理（リサイズ、圧縮等）
- 複数アカウント対応

**現時点では GAS で開始し、壊れたら移行を検討** という方針で問題ない。

### 代替構成: Python + GitHub Actions（参考）

**利点**:

- 処理の自由度が高い
- Claude Code との相性が良い
- ライブラリが豊富

**構成**:

- GitHub リポジトリにスクリプト配置
- GitHub Actions で毎日定時実行
- 認証情報は GitHub Secrets に保存
- スプレッドシート連携は Google Sheets API 経由

---

## 実装フェーズ

### Step 1: 初期セットアップ

1. Google Takeout でエクスポート
2. グルーピングスクリプト作成・実行
3. スプレッドシート生成

### Step 2: Instagram投稿機能

1. Instagram Graph API 認証設定
2. カルーセル投稿スクリプト作成
3. テスト投稿（1件）
4. 定期実行設定

### Step 3: X投稿機能

1. X API 認証設定
2. 複数画像投稿スクリプト作成
3. テスト投稿
4. Instagram処理に統合

### Step 4: 継続運用機能

1. 新規フォルダ検知スクリプト
2. 運用テスト

---

## 未決定事項（実装時に確認）

1. **投稿時刻**: 何時に投稿するか（エンゲージメント観点で昼12時 or 夜20時頃が一般的）
2. **エラー通知の手段**: メール / LINE Notify / Slack のいずれを使うか
3. **グルーピング閾値の初期値**: 10分で開始し、運用しながら調整（設定シートで変更可能）

---

## 補足: 画像ホスティングの設計判断

### Google Drive 直リンクは使用しない（重要）

~~Google Drive の直接リンク（`https://drive.google.com/uc?export=view&id=XXX`）~~

Instagram Graph API は、リダイレクト・Cookie・Range ヘッダを含むURLを拒否する傾向が強い。Google Driveの共有リンクはこれに該当し、**たまに通る→ある日突然全滅**という不安定な挙動になる。

### 原則: 外部ストレージ経由で投稿

```
Google Drive（マスターデータ）
    ↓ 投稿時に一時転送
Cloudflare R2 / Google Cloud Storage（一時ホスティング）
    ↓ 署名付きURL生成
Instagram API に渡す
    ↓ 投稿完了後
一時ファイル削除（任意）
```

**推奨: Cloudflare R2**

- 無料枠: 10GB ストレージ、月100万リクエスト
- S3互換APIで扱いやすい
- 署名付きURLで一時公開可能

**代替: Google Cloud Storage**

- GCPアカウントがあれば統一管理できる
- 無料枠は小さいが、この用途なら十分

### 実装フロー（投稿処理時）

1. Drive から画像を取得（Blob）
2. R2 / GCS にアップロード
3. 署名付きURL（有効期限: 1時間程度）を生成
4. Instagram API にURLを渡す
5. 投稿完了後、一時ファイルを削除（または放置して自動期限切れ）

X API は画像を直接アップロードできるため、この問題は発生しない。

---

## 仕様変更履歴

### 2025-01 実装時の変更

#### 1. 技術選定: GAS → Python + GitHub Actions

**変更理由:**

- R2へのS3署名（AWS Signature V4）をGASで自前実装するのは複雑でエラーが起きやすい
- X API の OAuth 1.0a 認証も同様に複雑
- Pythonなら boto3（R2）、tweepy（X）など成熟したライブラリが使える
- デバッグ・テストがAIの支援を受けやすい

**実装構成:**

```
src/auto_post/
├── config.py        # 設定管理
├── notion_db.py     # Notion連携
├── r2_storage.py    # R2ストレージ
├── instagram.py     # Instagram API
├── x_twitter.py     # X API
├── poster.py        # 投稿オーケストレーター
└── cli.py           # CLIインターフェース

.github/workflows/
└── daily-post.yml   # 毎日定時実行
```

#### 2. データ管理: Google スプレッドシート → Notion

**変更理由:**

- Google Sheets を使うと Google Cloud の設定（サービスアカウント、API有効化）が必要
- Notion なら API キー1つで完結
- 画像プレビューが見やすい
- 手動での調整がしやすい

**Notion データベース構成:**

| プロパティ      | 型       | 説明                  |
| --------------- | -------- | --------------------- |
| 作品名          | Title    | 作品の名前            |
| 生徒名          | Select   | 生徒の名前            |
| 画像            | Files    | R2にアップした画像URL |
| 投稿予定日      | Date     | 投稿スケジュール      |
| スキップ        | Checkbox | 投稿しない場合 TRUE   |
| キャプション    | Text     | カスタムキャプション  |
| タグ            | Text     | ハッシュタグ          |
| Instagram投稿済 | Checkbox | 投稿完了フラグ        |
| Instagram投稿ID | Text     | 投稿ID                |
| X投稿済         | Checkbox | 投稿完了フラグ        |
| X投稿ID         | Text     | 投稿ID                |
| エラーログ      | Text     | エラー記録            |

#### 3. 写真のグルーピング: タイムスタンプ自動 → フォルダベース手動

**変更理由:**

- タイムスタンプによる自動グルーピングは、実際の画像を見ないと正しさが判断できない
- JSONファイルを編集して調整するのは非現実的
- Finder/エクスプローラーで画像を見ながらフォルダ分けする方が確実

**新しいワークフロー:**

1. Google Takeout で写真をエクスポート
2. **手動でフォルダ分け** - 画像を見ながら作品ごとにフォルダに整理
3. `import-folders` コマンドでインポート（フォルダ名 = 作品名）
4. Notionで画像プレビューを見ながら微調整
5. 11枚以上の作品は投稿時に自動分割

**フォルダ構造:**

```
photos/
├── 熊の置物/
│   ├── photo1.jpg
│   └── photo2.jpg
├── フクロウのレリーフ/
│   └── photo3.jpg
└── 猫の彫刻/
    ├── photo4.jpg
    └── ... (15枚) → 投稿時に自動で2回に分割
```

**Note:** フォルダベースのインポート機能は別セッションで実装予定

#### 4. 画像ストレージ

R2 の使い方は当初仕様通り。ただし以下を追加:

- `R2_PUBLIC_URL` 環境変数で公開URLを設定可能
- Notion の画像プレビューに公開URLを使用
