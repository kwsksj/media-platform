# Monorepo Integration & Migration Record

## Current Status

`media-platform` は統合済みで、責務単位の構成へ整理されています。

```text
apps/gallery-web
apps/admin-web
apps/worker-api
tools/ingest
tools/publish
tools/gallery-build
docs
```

## Migration Outcome (Completed)

- `/apps/gallery-web` に公開ギャラリーUIを分離
- `/apps/admin-web` に管理UI（`admin/shared/scripts`）を分離
- `/apps/worker-api` に Worker API と `wrangler.toml` を分離
- `/tools/ingest`, `/tools/publish`, `/tools/gallery-build` を運用入口として整備
- `/docs` に構成・運用手順を集約
- `Makefile` / ドキュメント / 補助スクリプトの参照を新構成へ切替

## Why This Repository Remains Canonical

- GitHub Actions の定期実行が稼働済み
- repository secrets が揃っている
- GitHub API/CLI から secret の値は取得できないため、正本の移動コストが高い

## Secrets Handling Rules

- secret 値を terminal/log に出力しない
- `.env` や認証情報を commit しない
- 他repoへ移す場合はローカルの正本（`.env` / password manager / provider dashboard）から再設定する

## Validation Commands

```bash
# 構成チェック
make check-monorepo

# auto-post CLI dry-run
make publish-dry

# catch-up dry-run
make publish-catchup-dry

# gallery export dry-run (no R2 upload)
make gallery-export

# tag recalc dry-run
make gallery-tag-recalc-dry

# worker deploy dry-run
make worker-dry
```

## Legacy Record

- 旧統合作業の履歴: `docs/history/monorepo-migration-plan.md`
