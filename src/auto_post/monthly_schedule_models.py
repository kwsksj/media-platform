"""Data models and config objects for monthly schedule."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from PIL import ImageFont

JST = ZoneInfo("Asia/Tokyo")


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
        # Lazy import to avoid circular dependency.
        from .monthly_schedule_utils import _safe_positive_int

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


__all__ = [
    "JST",
    "DayCard",
    "ScheduleEntry",
    "ScheduleFontPaths",
    "ScheduleFontSet",
    "ScheduleJsonSourceConfig",
    "ScheduleRenderConfig",
    "ScheduleSourceConfig",
]
