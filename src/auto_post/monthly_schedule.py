"""Monthly classroom schedule image generation from Notion."""

from __future__ import annotations

import calendar
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from notion_client import Client
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")

# Palette aligned to apps/gallery-web/gallery.html.
PALETTE = {
    "bg_top": (245, 241, 236),
    "bg_bottom": (234, 225, 217),
    "paper": (255, 255, 255),
    "ink": (78, 52, 46),
    "subtle": (120, 90, 78),
    "muted": (161, 136, 127),
    "line": (211, 194, 185),
    "line_light": (232, 221, 214),
    "accent": (200, 111, 52),
    "accent_2": (90, 140, 54),
    "sun_bg": (255, 246, 236),
    "sat_bg": (243, 249, 241),
}

WEEKDAY_LABELS = ["月", "火", "水", "木", "金", "土", "日"]


@dataclass(frozen=True)
class ScheduleEntry:
    """One schedule item for a single day."""

    day: date
    title: str
    classroom: str
    venue: str
    start: datetime | None = None
    end: datetime | None = None


@dataclass(frozen=True)
class ScheduleSourceConfig:
    """Notion source config for monthly schedule."""

    database_id: str
    date_property: str = "日付"
    title_property: str = ""
    classroom_property: str = "教室"
    venue_property: str = "会場"
    timezone: str = "Asia/Tokyo"

    @classmethod
    def from_env(cls) -> "ScheduleSourceConfig":
        database_id = os.environ.get("MONTHLY_SCHEDULE_NOTION_DATABASE_ID", "").strip()
        if not database_id:
            raise ValueError("MONTHLY_SCHEDULE_NOTION_DATABASE_ID is required")
        return cls(
            database_id=database_id,
            date_property=os.environ.get("MONTHLY_SCHEDULE_DATE_PROP", "日付").strip() or "日付",
            title_property=os.environ.get("MONTHLY_SCHEDULE_TITLE_PROP", "").strip(),
            classroom_property=os.environ.get("MONTHLY_SCHEDULE_CLASSROOM_PROP", "教室").strip() or "教室",
            venue_property=os.environ.get("MONTHLY_SCHEDULE_VENUE_PROP", "会場").strip() or "会場",
            timezone=os.environ.get("MONTHLY_SCHEDULE_TIMEZONE", "Asia/Tokyo").strip() or "Asia/Tokyo",
        )


@dataclass(frozen=True)
class ScheduleRenderConfig:
    """Render options for calendar image."""

    width: int = 1536
    height: int = 2048
    font_path: str = ""

    @classmethod
    def from_env(cls) -> "ScheduleRenderConfig":
        return cls(
            width=_safe_positive_int(os.environ.get("MONTHLY_SCHEDULE_IMAGE_WIDTH"), 1536),
            height=_safe_positive_int(os.environ.get("MONTHLY_SCHEDULE_IMAGE_HEIGHT"), 2048),
            font_path=os.environ.get("MONTHLY_SCHEDULE_FONT_PATH", "").strip(),
        )


@dataclass(frozen=True)
class ScheduleJsonSourceConfig:
    """JSON source config (R2 key or direct URL)."""

    key: str = "schedule_index.json"
    url: str = ""
    timezone: str = "Asia/Tokyo"

    @classmethod
    def from_env(cls) -> "ScheduleJsonSourceConfig":
        return cls(
            key=os.environ.get("MONTHLY_SCHEDULE_JSON_KEY", "schedule_index.json").strip() or "schedule_index.json",
            url=os.environ.get("MONTHLY_SCHEDULE_JSON_URL", "").strip(),
            timezone=os.environ.get("MONTHLY_SCHEDULE_TIMEZONE", "Asia/Tokyo").strip() or "Asia/Tokyo",
        )


class MonthlyScheduleNotionClient:
    """Fetch monthly classroom schedules from a Notion database."""

    def __init__(self, token: str, source: ScheduleSourceConfig):
        self.client = Client(auth=token, notion_version="2022-06-28")
        self.source = source
        self._title_property_name: str | None = source.title_property or None

    def fetch_month_entries(self, year: int, month: int) -> list[ScheduleEntry]:
        first_day = date(year, month, 1)
        next_month = (first_day.replace(day=28) + timedelta(days=4)).replace(day=1)
        last_day = next_month - timedelta(days=1)
        tz = ZoneInfo(self.source.timezone)

        body = {
            "filter": {
                "and": [
                    {
                        "property": self.source.date_property,
                        "date": {"on_or_after": first_day.isoformat()},
                    },
                    {
                        "property": self.source.date_property,
                        "date": {"on_or_before": last_day.isoformat()},
                    },
                ]
            },
            "sorts": [{"property": self.source.date_property, "direction": "ascending"}],
        }

        entries: list[ScheduleEntry] = []
        start_cursor: str | None = None

        while True:
            payload = dict(body)
            if start_cursor:
                payload["start_cursor"] = start_cursor

            response = self.client.request(
                path=f"databases/{self.source.database_id}/query",
                method="POST",
                body=payload,
            )

            for page in response.get("results", []):
                entry = self._parse_page(page, tz)
                if entry is None:
                    continue
                if entry.day.year == year and entry.day.month == month:
                    entries.append(entry)

            if not response.get("has_more"):
                break
            start_cursor = response.get("next_cursor")

        entries.sort(key=_entry_sort_key)
        return entries

    def _parse_page(self, page: dict, tz: ZoneInfo) -> ScheduleEntry | None:
        props = page.get("properties", {})
        date_prop = props.get(self.source.date_property, {})
        date_obj = date_prop.get("date") if isinstance(date_prop, dict) else None
        if not date_obj or not date_obj.get("start"):
            return None

        day, start_dt = _parse_notion_datetime(date_obj.get("start"), tz)
        if day is None:
            return None
        _, end_dt = _parse_notion_datetime(date_obj.get("end"), tz)

        title = self._extract_title(props)
        classroom = _extract_text(props.get(self.source.classroom_property, {}))
        venue = _extract_text(props.get(self.source.venue_property, {}))

        return ScheduleEntry(
            day=day,
            title=title,
            classroom=classroom,
            venue=venue,
            start=start_dt,
            end=end_dt,
        )

    def _extract_title(self, props: dict) -> str:
        if self._title_property_name and self._title_property_name in props:
            text = _extract_text(props.get(self._title_property_name, {}))
            if text:
                return text

        for prop_name, prop in props.items():
            if isinstance(prop, dict) and prop.get("type") == "title":
                self._title_property_name = prop_name
                text = _extract_text(prop)
                if text:
                    return text
                break

        return ""


def resolve_target_year_month(
    *,
    now: datetime | None = None,
    target: str = "next",
    year: int | None = None,
    month: int | None = None,
) -> tuple[int, int]:
    """Resolve year/month for posting target."""
    if (year is None) != (month is None):
        raise ValueError("year and month must be provided together")
    if year is not None and month is not None:
        if not 1 <= month <= 12:
            raise ValueError("month must be between 1 and 12")
        return year, month

    base = (now or datetime.now(tz=JST)).astimezone(JST)
    if target == "current":
        return base.year, base.month
    if target == "next":
        next_month = (base.replace(day=28) + timedelta(days=4)).replace(day=1)
        return next_month.year, next_month.month
    raise ValueError("target must be 'current' or 'next'")


def build_monthly_caption(
    year: int,
    month: int,
    entries: list[ScheduleEntry],
    default_tags: str,
    template: str = "",
) -> str:
    """Build SNS caption for monthly schedule post."""
    classrooms = sorted({e.classroom for e in entries if e.classroom})
    classroom_text = " / ".join(_short_classroom_name(value) for value in classrooms) if classrooms else "各教室"

    if template:
        base = template.format(year=year, month=month, classrooms=classroom_text)
    else:
        base = (
            f"{year}年{month}月の教室日程です。\n"
            "最新の空き状況や詳細は予約ページをご確認ください。"
        )

    tags = _normalize_hashtags(default_tags)
    if tags:
        return f"{base}\n\n{tags}"
    return base


def extract_month_entries_from_json(
    data: dict[str, Any],
    year: int,
    month: int,
    timezone: str = "Asia/Tokyo",
) -> list[ScheduleEntry]:
    """Extract month entries from schedule JSON."""
    tz = ZoneInfo(timezone)
    out: list[ScheduleEntry] = []

    dates = data.get("dates")
    if isinstance(dates, dict):
        for raw_date, groups in dates.items():
            day = _parse_date_ymd(raw_date)
            if day is None or day.year != year or day.month != month:
                continue
            if isinstance(groups, list):
                for group in groups:
                    entry = _build_entry_from_dict(group, day=day, tz=tz)
                    if entry:
                        out.append(entry)
            else:
                entry = _build_entry_from_dict(groups, day=day, tz=tz)
                if entry:
                    out.append(entry)

    if not out:
        list_keys = ["entries", "schedules", "lessons", "items"]
        for key in list_keys:
            values = data.get(key)
            if not isinstance(values, list):
                continue
            for item in values:
                entry = _build_entry_from_any_date(item, tz)
                if not entry:
                    continue
                if entry.day.year == year and entry.day.month == month:
                    out.append(entry)
            if out:
                break

    out.sort(key=_entry_sort_key)
    return out


def render_monthly_schedule_image(
    year: int,
    month: int,
    entries: list[ScheduleEntry],
    config: ScheduleRenderConfig,
) -> Image.Image:
    """Render 3:4 monthly schedule image."""
    width, height = config.width, config.height
    image = _create_gradient_background(width, height)
    draw = ImageDraw.Draw(image)

    fonts = _resolve_fonts(config.font_path)
    title_font = _load_font(fonts, size=max(60, width // 22), bold=True)
    subtitle_font = _load_font(fonts, size=max(26, width // 48), bold=False)
    weekday_font = _load_font(fonts, size=max(24, width // 56), bold=True)
    day_font = _load_font(fonts, size=max(28, width // 44), bold=True)
    item_font = _load_font(fonts, size=max(19, width // 77), bold=False)
    meta_font = _load_font(fonts, size=max(18, width // 82), bold=False)

    margin = max(56, width // 24)
    header_h = int(height * 0.2)
    header_rect = (margin, margin, width - margin, margin + header_h)
    draw.rounded_rectangle(
        header_rect,
        radius=max(22, width // 48),
        fill=PALETTE["paper"],
        outline=PALETTE["line"],
        width=2,
    )

    title_text = f"{year}年 {month}月"
    subtitle_text = "木彫り教室 スケジュール"
    updated_text = f"更新: {datetime.now(tz=JST).strftime('%Y-%m-%d')}"
    draw.text((header_rect[0] + 36, header_rect[1] + 28), title_text, fill=PALETTE["ink"], font=title_font)
    draw.text(
        (header_rect[0] + 36, header_rect[1] + 38 + _font_height(draw, title_font)),
        subtitle_text,
        fill=PALETTE["subtle"],
        font=subtitle_font,
    )
    draw.text(
        (header_rect[0] + 36, header_rect[3] - _font_height(draw, meta_font) - 22),
        updated_text,
        fill=PALETTE["muted"],
        font=meta_font,
    )

    week_top = header_rect[3] + max(28, height // 72)
    grid_top = week_top + max(44, height // 42)
    grid_bottom = height - margin

    month_matrix = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
    row_count = len(month_matrix)
    col_gap = max(8, width // 192)
    row_gap = max(8, height // 240)
    grid_width = width - margin * 2
    cell_width = int((grid_width - col_gap * 6) / 7)
    grid_height = grid_bottom - grid_top
    cell_height = int((grid_height - row_gap * (row_count - 1)) / max(1, row_count))

    for col, label in enumerate(WEEKDAY_LABELS):
        x = margin + col * (cell_width + col_gap)
        y = week_top
        week_rect = (x, y, x + cell_width, y + max(34, height // 56))
        fill = PALETTE["paper"]
        text_color = PALETTE["subtle"]
        if col == 5:
            fill = PALETTE["sat_bg"]
            text_color = PALETTE["accent_2"]
        elif col == 6:
            fill = PALETTE["sun_bg"]
            text_color = PALETTE["accent"]
        draw.rounded_rectangle(
            week_rect,
            radius=max(12, width // 128),
            fill=fill,
            outline=PALETTE["line_light"],
            width=1,
        )
        _draw_centered_text(draw, week_rect, label, weekday_font, text_color)

    events_by_day: dict[int, list[ScheduleEntry]] = {}
    for entry in entries:
        events_by_day.setdefault(entry.day.day, []).append(entry)
    for day_entries in events_by_day.values():
        day_entries.sort(key=_entry_sort_key)

    for row_index, week in enumerate(month_matrix):
        for col_index, day_num in enumerate(week):
            x1 = margin + col_index * (cell_width + col_gap)
            y1 = grid_top + row_index * (cell_height + row_gap)
            x2 = x1 + cell_width
            y2 = y1 + cell_height
            rect = (x1, y1, x2, y2)

            cell_fill = PALETTE["paper"]
            if col_index == 5:
                cell_fill = PALETTE["sat_bg"]
            elif col_index == 6:
                cell_fill = PALETTE["sun_bg"]
            if day_num == 0:
                cell_fill = tuple(int(c * 0.96) for c in PALETTE["line_light"])

            draw.rounded_rectangle(
                rect,
                radius=max(14, width // 110),
                fill=cell_fill,
                outline=PALETTE["line_light"],
                width=1,
            )

            if day_num == 0:
                continue

            day_color = PALETTE["ink"]
            if col_index == 5:
                day_color = PALETTE["accent_2"]
            elif col_index == 6:
                day_color = PALETTE["accent"]

            draw.text((x1 + 14, y1 + 10), str(day_num), fill=day_color, font=day_font)

            day_events = events_by_day.get(day_num, [])
            _draw_day_events(
                draw=draw,
                events=day_events,
                rect=rect,
                font=item_font,
                text_color=PALETTE["subtle"],
                muted_color=PALETTE["muted"],
            )

    return image


def save_image(image: Image.Image, output_path: Path) -> str:
    """Save image as JPEG/PNG based on file extension."""
    suffix = output_path.suffix.lower()
    if suffix == ".png":
        image.save(output_path, format="PNG")
        return "image/png"
    image.save(output_path, format="JPEG", quality=95, optimize=True)
    return "image/jpeg"


def image_to_bytes(image: Image.Image, mime_type: str = "image/jpeg") -> bytes:
    """Encode image bytes for posting."""
    from io import BytesIO

    buf = BytesIO()
    if mime_type == "image/png":
        image.save(buf, format="PNG")
    else:
        image.save(buf, format="JPEG", quality=95, optimize=True)
    return buf.getvalue()


def default_schedule_filename(year: int, month: int, mime_type: str = "image/jpeg") -> str:
    ext = ".png" if mime_type == "image/png" else ".jpg"
    return f"schedule-{year}-{month:02d}{ext}"


def _create_gradient_background(width: int, height: int) -> Image.Image:
    image = Image.new("RGB", (width, height), color=PALETTE["bg_top"])
    draw = ImageDraw.Draw(image)

    for y in range(height):
        t = y / max(1, height - 1)
        r = int(PALETTE["bg_top"][0] * (1 - t) + PALETTE["bg_bottom"][0] * t)
        g = int(PALETTE["bg_top"][1] * (1 - t) + PALETTE["bg_bottom"][1] * t)
        b = int(PALETTE["bg_top"][2] * (1 - t) + PALETTE["bg_bottom"][2] * t)
        draw.line((0, y, width, y), fill=(r, g, b))

    glow_bbox = (
        int(width * 0.45),
        int(height * -0.12),
        int(width * 1.05),
        int(height * 0.45),
    )
    draw.ellipse(glow_bbox, fill=(255, 244, 226))
    return image


def _draw_day_events(
    *,
    draw: ImageDraw.ImageDraw,
    events: list[ScheduleEntry],
    rect: tuple[int, int, int, int],
    font: ImageFont.ImageFont,
    text_color: tuple[int, int, int],
    muted_color: tuple[int, int, int],
) -> None:
    x1, y1, x2, y2 = rect
    start_x = x1 + 12
    start_y = y1 + 18 + _font_height(draw, font) + 14
    max_width = (x2 - x1) - 24
    line_height = _font_height(draw, font) + 4
    available_h = max(0, (y2 - y1) - (start_y - y1) - 10)
    max_lines = max(1, available_h // max(1, line_height))

    if not events:
        return

    visible_count = min(len(events), max_lines)
    if len(events) > max_lines and max_lines >= 2:
        visible_count = max_lines - 1

    y = start_y
    for entry in events[:visible_count]:
        label = _format_event_line(entry)
        clipped = _truncate_text(draw, label, font, max_width)
        draw.text((start_x, y), clipped, fill=text_color, font=font)
        y += line_height

    hidden_count = len(events) - visible_count
    if hidden_count > 0:
        draw.text((start_x, y), f"+{hidden_count}件", fill=muted_color, font=font)


def _format_event_line(entry: ScheduleEntry) -> str:
    time_part = entry.start.strftime("%H:%M") if entry.start else ""
    classroom_part = _short_classroom_name(entry.classroom)
    venue_part = f"({entry.venue})" if entry.venue else ""

    pieces = [piece for piece in [time_part, classroom_part, venue_part, entry.title] if piece]
    if pieces:
        return " ".join(pieces)
    return "予定あり"


def _short_classroom_name(value: str) -> str:
    return value.replace("教室", "").strip()


def _resolve_fonts(font_path: str) -> dict[str, list[str]]:
    regular_candidates = []
    bold_candidates = []

    if font_path:
        regular_candidates.append(font_path)
        bold_candidates.append(font_path)

    regular_candidates.extend(
        [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
        ]
    )
    bold_candidates.extend(
        [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
        ]
    )
    return {"regular": regular_candidates, "bold": bold_candidates}


def _load_font(candidates: dict[str, list[str]], size: int, *, bold: bool) -> ImageFont.ImageFont:
    key = "bold" if bold else "regular"
    for candidate in candidates[key]:
        if not candidate:
            continue
        try:
            return ImageFont.truetype(candidate, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
    color: tuple[int, int, int],
) -> None:
    x1, y1, x2, y2 = rect
    w = _text_width(draw, text, font)
    h = _font_height(draw, font)
    x = x1 + ((x2 - x1) - w) / 2
    y = y1 + ((y2 - y1) - h) / 2
    draw.text((x, y), text, font=font, fill=color)


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return max(0, right - left)


def _font_height(draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont) -> int:
    left, top, right, bottom = draw.textbbox((0, 0), "Ag", font=font)
    return max(1, bottom - top)


def _truncate_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> str:
    if _text_width(draw, text, font) <= max_width:
        return text
    ellipsis = "…"
    for end in range(len(text), 0, -1):
        candidate = text[:end].rstrip() + ellipsis
        if _text_width(draw, candidate, font) <= max_width:
            return candidate
    return ellipsis


def _parse_notion_datetime(value: str | None, tz: ZoneInfo) -> tuple[date | None, datetime | None]:
    if not value:
        return None, None
    value = value.strip()
    if not value:
        return None, None

    has_time = "T" in value
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    else:
        parsed = parsed.astimezone(tz)

    if not has_time:
        return parsed.date(), None
    return parsed.date(), parsed


def _parse_date_ymd(raw: Any) -> date | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _build_entry_from_any_date(item: Any, tz: ZoneInfo) -> ScheduleEntry | None:
    if not isinstance(item, dict):
        return None

    day = None
    start_dt = None
    end_dt = None
    date_keys = ["date", "day", "ymd", "start", "start_at", "starts_at", "startAt"]
    for key in date_keys:
        raw = item.get(key)
        if raw is None:
            continue
        parsed_day, parsed_dt = _parse_json_datetime(raw, tz)
        if parsed_day:
            day = parsed_day
            if parsed_dt:
                start_dt = parsed_dt
            break

    if day is None:
        return None

    for key in ["end", "end_at", "ends_at", "endAt"]:
        raw = item.get(key)
        if raw is None:
            continue
        _, parsed_dt = _parse_json_datetime(raw, tz)
        if parsed_dt:
            end_dt = parsed_dt
            break

    return _build_entry_from_dict(item, day=day, tz=tz, start_dt=start_dt, end_dt=end_dt)


def _build_entry_from_dict(
    item: Any,
    *,
    day: date,
    tz: ZoneInfo,
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
) -> ScheduleEntry | None:
    if not isinstance(item, dict):
        title = "レッスン"
        classroom = ""
        venue = ""
        return ScheduleEntry(day=day, title=title, classroom=classroom, venue=venue)

    classroom = _pick_text(item, ["classroom", "classroom_name", "studio", "教室"])
    venue = _pick_text(item, ["venue", "venue_name", "会場", "location"])
    title = _pick_text(item, ["title", "name", "label", "event_name", "lesson_name", "lesson", "type"])

    if not title:
        participants = item.get("participants")
        if isinstance(participants, list) and participants:
            title = f"{len(participants)}名"
        elif _pick_text(item, ["lesson_id", "lessonId"]):
            title = "レッスン"
        else:
            title = "予定"

    if start_dt is None:
        for key in ["start", "start_at", "starts_at", "startAt", "time", "start_time"]:
            raw = item.get(key)
            if raw is None:
                continue
            parsed_day, parsed_dt = _parse_json_datetime(raw, tz, base_day=day)
            if parsed_dt:
                start_dt = parsed_dt
                if parsed_day:
                    day = parsed_day
                break

    if end_dt is None:
        for key in ["end", "end_at", "ends_at", "endAt", "end_time"]:
            raw = item.get(key)
            if raw is None:
                continue
            _, parsed_dt = _parse_json_datetime(raw, tz, base_day=day)
            if parsed_dt:
                end_dt = parsed_dt
                break

    return ScheduleEntry(
        day=day,
        title=title,
        classroom=classroom,
        venue=venue,
        start=start_dt,
        end=end_dt,
    )


def _parse_json_datetime(raw: Any, tz: ZoneInfo, base_day: date | None = None) -> tuple[date | None, datetime | None]:
    if raw is None:
        return None, None

    if isinstance(raw, datetime):
        value = raw.astimezone(tz) if raw.tzinfo else raw.replace(tzinfo=tz)
        return value.date(), value
    if isinstance(raw, date):
        return raw, None

    value = str(raw).strip()
    if not value:
        return None, None

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    if "T" in value:
        try:
            parsed = datetime.fromisoformat(value)
            parsed = parsed.astimezone(tz) if parsed.tzinfo else parsed.replace(tzinfo=tz)
            return parsed.date(), parsed
        except ValueError:
            return None, None

    # HH:MM style (time only)
    if len(value) <= 8 and ":" in value:
        try:
            parsed_time = datetime.strptime(value, "%H:%M").time()
            day = base_day or datetime.now(tz=tz).date()
            combined = datetime.combine(day, parsed_time, tz)
            return combined.date(), combined
        except ValueError:
            return None, None

    # Date-only style.
    parsed_day = _parse_date_ymd(value)
    if parsed_day:
        return parsed_day, None

    # Last try for variants like "YYYY-MM-DD HH:MM".
    try:
        parsed = datetime.fromisoformat(value.replace(" ", "T"))
        parsed = parsed.astimezone(tz) if parsed.tzinfo else parsed.replace(tzinfo=tz)
        return parsed.date(), parsed
    except ValueError:
        return None, None


def _pick_text(obj: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = obj.get(key)
        text = _to_text(value)
        if text:
            return text
    return ""


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        pieces = [_to_text(v) for v in value]
        return " / ".join([p for p in pieces if p])
    if isinstance(value, dict):
        for key in ["name", "title", "label", "value", "display_name", "displayName"]:
            text = _to_text(value.get(key))
            if text:
                return text
    return ""


def _extract_text(prop: object) -> str:
    if not isinstance(prop, dict):
        return ""

    p_type = prop.get("type")
    if p_type == "title":
        return _extract_rich_text(prop.get("title"))
    if p_type == "rich_text":
        return _extract_rich_text(prop.get("rich_text"))
    if p_type == "select":
        return str((prop.get("select") or {}).get("name") or "").strip()
    if p_type == "status":
        return str((prop.get("status") or {}).get("name") or "").strip()
    if p_type == "multi_select":
        names = [str(item.get("name") or "").strip() for item in prop.get("multi_select", [])]
        return " ".join([name for name in names if name])
    if p_type == "number":
        number = prop.get("number")
        return str(number) if number is not None else ""
    if p_type == "url":
        return str(prop.get("url") or "").strip()
    if p_type == "email":
        return str(prop.get("email") or "").strip()
    if p_type == "phone_number":
        return str(prop.get("phone_number") or "").strip()
    if p_type == "formula":
        formula = prop.get("formula") or {}
        formula_type = formula.get("type")
        if formula_type == "string":
            return str(formula.get("string") or "").strip()
        if formula_type == "number":
            number = formula.get("number")
            return str(number) if number is not None else ""
        if formula_type == "boolean":
            return "true" if formula.get("boolean") else "false"
    return ""


def _extract_rich_text(items: object) -> str:
    if not isinstance(items, list):
        return ""
    parts = [str(item.get("plain_text") or "") for item in items if isinstance(item, dict)]
    return "".join(parts).strip()


def _entry_sort_key(entry: ScheduleEntry) -> tuple[date, int, int, str]:
    if entry.start:
        return (entry.day, entry.start.hour, entry.start.minute, entry.title)
    return (entry.day, 99, 99, entry.title)


def _normalize_hashtags(raw: str) -> str:
    words = []
    for token in raw.replace("　", " ").split():
        value = token.strip()
        if not value:
            continue
        if not value.startswith("#"):
            value = f"#{value}"
        words.append(value)
    return " ".join(words)


def _safe_positive_int(raw: str | None, default: int) -> int:
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default
