from auto_post.notion_db import NotionDB


class _DummyPages:
    def __init__(self):
        self.create_calls = []

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return {"id": "page-1"}


class _DummyClient:
    def __init__(self):
        self.pages = _DummyPages()


def test_add_work_uses_relation_tags_when_tag_property_is_relation():
    db = NotionDB("token", "works-db")
    db.client = _DummyClient()

    relation_lookups = []

    db._is_property_valid = lambda prop: prop in {"タグ", "教室"}  # type: ignore[attr-defined]
    db._get_property_type = lambda prop: "relation" if prop == "タグ" else "select"  # type: ignore[attr-defined]
    db._get_relation_database_id = lambda prop: "tags-db" if prop == "タグ" else None  # type: ignore[attr-defined]

    def _fake_get_or_create(database_id: str, title: str) -> str:
        relation_lookups.append((database_id, title))
        return f"id-{title}"

    db._get_or_create_page_by_title = _fake_get_or_create  # type: ignore[method-assign]

    db.add_work(
        work_name="work-a",
        image_urls=["https://example.com/a.jpg"],
        classroom="東京教室",
        tags="#木彫り #作品",
    )

    properties = db.client.pages.create_calls[0]["properties"]
    assert "relation" in properties["タグ"]
    related_ids = {item["id"] for item in properties["タグ"]["relation"]}
    assert related_ids == {"id-木彫り", "id-作品"}
    assert {db_id for db_id, _ in relation_lookups} == {"tags-db"}


def test_add_work_uses_multi_select_tags_when_tag_property_is_multi_select():
    db = NotionDB("token", "works-db")
    db.client = _DummyClient()

    db._is_property_valid = lambda prop: prop in {"タグ", "教室"}  # type: ignore[attr-defined]
    db._get_property_type = lambda prop: "multi_select" if prop == "タグ" else "select"  # type: ignore[attr-defined]
    db._get_relation_database_id = lambda prop: None  # type: ignore[attr-defined]

    db.add_work(
        work_name="work-b",
        image_urls=["https://example.com/b.jpg"],
        classroom="東京教室",
        tags="#木彫り",
    )

    properties = db.client.pages.create_calls[0]["properties"]
    assert "multi_select" in properties["タグ"]
    tag_names = {item["name"] for item in properties["タグ"]["multi_select"]}
    assert tag_names == {"木彫り"}
