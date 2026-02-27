#!/usr/bin/env python3
"""
孤立R2画像（Notionに紐づいていない画像）をNotionページに紐づけるスクリプト

前回のバックフィルでR2にアップロードされたが、Notion連携が
無効になっていたために「孤立」状態になってしまった画像を対象に、
ローカルのフォルダ構造と照らし合わせてNotionページを作成・更新します。

使い方:
  # dry-run（確認のみ）
  python scripts/link_orphaned_images.py /path/to/WorksPhotes

  # 実行
  python scripts/link_orphaned_images.py /path/to/WorksPhotes --execute
"""

import argparse
import logging
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

# プロジェクトルートをパスに追加
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from auto_post.config import Config  # noqa: E402
from auto_post.grouping import IMAGE_EXTENSIONS, get_photo_metadata  # noqa: E402
from auto_post.notion_db import NotionDB  # noqa: E402
from auto_post.r2_storage import R2Storage  # noqa: E402
from auto_post.schedule_lookup import ScheduleLookup  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

KNOWN_R2_PREFIXES = (
    "photos/",
    "photos-light/",
    "images/",
    "images-light/",
    "uploads/",
    "uploads-light/",
)


def _extract_original_filename(r2_key: str) -> str:
    """R2キーからオリジナルファイル名を抽出する。"""
    basename = r2_key.split("/")[-1]
    match = re.match(r"^\d{14}_(.+)$", basename)
    if match:
        return match.group(1)
    return basename


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
    public_url = (public_url or "").rstrip("/")
    if public_url and url.startswith(f"{public_url}/"):
        key = url[len(public_url) :].lstrip("/")
        return unquote(key) if key else None
    parsed = urlparse(url)
    path = unquote(parsed.path.lstrip("/"))
    if path.startswith(KNOWN_R2_PREFIXES):
        return path
    return None


def _list_r2_keys_with_prefix(r2: R2Storage, prefix: str) -> list[str]:
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
        for obj in response.get("Contents", []):
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
    all_keys: set[str] = set()
    for prefix in prefixes:
        all_keys.update(_list_r2_keys_with_prefix(r2, prefix=prefix))
    return all_keys


def main():
    parser = argparse.ArgumentParser(description="孤立R2画像をNotionに連携")
    parser.add_argument("folder", type=Path, help="ローカルの WorksPhotes フォルダのパス")
    parser.add_argument("--execute", action="store_true", help="実際にNotion連携を実行")
    parser.add_argument("--env-file", type=Path, default=ROOT_DIR / ".env")
    args = parser.parse_args()

    dry_run = not args.execute
    root_folder = args.folder

    if not root_folder.exists():
        print(f"❌ フォルダが見つかりません: {root_folder}")
        return

    print("=" * 60)
    if dry_run:
        print("🔍 DRY-RUN モード (Notion更新は実行されません)")
    else:
        print("⚠️  EXECUTE モード (実際にNotion連携を実行します)")
        confirm = input("本当に実行しますか？ (yes/no): ")
        if confirm.strip().lower() != "yes":
            print("キャンセルしました。")
            return
    print("=" * 60)

    config = Config.load(env_file=args.env_file, allow_missing_instagram=True)
    notion = NotionDB(
        config.notion.token,
        config.notion.database_id,
        config.notion.tags_database_id,
    )
    r2 = R2Storage(config.r2)
    public_url = config.r2.public_url or ""

    try:
        schedule_lookup = ScheduleLookup(config)
    except Exception as e:
        logger.warning(f"Could not initialize ScheduleLookup: {e}")
        schedule_lookup = None

    # ------------------------------------------------
    # Step 1: ローカル画像ファイル名 -> 所属フォルダ名のマップ作成
    # ------------------------------------------------
    print(f"\n📁 ローカルフォルダをスキャン中: {root_folder}")
    local_file_candidates: dict[str, list[Path]] = {}

    for path in root_folder.rglob("*"):
        if path.suffix.lower() in IMAGE_EXTENSIONS and not path.name.startswith("."):
            local_file_candidates.setdefault(path.name, []).append(path)

    local_count = sum(len(paths) for paths in local_file_candidates.values())
    print(f"  ローカル画像数: {local_count}")

    # ------------------------------------------------
    # Step 2: Notion全ページから参照されているR2キーを取得
    # ------------------------------------------------
    print("\n📋 Notionデータベースから全ページを取得中...")
    all_pages = notion.list_database_pages(notion.database_id)
    notion_r2_keys = set()

    for page in all_pages:
        if page.get("archived"):
            continue
        for url in _get_page_image_urls(page):
            key = _url_to_r2_key(url, public_url)
            if key:
                notion_r2_keys.add(key)

    print(f"  Notionから参照されている画像数: {len(notion_r2_keys)}")

    # ------------------------------------------------
    # Step 3: R2全オブジェクトリストから「孤立キー」を特定
    # ------------------------------------------------
    print("\n📦 R2バケットから全オブジェクトキーを取得中...")
    all_r2_keys = _list_all_r2_keys(r2)
    joined_prefixes = ", ".join(KNOWN_R2_PREFIXES)
    orphaned_r2_keys = all_r2_keys - notion_r2_keys

    print(f"  対象prefix: {joined_prefixes}")
    print(f"  R2全体: {len(all_r2_keys)}")
    print(f"  孤立画像: {len(orphaned_r2_keys)} 件")

    if not orphaned_r2_keys:
        print("\n✅ 孤立した画像はありません。処理を終了します。")
        return

    # ------------------------------------------------
    # Step 4: 孤立キーを所属フォルダでグループ化
    # ------------------------------------------------
    # folder_name -> {"urls": [...], "paths": [...]}
    link_plan: dict[str, dict[str, list]] = {}
    unmatched_keys = []

    for key in orphaned_r2_keys:
        fname = _extract_original_filename(key)
        candidates = local_file_candidates.get(fname, [])
        if not candidates:
            unmatched_keys.append(key)
            continue

        if len(candidates) > 1:
            candidates = sorted(candidates)
            logger.warning(
                "Multiple local matches for %s; using %s",
                fname,
                candidates[0],
            )
        matched_path = candidates[0]
        folder_name = matched_path.parent.name

        if folder_name not in link_plan:
            link_plan[folder_name] = {"urls": [], "paths": []}

        url = f"{public_url}/{key}" if public_url else key
        link_plan[folder_name]["urls"].append(url)
        link_plan[folder_name]["paths"].append(matched_path)

    print("\n" + "=" * 60)
    print("📊 連携計画サマリー")
    print("=" * 60)
    print(f"  連携可能フォルダ数: {len(link_plan)}")
    print(f"  ローカルに存在せず判別不能な画像: {len(unmatched_keys)} 件")

    for folder_name, data in link_plan.items():
        urls = data["urls"]
        print(f"\n  📂 {folder_name} ({len(urls)}枚)")
        for url in urls[:3]:
            print(f"    + {url}")
        if len(urls) > 3:
            print(f"    ... 他 {len(urls) - 3} 件")

    if not link_plan:
        print("\n✅ 連携可能な画像はありません。")
        return

    # ------------------------------------------------
    # Step 5: 実行 (Notion連携)
    # ------------------------------------------------
    if dry_run:
        print("\n" + "=" * 60)
        print("🔍 DRY-RUN完了。実際にNotionへ連携するには --execute を付与してください。")
        print("=" * 60)
        return

    print("\n⏳ Notion連携を実行中...")
    notion_created = 0
    notion_updated = 0
    errors = 0

    for folder_name, data in link_plan.items():
        new_urls = data["urls"]
        local_paths = data["paths"]
        print(f"\n  📂 {folder_name} の処理中...")

        # フォルダ内の画像の最古のタイムスタンプを代表日時とする
        folder_timestamp = None
        for path in local_paths:
            ts, _, _ = get_photo_metadata(path)
            if ts:
                if folder_timestamp is None or ts < folder_timestamp:
                    folder_timestamp = ts
        try:
            page_id = notion.find_page_by_title(folder_name)
            if page_id:
                # 既存ページに追記
                page = notion.client.pages.retrieve(page_id)
                files_prop = page.get("properties", {}).get("画像", {})
                existing_files = files_prop.get("files", [])

                files_payload = existing_files.copy()
                for i, url in enumerate(new_urls):
                    files_payload.append(
                        {
                            "type": "external",
                            "name": f"image_{len(existing_files) + i + 1}",
                            "external": {"url": url},
                        }
                    )

                notion.client.pages.update(
                    page_id=page_id, properties={"画像": {"files": files_payload}}
                )
                notion_updated += 1
                logger.info(
                    "Updated existing Notion page: %s (+%s images)",
                    folder_name,
                    len(new_urls),
                )

            else:
                # 新規ページ作成
                classroom = None
                if schedule_lookup and folder_timestamp:
                    classroom = schedule_lookup.lookup_classroom(folder_timestamp)

                notion.add_work(
                    work_name=folder_name,
                    image_urls=new_urls,
                    creation_date=folder_timestamp,
                    classroom=classroom,
                )
                notion_created += 1
                logger.info(
                    "Created new Notion page: %s (%s images, Date: %s)",
                    folder_name,
                    len(new_urls),
                    folder_timestamp,
                )

        except Exception as e:
            errors += 1
            logger.error(f"Failed to link Notion page for {folder_name}: {e}")

    print("\n" + "=" * 60)
    print("🎉 連携完了")
    print("=" * 60)
    print(f"  Notion新規作成: {notion_created} ページ")
    print(f"  Notionページ更新: {notion_updated} ページ")
    print(f"  エラー: {errors} 件")


if __name__ == "__main__":
    main()
