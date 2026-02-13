# Monorepo Migration Record (Historical)

この文書は、`gallery` + `auto-post` の統合計画の実施結果を残すための履歴です。

## Current Status

- canonical repository: `/Users/kawasakiseiji/development/auto-post`
- gallery module: `/Users/kawasakiseiji/development/auto-post/apps/gallery`
- split-repo (`gallery`) は legacy 扱い

## Decision Summary

- canonical は `auto-post` を採用
- 理由:
  - GitHub Actions の定期実行が既に `auto-post` で運用済み
  - 必要な repository secrets が `auto-post` に設定済み
  - GitHub Actions secret 値は API/CLI で取得できず、repo 変更時に再入力コストが高い

## Execution Summary

1. `gallery` を `apps/gallery` に取り込み
2. root 側のコマンド導線（Makefile）と統合ドキュメントを整備
3. dry-run / deploy / schedule / 手動実行 / admin upload を順次検証

## Validation Snapshot

確認済み:

- `auto-post post --dry-run`
- `auto-post export-gallery-json --no-upload --no-thumbs --no-light`
- `cd apps/gallery && npx wrangler deploy`（本番 deploy 実行）
- Daily Gallery Export（schedule）成功
- Daily Auto Post（schedule）成功
- `workflow_dispatch`（手動実行）成功
- `admin.html` からのアップロード/更新 成功

## Current Operation Rule

- 日常運用・改修は `auto-post/main` を正本として実施
- gallery 関連の変更は `apps/gallery` に集約
- split-repo 側は履歴参照・緊急比較用途に限定

## Related Docs

- `../../../MONOREPO_INTEGRATION.md`
- `../README.md`
