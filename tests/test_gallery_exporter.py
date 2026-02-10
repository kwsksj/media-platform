"""Tests for gallery exporter author ID handling."""

import pytest

from auto_post.gallery_exporter import GalleryExporter


class _FakeNotion:
    def __init__(self, db_info: dict, pages: list[dict]):
        self._db_info = db_info
        self._pages = pages

    def get_database_info(self, _database_id: str) -> dict:
        return self._db_info

    def list_database_pages(self, _database_id: str) -> list[dict]:
        return self._pages


def _make_exporter() -> GalleryExporter:
    return GalleryExporter.__new__(GalleryExporter)


def test_build_author_id_map_uses_student_id_property():
    exporter = _make_exporter()
    exporter.notion = _FakeNotion(
        db_info={"properties": {"生徒ID": {"type": "rich_text"}}},
        pages=[
            {
                "id": "author-1",
                "properties": {
                    "生徒ID": {
                        "type": "rich_text",
                        "rich_text": [{"plain_text": "ST-001"}],
                    }
                },
            },
            {
                "id": "author-2",
                "properties": {"生徒ID": {"type": "number", "number": 102}},
            },
            {
                "id": "author-3",
                "properties": {
                    "生徒ID": {
                        "type": "unique_id",
                        "unique_id": {"prefix": "S-", "number": 55},
                    }
                },
            },
            {
                "id": "author-4",
                "properties": {
                    "生徒ID": {
                        "type": "unique_id",
                        "unique_id": {"prefix": "T", "number": 9},
                    }
                },
            },
        ],
    )

    author_map = exporter._build_author_id_map("author-db")

    assert author_map == {
        "author-1": "ST-001",
        "author-2": "102",
        "author-3": "S-55",
        "author-4": "T-9",
    }


def test_build_author_id_map_skips_name_like_values():
    exporter = _make_exporter()
    exporter.notion = _FakeNotion(
        db_info={"properties": {"生徒ID": {"type": "rich_text"}}},
        pages=[
            {
                "id": "author-1",
                "properties": {
                    "生徒ID": {"type": "rich_text", "rich_text": [{"plain_text": "たろう"}]}
                },
            },
            {
                "id": "author-2",
                "properties": {
                    "生徒ID": {
                        "type": "rich_text",
                        "rich_text": [{"plain_text": "nickname|本名"}],
                    }
                },
            },
            {
                "id": "author-3",
                "properties": {
                    "生徒ID": {"type": "rich_text", "rich_text": [{"plain_text": "TARO"}]}
                },
            },
        ],
    )

    author_map = exporter._build_author_id_map("author-db")

    assert author_map == {}


def test_format_author_joins_relation_ids():
    exporter = _make_exporter()

    author = exporter._format_author(["ST-001", "ST-002"], props={})

    assert author == "ST-001 / ST-002"


def test_format_author_select_fallback_accepts_only_id_like_value():
    exporter = _make_exporter()

    safe_author = exporter._format_author(
        [],
        props={"作者": {"select": {"name": "ST-001"}}},
    )
    unsafe_author = exporter._format_author(
        [],
        props={"作者": {"select": {"name": "山田太郎"}}},
    )

    assert safe_author == "ST-001"
    assert unsafe_author is None


def test_resolve_ready_property_name_prefers_env_override(monkeypatch):
    exporter = _make_exporter()
    monkeypatch.setenv("NOTION_WORKS_READY_PROP", "公開可")

    prop = exporter._resolve_ready_property_name(
        {
            "properties": {
                "整備済み": {"type": "checkbox"},
                "公開可": {"type": "checkbox"},
            }
        }
    )

    assert prop == "公開可"


def test_resolve_ready_property_name_falls_back_to_known_candidates(monkeypatch):
    exporter = _make_exporter()
    monkeypatch.delenv("NOTION_WORKS_READY_PROP", raising=False)

    prop = exporter._resolve_ready_property_name(
        {
            "properties": {
                "整備済": {"type": "checkbox"},
            }
        }
    )

    assert prop == "整備済"


def test_resolve_ready_property_name_detects_ready_like_checkbox(monkeypatch):
    exporter = _make_exporter()
    monkeypatch.delenv("NOTION_WORKS_READY_PROP", raising=False)

    prop = exporter._resolve_ready_property_name(
        {
            "properties": {
                "公開Ready": {"type": "checkbox"},
            }
        }
    )

    assert prop == "公開Ready"


def test_resolve_ready_property_name_accepts_formula_from_env(monkeypatch):
    exporter = _make_exporter()
    monkeypatch.setenv("NOTION_WORKS_READY_PROP", "公開可判定")

    prop = exporter._resolve_ready_property_name(
        {
            "properties": {
                "公開可判定": {"type": "formula"},
            }
        }
    )

    assert prop == "公開可判定"


def test_resolve_ready_property_name_detects_ready_like_formula(monkeypatch):
    exporter = _make_exporter()
    monkeypatch.delenv("NOTION_WORKS_READY_PROP", raising=False)

    prop = exporter._resolve_ready_property_name(
        {
            "properties": {
                "ready_formula": {"type": "formula"},
            }
        }
    )

    assert prop == "ready_formula"


def test_resolve_ready_property_name_raises_if_not_found(monkeypatch):
    exporter = _make_exporter()
    monkeypatch.delenv("NOTION_WORKS_READY_PROP", raising=False)

    with pytest.raises(ValueError):
        exporter._resolve_ready_property_name(
            {
                "properties": {
                    "作品名": {"type": "title"},
                    "公開状態": {"type": "select"},
                }
            }
        )


def test_is_page_ready_accepts_checkbox_true():
    exporter = _make_exporter()
    page = {
        "properties": {
            "整備済み": {"type": "checkbox", "checkbox": True},
        }
    }

    assert exporter._is_page_ready(page, "整備済み") is True


def test_is_page_ready_accepts_formula_boolean_true():
    exporter = _make_exporter()
    page = {
        "properties": {
            "整備済み": {"type": "formula", "formula": {"type": "boolean", "boolean": True}},
        }
    }

    assert exporter._is_page_ready(page, "整備済み") is True


def test_is_page_ready_rejects_false_or_missing():
    exporter = _make_exporter()
    false_page = {
        "properties": {
            "整備済み": {"type": "checkbox", "checkbox": False},
        }
    }
    missing_page = {"properties": {}}

    assert exporter._is_page_ready(false_page, "整備済み") is False
    assert exporter._is_page_ready(missing_page, "整備済み") is False
