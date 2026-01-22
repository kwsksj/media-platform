#!/usr/bin/env python3
"""
Standalone script to update Notion location data.
Bypasses package installation issues by directly using source code.
"""

import sys
import os
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add source to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv
from notion_client import Client

# Load environment
load_dotenv(".env")

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
TAGS_DATABASE_ID = os.getenv("TAGS_DATABASE_ID")

# Location definitions (from gps_utils.py)
@dataclass
class LocationTag:
    classroom: str
    venue: str

LOCATIONS = [
    {"name": "東京教室", "venue": "浅草橋会場", "lat": 35.6968, "lon": 139.7850, "radius_km": 0.5},
    {"name": "沼津教室", "venue": "沼津会場", "lat": 35.0960, "lon": 138.8638, "radius_km": 0.5},
    {"name": "つくば教室", "venue": "つくば会場", "lat": 36.0835, "lon": 140.0764, "radius_km": 0.5},
]

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two points in km."""
    import math
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

def identify_location(lat: float, lon: float) -> LocationTag | None:
    """Identify location from GPS coordinates."""
    for loc in LOCATIONS:
        dist = haversine_distance(lat, lon, loc["lat"], loc["lon"])
        if dist <= loc["radius_km"]:
            return LocationTag(classroom=loc["name"], venue=loc["venue"])
    return None

def parse_json_metadata(json_path: Path) -> tuple[datetime | None, LocationTag | None]:
    """Parse timestamp and location from Google Takeout JSON."""
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Parse Timestamp - use utcfromtimestamp and add 9 hours for JST
        timestamp = None
        timestamp_data = data.get("photoTakenTime") or data.get("creationTime")
        if timestamp_data and isinstance(timestamp_data, dict):
            ts_str = timestamp_data.get("timestamp")
            if ts_str:
                # Convert UTC to JST (UTC+9)
                timestamp = datetime.utcfromtimestamp(int(ts_str)) + timedelta(hours=9)

        # Parse Location
        location = None
        geo_data = data.get("geoDataExif") or data.get("geoData")
        if geo_data:
            lat = geo_data.get("latitude")
            lon = geo_data.get("longitude")
            if lat and lon and (lat != 0.0 or lon != 0.0):
                location = identify_location(lat, lon)

        return timestamp, location

    except Exception as e:
        logger.debug(f"Failed to parse JSON: {json_path}: {e}")
        return None, None

def scan_folder(folder: Path) -> tuple[datetime | None, LocationTag | None]:
    """Scan folder and return first found timestamp and location."""
    json_files = list(folder.glob("*.json"))

    for json_file in json_files:
        ts, loc = parse_json_metadata(json_file)
        if ts and loc:
            return ts, loc
        if ts and not loc:
            # Keep searching for location
            continue

    # Return whatever we found
    for json_file in json_files:
        ts, loc = parse_json_metadata(json_file)
        if ts:
            return ts, loc

    return None, None

def find_page_by_title(client: Client, database_id: str, title: str) -> str | None:
    """Find a Notion page by title using Search API."""
    try:
        response = client.search(
            query=title,
            filter={"property": "object", "value": "page"}
        )

        for result in response["results"]:
            # Check exact title match (title is unique with "Work" suffix)
            props = result.get("properties", {})
            title_prop = props.get("作品名", {})
            if title_prop.get("title"):
                page_title = title_prop["title"][0]["plain_text"] if title_prop["title"] else ""
                if page_title == title:
                    return result["id"]

    except Exception as e:
        logger.error(f"Error searching for '{title}': {e}")
    return None

def get_or_create_tag(client: Client, tags_db_id: str, tag_name: str) -> str | None:
    """Get or create a tag in the tags database."""
    try:
        # Search for existing tag
        response = client.databases.query(
            database_id=tags_db_id,
            filter={"property": "名前", "title": {"equals": tag_name}}
        )

        if response["results"]:
            return response["results"][0]["id"]

        # Create new tag
        new_page = client.pages.create(
            parent={"database_id": tags_db_id},
            properties={"名前": {"title": [{"text": {"content": tag_name}}]}}
        )
        return new_page["id"]

    except Exception as e:
        logger.error(f"Error with tag '{tag_name}': {e}")
        return None

def update_page_location(client: Client, page_id: str, classroom: str, tags_db_id: str | None):
    """Update a Notion page with classroom and tag."""
    try:
        # Get existing tags
        page = client.pages.retrieve(page_id=page_id)
        existing_tags = page.get("properties", {}).get("タグ", {})

        existing_ids = []
        if existing_tags.get("type") == "relation":
            existing_ids = [r["id"] for r in existing_tags.get("relation", [])]

        # Add classroom tag if tags DB exists
        if tags_db_id:
            tag_id = get_or_create_tag(client, tags_db_id, classroom)
            if tag_id and tag_id not in existing_ids:
                existing_ids.append(tag_id)

        # Update page
        properties = {
            "教室": {"select": {"name": classroom}}
        }

        if tags_db_id and existing_ids:
            properties["タグ"] = {"relation": [{"id": tid} for tid in existing_ids]}

        client.pages.update(page_id=page_id, properties=properties)
        return True

    except Exception as e:
        logger.error(f"Error updating page {page_id}: {e}")
        return False

def main():
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        print("Error: NOTION_TOKEN and NOTION_DATABASE_ID must be set in .env")
        sys.exit(1)

    works_folder = Path("/Users/kawasakiseiji/development/auto-post/WorksPhotes")

    if not works_folder.exists():
        print(f"Error: Folder not found: {works_folder}")
        sys.exit(1)

    client = Client(auth=NOTION_TOKEN)

    # Collect all folders
    subfolders = sorted([p for p in works_folder.iterdir() if p.is_dir()])
    print(f"Found {len(subfolders)} folders to process")

    updated = 0
    skipped_no_location = 0
    not_found = 0

    for folder in subfolders:
        ts, loc = scan_folder(folder)

        if not loc:
            skipped_no_location += 1
            continue

        if not ts:
            skipped_no_location += 1
            continue

        # Generate work name
        work_name = ts.strftime("%Y-%m-%d %H:%M Work")

        print(f"Checking '{work_name}' (Location: {loc.classroom})...")

        # Find page in Notion
        page_id = find_page_by_title(client, NOTION_DATABASE_ID, work_name)

        if not page_id:
            logger.warning(f"Page not found: {work_name}")
            not_found += 1
            continue

        # Update page
        if update_page_location(client, page_id, loc.classroom, TAGS_DATABASE_ID):
            print(f"  Updated: {work_name} -> {loc.classroom}")
            updated += 1
        else:
            print(f"  Failed to update: {work_name}")

    print(f"\nUpdate Complete:")
    print(f"  Works updated: {updated}")
    print(f"  Skipped (no location/timestamp): {skipped_no_location}")
    print(f"  Not matched in Notion: {not_found}")

if __name__ == "__main__":
    main()
