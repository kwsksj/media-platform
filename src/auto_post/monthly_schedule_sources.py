"""Schedule data sources (Notion / JSON) for monthly schedule."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from notion_client import Client

from .monthly_schedule_models import ScheduleEntry, ScheduleSourceConfig
from .monthly_schedule_text import _normalize_slot
from .monthly_schedule_utils import _calendar_visible_date_range, _entry_sort_key


class MonthlyScheduleNotionClient:
    """Fetch monthly classroom schedules from a Notion database."""

    def __init__(self, token: str, source: ScheduleSourceConfig):
        self.client = Client(auth=token, notion_version="2022-06-28")
        self.source = source
        self._title_property_name: str | None = source.title_property or None

    def fetch_month_entries(self, year: int, month: int, *, include_adjacent: bool = False) -> list[ScheduleEntry]:
        first_day = date(year, month, 1)
        next_month = (first_day.replace(day=28) + timedelta(days=4)).replace(day=1)
        last_day = next_month - timedelta(days=1)
        range_start = first_day
        range_end = last_day
        if include_adjacent:
            range_start, range_end = _calendar_visible_date_range(year, month)
        tz = ZoneInfo(self.source.timezone)

        body = {
            "filter": {
                "and": [
                    {
                        "property": self.source.date_property,
                        "date": {"on_or_after": range_start.isoformat()},
                    },
                    {
                        "property": self.source.date_property,
                        "date": {"on_or_before": range_end.isoformat()},
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
                if range_start <= entry.day <= range_end:
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


def extract_month_entries_from_json(
    data: dict[str, Any],
    year: int,
    month: int,
    timezone: str = "Asia/Tokyo",
    *,
    include_adjacent: bool = False,
) -> list[ScheduleEntry]:
    """Extract month entries from schedule JSON."""
    tz = ZoneInfo(timezone)
    range_start = date(year, month, 1)
    next_month = (range_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    range_end = next_month - timedelta(days=1)
    if include_adjacent:
        range_start, range_end = _calendar_visible_date_range(year, month)
    out: list[ScheduleEntry] = []
    payload = data
    wrapped = data.get("data")
    if isinstance(wrapped, dict):
        payload = wrapped

    dates = payload.get("dates")
    if isinstance(dates, dict):
        for raw_date, groups in dates.items():
            day = _parse_date_ymd(raw_date)
            if day is None or not (range_start <= day <= range_end):
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
                if range_start <= entry.day <= range_end:
                    out.append(entry)
            if out:
                break

    out.sort(key=_entry_sort_key)
    return out


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
        return None

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


__all__ = [
    "MonthlyScheduleNotionClient",
    "extract_month_entries_from_json",
    "_build_entry_from_any_date",
    "_build_entry_from_dict",
    "_extract_rich_text",
    "_extract_text",
    "_parse_date_ymd",
    "_parse_json_datetime",
    "_parse_notion_datetime",
    "_pick_text",
    "_to_text",
]
