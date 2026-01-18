"""Tests for grouping module."""

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from auto_post.grouping import (
    PhotoGroup,
    PhotoInfo,
    group_by_time,
    parse_filename_timestamp,
    parse_takeout_timestamp,
    export_grouping,
    import_grouping,
)


class TestParseFilenameTimestamp:
    """Tests for parse_filename_timestamp function."""

    def test_yyyymmdd_hhmmss_format(self):
        """Test YYYYMMDD_HHMMSS format."""
        result = parse_filename_timestamp("IMG_20230415_123456.jpg")
        assert result == datetime(2023, 4, 15, 12, 34, 56)

    def test_date_only_format(self):
        """Test date-based filename."""
        result = parse_filename_timestamp("20230415_123456.jpg")
        assert result == datetime(2023, 4, 15, 12, 34, 56)

    def test_invalid_format(self):
        """Test invalid format returns None."""
        result = parse_filename_timestamp("random_photo.jpg")
        assert result is None

    def test_edge_case_midnight(self):
        """Test midnight timestamp."""
        result = parse_filename_timestamp("IMG_20231231_000000.jpg")
        assert result == datetime(2023, 12, 31, 0, 0, 0)


class TestParseTakeoutTimestamp:
    """Tests for parse_takeout_timestamp function."""

    def test_photo_taken_time(self):
        """Test parsing photoTakenTime from JSON."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "photoTakenTime": {"timestamp": "1681560896"}
            }, f)
            f.flush()

            result = parse_takeout_timestamp(Path(f.name))
            assert result == datetime.fromtimestamp(1681560896)

    def test_creation_time_fallback(self):
        """Test falling back to creationTime."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "creationTime": {"timestamp": "1681560896"}
            }, f)
            f.flush()

            result = parse_takeout_timestamp(Path(f.name))
            assert result == datetime.fromtimestamp(1681560896)

    def test_invalid_json(self):
        """Test invalid JSON returns None."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json")
            f.flush()

            result = parse_takeout_timestamp(Path(f.name))
            assert result is None


class TestGroupByTime:
    """Tests for group_by_time function."""

    def test_single_photo(self):
        """Test single photo becomes one group."""
        photos = [
            PhotoInfo(path=Path("photo1.jpg"), timestamp=datetime(2023, 4, 15, 12, 0, 0))
        ]
        groups = group_by_time(photos, threshold_minutes=10)

        assert len(groups) == 1
        assert groups[0].photo_count == 1

    def test_photos_within_threshold(self):
        """Test photos within threshold stay in same group."""
        photos = [
            PhotoInfo(path=Path("photo1.jpg"), timestamp=datetime(2023, 4, 15, 12, 0, 0)),
            PhotoInfo(path=Path("photo2.jpg"), timestamp=datetime(2023, 4, 15, 12, 5, 0)),
            PhotoInfo(path=Path("photo3.jpg"), timestamp=datetime(2023, 4, 15, 12, 9, 0)),
        ]
        groups = group_by_time(photos, threshold_minutes=10)

        assert len(groups) == 1
        assert groups[0].photo_count == 3

    def test_photos_exceed_threshold(self):
        """Test photos exceeding threshold split into groups."""
        photos = [
            PhotoInfo(path=Path("photo1.jpg"), timestamp=datetime(2023, 4, 15, 12, 0, 0)),
            PhotoInfo(path=Path("photo2.jpg"), timestamp=datetime(2023, 4, 15, 12, 5, 0)),
            PhotoInfo(path=Path("photo3.jpg"), timestamp=datetime(2023, 4, 15, 12, 20, 0)),  # 15 min gap
            PhotoInfo(path=Path("photo4.jpg"), timestamp=datetime(2023, 4, 15, 12, 25, 0)),
        ]
        groups = group_by_time(photos, threshold_minutes=10)

        assert len(groups) == 2
        assert groups[0].photo_count == 2
        assert groups[1].photo_count == 2

    def test_max_per_group_splits(self):
        """Test groups are split when exceeding max_per_group."""
        photos = [
            PhotoInfo(path=Path(f"photo{i}.jpg"), timestamp=datetime(2023, 4, 15, 12, i, 0))
            for i in range(15)
        ]
        groups = group_by_time(photos, threshold_minutes=60, max_per_group=10)

        assert len(groups) == 2
        assert groups[0].photo_count == 10
        assert groups[1].photo_count == 5

    def test_empty_photos(self):
        """Test empty photo list returns empty groups."""
        groups = group_by_time([])
        assert groups == []

    def test_group_ids_are_sequential(self):
        """Test group IDs are sequential starting from 1."""
        photos = [
            PhotoInfo(path=Path("photo1.jpg"), timestamp=datetime(2023, 4, 15, 12, 0, 0)),
            PhotoInfo(path=Path("photo2.jpg"), timestamp=datetime(2023, 4, 15, 13, 0, 0)),
            PhotoInfo(path=Path("photo3.jpg"), timestamp=datetime(2023, 4, 15, 14, 0, 0)),
        ]
        groups = group_by_time(photos, threshold_minutes=10)

        assert [g.id for g in groups] == [1, 2, 3]


class TestPhotoGroup:
    """Tests for PhotoGroup dataclass."""

    def test_timestamp_returns_earliest(self):
        """Test timestamp property returns earliest photo timestamp."""
        group = PhotoGroup(
            id=1,
            photos=[
                PhotoInfo(path=Path("photo1.jpg"), timestamp=datetime(2023, 4, 15, 12, 5, 0)),
                PhotoInfo(path=Path("photo2.jpg"), timestamp=datetime(2023, 4, 15, 12, 0, 0)),
                PhotoInfo(path=Path("photo3.jpg"), timestamp=datetime(2023, 4, 15, 12, 10, 0)),
            ],
        )
        assert group.timestamp == datetime(2023, 4, 15, 12, 0, 0)

    def test_timestamp_empty_group(self):
        """Test empty group returns None timestamp."""
        group = PhotoGroup(id=1, photos=[])
        assert group.timestamp is None

    def test_photo_count(self):
        """Test photo_count property."""
        group = PhotoGroup(
            id=1,
            photos=[
                PhotoInfo(path=Path("photo1.jpg"), timestamp=datetime(2023, 4, 15, 12, 0, 0)),
                PhotoInfo(path=Path("photo2.jpg"), timestamp=datetime(2023, 4, 15, 12, 5, 0)),
            ],
        )
        assert group.photo_count == 2


class TestExportImportGrouping:
    """Tests for export_grouping and import_grouping functions."""

    def test_export_import_roundtrip(self):
        """Test export then import preserves data."""
        groups = [
            PhotoGroup(
                id=1,
                photos=[
                    PhotoInfo(path=Path("/path/photo1.jpg"), timestamp=datetime(2023, 4, 15, 12, 0, 0), title="photo1"),
                    PhotoInfo(path=Path("/path/photo2.jpg"), timestamp=datetime(2023, 4, 15, 12, 5, 0), title="photo2"),
                ],
                work_name="Test Work",
                student_name="Taro",
            ),
        ]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            output_path = Path(f.name)

        export_grouping(groups, output_path)
        imported = import_grouping(output_path)

        assert len(imported) == 1
        assert imported[0].id == 1
        assert imported[0].work_name == "Test Work"
        assert imported[0].student_name == "Taro"
        assert imported[0].photo_count == 2
        assert imported[0].photos[0].path == Path("/path/photo1.jpg")
        assert imported[0].photos[1].path == Path("/path/photo2.jpg")
