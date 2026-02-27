#!/usr/bin/env python3
"""
Notion / gallery.json の画像リンク健全性チェック。

確認項目:
- URLへのHTTPアクセス可否（HEAD→GETフォールバック）
- R2キーへ変換できるURLが、実際にR2に存在するか

使い方:
  # 既定: Notion + R2上の gallery.json をチェック
  python scripts/check_image_links.py

  # ローカル gallery.json を使う
  python scripts/check_image_links.py --gallery-file /path/to/gallery.json

  # JSONレポート出力
  python scripts/check_image_links.py --output reports/image_link_report.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

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
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

USER_AGENT = "media-platform-link-check/1.0"
KNOWN_R2_PREFIXES = (
    "photos/",
    "photos-light/",
    "images/",
    "images-light/",
    "uploads/",
    "uploads-light/",
    "thumbs/",
)


@dataclass
class UrlRef:
    url: str
    source: str  # notion | gallery
    item_id: str
    context: str


def _get_page_title(page: dict) -> str:
    title_prop = page.get("properties", {}).get("作品名", {})
    titles = title_prop.get("title", [])
    if titles:
        return titles[0].get("plain_text", "(無題)")
    return "(無題)"


def _get_page_image_urls(page: dict) -> list[str]:
    files_prop = page.get("properties", {}).get("画像", {})
    files = files_prop.get("files", [])
    urls: list[str] = []
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
    if not url:
        return None

    public_url = (public_url or "").rstrip("/")
    if public_url and url.startswith(f"{public_url}/"):
        key = url[len(public_url) :].lstrip("/")
        return urllib.parse.unquote(key) if key else None

    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lstrip("/")
    if not path:
        return None

    if path.startswith(KNOWN_R2_PREFIXES):
        return urllib.parse.unquote(path)

    if public_url:
        pub = urllib.parse.urlparse(public_url)
        if parsed.netloc and parsed.netloc == pub.netloc:
            return urllib.parse.unquote(path)

    return None


def _check_http(url: str, timeout_sec: float) -> tuple[bool, int | None, str]:
    parsed = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(
        urllib.parse.unquote(parsed.path),
        safe="/:@-._~!$&'()*+,;=%",
    )
    query = urllib.parse.quote(
        urllib.parse.unquote(parsed.query),
        safe="=&?/:;+,%@-._~!$'()*",
    )
    request_url = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, path, query, parsed.fragment)
    )

    headers = {"User-Agent": USER_AGENT}

    def _run(method: str) -> tuple[int, str]:
        req = urllib.request.Request(url=request_url, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout_sec) as res:
            return int(res.getcode()), method

    try:
        status, method = _run("HEAD")
        if 200 <= status < 400:
            return True, status, method
        return False, status, f"{method}_non_2xx"
    except urllib.error.HTTPError as e:
        # Some origins block HEAD; retry with GET.
        if e.code not in {403, 405, 400, 501}:
            return False, int(e.code), f"HEAD_http_error:{e.code}"
    except Exception as e:  # noqa: BLE001
        logger.debug("HEAD failed for %s: %s", url, e)

    try:
        status, method = _run("GET")
        if 200 <= status < 400:
            return True, status, method
        return False, status, f"{method}_non_2xx"
    except urllib.error.HTTPError as e:
        return False, int(e.code), f"GET_http_error:{e.code}"
    except Exception as e:  # noqa: BLE001
        return False, None, f"GET_error:{type(e).__name__}"


def _list_all_r2_keys(r2: R2Storage, prefix: str) -> set[str]:
    keys: set[str] = set()
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
        res = client.list_objects_v2(**kwargs)
        for obj in res.get("Contents", []):
            key = str(obj.get("Key", "")).strip()
            if key:
                keys.add(key)
        if res.get("IsTruncated"):
            continuation_token = res.get("NextContinuationToken")
        else:
            break
    return keys


def _list_r2_key_pool_for_refs(r2: R2Storage, keys: list[str]) -> set[str]:
    prefixes = sorted({f"{key.split('/', 1)[0]}/" for key in keys if "/" in key})
    pool: set[str] = set()
    for prefix in prefixes:
        print(f"R2一覧取得: prefix={prefix}")
        pool.update(_list_all_r2_keys(r2, prefix=prefix))
    return pool


def _collect_notion_refs(notion: NotionDB, include_archived: bool) -> list[UrlRef]:
    refs: list[UrlRef] = []
    pages = notion.list_database_pages(notion.database_id)
    for page in pages:
        if not include_archived and page.get("archived"):
            continue
        page_id = str(page.get("id", "")).strip()
        title = _get_page_title(page)
        image_urls = _get_page_image_urls(page)
        for idx, url in enumerate(image_urls, start=1):
            refs.append(
                UrlRef(
                    url=url,
                    source="notion",
                    item_id=page_id,
                    context=f"{title} image#{idx}",
                )
            )
    return refs


def _extract_gallery_urls(gallery_data: dict | list) -> list[UrlRef]:
    refs: list[UrlRef] = []
    works = gallery_data.get("works", []) if isinstance(gallery_data, dict) else gallery_data
    if not isinstance(works, list):
        return refs

    for idx, work in enumerate(works, start=1):
        if not isinstance(work, dict):
            continue
        work_id = str(work.get("id", "")).strip() or f"work#{idx}"

        images = work.get("images", [])
        if isinstance(images, list):
            for i, url in enumerate(images, start=1):
                if not isinstance(url, str) or not url.strip():
                    continue
                refs.append(
                    UrlRef(
                        url=url.strip(),
                        source="gallery",
                        item_id=work_id,
                        context=f"images[{i - 1}]",
                    )
                )

        images_light = work.get("images_light", [])
        if isinstance(images_light, list):
            for i, url in enumerate(images_light, start=1):
                if not isinstance(url, str) or not url.strip():
                    continue
                refs.append(
                    UrlRef(
                        url=url.strip(),
                        source="gallery",
                        item_id=work_id,
                        context=f"images_light[{i - 1}]",
                    )
                )

        thumb = work.get("thumb")
        if isinstance(thumb, str) and thumb.strip():
            refs.append(
                UrlRef(
                    url=thumb.strip(),
                    source="gallery",
                    item_id=work_id,
                    context="thumb",
                )
            )

    return refs


def _load_gallery_data(
    r2: R2Storage,
    gallery_file: Path | None,
    gallery_key: str,
) -> tuple[dict | list | None, str]:
    if gallery_file:
        with open(gallery_file, "r", encoding="utf-8") as f:
            return json.load(f), f"file:{gallery_file}"
    return r2.get_json(gallery_key), f"r2:{gallery_key}"


def main() -> None:
    parser = argparse.ArgumentParser(description="画像リンク健全性チェック")
    parser.add_argument("--env-file", type=Path, default=ROOT_DIR / ".env")
    parser.add_argument("--gallery-file", type=Path, help="ローカルの gallery.json パス")
    parser.add_argument(
        "--gallery-key",
        default="gallery.json",
        help="R2上の gallery.json キー（--gallery-file 未指定時）",
    )
    parser.add_argument(
        "--include-archived",
        action="store_true",
        help="archived=true の Notion ページもチェック対象に含める",
    )
    parser.add_argument(
        "--skip-http",
        action="store_true",
        help="HTTP疎通チェックをスキップする",
    )
    parser.add_argument("--timeout", type=float, default=8.0, help="HTTPタイムアウト秒")
    parser.add_argument("--max-details", type=int, default=30, help="詳細表示の最大件数")
    parser.add_argument("--output", type=Path, help="JSONレポート出力パス")
    args = parser.parse_args()

    config = Config.load(env_file=args.env_file, allow_missing_instagram=True)
    notion = NotionDB(
        config.notion.token,
        config.notion.database_id,
        config.notion.tags_database_id,
    )
    r2 = R2Storage(config.r2)
    public_url = config.r2.public_url or ""

    print("=" * 70)
    print("🔎 画像リンク健全性チェック")
    print("=" * 70)

    notion_refs = _collect_notion_refs(notion, include_archived=args.include_archived)
    print(f"Notion参照URL: {len(notion_refs)}")

    gallery_data, gallery_source = _load_gallery_data(
        r2=r2,
        gallery_file=args.gallery_file,
        gallery_key=args.gallery_key,
    )
    if gallery_data is None:
        print(f"⚠️ gallery データを読み込めませんでした: {gallery_source}")
        gallery_refs = []
    else:
        gallery_refs = _extract_gallery_urls(gallery_data)
    print(f"gallery参照URL ({gallery_source}): {len(gallery_refs)}")

    refs = notion_refs + gallery_refs
    unique_urls = sorted({ref.url for ref in refs})
    refs_by_url: dict[str, list[UrlRef]] = {}
    for ref in refs:
        refs_by_url.setdefault(ref.url, []).append(ref)

    print(f"ユニークURL総数: {len(unique_urls)}")

    url_to_key = {url: _url_to_r2_key(url, public_url) for url in unique_urls}
    mapped_keys = sorted({key for key in url_to_key.values() if key})
    unmapped_urls = [url for url, key in url_to_key.items() if not key]

    print(f"R2キーへ変換できたURL: {len(mapped_keys)} keys")
    print(f"R2キーへ変換不可URL: {len(unmapped_urls)}")

    r2_key_pool = _list_r2_key_pool_for_refs(r2, mapped_keys)
    missing_r2_keys = [key for key in mapped_keys if key not in r2_key_pool]

    key_missing_set = set(missing_r2_keys)
    broken_by_r2 = [url for url, key in url_to_key.items() if key and key in key_missing_set]

    http_failures: list[dict] = []
    if not args.skip_http:
        print("HTTP疎通チェック中...")
        for i, url in enumerate(unique_urls, start=1):
            ok, status, detail = _check_http(url, timeout_sec=args.timeout)
            if not ok:
                http_failures.append({"url": url, "status": status, "detail": detail})
            if i % 200 == 0:
                print(f"  ... {i}/{len(unique_urls)}")

    http_failure_urls = {row["url"] for row in http_failures}
    broken_urls = sorted(set(broken_by_r2) | http_failure_urls)

    notion_broken = [
        ref for url in broken_urls for ref in refs_by_url.get(url, []) if ref.source == "notion"
    ]
    gallery_broken = [
        ref for url in broken_urls for ref in refs_by_url.get(url, []) if ref.source == "gallery"
    ]

    print("\n" + "=" * 70)
    print("📊 結果サマリー")
    print("=" * 70)
    print(f"壊れURL（総数）: {len(broken_urls)}")
    print(f"  Notion参照由来: {len(notion_broken)}")
    print(f"  gallery参照由来: {len(gallery_broken)}")
    print(f"R2未存在キー: {len(missing_r2_keys)}")
    print(f"HTTP失敗URL: {len(http_failures)}")

    if missing_r2_keys:
        print("\n❌ R2未存在キー（先頭）")
        for key in missing_r2_keys[: args.max_details]:
            print(f"  - {key}")

    if http_failures:
        print("\n❌ HTTP失敗URL（先頭）")
        for row in http_failures[: args.max_details]:
            print(f"  - {row['status'] or '-'} {row['detail']} {row['url']}")

    if broken_urls:
        print("\n❌ 壊れ参照（先頭）")
        shown = 0
        for url in broken_urls:
            for ref in refs_by_url.get(url, []):
                print(f"  - [{ref.source}] {ref.item_id} {ref.context} -> {url}")
                shown += 1
                if shown >= args.max_details:
                    break
            if shown >= args.max_details:
                break

    if unmapped_urls:
        print("\nℹ️ R2キー変換不可URL（先頭）")
        for url in unmapped_urls[: args.max_details]:
            print(f"  - {url}")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "summary": {
                "notion_refs": len(notion_refs),
                "gallery_refs": len(gallery_refs),
                "unique_urls": len(unique_urls),
                "mapped_keys": len(mapped_keys),
                "unmapped_urls": len(unmapped_urls),
                "missing_r2_keys": len(missing_r2_keys),
                "http_failures": len(http_failures),
                "broken_urls": len(broken_urls),
            },
            "missing_r2_keys": missing_r2_keys,
            "http_failures": http_failures,
            "broken_urls": broken_urls,
            "broken_refs": [
                {
                    "url": ref.url,
                    "source": ref.source,
                    "item_id": ref.item_id,
                    "context": ref.context,
                }
                for url in broken_urls
                for ref in refs_by_url.get(url, [])
            ],
            "unmapped_urls": unmapped_urls,
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"\n📝 レポート出力: {args.output}")

    if broken_urls:
        sys.exit(2)

    print("\n✅ 壊れリンクは検出されませんでした。")


if __name__ == "__main__":
    main()
