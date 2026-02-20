import click
from pathlib import Path

from auto_post.cli import (
    MonthlyScheduleItem,
    _parse_skip_target_months,
    _prepare_monthly_schedule_images,
)


def test_parse_skip_target_months_empty():
    assert _parse_skip_target_months("") == set()


def test_parse_skip_target_months_valid_tokens():
    actual = _parse_skip_target_months("2026-03, 2026-04 2026/05")
    assert actual == {(2026, 3), (2026, 4), (2026, 5)}


def test_parse_skip_target_months_invalid_token():
    try:
        _parse_skip_target_months("2026-03,foo")
        assert False, "Expected ClickException"
    except click.ClickException as e:
        assert "invalid token" in str(e)


def test_parse_skip_target_months_invalid_month():
    try:
        _parse_skip_target_months("2026-13")
        assert False, "Expected ClickException"
    except click.ClickException as e:
        assert "invalid month" in str(e)


def test_prepare_monthly_schedule_images_keeps_post_payload_jpeg_when_output_png(tmp_path):
    month_items = [
        MonthlyScheduleItem(
            year=2026,
            month=3,
            caption_entries=[],
            image=object(),
        )
    ]
    save_calls: list[Path] = []
    encode_calls: list[str] = []

    def fake_default_schedule_filename(year: int, month: int, mime_type: str) -> str:
        assert mime_type == "image/jpeg"
        return f"schedule-{year}-{month:02d}.jpg"

    def fake_image_to_bytes(image, mime_type: str) -> bytes:
        encode_calls.append(mime_type)
        return b"jpeg-bytes"

    def fake_save_image(image, output_path: Path) -> str:
        save_calls.append(output_path)
        return "image/png"

    output = tmp_path / "monthly.png"
    images_data, saved_outputs = _prepare_monthly_schedule_images(
        month_items,
        output,
        default_schedule_filename=fake_default_schedule_filename,
        image_to_bytes=fake_image_to_bytes,
        save_image=fake_save_image,
    )

    assert save_calls == [output]
    assert saved_outputs == [output]
    assert encode_calls == ["image/jpeg"]
    assert images_data == [(b"jpeg-bytes", "schedule-2026-03.jpg", "image/jpeg")]
