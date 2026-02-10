"""Export gallery.json from Notion and upload to R2."""

from __future__ import annotations

import io
import logging
import os
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
AUTHOR_STUDENT_ID_PROP_CANDIDATES = (
    "生徒ID",
    "生徒 Id",
    "生徒 id",
    "student_id",
    "Student ID",
    "StudentId",
)
READY_PROP_ENV = "NOTION_WORKS_READY_PROP"
READY_PROP_CANDIDATES = (
    "整備済み",
    "整備済",
)


@dataclass
class ExportStats:
    total_pages: int = 0
    exported: int = 0
    skipped_not_ready: int = 0
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
        ready_prop = self._resolve_ready_property_name(db_info)
        pages = self.notion.list_database_pages(self.notion.database_id)

        tag_db_id = self._get_relation_database_id(db_info, "タグ")
        author_db_id = self._get_relation_database_id(db_info, "作者")

        tag_map = self.notion.get_database_title_map(tag_db_id) if tag_db_id else {}
        author_map = self._build_author_id_map(author_db_id) if author_db_id else {}

        stats = ExportStats(total_pages=len(pages))
        works: list[dict] = []

        for page in pages:
            if not self._is_page_ready(page, ready_prop):
                stats.skipped_not_ready += 1
                continue

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

    def _resolve_ready_property_name(self, db_info: dict) -> str:
        properties = db_info.get("properties", {})
        preferred = (os.getenv(READY_PROP_ENV) or READY_PROP_CANDIDATES[0]).strip()

        candidates = list(
            dict.fromkeys(name for name in (preferred, *READY_PROP_CANDIDATES) if name)
        )

        for name in candidates:
            schema = properties.get(name)
            if self._is_ready_schema_type(schema):
                return name

        for name, schema in properties.items():
            if not self._is_ready_schema_type(schema):
                continue
            normalized = str(name or "").strip().lower()
            if "整備済" in normalized or "ready" in normalized:
                return name

        raise ValueError(
            "Ready property not found. "
            "Set NOTION_WORKS_READY_PROP to a checkbox or formula boolean property name."
        )

    def _is_ready_schema_type(self, schema: dict | None) -> bool:
        if not isinstance(schema, dict):
            return False
        # formula type can also represent a derived ready flag
        return schema.get("type") in {"checkbox", "formula"}

    def _is_page_ready(self, page: dict, ready_prop: str) -> bool:
        prop = page.get("properties", {}).get(ready_prop, {})
        prop_type = prop.get("type")
        if prop_type == "checkbox":
            return bool(prop.get("checkbox"))
        if prop_type == "formula":
            formula = prop.get("formula") or {}
            if formula.get("type") == "boolean":
                return bool(formula.get("boolean"))
        return False

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

        author_ids = self._get_relation_names(props, "作者", author_map)
        author_name = self._format_author(author_ids, props)

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

    def _format_author(self, author_ids: list[str], props: dict) -> str | None:
        if author_ids:
            return " / ".join([author_id for author_id in author_ids if author_id]) or None
        # Fallback if relation is not used. Only allow ID-like values.
        select_val = self._get_select(props, "作者")
        if select_val:
            return self._sanitize_student_id(select_val) or None
        return None

    def _build_author_id_map(self, author_db_id: str) -> dict[str, str]:
        author_db_info = self.notion.get_database_info(author_db_id)
        student_id_prop = self._pick_property_name(
            author_db_info,
            AUTHOR_STUDENT_ID_PROP_CANDIDATES,
        )
        if not student_id_prop:
            logger.warning(
                "Student ID property not found in author database %s. expected one of: %s",
                author_db_id,
                ", ".join(AUTHOR_STUDENT_ID_PROP_CANDIDATES),
            )
            return {}

        pages = self.notion.list_database_pages(author_db_id)
        author_map: dict[str, str] = {}
        for page in pages:
            props = page.get("properties", {})
            raw_student_id = self._extract_property_text(props.get(student_id_prop, {}))
            student_id = self._sanitize_student_id(raw_student_id)
            if not student_id:
                logger.warning("Missing/invalid student ID on author page: %s", page.get("id"))
                continue
            author_map[page["id"]] = student_id

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
        if prop_type == "number":
            return self._stringify_number(prop.get("number"))
        if prop_type == "unique_id":
            unique_id = prop.get("unique_id") or {}
            return self._stringify_unique_id(
                prefix=unique_id.get("prefix"),
                number=unique_id.get("number"),
            )
        return ""

    def _sanitize_student_id(self, raw_value: str) -> str:
        value = (raw_value or "").strip()
        if not value:
            return ""
        # Reject values that likely include human names.
        if re.search(r"\s*[|｜]\s*", value):
            return ""
        # Hiragana, full-width Katakana, half-width Katakana, CJK Unified Ideographs
        if re.search(r"[ぁ-んァ-ヶｦ-ﾝ一-龥]", value):
            return ""
        if not re.search(r"\d", value):
            return ""
        return value

    def _stringify_number(self, value: int | float | None) -> str:
        if value is None:
            return ""
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    def _stringify_unique_id(self, prefix: str | None, number: int | float | None) -> str:
        number_text = self._stringify_number(number)
        if not number_text:
            return ""
        prefix_text = (prefix or "").strip()
        if not prefix_text:
            return number_text
        # Notion unique_id prefixes may or may not include a trailing "-".
        # Avoid duplicating the separator when the prefix already ends with one.
        if prefix_text.endswith("-"):
            return f"{prefix_text}{number_text}"
        return f"{prefix_text}-{number_text}"

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
