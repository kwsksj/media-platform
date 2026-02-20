"""Tests for poster module."""

from datetime import datetime
from unittest.mock import Mock

from auto_post.notion_db import WorkItem
from auto_post.poster import Poster, generate_caption


def _make_work(page_id: str, work_name: str, creation_date: datetime) -> WorkItem:
    return WorkItem(
        page_id=page_id,
        work_name=work_name,
        student_name=None,
        classroom=None,
        image_urls=["https://example.com/test.jpg"],
        creation_date=creation_date,
        scheduled_date=None,
        skip=False,
        caption=None,
        tags=None,
        ig_posted=False,
        ig_post_id=None,
        x_posted=False,
        x_post_id=None,
        threads_posted=False,
        threads_post_id=None,
    )


class TestGenerateCaption:
    """Tests for generate_caption function."""

    def test_with_work_name(self):
        """Test caption generation with work name."""
        result = generate_caption(
            work_name="ふくろう",
            custom_caption=None,
            tags=None,
            default_tags="#tag1 #tag2",
        )
        assert result == "ふくろう の木彫りです！\n\n#tag1 #tag2"

    def test_with_custom_caption(self):
        """Test that custom caption is appended."""
        result = generate_caption(
            work_name="ふくろう",
            custom_caption="カスタムキャプション",
            tags="#custom",
            default_tags="#tag1 #tag2",
        )
        # Implementation appends custom caption and includes default tags
        expected = "ふくろう の木彫りです！\nカスタムキャプション\n\n#tag1 #tag2\n#custom"
        assert result == expected

    def test_with_custom_tags(self):
        """Test custom tags are appended to default tags."""
        result = generate_caption(
            work_name="ねこ",
            custom_caption=None,
            tags="#猫 #cat",
            default_tags="#tag1 #tag2",
        )
        # Default tags come first
        assert result == "ねこ の木彫りです！\n\n#tag1 #tag2\n#猫 #cat"

    def test_empty_work_name(self):
        """Test with empty work name returns only tags."""
        result = generate_caption(
            work_name="",
            custom_caption=None,
            tags=None,
            default_tags="#tag1 #tag2",
        )
        assert result == "#tag1 #tag2"

    def test_whitespace_handling(self):
        """Test whitespace is trimmed and tags combined."""
        result = generate_caption(
            work_name="  いぬ  ",
            custom_caption=None,
            tags="  #dog  ",
            default_tags="#tag1",
        )
        assert result == "いぬ の木彫りです！\n\n#tag1\n#dog"

    def test_none_values(self):
        """Test with None values."""
        result = generate_caption(
            work_name="くま",
            custom_caption=None,
            tags=None,
            default_tags="#default",
        )
        assert result == "くま の木彫りです！\n\n#default"

    def test_creation_date_no_blank_line_before_tags(self):
        """Test completion date is followed directly by tags."""
        result = generate_caption(
            work_name="はと",
            custom_caption=None,
            tags="#class",
            default_tags="#default",
            creation_date=datetime(2024, 1, 2),
        )
        expected = "はと の木彫りです！\n\n完成日: 2024年01月02日\n#default\n#class"
        assert result == expected


class TestRunDailyPost:
    def test_selects_oldest_and_year_start_candidates(self, monkeypatch):
        poster = object.__new__(Poster)
        poster.notion = Mock()

        oldest_work = _make_work("old-1", "oldest", datetime(2023, 12, 31))
        year_start_work = _make_work("jan-1", "january", datetime(2026, 1, 5))

        poster.notion.get_posts_for_date.return_value = []
        poster.notion.get_catchup_candidates.return_value = []
        poster.notion.get_basic_candidates.return_value = [oldest_work]
        poster.notion.get_year_start_candidates.return_value = [year_start_work]
        poster.notion.update_post_status.return_value = None

        posted_ids: list[str] = []

        def fake_process_post(work: WorkItem, dry_run: bool = False, platforms: list[str] | None = None) -> dict:
            posted_ids.append(work.page_id)
            return {"instagram": True, "x": False, "threads": False, "errors": []}

        poster._process_post = fake_process_post  # type: ignore[method-assign]

        monkeypatch.setattr("auto_post.poster.time.sleep", lambda _seconds: None)

        target_date = datetime(2026, 2, 20)
        result = poster.run_daily_post(
            target_date=target_date,
            dry_run=True,
            platforms=["instagram"],
            basic_limit=1,
            catchup_limit=0,
            year_start_limit=1,
        )

        assert posted_ids == ["old-1", "jan-1"]
        assert result["processed"] == ["oldest", "january"]
        poster.notion.get_year_start_candidates.assert_called_once_with(
            "instagram",
            start_date=datetime(2026, 1, 1),
            limit=10,
        )

    def test_year_start_limit_zero_does_not_enqueue_year_start(self, monkeypatch):
        poster = object.__new__(Poster)
        poster.notion = Mock()

        oldest_work = _make_work("old-1", "oldest", datetime(2023, 12, 31))
        year_start_work = _make_work("jan-1", "january", datetime(2026, 1, 5))

        poster.notion.get_posts_for_date.return_value = []
        poster.notion.get_catchup_candidates.return_value = []
        poster.notion.get_basic_candidates.return_value = [oldest_work]
        poster.notion.get_year_start_candidates.return_value = [year_start_work]
        poster.notion.update_post_status.return_value = None

        posted_ids: list[str] = []

        def fake_process_post(work: WorkItem, dry_run: bool = False, platforms: list[str] | None = None) -> dict:
            posted_ids.append(work.page_id)
            return {"instagram": True, "x": False, "threads": False, "errors": []}

        poster._process_post = fake_process_post  # type: ignore[method-assign]

        monkeypatch.setattr("auto_post.poster.time.sleep", lambda _seconds: None)

        result = poster.run_daily_post(
            target_date=datetime(2026, 2, 20),
            dry_run=True,
            platforms=["instagram"],
            basic_limit=1,
            catchup_limit=0,
            year_start_limit=0,
        )

        assert posted_ids == ["old-1"]
        assert result["processed"] == ["oldest"]
