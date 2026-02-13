# Monorepo Migration Record (Historical)

この文書は、`gallery` + `media-platform`（旧 `auto-post`）の統合計画の実施結果を残すための履歴です。

## Current Status

- canonical repository: `media-platform` (`<repo-root>`)
- gallery module (at integration time): `<repo-root>/apps/gallery`
- current layout: `<repo-root>/apps/gallery-web`, `<repo-root>/apps/admin-web`, `<repo-root>/apps/worker-api`
- GitHub repository: `kwsksj/media-platform`（rename 済み）
- local workspace path: `/Users/kawasakiseiji/development/media-platform`
- split-repo (`gallery`) は legacy 扱い

## Decision Summary

- canonical は `media-platform`（旧 `auto-post`）を採用
- 理由:
  - GitHub Actions の定期実行が既に canonical repo で運用済み
  - 必要な repository secrets が既に canonical repo に設定済み
  - GitHub Actions secret 値は API/CLI で取得できず、repo 変更時に再入力コストが高い

## Execution Summary

1. `gallery` を `apps/gallery` に取り込み
2. root 側のコマンド導線（Makefile）と統合ドキュメントを整備
3. dry-run / deploy / schedule / 手動実行 / admin upload を順次検証

## Validation Snapshot

確認済み:

- `auto-post post --dry-run`
- `auto-post export-gallery-json --no-upload --no-thumbs --no-light`
- `cd apps/worker-api && npx wrangler deploy`（本番 deploy 実行）
- Daily Gallery Export（schedule）成功
- Daily Auto Post（schedule）成功
- `workflow_dispatch`（手動実行）成功
- `admin.html` からのアップロード/更新 成功
- repo rename 後の `admin.html` ギャラリー更新トリガー成功

## Current Operation Rule

- 日常運用・改修は `media-platform/main` を正本として実施
- gallery 関連の変更は `apps/gallery-web` / `apps/admin-web` / `apps/worker-api` に責務分離して実施
- split-repo 側は履歴参照・緊急比較用途に限定

## Related Docs

- `../monorepo-integration.md`
- `../README.md`
