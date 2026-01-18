"""Photo grouping functionality for Google Takeout imports."""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Supported image extensions
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic"}


@dataclass
class PhotoInfo:
    """Information about a single photo."""

    path: Path
    timestamp: datetime
    title: str | None = None

    def __lt__(self, other: "PhotoInfo") -> bool:
        return self.timestamp < other.timestamp


@dataclass
class PhotoGroup:
    """A group of related photos (one work)."""

    id: int
    photos: list[PhotoInfo] = field(default_factory=list)
    work_name: str = ""
    student_name: str | None = None

    @property
    def timestamp(self) -> datetime | None:
        """Return the earliest timestamp in the group."""
        if not self.photos:
            return None
        return min(p.timestamp for p in self.photos)

    @property
    def photo_count(self) -> int:
        return len(self.photos)


def parse_takeout_timestamp(json_path: Path) -> datetime | None:
    """Parse timestamp from Google Takeout JSON metadata file."""
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)

        # Google Takeout uses photoTakenTime.timestamp (Unix timestamp)
        if "photoTakenTime" in data and "timestamp" in data["photoTakenTime"]:
            ts = int(data["photoTakenTime"]["timestamp"])
            return datetime.fromtimestamp(ts)

        # Fallback: creationTime
        if "creationTime" in data and "timestamp" in data["creationTime"]:
            ts = int(data["creationTime"]["timestamp"])
            return datetime.fromtimestamp(ts)

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.debug(f"Failed to parse JSON {json_path}: {e}")

    return None


def parse_filename_timestamp(filename: str) -> datetime | None:
    """Try to extract timestamp from filename patterns."""
    # Pattern: IMG_20230415_123456.jpg or 20230415_123456.jpg
    patterns = [
        r"(\d{8})_(\d{6})",  # YYYYMMDD_HHMMSS
        r"(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})",  # YYYY-MM-DD_HH-MM-SS
        r"(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})",  # YYYYMMDDHHMMSS
    ]

    for pattern in patterns:
        match = re.search(pattern, filename)
        if match:
            groups = match.groups()
            try:
                if len(groups) == 2:
                    # YYYYMMDD_HHMMSS format
                    date_str, time_str = groups
                    return datetime.strptime(f"{date_str}{time_str}", "%Y%m%d%H%M%S")
                elif len(groups) == 6:
                    return datetime(
                        int(groups[0]),
                        int(groups[1]),
                        int(groups[2]),
                        int(groups[3]),
                        int(groups[4]),
                        int(groups[5]),
                    )
            except ValueError:
                continue

    return None


def get_photo_timestamp(photo_path: Path) -> datetime | None:
    """Get timestamp for a photo, trying JSON metadata first, then filename."""
    # Try Google Takeout JSON metadata
    json_path = Path(str(photo_path) + ".json")
    if json_path.exists():
        ts = parse_takeout_timestamp(json_path)
        if ts:
            return ts

    # Try filename parsing
    ts = parse_filename_timestamp(photo_path.name)
    if ts:
        return ts

    # Fallback to file modification time
    return datetime.fromtimestamp(photo_path.stat().st_mtime)


def scan_photos(folder: Path) -> list[PhotoInfo]:
    """Scan a folder for photos and extract their timestamps."""
    photos = []

    for path in folder.rglob("*"):
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            timestamp = get_photo_timestamp(path)
            if timestamp:
                photos.append(PhotoInfo(path=path, timestamp=timestamp, title=path.stem))
            else:
                logger.warning(f"Could not determine timestamp for: {path}")

    # Sort by timestamp
    photos.sort()
    logger.info(f"Found {len(photos)} photos in {folder}")
    return photos


def group_by_time(
    photos: list[PhotoInfo],
    threshold_minutes: int = 10,
    max_per_group: int = 10,
) -> list[PhotoGroup]:
    """
    Group photos by time intervals.

    Args:
        photos: List of PhotoInfo objects (should be pre-sorted by timestamp)
        threshold_minutes: Time gap threshold to split groups (default: 10 minutes)
        max_per_group: Maximum photos per group (default: 10 for Instagram carousel)

    Returns:
        List of PhotoGroup objects
    """
    if not photos:
        return []

    groups: list[PhotoGroup] = []
    current_group = PhotoGroup(id=1, photos=[photos[0]])

    for photo in photos[1:]:
        prev_photo = current_group.photos[-1]
        time_diff = (photo.timestamp - prev_photo.timestamp).total_seconds() / 60

        # Start new group if time gap exceeds threshold
        if time_diff > threshold_minutes:
            groups.append(current_group)
            current_group = PhotoGroup(id=len(groups) + 1, photos=[photo])
        else:
            current_group.photos.append(photo)

    # Add the last group
    groups.append(current_group)

    # Split groups that exceed max_per_group
    final_groups: list[PhotoGroup] = []
    group_id = 1

    for group in groups:
        if group.photo_count <= max_per_group:
            group.id = group_id
            final_groups.append(group)
            group_id += 1
        else:
            # Split into multiple groups
            for i in range(0, group.photo_count, max_per_group):
                subset = group.photos[i : i + max_per_group]
                new_group = PhotoGroup(id=group_id, photos=subset)
                final_groups.append(new_group)
                group_id += 1
                logger.info(
                    f"Split large group: created group {group_id - 1} with {len(subset)} photos"
                )

    return final_groups


def export_grouping(groups: list[PhotoGroup], output_path: Path) -> None:
    """Export grouping data to a JSON file for manual review/editing."""
    data = {
        "version": 1,
        "generated_at": datetime.now().isoformat(),
        "groups": [],
    }

    for group in groups:
        group_data = {
            "id": group.id,
            "work_name": group.work_name or f"Work_{group.id:03d}",
            "student_name": group.student_name,
            "photo_count": group.photo_count,
            "first_timestamp": group.timestamp.isoformat() if group.timestamp else None,
            "photos": [
                {
                    "path": str(photo.path),
                    "timestamp": photo.timestamp.isoformat(),
                    "title": photo.title,
                }
                for photo in group.photos
            ],
        }
        data["groups"].append(group_data)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"Exported grouping to {output_path}")


def import_grouping(input_path: Path) -> list[PhotoGroup]:
    """Import grouping data from a JSON file."""
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    groups = []
    for group_data in data["groups"]:
        photos = [
            PhotoInfo(
                path=Path(p["path"]),
                timestamp=datetime.fromisoformat(p["timestamp"]),
                title=p.get("title"),
            )
            for p in group_data["photos"]
        ]
        group = PhotoGroup(
            id=group_data["id"],
            photos=photos,
            work_name=group_data.get("work_name", ""),
            student_name=group_data.get("student_name"),
        )
        groups.append(group)

    logger.info(f"Imported {len(groups)} groups from {input_path}")
    return groups


def print_grouping_summary(groups: list[PhotoGroup]) -> None:
    """Print a summary of the grouping for review."""
    total_photos = sum(g.photo_count for g in groups)
    print(f"\nGrouping Summary: {len(groups)} groups, {total_photos} photos\n")
    print("-" * 70)

    for group in groups:
        ts = group.timestamp.strftime("%Y-%m-%d %H:%M") if group.timestamp else "N/A"
        name = group.work_name or f"Work_{group.id:03d}"
        student = f" ({group.student_name})" if group.student_name else ""
        print(f"Group {group.id:3d}: {group.photo_count:2d} photos | {ts} | {name}{student}")

        # Show first few photo filenames
        for i, photo in enumerate(group.photos[:3]):
            print(f"           - {photo.path.name}")
        if group.photo_count > 3:
            print(f"           ... and {group.photo_count - 3} more")
        print()
