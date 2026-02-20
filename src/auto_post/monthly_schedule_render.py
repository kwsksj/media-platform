"""Image rendering for monthly schedule."""

from __future__ import annotations

import calendar
import colorsys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance

from .monthly_schedule_fonts import (
    _draw_centered_mixed_text,
    _draw_mixed_text,
    _fit_font_set_to_width,
    _load_font_set,
    _mixed_font_height,
    _mixed_text_width,
    _resolve_required_font_paths,
)
from .monthly_schedule_models import ScheduleEntry, ScheduleFontSet, ScheduleRenderConfig
from .monthly_schedule_text import (
    NIGHT_BADGE_STYLE,
    _build_day_cards,
    _build_fixed_time_rows,
    _get_classroom_card_style,
    _get_venue_badge_style,
    _is_night_time_text,
    _resolve_night_time_line_indexes,
    _short_classroom_name,
)
from .monthly_schedule_utils import _entry_sort_key

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

    month_matrix = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
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

    events_by_day: dict = {}
    for entry in entries:
        events_by_day.setdefault(entry.day, []).append(entry)
    for day_entries in events_by_day.values():
        day_entries.sort(key=_entry_sort_key)

    for row_index, week in enumerate(month_matrix):
        for col_index, cell_date in enumerate(week):
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
            if cell_date.month != month:
                cell_fill = PALETTE["empty_cell"]

            draw.rounded_rectangle(
                rect,
                radius=max(14, width // 110),
                fill=cell_fill,
            )

            day_color = PALETTE["ink"]
            if col_index == 5:
                day_color = PALETTE["accent_2"]
            elif col_index == 6:
                day_color = PALETTE["accent"]
            if cell_date.month != month:
                day_color = PALETTE["muted"]

            _draw_mixed_text(
                draw,
                (x1 + 14, y1 + 6),
                str(cell_date.day),
                day_fonts,
                fill=day_color,
            )

            day_events = events_by_day.get(cell_date, [])
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

    return _apply_clear_warm_background_style(image)


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


def _apply_clear_warm_background_style(image: Image.Image) -> Image.Image:
    """Apply selected 'clear-warmbg' finish to final calendar image."""
    styled = ImageEnhance.Color(image).enhance(1.08)
    styled = ImageEnhance.Contrast(styled).enhance(1.06)
    styled = ImageEnhance.Sharpness(styled).enhance(1.08)
    if styled.mode != "RGB":
        styled = styled.convert("RGB")

    pixels = styled.load()
    width, height = styled.size
    warm = (245, 226, 205)
    blend = 0.22
    for y in range(height):
        for x in range(width):
            r, g, b = pixels[x, y]
            _, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
            # Warm up low-saturation bright areas (background/empty cells) while preserving card colors.
            if s < 0.22 and v > 0.70:
                nr = int(r * (1 - blend) + warm[0] * blend)
                ng = int(g * (1 - blend) + warm[1] * blend)
                nb = int(b * (1 - blend) + warm[2] * blend)
                pixels[x, y] = (nr, ng, nb)
    return styled


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


def _pick_smaller_font_set(current: ScheduleFontSet | None, candidate: ScheduleFontSet) -> ScheduleFontSet:
    if current is None:
        return candidate
    current_size = int(getattr(current.num_font, "size", 0))
    candidate_size = int(getattr(candidate.num_font, "size", 0))
    if candidate_size < current_size:
        return candidate
    return current


__all__ = [
    "PALETTE",
    "WEEKDAY_LABELS",
    "default_schedule_filename",
    "image_to_bytes",
    "render_monthly_schedule_image",
    "save_image",
    "_apply_clear_warm_background_style",
    "_create_gradient_background",
    "_draw_day_events",
    "_pick_smaller_font_set",
]
