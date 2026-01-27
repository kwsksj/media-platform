"""Tests for poster module."""

import pytest

from auto_post.poster import generate_caption


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
        expected = "ふくろう の木彫りです！\nカスタムキャプション\n\n#tag1 #tag2\n\n#custom"
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
        assert result == "ねこ の木彫りです！\n\n#tag1 #tag2\n\n#猫 #cat"

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
        assert result == "いぬ の木彫りです！\n\n#tag1\n\n#dog"

    def test_none_values(self):
        """Test with None values."""
        result = generate_caption(
            work_name="くま",
            custom_caption=None,
            tags=None,
            default_tags="#default",
        )
        assert result == "くま の木彫りです！\n\n#default"
