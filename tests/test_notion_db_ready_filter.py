from __future__ import annotations

from datetime import datetime

from auto_post.notion_db import NotionDB


class _DummyDatabases:
    def __init__(self, properties: dict):
        self._properties = properties

    def retrieve(self, _database_id: str) -> dict:
        return {"properties": self._properties}


class _DummyClient:
    def __init__(self, properties: dict):
        self.databases = _DummyDatabases(properties)
        self.calls: list[dict] = []

    def request(self, *, path: str, method: str, body: dict) -> dict:
        self.calls.append({"path": path, "method": method, "body": body})
        return {"results": []}


def _last_filters(db: NotionDB) -> list[dict]:
    body = db.client.calls[-1]["body"]  # type: ignore[attr-defined]
    return body["filter"]["and"]


def test_get_posts_for_date_adds_ready_checkbox_filter():
    db = NotionDB("token", "works-db")
    db.client = _DummyClient(
        {
            "整備済み": {"type": "checkbox"},
        }
    )

    db.get_posts_for_date(datetime(2026, 2, 27))

    filters = _last_filters(db)
    assert {"property": "整備済み", "checkbox": {"equals": True}} in filters
    assert {"property": "完成日", "date": {"on_or_after": "2025-01-01"}} in filters


def test_get_basic_candidates_adds_ready_formula_filter():
    db = NotionDB("token", "works-db")
    db.client = _DummyClient(
        {
            "Ready": {"type": "formula"},
        }
    )

    db.get_basic_candidates("instagram", limit=1)

    filters = _last_filters(db)
    assert {"property": "Ready", "formula": {"checkbox": {"equals": True}}} in filters
    assert {"property": "完成日", "date": {"on_or_after": "2025-01-01"}} in filters


def test_get_catchup_candidates_uses_ready_fallback_property_name():
    db = NotionDB("token", "works-db")
    db.client = _DummyClient(
        {
            "整備済": {"type": "checkbox"},
        }
    )

    db.get_catchup_candidates("x", ["instagram", "threads"], limit=1)

    filters = _last_filters(db)
    assert {"property": "整備済", "checkbox": {"equals": True}} in filters
    assert {"property": "完成日", "date": {"on_or_after": "2025-01-01"}} in filters


def test_is_page_ready_fallback_prefers_env_property(monkeypatch):
    db = NotionDB("token", "works-db")
    monkeypatch.setenv("NOTION_WORKS_READY_PROP", "公開可")

    def _raise_schema_error():
        raise RuntimeError("schema unavailable")

    db._resolve_ready_property = _raise_schema_error  # type: ignore[method-assign]

    props = {
        "公開可": {"type": "checkbox", "checkbox": True},
        "整備済み": {"type": "checkbox", "checkbox": False},
    }

    assert db._is_page_ready(props) is True
