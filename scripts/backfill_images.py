#!/usr/bin/env python3
"""
欠け画像バックフィルスクリプト（R2ファイル名突合方式）

ローカルフォルダの画像ファイル名と、R2上の既存ファイル名を比較し、
R2にまだアップロードされていない画像をアップロードする。
その後、画像が先生用UI（Notion）に表示されるよう、ローカルの親フォルダ名を
タイトルとしたNotionページを作成（または既存ページを更新）して紐づける。

使い方:
  # dry-run（確認のみ）
  python scripts/backfill_images.py /path/to/WorksPhotes

  # 実行
  python scripts/backfill_images.py /path/to/WorksPhotes --execute
"""

import argparse
import logging
import mimetypes
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from auto_post.config import Config
from auto_post.grouping import IMAGE_EXTENSIONS, get_photo_metadata
from auto_post.notion_db import NotionDB
from auto_post.r2_storage import R2Storage
from auto_post.schedule_lookup import ScheduleLookup

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


def _extract_original_filename(r2_key: str) -> str:
    """R2キーからオリジナルファイル名を抽出する。
    R2キー形式: photos/{timestamp14}_{filename}
    """
    basename = r2_key.split("/")[-1]
    match = re.match(r"^\d{14}_(.+)$", basename)
    if match:
        return match.group(1)
    return basename


def _list_all_r2_keys(r2: R2Storage, prefix: str = "photos/") -> list[str]:
    """R2バケット内の全オブジェクトキーをリストする。"""
    keys = []
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


def main():
    parser = argparse.ArgumentParser(
        description="欠け画像バックフィル（R2ファイル名突合）"
    )
    parser.add_argument(
        "folder",
        type=Path,
        help="画像フォルダのパス",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="実際にアップロードを実行する (指定しない場合はdry-run)",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=ROOT_DIR / ".env",
        help=".envファイルのパス",
    )
    args = parser.parse_args()

    dry_run = not args.execute
    root_folder = args.folder

    if not root_folder.exists():
        print(f"❌ フォルダが見つかりません: {root_folder}")
        return

    if dry_run:
        print("=" * 60)
        print("🔍 DRY-RUN モード (アップロードは実行されません)")
        print("=" * 60)
    else:
        print("=" * 60)
        print("⚠️  EXECUTE モード (実際にR2へアップロードします)")
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

    try:
        schedule_lookup = ScheduleLookup(config)
    except Exception as e:
        logger.warning(f"Could not initialize ScheduleLookup: {e}")
        schedule_lookup = None

    # ------------------------------------------------
    # Step 1: ローカル画像をスキャン
    # ------------------------------------------------
    print(f"\n📁 ローカルフォルダをスキャン中: {root_folder}")
    local_images: dict[str, Path] = {}  # filename -> path

    for path in root_folder.rglob("*"):
        if path.suffix.lower() in IMAGE_EXTENSIONS and not path.name.startswith("."):
            local_images[path.name] = path

    print(f"  ローカル画像数: {len(local_images)}")

    # ------------------------------------------------
    # Step 2: R2全オブジェクトを取得
    # ------------------------------------------------
    print("\n📦 R2バケットから全オブジェクトキーを取得中...")
    all_r2_keys = _list_all_r2_keys(r2, prefix="photos/")
    print(f"  R2 photos/ 総数: {len(all_r2_keys)}")

    # R2にあるオリジナルファイル名を抽出
    r2_filenames = set()
    for key in all_r2_keys:
        fname = _extract_original_filename(key)
        r2_filenames.add(fname)

    print(f"  R2上のユニークファイル名: {len(r2_filenames)}")

    # ------------------------------------------------
    # Step 3: 欠け画像を特定
    # ------------------------------------------------
    # フォルダ単位で欠け画像をグループ化
    missing_by_folder: dict[str, list[Path]] = {}
    for fname, path in sorted(local_images.items()):
        if fname not in r2_filenames:
            folder_name = path.parent.name
            if folder_name not in missing_by_folder:
                missing_by_folder[folder_name] = []
            missing_by_folder[folder_name].append(path)

    missing_images = [path for paths in missing_by_folder.values() for path in paths]
    already_count = len(local_images) - len(missing_images)

    print(f"\n" + "=" * 60)
    print("📊 バックフィル対象サマリー")
    print("=" * 60)
    print(f"  ローカル画像:     {len(local_images)}")
    print(f"  R2に既存:         {already_count}")
    print(f"  アップロード対象:  {len(missing_images)}")

    if len(missing_images) <= 100:
        for folder_name, paths in missing_by_folder.items():
            print(f"\n  📂 {folder_name} ({len(paths)}件):")
            for path in paths:
                print(f"    + {path.name}")
    else:
        print(f"  (件数が多いため先頭ダイジェスト表示)")
        count = 0
        for folder_name, paths in missing_by_folder.items():
            print(f"\n  📂 {folder_name} ({len(paths)}件):")
            for path in paths[:5]:
                print(f"    + {path.name}")
            if len(paths) > 5:
                print(f"    ... 他 {len(paths) - 5} 件")
            count += len(paths)
            if count >= 30:
                print(f"\n    ... 以降省略")
                break

    if not missing_images:
        print("\n✅ 全画像がR2に存在します。バックフィル不要です。")
        return

    # ------------------------------------------------
    # Step 4: 実行
    # ------------------------------------------------
    if dry_run:
        print(f"\n" + "=" * 60)
        print("🔍 DRY-RUN 完了。実際にアップロード・Notion連携するには --execute を付けてください。")
        print(f"   python scripts/backfill_images.py {root_folder} --execute")
        print("=" * 60)
        return

    print(f"\n⏳ {len(missing_images)} 件をR2にアップロード＆Notion連携中...")
    uploaded = 0
    errors = 0
    notion_created = 0
    notion_updated = 0

    for folder_name, paths in missing_by_folder.items():
        print(f"\n  📂 {folder_name} の処理中...")
        new_urls = []

        # 1. R2へアップロード
        for path in paths:
            fname = path.name
            try:
                content = path.read_bytes()
                mime_type, _ = mimetypes.guess_type(str(path))
                if not mime_type:
                    mime_type = "image/jpeg"

                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                key = f"photos/{timestamp}_{fname}"
                r2.upload(content, key, mime_type)

                if public_url:
                    url = f"{public_url}/{key}"
                else:
                    url = key

                new_urls.append(url)
                uploaded += 1
                logger.info(f"Uploaded: {fname} -> {key}")

            except Exception as e:
                errors += 1
                logger.error(f"Failed to upload {fname}: {e}")

        if not new_urls:
            continue

        # フォルダ内の画像の最古のタイムスタンプを代表日時とする
        folder_timestamp = None
        for path in paths:
            ts, _, _ = get_photo_metadata(path)
            if ts:
                if folder_timestamp is None or ts < folder_timestamp:
                    folder_timestamp = ts

        # 2. Notionへ連携 (ページ検索 → 追加 or 新規作成)
        try:
            page_id = notion.find_page_by_title(folder_name)
            if page_id:
                # 既存ページがある場合は、現在の画像を取得して追記する
                page = notion.client.pages.retrieve(page_id)
                files_prop = page.get("properties", {}).get("画像", {})
                existing_files = files_prop.get("files", [])

                files_payload = existing_files.copy()
                for i, url in enumerate(new_urls):
                    files_payload.append({
                        "type": "external",
                        "name": f"image_{len(existing_files) + i + 1}",
                        "external": {"url": url}
                    })

                notion.client.pages.update(
                    page_id=page_id,
                    properties={"画像": {"files": files_payload}}
                )
                notion_updated += 1
                logger.info(f"Updated existing Notion page: {folder_name} (+{len(new_urls)} images)")

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
                logger.info(f"Created new Notion page: {folder_name} ({len(new_urls)} images, Date: {folder_timestamp})")

        except Exception as e:
            errors += 1
            logger.error(f"Failed to link Notion page for {folder_name}: {e}")

    # ------------------------------------------------
    # 結果サマリー
    # ------------------------------------------------
    print(f"\n" + "=" * 60)
    print("🎉 バックフィル完了")
    print("=" * 60)
    print(f"  R2アップロード: {uploaded} 件")
    print(f"  Notion新規作成: {notion_created} ページ")
    print(f"  Notion更新更新: {notion_updated} ページ")
    print(f"  エラー: {errors} 件")


if __name__ == "__main__":
    main()
