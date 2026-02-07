"""Export gallery.json from Notion and upload to R2."""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import requests
from PIL import Image, ImageOps

from .config import Config
from .notion_db import NotionDB
from .r2_storage import R2Storage

logger = logging.getLogger(__name__)

THUMB_WIDTH_DEFAULT = 600
THUMB_RATIO = 4 / 5
GALLERY_JSON_KEY = "gallery.json"
THUMB_PREFIX = "thumbs"
LIGHT_MAX_SIZE_DEFAULT = 1600
LIGHT_QUALITY_DEFAULT = 75
LIGHT_PREFIX_SUFFIX = "-light"
AUTHOR_NICKNAME_PROP_CANDIDATES = ("ニックネーム", "nickname", "Nickname")
AUTHOR_REAL_NAME_PROP_CANDIDATES = ("本名", "real_name", "Real Name")


@dataclass
class ExportStats:
    total_pages: int = 0
    exported: int = 0
    skipped_no_images: int = 0
    skipped_no_completed_date: int = 0
    thumb_generated: int = 0
    thumb_skipped_existing: int = 0
    thumb_failed: int = 0
    light_generated: int = 0
    light_skipped_existing: int = 0
    light_failed: int = 0


class GalleryExporter:
    """Export works from Notion into gallery.json and upload to R2."""

    def __init__(self, config: Config):
        self.config = config
        self.notion = NotionDB(
            config.notion.token,
            config.notion.database_id,
            config.notion.tags_database_id,
        )
        self.r2 = R2Storage(config.r2)

        if not self.config.r2.public_url:
            raise ValueError("R2_PUBLIC_URL is required for gallery export")

    def export(
        self,
        output_path: Path | None = None,
        upload: bool = True,
        generate_thumbs: bool = True,
        thumb_width: int = THUMB_WIDTH_DEFAULT,
        generate_light_images: bool = True,
        light_max_size: int = LIGHT_MAX_SIZE_DEFAULT,
        light_quality: int = LIGHT_QUALITY_DEFAULT,
        overwrite_thumbs: bool = False,
        overwrite_light_images: bool = False,
    ) -> tuple[dict, ExportStats]:
        db_info = self.notion.get_database_info()
        pages = self.notion.list_database_pages(self.notion.database_id)

        tag_db_id = self._get_relation_database_id(db_info, "タグ")
        author_db_id = self._get_relation_database_id(db_info, "作者")

        tag_map = self.notion.get_database_title_map(tag_db_id) if tag_db_id else {}
        author_map = self._build_author_name_map(author_db_id) if author_db_id else {}

        stats = ExportStats(total_pages=len(pages))
        works: list[dict] = []

        for page in pages:
            work = self._parse_work_page(
                page=page,
                tag_map=tag_map,
                author_map=author_map,
                generate_thumbs=generate_thumbs,
                thumb_width=thumb_width,
                generate_light_images=generate_light_images,
                light_max_size=light_max_size,
                light_quality=light_quality,
                overwrite_thumbs=overwrite_thumbs,
                overwrite_light_images=overwrite_light_images,
                stats=stats,
            )
            if work:
                works.append(work)
                stats.exported += 1

        works.sort(key=lambda w: w["id"])
        works.sort(key=lambda w: w["completed_date"], reverse=True)

        payload = {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "works": works,
        }

        if output_path:
            output_path.write_text(
                self._dump_json(payload),
                encoding="utf-8",
            )

        if upload:
            self.r2.put_json(
                payload,
                GALLERY_JSON_KEY,
                cache_control="max-age=300",
                ensure_ascii=False,
            )

        return payload, stats

    def _get_relation_database_id(self, db_info: dict, prop_name: str) -> str | None:
        prop = db_info.get("properties", {}).get(prop_name)
        if not prop:
            logger.warning("Relation property not found: %s", prop_name)
            return None
        if prop.get("type") != "relation":
            logger.warning("Property %s is not relation (type=%s)", prop_name, prop.get("type"))
            return None
        return prop.get("relation", {}).get("database_id")

    def _parse_work_page(
        self,
        page: dict,
        tag_map: dict[str, str],
        author_map: dict[str, str],
        generate_thumbs: bool,
        thumb_width: int,
        generate_light_images: bool,
        light_max_size: int,
        light_quality: int,
        overwrite_thumbs: bool,
        overwrite_light_images: bool,
        stats: ExportStats,
    ) -> dict | None:
        props = page.get("properties", {})

        work_id = page.get("id")
        title = self._get_title_from_props(props, "作品名")

        completed_date = self._get_date(props, "完成日")
        if not completed_date:
            stats.skipped_no_completed_date += 1
            logger.warning("Missing completed_date: %s", work_id)
            return None

        images = self._get_files(props, "画像")
        if not images:
            stats.skipped_no_images += 1
            logger.warning("No images: %s", work_id)
            return None

        caption = self._get_rich_text(props, "キャプション")
        studio = self._get_select(props, "教室")

        tags = self._get_relation_names(props, "タグ", tag_map)
        if not tags:
            tags = self._get_tags_fallback(props)

        author = self._get_relation_names(props, "作者", author_map)
        author_name = self._format_author(author, props)

        thumb_url = None
        if generate_thumbs:
            thumb_url = self._ensure_thumbnail(
                work_id=work_id,
                image_url=images[0],
                thumb_width=thumb_width,
                overwrite=overwrite_thumbs,
                stats=stats,
            )

        if not thumb_url:
            thumb_url = images[0]

        images_light: list[str] | None = None
        if generate_light_images:
            images_light = []
            has_light = False
            for image_url in images:
                light_url = self._ensure_light_image(
                    image_url=image_url,
                    max_size=light_max_size,
                    quality=light_quality,
                    overwrite=overwrite_light_images,
                    stats=stats,
                )
                if light_url:
                    images_light.append(light_url)
                    has_light = True
                else:
                    images_light.append(image_url)
            if not has_light:
                images_light = None

        work = {
            "id": work_id,
            "title": title or "",
            "completed_date": completed_date,
            "caption": caption or None,
            "author": author_name,
            "studio": studio or None,
            "tags": tags,
            "images": images,
            "thumb": thumb_url,
        }
        if images_light:
            work["images_light"] = images_light
        return work

    def _format_author(self, author_names: list[str], props: dict) -> str | None:
        if author_names:
            nicknames = [self._extract_author_nickname(n) for n in author_names]
            return " / ".join([n for n in nicknames if n]) or None
        # Fallback if relation is not used
        select_val = self._get_select(props, "作者")
        if select_val:
            return self._extract_author_nickname(select_val)
        return None

    def _extract_author_nickname(self, raw_name: str) -> str:
        text = (raw_name or "").strip()
        if not text:
            return ""
        parts = re.split(r"\s*[|｜]\s*", text, maxsplit=1)
        nickname = parts[0].strip()
        real_name = parts[1].strip() if len(parts) > 1 else ""
        return self._normalize_nickname(nickname, real_name) or real_name

    def _build_author_name_map(self, author_db_id: str) -> dict[str, str]:
        author_db_info = self.notion.get_database_info(author_db_id)
        author_title_prop = self.notion.get_title_property_name(author_db_info)
        nickname_prop = self._pick_property_name(
            author_db_info,
            AUTHOR_NICKNAME_PROP_CANDIDATES,
        )
        real_name_prop = self._pick_property_name(
            author_db_info,
            AUTHOR_REAL_NAME_PROP_CANDIDATES,
        )

        pages = self.notion.list_database_pages(author_db_id)
        author_map: dict[str, str] = {}
        for page in pages:
            props = page.get("properties", {})
            title = self._extract_property_text(props.get(author_title_prop, {})) if author_title_prop else ""
            parsed_nickname, parsed_real_name = self._split_name_label(title)
            raw_nickname = self._extract_property_text(props.get(nickname_prop, {})) if nickname_prop else ""
            raw_real_name = self._extract_property_text(props.get(real_name_prop, {})) if real_name_prop else ""

            real_name = raw_real_name or parsed_real_name
            nickname = self._normalize_nickname(raw_nickname or parsed_nickname, real_name)
            display_name = nickname or parsed_nickname or real_name or title
            author_map[page["id"]] = display_name

        return author_map

    def _pick_property_name(self, database_info: dict, candidates: tuple[str, ...]) -> str | None:
        properties = database_info.get("properties", {})
        for name in candidates:
            if name in properties:
                return name
        return None

    def _extract_property_text(self, prop: dict) -> str:
        prop_type = prop.get("type")
        if prop_type == "title":
            return "".join(item.get("plain_text", "") for item in prop.get("title", [])).strip()
        if prop_type == "rich_text":
            return "".join(item.get("plain_text", "") for item in prop.get("rich_text", [])).strip()
        if prop_type == "select":
            return (prop.get("select", {}) or {}).get("name", "").strip()
        return ""

    def _split_name_label(self, raw_name: str) -> tuple[str, str]:
        text = (raw_name or "").strip()
        if not text:
            return "", ""
        parts = re.split(r"\s*[|｜]\s*", text, maxsplit=1)
        nickname = parts[0].strip()
        real_name = parts[1].strip() if len(parts) > 1 else ""
        return nickname, real_name

    def _normalize_nickname(self, nickname: str, real_name: str) -> str:
        nickname = (nickname or "").strip()
        real_name = (real_name or "").strip()
        if not nickname:
            return ""
        if not real_name or nickname != real_name:
            return nickname
        shortened = real_name[:2].strip()
        return shortened or nickname

    def _get_title_from_props(self, props: dict, key: str) -> str:
        if props.get(key, {}).get("title"):
            return "".join(t.get("plain_text", "") for t in props[key]["title"]).strip()
        return ""

    def _get_date(self, props: dict, key: str) -> str | None:
        date_obj = props.get(key, {}).get("date")
        if date_obj and date_obj.get("start"):
            return date_obj["start"][:10]
        return None

    def _get_select(self, props: dict, key: str) -> str | None:
        sel = props.get(key, {}).get("select")
        if sel:
            return sel.get("name")
        return None

    def _get_rich_text(self, props: dict, key: str) -> str | None:
        rtext = props.get(key, {}).get("rich_text")
        if rtext:
            return "".join(t.get("plain_text", "") for t in rtext).strip()
        return None

    def _get_files(self, props: dict, key: str) -> list[str]:
        files = props.get(key, {}).get("files", [])
        urls = []
        for file in files:
            if file.get("type") == "external":
                urls.append(file["external"]["url"])
            elif file.get("type") == "file":
                urls.append(file["file"]["url"])
        return urls

    def _get_relation_names(
        self,
        props: dict,
        key: str,
        name_map: dict[str, str],
    ) -> list[str]:
        rel = props.get(key, {})
        if rel.get("type") != "relation":
            return []
        ids = [r.get("id") for r in rel.get("relation", []) if r.get("id")]
        names = [name_map.get(rid, "") for rid in ids]
        return [n for n in names if n]

    def _get_tags_fallback(self, props: dict) -> list[str]:
        t_prop = props.get("タグ")
        if not t_prop:
            return []
        if t_prop.get("type") == "multi_select":
            return [opt.get("name") for opt in t_prop.get("multi_select", []) if opt.get("name")]
        if t_prop.get("type") == "rich_text":
            raw = self._get_rich_text(props, "タグ")
            if raw:
                return [t.strip().lstrip("#") for t in raw.split() if t.strip()]
        return []

    def _ensure_thumbnail(
        self,
        work_id: str,
        image_url: str,
        thumb_width: int,
        overwrite: bool,
        stats: ExportStats,
    ) -> str | None:
        key = f"{THUMB_PREFIX}/{work_id}.jpg"
        if not overwrite and self.r2.exists(key):
            stats.thumb_skipped_existing += 1
            return self._public_url(key)

        try:
            resp = requests.get(image_url, timeout=30)
            resp.raise_for_status()
            image = Image.open(io.BytesIO(resp.content))
            image = ImageOps.exif_transpose(image)
            image = self._center_crop(image, THUMB_RATIO)
            image = image.resize(
                (thumb_width, int(thumb_width / THUMB_RATIO)), Image.LANCZOS
            ).convert("RGB")

            buf = io.BytesIO()
            image.save(buf, format="JPEG", quality=80)
            self.r2.upload(
                buf.getvalue(),
                key,
                "image/jpeg",
                cache_control="max-age=31536000",
            )
            stats.thumb_generated += 1
            return self._public_url(key)
        except Exception as e:
            stats.thumb_failed += 1
            logger.warning("Thumbnail generation failed (%s): %s", work_id, e)
            return None

    def _ensure_light_image(
        self,
        image_url: str,
        max_size: int,
        quality: int,
        overwrite: bool,
        stats: ExportStats,
    ) -> str | None:
        key = self._build_light_key(image_url)
        if not key:
            stats.light_failed += 1
            logger.warning("Light image key build failed: %s", image_url)
            return None

        if not overwrite and self.r2.exists(key):
            stats.light_skipped_existing += 1
            return self._public_url(key)

        try:
            resp = requests.get(image_url, timeout=30)
            resp.raise_for_status()
            image = Image.open(io.BytesIO(resp.content))
            image = ImageOps.exif_transpose(image)
            image = self._convert_to_rgb(image)
            image = self._resize_to_max(image, max_size)

            buf = io.BytesIO()
            image.save(buf, format="JPEG", quality=quality)
            self.r2.upload(
                buf.getvalue(),
                key,
                "image/jpeg",
                cache_control="max-age=31536000",
            )
            stats.light_generated += 1
            return self._public_url(key)
        except Exception as e:
            stats.light_failed += 1
            logger.warning("Light image generation failed (%s): %s", image_url, e)
            return None

    def _center_crop(self, image: Image.Image, target_ratio: float) -> Image.Image:
        width, height = image.size
        current_ratio = width / height
        if current_ratio > target_ratio:
            new_width = int(height * target_ratio)
            left = (width - new_width) // 2
            box = (left, 0, left + new_width, height)
        else:
            new_height = int(width / target_ratio)
            top = (height - new_height) // 2
            box = (0, top, width, top + new_height)
        return image.crop(box)

    def _resize_to_max(self, image: Image.Image, max_size: int) -> Image.Image:
        width, height = image.size
        longest = max(width, height)
        if longest <= max_size:
            return image
        scale = max_size / longest
        new_width = max(1, int(width * scale))
        new_height = max(1, int(height * scale))
        return image.resize((new_width, new_height), Image.LANCZOS)

    def _convert_to_rgb(self, image: Image.Image) -> Image.Image:
        if image.mode in ("RGBA", "LA") or (
            image.mode == "P" and "transparency" in image.info
        ):
            background = Image.new("RGB", image.size, (255, 255, 255))
            alpha = image.split()[-1]
            background.paste(image, mask=alpha)
            return background
        return image.convert("RGB")

    def _build_light_key(self, image_url: str) -> str | None:
        parsed = urlparse(image_url)
        if not parsed.path:
            return None
        parts = [p for p in PurePosixPath(parsed.path).parts if p != "/"]
        if not parts:
            return None

        base = parts[0]
        prefix = base if base.endswith(LIGHT_PREFIX_SUFFIX) else f"{base}{LIGHT_PREFIX_SUFFIX}"
        filename = parts[-1]
        stem = Path(filename).stem
        ext = Path(filename).suffix.lower()
        out_ext = ext if ext in {".jpg", ".jpeg"} else ".jpg"
        new_filename = f"{stem}{out_ext}"

        key_parts = [prefix, *parts[1:-1], new_filename]
        return "/".join([p for p in key_parts if p])

    def _public_url(self, key: str) -> str:
        base = (self.config.r2.public_url or "").rstrip("/")
        return f"{base}/{key}"

    def _dump_json(self, payload: dict) -> str:
        import json

        return json.dumps(payload, ensure_ascii=False, indent=2)
