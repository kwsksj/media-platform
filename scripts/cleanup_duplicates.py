#!/usr/bin/env python3
"""
重複インポートされたデータのクリーンアップスクリプト

WorksPhotesフォルダから多重取り込みされた以下を削除する:
1. 整備済=OFF の Notion ページ → アーカイブ + 紐づくR2画像を削除
2. Notionページに紐づかない孤立R2画像 → （オプションで）削除

ギャラリーに反映済み（整備済=ON）のアイテムは一切触れない。
未整理アップロード画像がある運用を考慮し、孤立R2画像の削除はデフォルト無効。

使い方:
  # dry-run（確認のみ）
  python scripts/cleanup_duplicates.py

  # 孤立R2画像も削除対象に含める（明示指定）
  python scripts/cleanup_duplicates.py --delete-orphaned-r2

  # 実行
  python scripts/cleanup_duplicates.py --execute
"""

import argparse
import logging
import sys
from pathlib import Path
from urllib.parse import urlparse

# プロジェクトルートをパスに追加
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from auto_post.config import Config  # noqa: E402
from auto_post.notion_db import NotionDB  # noqa: E402
from auto_post.r2_storage import R2Storage  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
# Reduce noise from libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ---------- 整備済プロパティ名候補 ----------
READY_PROP_CANDIDATES = ("整備済み", "整備済")
KNOWN_R2_PREFIXES = (
    "photos/",
    "photos-light/",
    "images/",
    "images-light/",
    "uploads/",
    "uploads-light/",
)


def _resolve_ready_prop(db_info: dict) -> str:
    """データベーススキーマから整備済プロパティ名を解決する。"""
    props = db_info.get("properties", {})
    for name in READY_PROP_CANDIDATES:
        schema = props.get(name)
        if isinstance(schema, dict) and schema.get("type") in {"checkbox", "formula"}:
            return name
    # フォールバック: checkbox/formula で「整備」を含むプロパティ
    for name, schema in props.items():
        if not isinstance(schema, dict):
            continue
        if schema.get("type") not in {"checkbox", "formula"}:
            continue
        if "整備" in str(name).lower() or "ready" in str(name).lower():
            return name
    raise ValueError("整備済プロパティが見つかりません。")


def _is_page_ready(page: dict, ready_prop: str) -> bool:
    """ページが整備済かどうか判定する。"""
    prop = page.get("properties", {}).get(ready_prop, {})
    prop_type = prop.get("type")
    if prop_type == "checkbox":
        return bool(prop.get("checkbox"))
    if prop_type == "formula":
        formula = prop.get("formula") or {}
        if formula.get("type") == "boolean":
            return bool(formula.get("boolean"))
    return False


def _get_page_title(page: dict) -> str:
    """ページの作品名を取得する。"""
    title_prop = page.get("properties", {}).get("作品名", {})
    titles = title_prop.get("title", [])
    if titles:
        return titles[0].get("plain_text", "(無題)")
    return "(無題)"


def _get_page_image_urls(page: dict) -> list[str]:
    """ページから画像URLを抽出する。"""
    files_prop = page.get("properties", {}).get("画像", {})
    files = files_prop.get("files", [])
    urls = []
    for f in files:
        if f.get("type") == "external":
            url = f.get("external", {}).get("url", "")
            if url:
                urls.append(url)
        elif f.get("type") == "file":
            url = f.get("file", {}).get("url", "")
            if url:
                urls.append(url)
    return urls


def _url_to_r2_key(url: str, public_url: str) -> str | None:
    """画像URLからR2キーを抽出する。"""
    if not url:
        return None
    # https://pub-xxx.r2.dev/photos/xxx_yyy.jpg -> photos/xxx_yyy.jpg
    if public_url and url.startswith(public_url):
        key = url[len(public_url) :].lstrip("/")
        return key if key else None
    # URLパースでパスだけ取る
    parsed = urlparse(url)
    path = parsed.path.lstrip("/")
    if path.startswith(KNOWN_R2_PREFIXES):
        return path
    return None


def _list_r2_keys_with_prefix(r2: R2Storage, prefix: str) -> list[str]:
    """指定prefix配下のR2オブジェクトキーをリストする。"""
    keys: list[str] = []
    client = r2._create_client()
    continuation_token = None

    while True:
        kwargs = {
            "Bucket": r2.config.bucket_name,
            "Prefix": prefix,
            "MaxKeys": 1000,
        }
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token

        response = client.list_objects_v2(**kwargs)
        contents = response.get("Contents", [])
        for obj in contents:
            key = obj.get("Key", "")
            if key:
                keys.append(key)

        if response.get("IsTruncated"):
            continuation_token = response.get("NextContinuationToken")
        else:
            break

    return keys


def _list_all_r2_keys(
    r2: R2Storage,
    prefixes: tuple[str, ...] = KNOWN_R2_PREFIXES,
) -> set[str]:
    """R2バケット内の既知画像prefix配下オブジェクトキーをリストする。"""
    all_keys: set[str] = set()
    for prefix in prefixes:
        all_keys.update(_list_r2_keys_with_prefix(r2, prefix=prefix))
    return all_keys


def main():
    parser = argparse.ArgumentParser(description="重複インポートデータのクリーンアップ")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="実際に削除を実行する (指定しない場合はdry-run)",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=ROOT_DIR / ".env",
        help=".envファイルのパス",
    )
    parser.add_argument(
        "--delete-orphaned-r2",
        action="store_true",
        help="Notionに未紐づけの孤立R2画像も削除対象に含める（デフォルト: 含めない）",
    )
    args = parser.parse_args()

    dry_run = not args.execute
    delete_orphaned_r2 = bool(args.delete_orphaned_r2)

    if dry_run:
        print("=" * 60)
        print("🔍 DRY-RUN モード (削除は実行されません)")
        print("=" * 60)
    else:
        print("=" * 60)
        print("⚠️  EXECUTE モード (実際にデータを削除します)")
        print("=" * 60)
        confirm = input("本当に実行しますか？ (yes/no): ")
        if confirm.strip().lower() != "yes":
            print("キャンセルしました。")
            return

    # 設定読み込み
    config = Config.load(env_file=args.env_file, allow_missing_instagram=True)
    notion = NotionDB(
        config.notion.token,
        config.notion.database_id,
        config.notion.tags_database_id,
    )
    r2 = R2Storage(config.r2)
    public_url = config.r2.public_url or ""

    # ------------------------------------------------
    # Step 1: Notion 全ページ取得
    # ------------------------------------------------
    print("\n📋 Notionデータベースから全ページを取得中...")
    db_info = notion.get_database_info()
    ready_prop = _resolve_ready_prop(db_info)
    print(f"  整備済プロパティ: {ready_prop}")

    all_pages = notion.list_database_pages(notion.database_id)
    print(f"  総ページ数: {len(all_pages)}")

    # 分類
    ready_pages = []
    not_ready_pages = []
    notion_r2_keys_all = set()  # 全ページから参照されているR2キー
    notion_r2_keys_ready = set()  # 整備済ページから参照されているR2キー

    for page in all_pages:
        is_ready = _is_page_ready(page, ready_prop)
        image_urls = _get_page_image_urls(page)
        r2_keys = set()
        for url in image_urls:
            key = _url_to_r2_key(url, public_url)
            if key:
                r2_keys.add(key)

        notion_r2_keys_all.update(r2_keys)

        if is_ready:
            ready_pages.append(page)
            notion_r2_keys_ready.update(r2_keys)
        else:
            not_ready_pages.append(page)

    print(f"  整備済: {len(ready_pages)} 件 (保持)")
    print(f"  未整備: {len(not_ready_pages)} 件 (削除候補)")

    # ------------------------------------------------
    # Step 2: R2 全オブジェクト取得
    # ------------------------------------------------
    print("\n📦 R2バケットから全オブジェクトキーを取得中...")
    all_r2_keys = _list_all_r2_keys(r2)
    joined_prefixes = ", ".join(KNOWN_R2_PREFIXES)
    print(f"  R2対象prefix: {joined_prefixes}")
    print(f"  R2対象オブジェクト総数: {len(all_r2_keys)}")

    # 孤立R2キー = R2にあるが、Notionのどのページからも参照されていないもの
    orphaned_r2_keys = all_r2_keys - notion_r2_keys_all
    print(f"  Notionから参照されていない孤立画像: {len(orphaned_r2_keys)} 件")

    # 未整備ページのR2キー（整備済ページからも参照されているものは除外）
    not_ready_r2_keys = set()
    for page in not_ready_pages:
        image_urls = _get_page_image_urls(page)
        for url in image_urls:
            key = _url_to_r2_key(url, public_url)
            if key and key not in notion_r2_keys_ready:
                not_ready_r2_keys.add(key)

    # ------------------------------------------------
    # Step 3: 削除対象のサマリー
    # ------------------------------------------------
    # 削除対象R2キー
    # - default: 未整備ページ由来のみ
    # - --delete-orphaned-r2 指定時: 孤立キーも含める
    r2_keys_to_delete = set(not_ready_r2_keys)
    if delete_orphaned_r2:
        r2_keys_to_delete.update(orphaned_r2_keys)
    notion_pages_to_archive = not_ready_pages

    print("\n" + "=" * 60)
    print("📊 クリーンアップ対象サマリー")
    print("=" * 60)
    print(f"\n🗂  Notionページ アーカイブ対象: {len(notion_pages_to_archive)} 件")
    for page in notion_pages_to_archive:
        title = _get_page_title(page)
        page_id = page["id"]
        image_urls = _get_page_image_urls(page)
        print(f"  - [{page_id[:8]}...] {title} (画像: {len(image_urls)}枚)")

    print(f"\n🖼  R2画像 削除対象: {len(r2_keys_to_delete)} 件")
    print("    内訳:")
    if delete_orphaned_r2:
        print(f"      孤立画像 (Notionページなし): {len(orphaned_r2_keys)} 件")
    else:
        print(f"      孤立画像 (Notionページなし): {len(orphaned_r2_keys)} 件（今回は削除対象外）")
    print(f"      未整備ページの画像: {len(not_ready_r2_keys)} 件")

    if len(r2_keys_to_delete) <= 50:
        for key in sorted(r2_keys_to_delete):
            tag = "孤立" if key in orphaned_r2_keys else "未整備"
            print(f"    - [{tag}] {key}")
    else:
        print("    (件数が多いため先頭20件を表示)")
        for key in sorted(r2_keys_to_delete)[:20]:
            tag = "孤立" if key in orphaned_r2_keys else "未整備"
            print(f"    - [{tag}] {key}")
        print(f"    ... 他 {len(r2_keys_to_delete) - 20} 件")

    print(f"\n✅ 保持: 整備済 {len(ready_pages)} 件のNotionページと紐づくR2画像")

    # ------------------------------------------------
    # Step 4: 実行
    # ------------------------------------------------
    if dry_run:
        print("\n" + "=" * 60)
        print(
            "🔍 DRY-RUN 完了。実際に削除するには --execute オプションを付けて再実行してください。"
        )
        if not delete_orphaned_r2 and orphaned_r2_keys:
            print("   孤立R2画像も削除したい場合は --delete-orphaned-r2 を追加してください。")
        print("   python scripts/cleanup_duplicates.py --execute")
        print("=" * 60)
        return

    # 実行モード
    print("\n⏳ クリーンアップを実行中...")

    # 4a: Notion ページをアーカイブ
    archived_count = 0
    archive_errors = 0
    for page in notion_pages_to_archive:
        page_id = page["id"]
        title = _get_page_title(page)
        try:
            notion.client.pages.update(page_id=page_id, archived=True)
            archived_count += 1
            logger.info(f"Archived Notion page: {title} ({page_id})")
        except Exception as e:
            archive_errors += 1
            logger.error(f"Failed to archive {title} ({page_id}): {e}")

    # 4b: R2 画像を削除
    deleted_count = 0
    delete_errors = 0
    r2_keys_list = sorted(r2_keys_to_delete)
    # バッチ削除（1000件ずつ）
    batch_size = 100
    for i in range(0, len(r2_keys_list), batch_size):
        batch = r2_keys_list[i : i + batch_size]
        for key in batch:
            try:
                r2.delete(key)
                deleted_count += 1
            except Exception as e:
                delete_errors += 1
                logger.error(f"Failed to delete R2 key {key}: {e}")

    # ------------------------------------------------
    # 結果サマリー
    # ------------------------------------------------
    print("\n" + "=" * 60)
    print("🎉 クリーンアップ完了")
    print("=" * 60)
    print(f"  Notionページ アーカイブ: {archived_count} 件 (エラー: {archive_errors})")
    print(f"  R2画像 削除: {deleted_count} 件 (エラー: {delete_errors})")
    print(f"  保持: 整備済 {len(ready_pages)} 件")


if __name__ == "__main__":
    main()
