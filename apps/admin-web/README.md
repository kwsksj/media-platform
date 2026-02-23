# admin-web

先生専用のアップロード/整備UIです（Cloudflare Access 配下運用を想定）。

## Main Files

- `admin.html`: 管理UI本体
- `admin/`: 管理UI専用JS/CSS
- `shared/`: 共通UIロジック
- `scripts/`: インデックス生成、R2アップロード、smoke test、タグ再計算
- `admin-upload-ui-spec.md`: 仕様書
- `docs/CHANGELOG.md`: 管理UI仕様の変更履歴

## NPM Scripts

```bash
npm run build:admin-indexes
npm run upload:admin-indexes
npm run upload:admin-html
npm run test:upload-queue-smoke
npm run tag-recalc:dry
npm run tag-recalc:apply
```

## API Endpoints (Worker)

- `GET /admin/notion/schema`
- `GET /admin/notion/works?unprepared=1`
- `POST /admin/r2/upload`
- `POST /admin/notion/work` / `PATCH /admin/notion/work`
- `POST /admin/image/split` / `POST /admin/image/move` / `POST /admin/image/merge`
- `POST /admin/trigger-gallery-update`
- `POST /admin/notify/students-after-gallery-update`
- `POST /admin/curation/work-sync-status`
- `POST /admin/tag-recalc`

## Notes

- 秘匿情報は `apps/worker-api` 側の環境変数/secretに配置する
- `gallery.json` 更新は Worker 経由で GitHub Actions をトリガーする
