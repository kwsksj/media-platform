"""Utility helpers for monthly schedule."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from .monthly_schedule_models import JST, ScheduleEntry


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


def _calendar_visible_date_range(year: int, month: int) -> tuple[date, date]:
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    if not weeks:
        day = date(year, month, 1)
        return day, day
    return weeks[0][0], weeks[-1][-1]


def _entry_sort_key(entry: ScheduleEntry) -> tuple[date, int, int, str]:
    if entry.start:
        return (entry.day, entry.start.hour, entry.start.minute, entry.title)
    return (entry.day, 99, 99, entry.title)


def _safe_positive_int(raw: str | None, default: int) -> int:
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


__all__ = [
    "resolve_target_year_month",
    "_calendar_visible_date_range",
    "_entry_sort_key",
    "_safe_positive_int",
]
