#!/usr/bin/env python3
"""
Update Notion classroom based on completion date schedule.
"""

import os
from datetime import datetime
from dotenv import load_dotenv
from notion_client import Client

load_dotenv(".env")

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

# Classroom schedule from user
CLASSROOM_SCHEDULE = {
    "2024-12-14": "東京教室",
    "2024-12-15": "東京教室",
    "2025-01-25": "東京教室",
    "2025-01-26": "東京教室",
    "2025-01-30": "沼津教室",
    "2025-01-31": "沼津教室",
    "2025-02-01": "沼津教室",
    "2025-02-02": "沼津教室",
    "2025-02-05": "東京教室",
    "2025-02-08": "東京教室",
    "2025-02-09": "東京教室",
    "2025-02-12": "つくば教室",
    "2025-02-15": "東京教室",
    "2025-02-16": "つくば教室",
    "2025-02-19": "東京教室",
    "2025-02-27": "沼津教室",
    "2025-02-28": "沼津教室",
    "2025-03-01": "沼津教室",
    "2025-03-02": "沼津教室",
    "2025-03-08": "東京教室",
    "2025-03-09": "東京教室",
    "2025-03-16": "東京教室",
    "2025-03-19": "つくば教室",
    "2025-03-22": "東京教室",
    "2025-03-23": "つくば教室",
    "2025-03-26": "東京教室",
    "2025-04-03": "沼津教室",
    "2025-04-04": "沼津教室",
    "2025-04-05": "沼津教室",
    "2025-04-06": "沼津教室",
    "2025-04-12": "東京教室",
    "2025-04-13": "東京教室",
    "2025-04-16": "つくば教室",
    "2025-04-19": "東京教室",
    "2025-04-20": "つくば教室",
    "2025-04-23": "東京教室",
    "2025-04-26": "東京教室",
    "2025-05-01": "沼津教室",
    "2025-05-02": "沼津教室",
    "2025-05-03": "沼津教室",
    "2025-05-10": "東京教室",
    "2025-05-11": "東京教室",
    "2025-05-14": "つくば教室",
    "2025-05-18": "つくば教室",
    "2025-05-21": "東京教室",
    "2025-05-24": "東京教室",
    "2025-05-31": "東京教室",
    "2025-06-01": "東京教室",
    "2025-06-05": "沼津教室",
    "2025-06-06": "沼津教室",
    "2025-06-07": "沼津教室",
    "2025-06-08": "沼津教室",
    "2025-06-14": "東京教室",
    "2025-06-15": "東京教室",
    "2025-06-18": "つくば教室",
    "2025-06-21": "東京教室",
    "2025-06-22": "つくば教室",
    "2025-06-25": "東京教室",
    "2025-07-03": "沼津教室",
    "2025-07-04": "沼津教室",
    "2025-07-05": "沼津教室",
    "2025-07-06": "沼津教室",
    "2025-07-07": "沼津教室",
    "2025-07-12": "東京教室",
    "2025-07-13": "東京教室",
    "2025-07-16": "つくば教室",
    "2025-07-19": "東京教室",
    "2025-07-20": "東京教室",
    "2025-07-23": "東京教室",
    "2025-07-25": "つくば教室",
    "2025-07-27": "つくば教室",
    "2025-08-02": "東京教室",
    "2025-08-03": "東京教室",
    "2025-08-07": "沼津教室",
    "2025-08-08": "沼津教室",
    "2025-08-09": "沼津教室",
    "2025-08-10": "沼津教室",
    "2025-08-20": "つくば教室",
    "2025-08-23": "東京教室",
    "2025-08-24": "東京教室",
    "2025-08-27": "東京教室",
    "2025-08-31": "つくば教室",
    "2025-09-04": "沼津教室",
    "2025-09-05": "沼津教室",
    "2025-09-06": "沼津教室",
    "2025-09-07": "沼津教室",
    "2025-09-13": "東京教室",
    "2025-09-14": "東京教室",
    "2025-09-17": "つくば教室",
    "2025-09-20": "東京教室",
    "2025-09-21": "東京教室",
    "2025-09-24": "東京教室",
    "2025-09-28": "つくば教室",
    "2025-10-02": "沼津教室",
    "2025-10-03": "沼津教室",
    "2025-10-04": "沼津教室",
    "2025-10-05": "沼津教室",
    "2025-10-11": "東京教室",
    "2025-10-12": "東京教室",
    "2025-10-15": "つくば教室",
    "2025-10-18": "東京教室",
    "2025-10-19": "東京教室",
    "2025-10-22": "東京教室",
    "2025-10-25": "東京教室",
    "2025-10-26": "つくば教室",
    "2025-11-06": "沼津教室",
    "2025-11-07": "沼津教室",
    "2025-11-08": "沼津教室",
    "2025-11-09": "沼津教室",
    "2025-11-15": "東京教室",
    "2025-11-16": "東京教室",
    "2025-11-19": "つくば教室",
    "2025-11-22": "東京教室",
    "2025-11-23": "東京教室",
    "2025-11-26": "東京教室",
    "2025-11-30": "つくば教室",
    "2025-12-04": "沼津教室",
    "2025-12-05": "沼津教室",
    "2025-12-06": "沼津教室",
    "2025-12-07": "沼津教室",
    "2025-12-10": "東京教室",
    "2025-12-13": "東京教室",
    "2025-12-14": "東京教室",
    "2025-12-17": "東京教室",
    "2025-12-20": "東京教室",
    "2025-12-21": "東京教室",
    "2025-12-24": "つくば教室",
    "2025-12-28": "つくば教室",
    "2026-01-08": "沼津教室",
    "2026-01-09": "沼津教室",
    "2026-01-10": "沼津教室",
    "2026-01-11": "沼津教室",
    "2026-01-14": "東京教室",
    "2026-01-17": "東京教室",
    "2026-01-18": "東京教室",
    "2026-01-21": "つくば教室",
    "2026-01-24": "東京教室",
    "2026-01-25": "東京教室",
    "2026-01-28": "東京教室",
    "2026-02-01": "つくば教室",
    "2026-02-05": "沼津教室",
    "2026-02-06": "沼津教室",
    "2026-02-07": "沼津教室",
    "2026-02-08": "沼津教室",
    "2026-02-11": "東京教室",
    "2026-02-14": "東京教室",
    "2026-02-15": "東京教室",
    "2026-02-18": "つくば教室",
    "2026-02-21": "東京教室",
    "2026-02-22": "東京教室",
    "2026-02-25": "東京教室",
    "2026-03-01": "つくば教室",
    "2026-03-05": "沼津教室",
    "2026-03-06": "沼津教室",
    "2026-03-07": "沼津教室",
    "2026-03-08": "沼津教室",
    "2026-03-11": "つくば教室",
    "2026-03-14": "東京教室",
    "2026-03-15": "東京教室",
    "2026-03-18": "東京教室",
    "2026-03-21": "東京教室",
    "2026-03-22": "東京教室",
    "2026-03-25": "東京教室",
}

def get_all_pages(client: Client, database_id: str):
    """Get all pages from database using Search API."""
    all_pages = []
    start_cursor = None

    while True:
        response = client.search(
            query="Work",
            filter={"property": "object", "value": "page"},
            start_cursor=start_cursor,
            page_size=100
        )

        for result in response["results"]:
            # Check if it has 作品名 property (our database)
            props = result.get("properties", {})
            if "作品名" in props:
                all_pages.append(result)

        if not response.get("has_more"):
            break
        start_cursor = response.get("next_cursor")

    return all_pages

def extract_completion_date(page) -> str | None:
    """Extract 完成日 date from page properties."""
    props = page.get("properties", {})
    completion_date_prop = props.get("完成日", {})

    if completion_date_prop.get("type") == "date":
        date_obj = completion_date_prop.get("date")
        if date_obj and date_obj.get("start"):
            return date_obj["start"][:10]  # YYYY-MM-DD

    return None

def extract_title(page) -> str:
    """Extract title from page."""
    props = page.get("properties", {})
    title_prop = props.get("作品名", {})
    if title_prop.get("title"):
        return title_prop["title"][0]["plain_text"] if title_prop["title"] else ""
    return ""

def main():
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        print("Error: NOTION_TOKEN and NOTION_DATABASE_ID must be set")
        return

    client = Client(auth=NOTION_TOKEN)

    print("Fetching all pages from Notion...")
    pages = get_all_pages(client, NOTION_DATABASE_ID)
    print(f"Found {len(pages)} pages")

    updated = 0
    skipped_no_date = 0
    skipped_not_in_schedule = 0

    for page in pages:
        page_id = page["id"]
        title = extract_title(page)
        completion_date = extract_completion_date(page)

        if not completion_date:
            skipped_no_date += 1
            continue

        # Look up classroom from schedule
        classroom = CLASSROOM_SCHEDULE.get(completion_date)

        if not classroom:
            print(f"  No schedule for: {title} (date: {completion_date})")
            skipped_not_in_schedule += 1
            continue

        # Update page
        print(f"Updating: {title} -> {classroom}")
        try:
            client.pages.update(
                page_id=page_id,
                properties={
                    "教室": {"select": {"name": classroom}}
                }
            )
            updated += 1
        except Exception as e:
            print(f"  Error updating {title}: {e}")

    print(f"\nUpdate Complete:")
    print(f"  Works updated: {updated}")
    print(f"  Skipped (no completion date): {skipped_no_date}")
    print(f"  Skipped (date not in schedule): {skipped_not_in_schedule}")

if __name__ == "__main__":
    main()
