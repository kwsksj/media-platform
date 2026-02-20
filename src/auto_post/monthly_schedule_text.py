"""Text formatting and day-card building for monthly schedule."""

from __future__ import annotations

from datetime import datetime

from .monthly_schedule_models import DayCard, ScheduleEntry
from .monthly_schedule_utils import _entry_sort_key

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


__all__ = [
    "CLASSROOM_CARD_STYLES",
    "NIGHT_BADGE_STYLE",
    "VENUE_BADGE_STYLES",
    "build_monthly_caption",
    "_build_day_cards",
    "_build_fixed_time_rows",
    "_expand_time_values",
    "_extract_start_hour_from_time_text",
    "_format_clock",
    "_format_time_range",
    "_get_classroom_card_style",
    "_get_venue_badge_style",
    "_is_night_entry",
    "_is_night_time_text",
    "_merge_time_text",
    "_normalize_hashtags",
    "_normalize_slot",
    "_resolve_night_time_line_indexes",
    "_short_classroom_name",
    "_time_text_to_sort_key",
]
