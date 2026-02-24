"""Schedule-based classroom lookup for photo imports.

Given a photo date, determine which classroom was active on that day
by looking up the schedule data from R2 (schedule_index.json).
"""

import logging
from datetime import date, datetime
from typing import Any

from .config import Config
from .monthly_schedule_models import ScheduleEntry, ScheduleJsonSourceConfig
from .monthly_schedule_sources import extract_month_entries_from_json
from .r2_storage import R2Storage

logger = logging.getLogger(__name__)


class ScheduleLookup:
    """Look up classroom name from schedule data by date."""

    def __init__(self, config: Config):
        self.r2 = R2Storage(config.r2)
        self._cache: dict[str, list[ScheduleEntry]] = {}  # "YYYY-MM" -> entries
        self._json_config = ScheduleJsonSourceConfig.from_env()
        self._schedule_data: dict | None = None

    def _load_schedule_data(self) -> dict | None:
        """Load the full schedule_index.json from R2 (cached)."""
        if self._schedule_data is not None:
            return self._schedule_data

        key = self._json_config.key
        logger.info(f"Loading schedule data from R2: {key}")
        data = self.r2.get_json(key)
        if data is None:
            logger.warning(f"Schedule data not found in R2: {key}")
            self._schedule_data = {}
            return self._schedule_data

        self._schedule_data = data
        logger.info("Schedule data loaded successfully")
        return self._schedule_data

    def _get_month_entries(self, year: int, month: int) -> list[ScheduleEntry]:
        """Get schedule entries for a specific month (cached)."""
        cache_key = f"{year:04d}-{month:02d}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        data = self._load_schedule_data()
        if not data:
            self._cache[cache_key] = []
            return []

        entries = extract_month_entries_from_json(
            data, year, month,
            timezone=self._json_config.timezone,
        )
        self._cache[cache_key] = entries
        return entries

    def lookup_classroom(self, photo_date: date | datetime) -> str | None:
        """Look up classroom for a given date.

        Returns the classroom name if found, None otherwise.
        If multiple classrooms are found for the same day, returns the first one.
        """
        if isinstance(photo_date, datetime):
            day = photo_date.date()
        else:
            day = photo_date

        entries = self._get_month_entries(day.year, day.month)

        # Find entries matching this day
        matching = [e for e in entries if e.day == day]
        if not matching:
            return None

        # Return the first classroom found
        for entry in matching:
            if entry.classroom:
                return entry.classroom

        return None

    def lookup_classroom_and_venue(
        self, photo_date: date | datetime
    ) -> tuple[str | None, str | None]:
        """Look up classroom and venue for a given date.

        Returns (classroom, venue) tuple, both may be None.
        """
        if isinstance(photo_date, datetime):
            day = photo_date.date()
        else:
            day = photo_date

        entries = self._get_month_entries(day.year, day.month)

        matching = [e for e in entries if e.day == day]
        if not matching:
            return None, None

        for entry in matching:
            if entry.classroom:
                return entry.classroom, entry.venue or None

        return None, None

    def preload_range(self, start_year: int, start_month: int,
                      end_year: int, end_month: int) -> None:
        """Preload schedule data for a date range."""
        year, month = start_year, start_month
        while (year, month) <= (end_year, end_month):
            self._get_month_entries(year, month)
            month += 1
            if month > 12:
                month = 1
                year += 1
