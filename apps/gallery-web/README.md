# gallery-web

公開ギャラリーUIです（Google Site iframe 埋め込み想定）。

## Main Files

- `gallery.html`: ギャラリーUI本体（単一HTML）
- `gallery.sample.json`: 共有用サンプルデータ
- `gallery-ui-spec.md`: UI仕様
- `scripts/upload-gallery-html.sh`: R2へ `gallery.html` をアップロード

## Upload

```bash
npm run upload:gallery-html
# or
bash ./scripts/upload-gallery-html.sh <bucket> <file>
```

`upload-gallery-html.sh` は既定で `apps/worker-api/wrangler.toml` を参照します。
