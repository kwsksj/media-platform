"""Font resolution and mixed-text drawing helpers for monthly schedule."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .monthly_schedule_models import ScheduleFontPaths, ScheduleFontSet, ScheduleRenderConfig

logger = logging.getLogger(__name__)

ZEN_REGULAR_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/zenkakugothicnew/ZenKakuGothicNew-Regular.ttf"
ZEN_BOLD_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/zenkakugothicnew/ZenKakuGothicNew-Bold.ttf"
COURIER_REGULAR_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/courierprime/CourierPrime-Regular.ttf"
COURIER_BOLD_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/courierprime/CourierPrime-Bold.ttf"

COURIER_ASCENT_OVERRIDE = 0.85
COURIER_DESCENT_OVERRIDE = 0.15
COURIER_LINE_GAP_OVERRIDE = 0.0
COURIER_SIZE_ADJUST = 1.20

ASCII_RUN_RE = re.compile(r"[\x00-\x7F]+")


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


__all__ = [
    "ASCII_RUN_RE",
    "COURIER_ASCENT_OVERRIDE",
    "COURIER_BOLD_URL",
    "COURIER_DESCENT_OVERRIDE",
    "COURIER_LINE_GAP_OVERRIDE",
    "COURIER_REGULAR_URL",
    "COURIER_SIZE_ADJUST",
    "ZEN_BOLD_URL",
    "ZEN_REGULAR_URL",
    "_download_font",
    "_draw_centered_mixed_text",
    "_draw_mixed_text",
    "_fit_font_set_to_width",
    "_font_height",
    "_is_ascii_char",
    "_is_valid_font_path",
    "_load_font_set",
    "_mixed_font_height",
    "_mixed_text_bbox",
    "_mixed_text_width",
    "_resolve_required_font_paths",
    "_resolve_single_font",
    "_scale_font_set",
    "_split_text_runs",
    "_text_width",
    "_truncate_mixed_text",
]
