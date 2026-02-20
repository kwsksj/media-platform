"""Tests for monthly schedule image generation."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from PIL import ImageFont

import auto_post.monthly_schedule as monthly_schedule
from auto_post.monthly_schedule import (
    ScheduleEntry,
    ScheduleFontPaths,
    ScheduleFontSet,
    ScheduleRenderConfig,
    _build_day_cards,
    _expand_time_values,
    build_monthly_caption,
    extract_month_entries_from_json,
    render_monthly_schedule_image,
    resolve_target_year_month,
)


def test_resolve_target_year_month_next():
    now = datetime(2026, 2, 25, 16, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    year, month = resolve_target_year_month(now=now, target="next")
    assert (year, month) == (2026, 3)


def test_resolve_target_year_month_current():
    now = datetime(2026, 2, 25, 16, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    year, month = resolve_target_year_month(now=now, target="current")
    assert (year, month) == (2026, 2)


def test_build_monthly_caption_defaults():
    entries = [
        ScheduleEntry(day=date(2026, 3, 1), title="午前クラス", classroom="東京教室", venue="浅草橋"),
        ScheduleEntry(day=date(2026, 3, 2), title="午後クラス", classroom="沼津教室", venue="沼津"),
    ]
    caption = build_monthly_caption(2026, 3, entries, default_tags="木彫り 教室日程")
    assert "2026年3月の教室日程です。" in caption
    assert "#木彫り" in caption
    assert "#教室日程" in caption


def test_render_monthly_schedule_image_size(monkeypatch):
    monkeypatch.setattr(
        monthly_schedule,
        "_resolve_required_font_paths",
        lambda config: ScheduleFontPaths(
            jp_regular="dummy",
            jp_bold="dummy",
            num_regular="dummy",
            num_bold="dummy",
        ),
    )
    monkeypatch.setattr(
        monthly_schedule,
        "_load_font_set",
        lambda paths, size, bold: ScheduleFontSet(
            jp_font=ImageFont.load_default(),
            num_font=ImageFont.load_default(),
        ),
    )

    entries = [
        ScheduleEntry(
            day=date(2026, 3, 5),
            title="体験クラス",
            classroom="東京教室",
            venue="浅草橋",
            start=datetime(2026, 3, 5, 10, 30, tzinfo=ZoneInfo("Asia/Tokyo")),
        ),
        ScheduleEntry(
            day=date(2026, 3, 5),
            title="夜クラス",
            classroom="つくば教室",
            venue="つくば",
            start=datetime(2026, 3, 5, 18, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
        ),
    ]
    image = render_monthly_schedule_image(2026, 3, entries, ScheduleRenderConfig(width=768, height=1024))
    assert image.size == (768, 1024)


def test_extract_month_entries_from_participants_index_shape():
    payload = {
        "generated_at": "2026-02-25T12:00:00+09:00",
        "timezone": "Asia/Tokyo",
        "dates": {
            "2026-03-05": [
                {
                    "lesson_id": "abc",
                    "classroom": "東京教室",
                    "venue": "浅草橋",
                    "start_at": "2026-03-05T10:30:00+09:00",
                    "participants": [
                        {"student_id": "s1", "display_name": "A"},
                        {"student_id": "s2", "display_name": "B"},
                    ],
                }
            ]
        },
    }
    entries = extract_month_entries_from_json(payload, 2026, 3, timezone="Asia/Tokyo")
    assert len(entries) == 1
    assert entries[0].day == date(2026, 3, 5)
    assert entries[0].classroom == "東京教室"
    assert entries[0].venue == "浅草橋"
    assert entries[0].title == "2名"


def test_extract_month_entries_from_wrapped_worker_response():
    payload = {
        "ok": True,
        "data": {
            "generated_at": "2026-02-25T12:00:00+09:00",
            "timezone": "Asia/Tokyo",
            "dates": {
                "2026-03-10": [
                    {
                        "lesson_id": "wrapped-1",
                        "classroom": "つくば教室",
                        "venue": "浅草橋",
                        "start_at": "2026-03-10T13:00:00+09:00",
                    }
                ]
            },
        },
    }
    entries = extract_month_entries_from_json(payload, 2026, 3, timezone="Asia/Tokyo")
    assert len(entries) == 1
    assert entries[0].classroom == "つくば教室"
    assert entries[0].start and entries[0].start.hour == 13


def test_extract_month_entries_supports_sheet_time_keys():
    payload = {
        "dates": {
            "2026-03-20": [
                {
                    "lesson_id": "sheet-1",
                    "教室": "沼津教室",
                    "会場": "東池袋",
                    "1部開始": "09:30",
                    "1部終了": "12:00",
                }
            ]
        }
    }
    entries = extract_month_entries_from_json(payload, 2026, 3, timezone="Asia/Tokyo")
    assert len(entries) == 1
    assert entries[0].classroom == "沼津教室"
    assert entries[0].venue == "東池袋"
    assert entries[0].start and entries[0].start.hour == 9 and entries[0].start.minute == 30
    assert entries[0].end and entries[0].end.hour == 12


def test_extract_month_entries_from_json_include_adjacent_weeks():
    payload = {
        "dates": {
            "2026-02-28": [
                {"lesson_id": "prev", "classroom": "東京教室", "venue": "浅草橋", "start_at": "2026-02-28T12:00:00+09:00"}
            ],
            "2026-03-20": [
                {"lesson_id": "mid", "classroom": "沼津教室", "venue": "東池袋", "start_at": "2026-03-20T09:30:00+09:00"}
            ],
            "2026-04-02": [
                {"lesson_id": "next", "classroom": "つくば教室", "venue": "浅草橋", "start_at": "2026-04-02T13:00:00+09:00"}
            ],
        }
    }
    month_only = extract_month_entries_from_json(payload, 2026, 3, timezone="Asia/Tokyo")
    assert [e.day for e in month_only] == [date(2026, 3, 20)]

    with_adjacent = extract_month_entries_from_json(
        payload,
        2026,
        3,
        timezone="Asia/Tokyo",
        include_adjacent=True,
    )
    assert [e.day for e in with_adjacent] == [date(2026, 2, 28), date(2026, 3, 20), date(2026, 4, 2)]


def test_extract_month_entries_ignores_invalid_dates_items_and_falls_back_to_entries():
    payload = {
        "dates": {
            "2026-03-05": [None, "invalid"],
        },
        "entries": [
            {
                "date": "2026-03-06",
                "classroom": "東京教室",
                "venue": "浅草橋",
                "start_at": "2026-03-06T10:30:00+09:00",
            }
        ],
    }
    entries = extract_month_entries_from_json(payload, 2026, 3, timezone="Asia/Tokyo")
    assert len(entries) == 1
    assert entries[0].day == date(2026, 3, 6)
    assert entries[0].classroom == "東京教室"
    assert entries[0].venue == "浅草橋"


def test_build_day_cards_merges_same_classroom_slots():
    entries = [
        ScheduleEntry(
            day=date(2026, 3, 1),
            title="",
            classroom="東京教室",
            venue="浅草橋",
            start=datetime(2026, 3, 1, 12, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
            end=datetime(2026, 3, 1, 16, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
            slot="first",
        ),
        ScheduleEntry(
            day=date(2026, 3, 1),
            title="",
            classroom="東京教室",
            venue="浅草橋",
            start=datetime(2026, 3, 1, 17, 30, tzinfo=ZoneInfo("Asia/Tokyo")),
            end=datetime(2026, 3, 1, 20, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
            slot="second",
        ),
        ScheduleEntry(
            day=date(2026, 3, 1),
            title="",
            classroom="東京教室",
            venue="浅草橋",
            start=datetime(2026, 3, 1, 12, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
            end=datetime(2026, 3, 1, 14, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
            slot="beginner",
        ),
    ]
    cards = _build_day_cards(entries)
    assert len(cards) == 1
    card = cards[0]
    assert card.classroom == "東京教室"
    assert card.first_time == "12:00~16:00"
    assert card.second_time == "17:30~20:00"
    assert card.beginner_time == "12:00~14:00"
    assert card.has_night is True


def test_build_day_cards_formats_single_digit_hour_with_leading_space():
    entries = [
        ScheduleEntry(
            day=date(2026, 3, 3),
            title="",
            classroom="つくば教室",
            venue="つくば",
            start=datetime(2026, 3, 3, 9, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
            end=datetime(2026, 3, 3, 13, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
            slot="first",
        )
    ]
    cards = _build_day_cards(entries)
    assert len(cards) == 1
    assert cards[0].first_time == " 9:00~13:00"


def test_expand_time_values_preserves_leading_space_for_alignment():
    assert _expand_time_values(" 9:00~13:00 / 14:00~17:00") == [" 9:00~13:00", "14:00~17:00"]
