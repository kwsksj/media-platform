"""Monthly classroom schedule image generation from Notion."""

from __future__ import annotations

import calendar
import logging
import os
import re
from dataclasses import dataclass, field
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
    "bg_top": (221, 214, 206),
    "bg_bottom": (221, 214, 206),
    "paper": (255, 255, 255),
    "empty_cell": (246, 242, 238),
    "ink": (78, 52, 46),
    "subtle": (120, 90, 78),
    "muted": (161, 136, 127),
    "line": (211, 194, 185),
    "line_light": (232, 221, 214),
    "accent": (191, 102, 43),
    "accent_2": (74, 128, 49),
    "sun_bg": (250, 236, 220),
    "sat_bg": (231, 243, 229),
}

WEEKDAY_LABELS = ["月", "火", "水", "木", "金", "土", "日"]

# Classroom colors aligned with reservation app palette.
CLASSROOM_CARD_STYLES = {
    "tokyo": {"fill": (233, 131, 136), "text": (255, 255, 255)},
    "tsukuba": {"fill": (106, 189, 166), "text": (255, 255, 255)},
    "numazu": {"fill": (106, 172, 217), "text": (255, 255, 255)},
    "default": {"fill": (162, 173, 186), "text": (255, 255, 255)},
}

VENUE_BADGE_STYLES = {
    "浅草橋": {"fill": (255, 255, 255), "text": (244, 139, 75)},
    "東池袋": {"fill": (255, 255, 255), "text": (196, 120, 209)},
    "複数会場": {"fill": (255, 255, 255), "text": (145, 153, 169)},
    "default": {"fill": (255, 255, 255), "text": (145, 153, 169)},
}

NIGHT_BADGE_STYLE = {
    "fill": (57, 84, 152),
    "text": (255, 255, 255),
}

ZEN_REGULAR_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/zenkakugothicnew/ZenKakuGothicNew-Regular.ttf"
ZEN_BOLD_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/zenkakugothicnew/ZenKakuGothicNew-Bold.ttf"
COURIER_REGULAR_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/courierprime/CourierPrime-Regular.ttf"
COURIER_BOLD_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/courierprime/CourierPrime-Bold.ttf"

COURIER_ASCENT_OVERRIDE = 0.85
COURIER_DESCENT_OVERRIDE = 0.15
COURIER_LINE_GAP_OVERRIDE = 0.0
COURIER_SIZE_ADJUST = 1.20

ASCII_RUN_RE = re.compile(r"[\x00-\x7F]+")


@dataclass(frozen=True)
class ScheduleEntry:
    """One schedule item for a single day."""

    day: date
    title: str
    classroom: str
    venue: str
    start: datetime | None = None
    end: datetime | None = None
    slot: str = ""


@dataclass
class DayCard:
    """Grouped card per day/classroom."""

    classroom: str
    venue: str
    first_time: str = ""
    second_time: str = ""
    beginner_time: str = ""
    has_night: bool = False
    other_times: list[str] = field(default_factory=list)


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
    font_cache_dir: str = ""
    font_jp_regular_path: str = ""
    font_jp_bold_path: str = ""
    font_num_regular_path: str = ""
    font_num_bold_path: str = ""

    @classmethod
    def from_env(cls) -> "ScheduleRenderConfig":
        return cls(
            width=_safe_positive_int(os.environ.get("MONTHLY_SCHEDULE_IMAGE_WIDTH"), 1536),
            height=_safe_positive_int(os.environ.get("MONTHLY_SCHEDULE_IMAGE_HEIGHT"), 2048),
            font_path=os.environ.get("MONTHLY_SCHEDULE_FONT_PATH", "").strip(),
            font_cache_dir=os.environ.get("MONTHLY_SCHEDULE_FONT_CACHE_DIR", "").strip(),
            font_jp_regular_path=os.environ.get("MONTHLY_SCHEDULE_FONT_JP_REGULAR_PATH", "").strip(),
            font_jp_bold_path=os.environ.get("MONTHLY_SCHEDULE_FONT_JP_BOLD_PATH", "").strip(),
            font_num_regular_path=os.environ.get("MONTHLY_SCHEDULE_FONT_NUM_REGULAR_PATH", "").strip(),
            font_num_bold_path=os.environ.get("MONTHLY_SCHEDULE_FONT_NUM_BOLD_PATH", "").strip(),
        )


@dataclass(frozen=True)
class ScheduleFontPaths:
    """Resolved font paths used for rendering."""

    jp_regular: str
    jp_bold: str
    num_regular: str
    num_bold: str


@dataclass(frozen=True)
class ScheduleFontSet:
    """Pair of Japanese/ASCII fonts at one size."""

    jp_font: ImageFont.ImageFont
    num_font: ImageFont.ImageFont
    num_baseline_offset: int = 0
    num_line_height: int = 0


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
            slot=_normalize_slot("", title),
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
    payload = data
    wrapped = data.get("data")
    if isinstance(wrapped, dict):
        payload = wrapped

    dates = payload.get("dates")
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
            values = payload.get(key)
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

    font_paths = _resolve_required_font_paths(config)
    title_fonts = _load_font_set(font_paths, size=max(72, width // 17), bold=True)
    month_fonts = _load_font_set(font_paths, size=max(64, width // 20), bold=True)
    weekday_fonts = _load_font_set(font_paths, size=max(28, width // 50), bold=True)
    day_fonts = _load_font_set(font_paths, size=max(38, width // 32), bold=True)
    classroom_fonts = _load_font_set(font_paths, size=max(33, width // 39), bold=True)
    venue_badge_fonts = _load_font_set(font_paths, size=max(22, width // 62), bold=True)
    time_fonts = _load_font_set(font_paths, size=max(25, width // 58), bold=True)
    beginner_label_fonts = _load_font_set(font_paths, size=max(22, width // 64), bold=True)
    hidden_fonts = _load_font_set(font_paths, size=max(17, width // 82), bold=True)
    night_badge_fonts = _load_font_set(font_paths, size=max(18, width // 74), bold=True)

    margin = max(24, width // 56)
    title_text = "川崎誠二 木彫り教室"
    month_text = f"{year}年 {month}月"
    title_w = _mixed_text_width(draw, title_text, title_fonts)
    title_h = _mixed_font_height(draw, title_fonts)
    month_w = _mixed_text_width(draw, month_text, month_fonts)
    month_h = _mixed_font_height(draw, month_fonts)
    header_bottom = margin - 2 + max(title_h, month_h)
    title_x = margin
    title_y = header_bottom - title_h
    month_x = width - margin - month_w
    min_month_x = title_x + title_w + max(18, width // 72)
    if month_x < min_month_x:
        month_x = min_month_x
    month_y = header_bottom - month_h

    _draw_mixed_text(draw, (title_x, title_y), title_text, title_fonts, fill=PALETTE["ink"])
    _draw_mixed_text(draw, (month_x, month_y), month_text, month_fonts, fill=PALETTE["ink"])

    week_top = header_bottom + max(18, height // 84)
    week_height = max(46, height // 52)
    grid_bottom = height - margin

    month_matrix = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
    row_count = len(month_matrix)
    col_gap = max(8, width // 192)
    row_gap = max(6, height // 320)
    grid_top = week_top + week_height + row_gap
    grid_width = width - margin * 2
    usable_grid_width = max(7, grid_width - col_gap * 6)
    cell_width_base = usable_grid_width // 7
    cell_width_remainder = usable_grid_width % 7
    cell_widths = [
        cell_width_base + (1 if col < cell_width_remainder else 0)
        for col in range(7)
    ]
    grid_height = grid_bottom - grid_top
    cell_height = int((grid_height - row_gap * (row_count - 1)) / max(1, row_count))
    col_lefts: list[int] = []
    cursor_x = margin
    for col in range(7):
        col_lefts.append(cursor_x)
        cursor_x += cell_widths[col] + col_gap

    for col, label in enumerate(WEEKDAY_LABELS):
        x = col_lefts[col]
        y = week_top
        week_rect = (x, y, x + cell_widths[col], y + week_height)
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
            radius=max(14, width // 110),
            fill=fill,
        )
        _draw_centered_mixed_text(draw, week_rect, label, weekday_fonts, text_color)

    events_by_day: dict[int, list[ScheduleEntry]] = {}
    for entry in entries:
        events_by_day.setdefault(entry.day.day, []).append(entry)
    for day_entries in events_by_day.values():
        day_entries.sort(key=_entry_sort_key)

    for row_index, week in enumerate(month_matrix):
        for col_index, day_num in enumerate(week):
            x1 = col_lefts[col_index]
            y1 = grid_top + row_index * (cell_height + row_gap)
            x2 = x1 + cell_widths[col_index]
            y2 = y1 + cell_height
            rect = (x1, y1, x2, y2)

            cell_fill = PALETTE["paper"]
            if col_index == 5:
                cell_fill = PALETTE["sat_bg"]
            elif col_index == 6:
                cell_fill = PALETTE["sun_bg"]
            if day_num == 0:
                cell_fill = PALETTE["empty_cell"]

            draw.rounded_rectangle(
                rect,
                radius=max(14, width // 110),
                fill=cell_fill,
            )

            if day_num == 0:
                continue

            day_color = PALETTE["ink"]
            if col_index == 5:
                day_color = PALETTE["accent_2"]
            elif col_index == 6:
                day_color = PALETTE["accent"]

            _draw_mixed_text(
                draw,
                (x1 + 14, y1 + 6),
                str(day_num),
                day_fonts,
                fill=day_color,
            )

            day_events = events_by_day.get(day_num, [])
            _draw_day_events(
                draw=draw,
                events=day_events,
                rect=rect,
                day_number_height=_mixed_font_height(draw, day_fonts),
                classroom_fonts=classroom_fonts,
                venue_badge_fonts=venue_badge_fonts,
                time_fonts=time_fonts,
                beginner_label_fonts=beginner_label_fonts,
                hidden_fonts=hidden_fonts,
                night_badge_fonts=night_badge_fonts,
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
    return Image.new("RGB", (width, height), color=PALETTE["bg_top"])


def _draw_day_events(
    *,
    draw: ImageDraw.ImageDraw,
    events: list[ScheduleEntry],
    rect: tuple[int, int, int, int],
    day_number_height: int,
    classroom_fonts: ScheduleFontSet,
    venue_badge_fonts: ScheduleFontSet,
    time_fonts: ScheduleFontSet,
    beginner_label_fonts: ScheduleFontSet,
    hidden_fonts: ScheduleFontSet,
    night_badge_fonts: ScheduleFontSet,
    muted_color: tuple[int, int, int],
) -> None:
    x1, y1, x2, y2 = rect
    cards = _build_day_cards(events)
    if not cards:
        return

    cell_margin_x = 8
    cell_margin_bottom = 6
    start_x = x1 + cell_margin_x
    start_y_min = y1 + max(50, day_number_height + 16)
    max_width = (x2 - x1) - cell_margin_x * 2

    classroom_h = _mixed_font_height(draw, classroom_fonts)
    line_h = _mixed_font_height(draw, time_fonts) + 3
    title_to_time_gap = 8
    beginner_gap = 6
    beginner_heading_h = _mixed_font_height(draw, beginner_label_fonts)
    base_card_h = max(90, classroom_h + title_to_time_gap + line_h * 2 + 20)
    beginner_extra_h = beginner_gap + beginner_heading_h + line_h
    card_gap = 6
    card_h = base_card_h + beginner_extra_h
    day_available_h = max(0, y2 - start_y_min - cell_margin_bottom)
    slot_h = card_h + card_gap
    max_cards = max(1, (day_available_h + card_gap) // max(1, slot_h))
    visible_cards = cards[:max_cards]
    if not visible_cards and cards:
        visible_cards = [cards[0]]
    has_beginner_block = True
    used_h = len(visible_cards) * card_h + max(0, len(visible_cards) - 1) * card_gap
    start_y = max(start_y_min, y2 - cell_margin_bottom - used_h)
    slot_h = card_h + card_gap

    y = start_y
    for card in visible_cards:
        lines, beginner_time = _build_fixed_time_rows(card)
        class_style = _get_classroom_card_style(card.classroom)
        card_rect = (start_x, y, start_x + max_width, y + card_h)
        draw.rounded_rectangle(
            card_rect,
            radius=10,
            fill=class_style["fill"],
        )

        # Keep a slightly wider left inset for classroom title, while tightening
        # overall horizontal padding for time lines.
        inner_x = card_rect[0] + 6
        inner_right = card_rect[2] - 6
        class_x = inner_x + 2
        class_y = card_rect[1] + 4

        classroom_text = _short_classroom_name(card.classroom) or "未定"
        venue_badge: tuple[str, dict[str, tuple[int, int, int]], ScheduleFontSet, int, int] | None = None
        class_right = inner_right
        if card.venue:
            venue_style = _get_venue_badge_style(card.venue)
            max_badge_text_w = max(30, max_width // 2)
            fit_badge_fonts = _fit_font_set_to_width(draw, card.venue, venue_badge_fonts, max_badge_text_w)
            badge_pad_top = 1
            badge_pad_bottom = 4
            badge_h = _mixed_font_height(draw, fit_badge_fonts) + badge_pad_top + badge_pad_bottom
            badge_w = _mixed_text_width(draw, card.venue, fit_badge_fonts) + 12
            badge_w = min(badge_w, max_badge_text_w + 12)
            class_right = max(class_x + 12, inner_right - badge_w - 8)
            venue_badge = (card.venue, venue_style, fit_badge_fonts, badge_w, badge_h)

        class_area_w = max(10, class_right - class_x)
        fit_classroom_fonts = _fit_font_set_to_width(draw, classroom_text, classroom_fonts, class_area_w)
        _draw_mixed_text(draw, (class_x, class_y), classroom_text, fit_classroom_fonts, fill=class_style["text"])
        class_h = _mixed_font_height(draw, fit_classroom_fonts)
        class_bottom = class_y + class_h

        if venue_badge:
            badge_text, badge_style, fit_badge_fonts, badge_w, badge_h = venue_badge
            badge_rect = (inner_right - badge_w, class_bottom - badge_h, inner_right, class_bottom)
            draw.rounded_rectangle(
                badge_rect,
                radius=8,
                fill=badge_style["fill"],
            )
            _draw_mixed_text(
                draw,
                (badge_rect[0] + 6, badge_rect[1]),
                badge_text,
                fit_badge_fonts,
                fill=badge_style["text"],
            )

        night_time_indexes = _resolve_night_time_line_indexes(card, lines)
        regular_time_fonts_for_card: ScheduleFontSet | None = None
        line_y = class_y + class_h + title_to_time_gap
        for index, value in enumerate(lines):
            line_x = inner_x
            line_area_w = max(10, inner_right - line_x)
            if index in night_time_indexes:
                badge_text = "夜"
                fit_night_fonts = _fit_font_set_to_width(draw, badge_text, night_badge_fonts, max(16, line_area_w // 3))
                night_pad_top = 1
                night_pad_bottom = 4
                night_badge_h = _mixed_font_height(draw, fit_night_fonts) + night_pad_top + night_pad_bottom
                night_badge_w = _mixed_text_width(draw, badge_text, fit_night_fonts) + 12
                night_y = line_y + max(0, (line_h - night_badge_h) // 2)
                night_rect = (line_x, night_y, line_x + night_badge_w, night_y + night_badge_h)
                draw.rounded_rectangle(night_rect, radius=7, fill=NIGHT_BADGE_STYLE["fill"])
                _draw_mixed_text(
                    draw,
                    (night_rect[0] + 6, night_rect[1]),
                    badge_text,
                    fit_night_fonts,
                    fill=NIGHT_BADGE_STYLE["text"],
                )
                line_x = night_rect[2] + 6
                line_area_w = max(10, inner_right - line_x)

            if value:
                fit_line_fonts = _fit_font_set_to_width(draw, value, time_fonts, line_area_w)
                regular_time_fonts_for_card = _pick_smaller_font_set(regular_time_fonts_for_card, fit_line_fonts)
                _draw_mixed_text(
                    draw,
                    (line_x, line_y),
                    value,
                    fit_line_fonts,
                    fill=class_style["text"],
                )
            line_y += line_h

        if has_beginner_block:
            line_y += beginner_gap
            if beginner_time:
                beginner_title = "はじめての方"
                fit_beginner_title_fonts = _fit_font_set_to_width(draw, beginner_title, beginner_label_fonts, max(10, inner_right - inner_x))
                _draw_mixed_text(
                    draw,
                    (class_x, line_y),
                    beginner_title,
                    fit_beginner_title_fonts,
                    fill=class_style["text"],
                )
                line_y += line_h
                beginner_base_fonts = regular_time_fonts_for_card or time_fonts
                fit_beginner_time_fonts = _fit_font_set_to_width(
                    draw,
                    beginner_time,
                    beginner_base_fonts,
                    max(10, inner_right - inner_x),
                )
                _draw_mixed_text(
                    draw,
                    (inner_x, line_y),
                    beginner_time,
                    fit_beginner_time_fonts,
                    fill=class_style["text"],
                )
        y += slot_h

    hidden_y = y - 2
    hidden_count = len(cards) - len(visible_cards)
    if hidden_count > 0:
        _draw_mixed_text(
            draw,
            (start_x + 4, hidden_y),
            f"+{hidden_count}件",
            hidden_fonts,
            fill=muted_color,
        )


def _short_classroom_name(value: str) -> str:
    return value.replace("教室", "").strip()


def _format_time_range(entry: ScheduleEntry) -> str:
    start_text = _format_clock(entry.start)
    end_text = _format_clock(entry.end)
    if start_text and end_text:
        return f"{start_text}~{end_text}"
    if start_text:
        return f"{start_text}~"
    if end_text:
        return f"~{end_text}"
    return "時間未定"


def _format_clock(value: datetime | None) -> str:
    if value is None:
        return ""
    return f"{value.hour:2d}:{value.minute:02d}"


def _expand_time_values(value: str) -> list[str]:
    text = str(value or "")
    if not text.strip():
        return []
    return [item.rstrip() for item in text.split(" / ") if item.strip()]


def _build_fixed_time_rows(card: DayCard) -> tuple[list[str], str]:
    values: list[str] = []
    for raw in [card.first_time, card.second_time]:
        values.extend(_expand_time_values(raw))
    beginner_values = _expand_time_values(card.beginner_time)

    if not values and not beginner_values:
        return ["時間未定", ""], ""

    morning: list[str] = []
    afternoon: list[str] = []
    unknown: list[str] = []
    night_values: list[str] = []
    non_night_values: list[str] = []
    for value in values:
        if _is_night_time_text(value):
            night_values.append(value)
        else:
            non_night_values.append(value)
        hour = _extract_start_hour_from_time_text(value)
        if hour is None:
            unknown.append(value)
        elif hour < 12:
            morning.append(value)
        else:
            afternoon.append(value)

    non_night_morning = [value for value in morning if value in non_night_values]
    non_night_afternoon = [value for value in afternoon if value in non_night_values]
    non_night_unknown = [value for value in unknown if value in non_night_values]

    line1 = non_night_morning[0] if non_night_morning else ""
    if not line1 and non_night_afternoon:
        line1 = non_night_afternoon[0]
    if not line1 and non_night_unknown:
        line1 = non_night_unknown[0]
    if not line1 and non_night_values:
        line1 = non_night_values[0]

    line2 = night_values[0] if night_values else ""
    if not line2:
        for candidate in [*non_night_afternoon, *non_night_unknown, *non_night_values]:
            if candidate and candidate != line1:
                line2 = candidate
                break

    if not line1 and line2 and _is_night_time_text(line2):
        line1 = ""

    beginner_time = beginner_values[0] if beginner_values else ""
    return [line1, line2], beginner_time


def _extract_start_hour_from_time_text(value: str) -> int | None:
    text = str(value or "")
    for token in text.replace("~", " ").split():
        if ":" not in token:
            continue
        try:
            hour = int(token.split(":", 1)[0])
        except ValueError:
            continue
        if 0 <= hour <= 23:
            return hour
    return None


def _build_day_cards(events: list[ScheduleEntry]) -> list[DayCard]:
    by_key: dict[str, DayCard] = {}

    for entry in sorted(events, key=_entry_sort_key):
        classroom = (entry.classroom or "").strip()
        venue = (entry.venue or "").strip()
        key = classroom or "未定"
        card = by_key.get(key)
        if card is None:
            card = DayCard(classroom=classroom, venue=venue)
            by_key[key] = card
        elif venue:
            if not card.venue:
                card.venue = venue
            elif card.venue != venue and card.venue != "複数会場":
                card.venue = "複数会場"

        time_text = _format_time_range(entry)
        slot = _normalize_slot(entry.slot, entry.title)
        if slot == "first":
            card.first_time = _merge_time_text(card.first_time, time_text)
        elif slot == "second":
            card.second_time = _merge_time_text(card.second_time, time_text)
        elif slot == "beginner":
            card.beginner_time = _merge_time_text(card.beginner_time, time_text)
        elif time_text and time_text not in card.other_times:
            card.other_times.append(time_text)

        if _is_night_entry(entry):
            card.has_night = True

    cards = list(by_key.values())
    for card in cards:
        for time_text in card.other_times:
            if not card.first_time:
                card.first_time = time_text
            elif not card.second_time and time_text != card.first_time:
                card.second_time = time_text
            elif not card.beginner_time and time_text not in {card.first_time, card.second_time}:
                card.beginner_time = time_text

    def _card_sort_key(card: DayCard) -> tuple[int, str]:
        first = card.first_time or card.second_time or card.beginner_time
        return (_time_text_to_sort_key(first), card.classroom)

    cards.sort(key=_card_sort_key)
    return cards


def _normalize_slot(slot: str, title: str = "") -> str:
    value = (slot or "").strip().lower()
    title_value = (title or "").strip()

    # Prefer explicit slot value from JSON over title text.
    if any(token in value for token in ["beginner", "初回", "はじめて"]):
        return "beginner"
    if any(token in value for token in ["second", "2部", "第2", "二部"]):
        return "second"
    if any(token in value for token in ["first", "1部", "第1", "一部"]):
        return "first"

    combined = title_value
    if any(token in combined for token in ["初回", "はじめて"]):
        return "beginner"
    if any(token in combined for token in ["2部", "第2", "二部"]):
        return "second"
    if any(token in combined for token in ["1部", "第1", "一部"]):
        return "first"
    return ""


def _merge_time_text(existing: str, new_text: str) -> str:
    if not new_text:
        return existing
    if not existing:
        return new_text
    values = [value.rstrip() for value in existing.split(" / ") if value.strip()]
    normalized_new = new_text.rstrip()
    if normalized_new in values:
        return existing
    return f"{existing} / {new_text}"


def _time_text_to_sort_key(time_text: str) -> int:
    value = (time_text or "").strip()
    if not value:
        return 10_000
    for token in value.replace(" - ", " ").replace("-", " ").replace("~", " ").split():
        if ":" not in token:
            continue
        try:
            hour_str, minute_str = token.split(":", 1)
            hour = int(hour_str)
            minute = int(minute_str)
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return hour * 60 + minute
        except ValueError:
            continue
    return 10_000


def _is_night_entry(entry: ScheduleEntry) -> bool:
    if entry.start and entry.start.hour >= 17:
        return True
    if entry.end and entry.end.hour >= 20:
        return True
    slot_text = (entry.slot or "").strip().lower()
    if "night" in slot_text or "夜" in slot_text:
        return True
    title = (entry.title or "").strip()
    if "夜" in title:
        return True
    return False


def _resolve_night_time_line_indexes(
    card: DayCard,
    lines: list[str],
) -> set[int]:
    if not card.has_night:
        return set()

    if len(lines) >= 2 and lines[1] and _is_night_time_text(lines[1]):
        # Keep badge on first time row while showing night time on second row.
        return {0}

    explicit = {index for index, value in enumerate(lines) if value and _is_night_time_text(value)}
    if explicit:
        if 0 in explicit:
            return {0}
        return explicit

    if len(lines) >= 2 and lines[1]:
        return {0}
    if lines and lines[0]:
        return {0}
    return set()


def _is_night_time_text(value: str) -> bool:
    for token in str(value or "").replace("~", " ").split():
        if ":" not in token:
            continue
        try:
            hour = int(token.split(":", 1)[0])
        except ValueError:
            continue
        if 0 <= hour <= 23:
            return hour >= 17
    return False


def _pick_smaller_font_set(current: ScheduleFontSet | None, candidate: ScheduleFontSet) -> ScheduleFontSet:
    if current is None:
        return candidate
    current_size = int(getattr(current.num_font, "size", 0))
    candidate_size = int(getattr(candidate.num_font, "size", 0))
    if candidate_size < current_size:
        return candidate
    return current


def _get_classroom_card_style(classroom: str) -> dict[str, tuple[int, int, int]]:
    value = (classroom or "").strip()
    if "東京" in value:
        return CLASSROOM_CARD_STYLES["tokyo"]
    if "つくば" in value:
        return CLASSROOM_CARD_STYLES["tsukuba"]
    if "沼津" in value:
        return CLASSROOM_CARD_STYLES["numazu"]
    return CLASSROOM_CARD_STYLES["default"]


def _get_venue_badge_style(venue: str) -> dict[str, tuple[int, int, int]]:
    value = (venue or "").strip()
    if value in VENUE_BADGE_STYLES:
        return VENUE_BADGE_STYLES[value]
    return VENUE_BADGE_STYLES["default"]


def _resolve_required_font_paths(config: ScheduleRenderConfig) -> ScheduleFontPaths:
    cache_dir = Path(config.font_cache_dir).expanduser() if config.font_cache_dir else Path.home() / ".cache" / "media-platform-fonts" / "monthly_schedule"
    cache_dir.mkdir(parents=True, exist_ok=True)

    base_path = Path(config.font_path).expanduser() if config.font_path else None
    base_files: dict[str, str] = {}
    if base_path:
        if base_path.is_file():
            for key in ["jp_regular", "jp_bold", "num_regular", "num_bold"]:
                base_files[key] = str(base_path)
        elif base_path.is_dir():
            base_files = {
                "jp_regular": str(base_path / "ZenKakuGothicNew-Regular.ttf"),
                "jp_bold": str(base_path / "ZenKakuGothicNew-Bold.ttf"),
                "num_regular": str(base_path / "CourierPrime-Regular.ttf"),
                "num_bold": str(base_path / "CourierPrime-Bold.ttf"),
            }

    jp_regular = _resolve_single_font(
        label="Zen Kaku Gothic New Regular",
        explicit=config.font_jp_regular_path,
        candidates=[
            base_files.get("jp_regular", ""),
            str(cache_dir / "ZenKakuGothicNew-Regular.ttf"),
            "/usr/share/fonts/truetype/zen-kaku-gothic-new/ZenKakuGothicNew-Regular.ttf",
            "/usr/share/fonts/truetype/zenkakugothicnew/ZenKakuGothicNew-Regular.ttf",
            "/usr/local/share/fonts/ZenKakuGothicNew-Regular.ttf",
            str(Path.home() / ".local/share/fonts/ZenKakuGothicNew-Regular.ttf"),
            str(Path.home() / "Library/Fonts/ZenKakuGothicNew-Regular.ttf"),
        ],
        download_url=ZEN_REGULAR_URL,
        download_path=cache_dir / "ZenKakuGothicNew-Regular.ttf",
    )
    jp_bold = _resolve_single_font(
        label="Zen Kaku Gothic New Bold",
        explicit=config.font_jp_bold_path,
        candidates=[
            base_files.get("jp_bold", ""),
            str(cache_dir / "ZenKakuGothicNew-Bold.ttf"),
            "/usr/share/fonts/truetype/zen-kaku-gothic-new/ZenKakuGothicNew-Bold.ttf",
            "/usr/share/fonts/truetype/zenkakugothicnew/ZenKakuGothicNew-Bold.ttf",
            "/usr/local/share/fonts/ZenKakuGothicNew-Bold.ttf",
            str(Path.home() / ".local/share/fonts/ZenKakuGothicNew-Bold.ttf"),
            str(Path.home() / "Library/Fonts/ZenKakuGothicNew-Bold.ttf"),
        ],
        download_url=ZEN_BOLD_URL,
        download_path=cache_dir / "ZenKakuGothicNew-Bold.ttf",
    )
    num_regular = _resolve_single_font(
        label="Courier Prime Regular",
        explicit=config.font_num_regular_path,
        candidates=[
            base_files.get("num_regular", ""),
            str(cache_dir / "CourierPrime-Regular.ttf"),
            "/usr/share/fonts/truetype/courier-prime/CourierPrime-Regular.ttf",
            "/usr/share/fonts/truetype/courierprime/CourierPrime-Regular.ttf",
            "/usr/local/share/fonts/CourierPrime-Regular.ttf",
            str(Path.home() / ".local/share/fonts/CourierPrime-Regular.ttf"),
            str(Path.home() / "Library/Fonts/CourierPrime-Regular.ttf"),
        ],
        download_url=COURIER_REGULAR_URL,
        download_path=cache_dir / "CourierPrime-Regular.ttf",
    )
    num_bold = _resolve_single_font(
        label="Courier Prime Bold",
        explicit=config.font_num_bold_path,
        candidates=[
            base_files.get("num_bold", ""),
            str(cache_dir / "CourierPrime-Bold.ttf"),
            "/usr/share/fonts/truetype/courier-prime/CourierPrime-Bold.ttf",
            "/usr/share/fonts/truetype/courierprime/CourierPrime-Bold.ttf",
            "/usr/local/share/fonts/CourierPrime-Bold.ttf",
            str(Path.home() / ".local/share/fonts/CourierPrime-Bold.ttf"),
            str(Path.home() / "Library/Fonts/CourierPrime-Bold.ttf"),
        ],
        download_url=COURIER_BOLD_URL,
        download_path=cache_dir / "CourierPrime-Bold.ttf",
    )
    return ScheduleFontPaths(
        jp_regular=jp_regular,
        jp_bold=jp_bold,
        num_regular=num_regular,
        num_bold=num_bold,
    )


def _resolve_single_font(
    *,
    label: str,
    explicit: str,
    candidates: list[str],
    download_url: str,
    download_path: Path,
) -> str:
    checked: list[str] = []
    for candidate in [explicit, *candidates]:
        value = str(candidate or "").strip()
        if not value:
            continue
        checked.append(value)
        if _is_valid_font_path(value):
            return value

    try:
        _download_font(download_url, download_path)
    except Exception as e:
        logger.warning("failed to download %s: %s", label, e)
    if _is_valid_font_path(str(download_path)):
        return str(download_path)

    checked_text = ", ".join(checked) if checked else "(none)"
    raise RuntimeError(f"{label} not found. checked={checked_text}")


def _download_font(url: str, target: Path) -> None:
    import requests

    target.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    body = response.content
    if not body:
        raise RuntimeError(f"empty response from {url}")
    temp = target.with_suffix(f"{target.suffix}.tmp")
    temp.write_bytes(body)
    temp.replace(target)


def _is_valid_font_path(path: str) -> bool:
    try:
        p = Path(path).expanduser()
    except Exception:
        return False
    if not p.exists() or not p.is_file():
        return False
    try:
        ImageFont.truetype(str(p), size=24)
    except Exception:
        return False
    return True


def _load_font_set(paths: ScheduleFontPaths, size: int, *, bold: bool) -> ScheduleFontSet:
    jp_path = paths.jp_bold if bold else paths.jp_regular
    num_path = paths.num_bold if bold else paths.num_regular
    jp_font = ImageFont.truetype(jp_path, size=size)
    num_size = max(1, int(round(size * COURIER_SIZE_ADJUST)))
    num_font = ImageFont.truetype(num_path, size=num_size)
    num_ascent, _ = num_font.getmetrics()
    target_ascent = max(1, int(round(num_size * COURIER_ASCENT_OVERRIDE)))
    target_descent = max(1, int(round(num_size * COURIER_DESCENT_OVERRIDE)))
    target_line_gap = max(0, int(round(num_size * COURIER_LINE_GAP_OVERRIDE)))
    target_line_height = max(1, target_ascent + target_descent + target_line_gap)
    base_offset = target_ascent - num_ascent
    jp_top = jp_font.getbbox("Ag")[1]
    num_top = num_font.getbbox("09:00")[1]
    optical_offset = jp_top - num_top
    return ScheduleFontSet(
        jp_font=jp_font,
        num_font=num_font,
        num_baseline_offset=max(0, base_offset, optical_offset),
        num_line_height=target_line_height,
    )


def _draw_centered_mixed_text(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    text: str,
    fonts: ScheduleFontSet,
    color: tuple[int, int, int],
) -> None:
    x1, y1, x2, y2 = rect
    left, top, right, bottom = _mixed_text_bbox(draw, text, fonts)
    w = max(0.0, right - left)
    h = max(0.0, bottom - top)
    x = x1 + ((x2 - x1) - w) / 2 - left
    y = y1 + ((y2 - y1) - h) / 2 - top
    _draw_mixed_text(draw, (x, y), text, fonts, fill=color)


def _draw_mixed_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    fonts: ScheduleFontSet,
    *,
    fill: tuple[int, int, int],
) -> None:
    x, y = xy
    for chunk, is_ascii in _split_text_runs(text):
        font = fonts.num_font if is_ascii else fonts.jp_font
        y_pos = y + fonts.num_baseline_offset if is_ascii else y
        draw.text((x, y_pos), chunk, font=font, fill=fill)
        x += _text_width(draw, chunk, font)


def _split_text_runs(text: str) -> list[tuple[str, bool]]:
    value = str(text or "")
    if not value:
        return []
    runs: list[tuple[str, bool]] = []
    current = [value[0]]
    current_ascii = _is_ascii_char(value[0])

    for ch in value[1:]:
        is_ascii = _is_ascii_char(ch)
        if is_ascii == current_ascii:
            current.append(ch)
            continue
        runs.append(("".join(current), current_ascii))
        current = [ch]
        current_ascii = is_ascii
    runs.append(("".join(current), current_ascii))
    return runs


def _is_ascii_char(ch: str) -> bool:
    return bool(ASCII_RUN_RE.fullmatch(ch))


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return max(0, right - left)


def _font_height(draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont) -> int:
    left, top, right, bottom = draw.textbbox((0, 0), "Ag", font=font)
    return max(1, bottom - top)


def _mixed_text_width(draw: ImageDraw.ImageDraw, text: str, fonts: ScheduleFontSet) -> int:
    width = 0
    for chunk, is_ascii in _split_text_runs(text):
        font = fonts.num_font if is_ascii else fonts.jp_font
        width += _text_width(draw, chunk, font)
    return width


def _mixed_text_bbox(
    draw: ImageDraw.ImageDraw,
    text: str,
    fonts: ScheduleFontSet,
) -> tuple[float, float, float, float]:
    left: float | None = None
    top: float | None = None
    right: float | None = None
    bottom: float | None = None
    x = 0.0
    for chunk, is_ascii in _split_text_runs(text):
        font = fonts.num_font if is_ascii else fonts.jp_font
        y_pos = float(fonts.num_baseline_offset) if is_ascii else 0.0
        c_left, c_top, c_right, c_bottom = draw.textbbox((x, y_pos), chunk, font=font)
        if left is None:
            left = float(c_left)
            top = float(c_top)
            right = float(c_right)
            bottom = float(c_bottom)
        else:
            left = min(left, float(c_left))
            top = min(top, float(c_top))
            right = max(right, float(c_right))
            bottom = max(bottom, float(c_bottom))
        x += float(_text_width(draw, chunk, font))
    if left is None or top is None or right is None or bottom is None:
        return (0.0, 0.0, 0.0, 0.0)
    return (left, top, right, bottom)


def _mixed_font_height(draw: ImageDraw.ImageDraw, fonts: ScheduleFontSet) -> int:
    num_h = fonts.num_line_height if fonts.num_line_height > 0 else _font_height(draw, fonts.num_font)
    return max(_font_height(draw, fonts.jp_font), num_h)


def _scale_font_set(fonts: ScheduleFontSet, scale: float) -> ScheduleFontSet:
    if scale >= 0.999:
        return fonts
    try:
        jp_size = max(1, int(round(float(getattr(fonts.jp_font, "size")) * scale)))
        num_size = max(1, int(round(float(getattr(fonts.num_font, "size")) * scale)))
        jp_font = fonts.jp_font.font_variant(size=jp_size)
        num_font = fonts.num_font.font_variant(size=num_size)
    except Exception:
        return fonts
    num_offset = int(round(fonts.num_baseline_offset * scale))
    base_num_h = fonts.num_line_height if fonts.num_line_height > 0 else _font_height(ImageDraw.Draw(Image.new("RGB", (10, 10))), fonts.num_font)
    num_line_h = max(1, int(round(base_num_h * scale)))
    return ScheduleFontSet(
        jp_font=jp_font,
        num_font=num_font,
        num_baseline_offset=num_offset,
        num_line_height=num_line_h,
    )


def _fit_font_set_to_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    fonts: ScheduleFontSet,
    max_width: int,
    min_scale: float = 0.62,
) -> ScheduleFontSet:
    if _mixed_text_width(draw, text, fonts) <= max_width:
        return fonts
    scale = 0.96
    fitted = fonts
    while scale >= min_scale:
        candidate = _scale_font_set(fonts, scale)
        if candidate is fonts and scale < 0.95:
            break
        fitted = candidate
        if _mixed_text_width(draw, text, candidate) <= max_width:
            return candidate
        scale -= 0.04
    return fitted


def _truncate_mixed_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    fonts: ScheduleFontSet,
    max_width: int,
) -> str:
    if _mixed_text_width(draw, text, fonts) <= max_width:
        return text
    ellipsis = "…"
    for end in range(len(text), 0, -1):
        candidate = text[:end].rstrip() + ellipsis
        if _mixed_text_width(draw, candidate, fonts) <= max_width:
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
    date_keys = ["date", "day", "ymd", "date_ymd", "日付", "start", "start_at", "starts_at", "startAt"]
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
        return ScheduleEntry(day=day, title=title, classroom=classroom, venue=venue, slot="")

    classroom = _pick_text(item, ["classroom", "classroom_name", "studio", "教室"])
    venue = _pick_text(item, ["venue", "venue_name", "会場", "location"])
    title = _pick_text(item, ["title", "name", "label", "event_name", "lesson_name", "lesson", "type"])
    slot = _pick_text(item, ["slot", "time_slot", "part", "部", "時間帯"])

    if not title:
        participants = item.get("participants")
        if isinstance(participants, list) and participants:
            title = f"{len(participants)}名"
        elif _pick_text(item, ["lesson_id", "lessonId"]):
            title = "レッスン"
        else:
            title = "予定"

    if start_dt is None:
        for key in [
            "start",
            "start_at",
            "starts_at",
            "startAt",
            "time",
            "start_time",
            "first_start",
            "firstStart",
            "second_start",
            "secondStart",
            "beginner_start",
            "beginnerStart",
            "1部開始",
            "2部開始",
            "初回者開始",
        ]:
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
        for key in [
            "end",
            "end_at",
            "ends_at",
            "endAt",
            "end_time",
            "first_end",
            "firstEnd",
            "second_end",
            "secondEnd",
            "1部終了",
            "2部終了",
        ]:
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
        slot=slot,
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
