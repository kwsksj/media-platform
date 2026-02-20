import click

from auto_post.cli import _parse_skip_target_months


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

