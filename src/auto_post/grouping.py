"""Photo grouping functionality for Google Takeout imports."""

import json
import logging
import re
import glob
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .gps_utils import LocationTag, get_location_for_file, identify_location

logger = logging.getLogger(__name__)

# Supported image extensions
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic"}


@dataclass
class PhotoInfo:
    """Information about a single photo."""

    path: Path
    timestamp: datetime
    title: str | None = None
    location: LocationTag | None = None
    has_json: bool = False

    def __lt__(self, other: "PhotoInfo") -> bool:
        return self.timestamp < other.timestamp


@dataclass
class PhotoGroup:
    """A group of related photos (one work)."""

    id: int
    photos: list[PhotoInfo] = field(default_factory=list)
    work_name: str = ""
    student_name: str | None = None
    location: LocationTag | None = None

    @property
    def timestamp(self) -> datetime | None:
        """Return the earliest timestamp in the group."""
        if not self.photos:
            return None
        return min(p.timestamp for p in self.photos)

    @property
    def photo_count(self) -> int:
        return len(self.photos)


def parse_takeout_metadata(json_path: Path) -> tuple[datetime | None, LocationTag | None]:
    """
    Parse timestamp and location from Google Takeout JSON sidecar.
    Returns: (timestamp, location_tag)
    """
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 1. Parse Timestamp
        timestamp = None
        # Prioritize photoTakenTime (Shooting Date) over creationTime (Upload/Edit Date)
        timestamp_data = data.get("photoTakenTime")
        if not timestamp_data:
            timestamp_data = data.get("creationTime")

        if timestamp_data and isinstance(timestamp_data, dict):
             ts_str = timestamp_data.get("timestamp")
             if ts_str:
                 # Google Photos JSON timestamps are UTC. Convert to JST (UTC+9)
                 timestamp = datetime.utcfromtimestamp(int(ts_str)) + timedelta(hours=9)

        # 2. Parse Location
        location = None
        geo_data = data.get("geoDataExif") or data.get("geoData")
        if geo_data:
            lat = geo_data.get("latitude")
            lon = geo_data.get("longitude")
            # Google Takeout sometimes returns 0.0 for missing data
            if lat and lon and (lat != 0.0 or lon != 0.0):
                location = identify_location(lat, lon)

        return timestamp, location

    except Exception as e:
        logger.debug(f"Failed to parse JSON metadata from {json_path}: {e}")
        return None, None


def parse_filename_timestamp(filename: str) -> datetime | None:
    """
    Parse timestamp from filename patterns.
    """
    patterns = [
        r"PXL_(\d{8})_(\d{6})",  # Pixel: PXL_YYYYMMDD_HHMMSS
        r"IMG_(\d{8})_(\d{6})",  # Android: IMG_YYYYMMDD_HHMMSS
        r"(\d{4})[-_](\d{2})[-_](\d{2})[-_\s](\d{2})[-_.](\d{2})[-_.](\d{2})", # Generic
    ]

    for pattern in patterns:
        match = re.search(pattern, filename)
        if match:
            try:
                groups = match.groups()
                if len(groups) == 6:
                     return datetime(
                         int(groups[0]), int(groups[1]), int(groups[2]),
                         int(groups[3]), int(groups[4]), int(groups[5])
                     )
                elif len(groups) == 2:
                    # PXL/IMG style
                    date_str = groups[0] # YYYYMMDD
                    time_str = groups[1] # HHMMSS
                    return datetime.strptime(f"{date_str}{time_str}", "%Y%m%d%H%M%S")
            except ValueError:
                continue

    return None


def get_photo_metadata(photo_path: Path) -> tuple[datetime | None, LocationTag | None, bool]:
    """
    Get timestamp and location for a photo from JSON or file attributes.
    Returns: (timestamp, location, has_json)
    """
    # 1. Direct match: photo.jpg*.json
    candidate_jsons = list(photo_path.parent.glob(f"{glob.escape(photo_path.name)}*.json"))

    # 2. If no direct match, check if it's an edited file
    stem = photo_path.stem
    suffixes_to_strip = ["-edited", "-編集済み"]
    original_stem = stem
    is_edited = False

    for s in suffixes_to_strip:
        if stem.endswith(s):
            original_stem = stem[:-len(s)]
            is_edited = True
            break

    if is_edited:
        original_candidates = list(photo_path.parent.glob(f"{glob.escape(original_stem)}*.json"))
        candidate_jsons.extend(original_candidates)

    for json_path in candidate_jsons:
        if json_path.exists():
            ts, loc = parse_takeout_metadata(json_path)
            if ts:
                return ts, loc, True

    # Also check base stem json (photo.json)
    json_path_no_ext = photo_path.with_suffix(".json")
    if json_path_no_ext.exists() and json_path_no_ext != photo_path:
        if json_path_no_ext not in candidate_jsons:
            ts, loc = parse_takeout_metadata(json_path_no_ext)
            if ts:
                return ts, loc, True

    # 3. Truncated Match (Google Takeout limits filenames to ~46 chars)
    if len(photo_path.stem) > 40:
        # Match first 40 chars
        truncated_candidates = list(photo_path.parent.glob(f"{glob.escape(photo_path.stem[:40])}*.json"))
        for json_path in truncated_candidates:
            # Logic: json_path.stem must be a prefix of photo_path.stem (truncated case)
            if photo_path.stem.startswith(json_path.stem):
                 if json_path not in candidate_jsons:
                    ts, loc = parse_takeout_metadata(json_path)
                    if ts:
                        return ts, loc, True

    # Try filename parsing for timestamp
    ts = parse_filename_timestamp(photo_path.name)

    # Try EXIF for location if not found in JSON
    # This is expensive so we do it last or if needed
    loc = get_location_for_file(photo_path)

    if ts:
        return ts, loc, False

    # Fallback to file modification time
    try:
        stat = photo_path.stat()
        return datetime.fromtimestamp(stat.st_mtime), loc, False
    except FileNotFoundError:
        return None, None, False


def scan_photos(folder: Path) -> list[PhotoInfo]:
    """
    Scan folder for images and extract metadata.
    Handles duplicate filtering (preferring edited versions).
    """
    if not folder.exists():
        logger.error(f"Folder not found: {folder}")
        return []

    all_files = {}  # Map path -> PhotoInfo
    edited_stems = set()
    edited_keywords = ["-edited", "編集済み"]

    for path in folder.rglob("*"):
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            # Skip hidden files
            if path.name.startswith("."):
                continue

            timestamp, location, has_json = get_photo_metadata(path)

            if timestamp:
                info = PhotoInfo(path=path, timestamp=timestamp, location=location, has_json=has_json)
                all_files[path] = info

                # Identify edited files
                for keyword in edited_keywords:
                    if keyword in path.stem:
                        base_stem = path.stem.replace(f"-{keyword}", "").replace(f" {keyword}", "").replace(keyword, "")
                        edited_stems.add(base_stem.strip(" -_"))
                        break
            else:
                logger.warning(f"Could not determine timestamp for: {path}")

    # Second pass: build final list, filtering out originals if edited exists
    photos = []

    for path, info in all_files.items():
        stem = path.stem

        is_original_of_edited = False
        if stem in edited_stems:
             has_keyword = any(k in stem for k in edited_keywords)
             if not has_keyword:
                 logger.info(f"Skipping original {path.name} in favor of edited version")
                 continue

        photos.append(info)

    # Sort by timestamp
    photos.sort()
    logger.info(f"Found {len(photos)} photos in {folder} (after filtering duplicates)")
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
        elif len(current_group.photos) >= max_per_group:
             # Or if max size reached? (Optional for organize/import-folders, but strict for Import)
             # Let's respect max_per_group
            groups.append(current_group)
            current_group = PhotoGroup(id=len(groups) + 1, photos=[photo])
        else:
            current_group.photos.append(photo)

    groups.append(current_group)

    # Assign names and locations
    for group in groups:
        if group.timestamp:
            group.work_name = group.timestamp.strftime("%Y-%m-%d %H:%M Work")

        # Find first location in the group
        for p in group.photos:
            if p.location:
                group.location = p.location
                break

    return groups

def print_grouping_summary(groups: list[PhotoGroup]):
    """Print summary of groups for preview."""
    print(f"\nGrouping Summary: {len(groups)} groups found")
    for group in groups:
        ts_str = group.timestamp.strftime("%Y-%m-%d %H:%M") if group.timestamp else "N/A"
        print(f"  Group {group.id}: {ts_str} ({group.photo_count} photos)")
        for p in group.photos:
            print(f"    - {p.path.name} ({p.timestamp.strftime('%H:%M:%S')})")

def export_grouping(groups: list[PhotoGroup], output_path: Path):
    """Export grouping to JSON."""
    data = []
    for g in groups:
        g_data = {
            "id": g.id,
            "work_name": g.work_name,
            "student_name": g.student_name,
            "photos": [str(p.path) for p in g.photos]
        }
        data.append(g_data)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def import_grouping(input_path: Path) -> list[PhotoGroup]:
    """Import grouping from JSON."""
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    groups = []
    for g_data in data:
        photos = []
        for p_path_str in g_data["photos"]:
            p_path = Path(p_path_str)
            timestamp, location, has_json = get_photo_metadata(p_path)
            if timestamp:
                photos.append(PhotoInfo(path=p_path, timestamp=timestamp, location=location, has_json=has_json))

        if photos:
            photos.sort()
            group = PhotoGroup(
                id=g_data["id"],
                photos=photos,
                work_name=g_data.get("work_name", ""),
                student_name=g_data.get("student_name")
            )
            groups.append(group)

    return groups
