"""Notion database integration."""

import logging
from dataclasses import dataclass
from datetime import datetime

from notion_client import Client

logger = logging.getLogger(__name__)


@dataclass
class WorkItem:
    """Represents a work item from Notion database."""

    page_id: str
    work_name: str
    student_name: str | None
    image_urls: list[str]
    scheduled_date: datetime | None
    skip: bool
    caption: str | None
    tags: str | None
    ig_posted: bool
    ig_post_id: str | None
    x_posted: bool
    x_post_id: str | None


class NotionDB:
    """Notion database client."""

    def __init__(self, token: str, database_id: str, tags_database_id: str | None = None):
        self.client = Client(auth=token, notion_version="2022-06-28")
        self.database_id = database_id
        self.tags_database_id = tags_database_id
        self.known_properties = None

    def _is_property_valid(self, prop_name: str) -> bool:
        """Check if a property exists in the database schema."""
        if self.known_properties is None:
            try:
                db = self.get_database_info()
                self.known_properties = set(db["properties"].keys())
            except Exception as e:
                logger.warning(f"Failed to fetch database schema: {e}")
                return True # Assume valid if check fails to avoid blocking

        return prop_name in self.known_properties

    def _get_or_create_tag_page(self, tag_name: str) -> str | None:
        """Find or create a page in the Keywords database."""
        if not self.tags_database_id:
            return None

        # Search for existing tag
        response = self.client.request(
            path=f"databases/{self.tags_database_id}/query",
            method="POST",
            body={
                "filter": {
                    "property": "名前", # Assumes default title property is "名前" or "Name" - usually "Name" or "名前" in JP
                    "title": {"equals": tag_name}
                }
            }
        )

        if response["results"]:
            return response["results"][0]["id"]

        # Create new tag
        # Note: Title property name varies. Try "名前" first, fallback if it fails?
        # Actually standard new DB has "Name" or "名前". Let's try standard "名前" since user created as "キーワード"
        # We can inspect schema, but for now Assume "名前". If user manually created, title is usually "名前" in JP locale or "Name".
        # Safe bet: retrieve DB schema first? Or just try "Name" then "名前"?
        # Let's inspect DB schema in __init__ if needed, but for now try to be generic or catch error.

        # We'll use a helper to get title property name
        try:
            prop_name = "名前" # User likely has Japanese UI
            create_resp = self.client.pages.create(
                parent={"database_id": self.tags_database_id},
                properties={
                    prop_name: {"title": [{"text": {"content": tag_name}}]}
                }
            )
            return create_resp["id"]
        except Exception as e:
            logger.warning(f"Failed to create tag '{tag_name}' with prop '名前': {e}. Trying 'Name'.")
            try:
                create_resp = self.client.pages.create(
                    parent={"database_id": self.tags_database_id},
                    properties={
                        "Name": {"title": [{"text": {"content": tag_name}}]}
                    }
                )
                return create_resp["id"]
            except Exception as e2:
                logger.error(f"Failed to create tag '{tag_name}': {e2}")
                return None


    # ... (existing methods) ...

    def add_work(
        self,
        work_name: str,
        image_urls: list[str],
        student_name: str | None = None,
        scheduled_date: datetime | None = None,
        creation_date: datetime | None = None,
        tags: str | None = None,
        location_tags: list[str] | None = None,
        classroom: str | None = None,
    ) -> str:
        """Add a new work item to the database. Returns page ID."""
        properties = {
            "作品名": {"title": [{"text": {"content": work_name}}]},
            "画像": {
                "files": [{"type": "external", "name": f"image_{i+1}", "external": {"url": url}} for i, url in enumerate(image_urls)]
            },
        }

        if student_name and self._is_property_valid("生徒名"):
            properties["生徒名"] = {"select": {"name": student_name}}
        if scheduled_date and self._is_property_valid("投稿予定日"):
            properties["投稿予定日"] = {"date": {"start": scheduled_date.strftime("%Y-%m-%d")}}
        if creation_date and self._is_property_valid("完成日"):
            properties["完成日"] = {"date": {"start": creation_date.strftime("%Y-%m-%d")}}

        # Prepare tags list
        tag_names = set()

        # Independent Classroom property (Select type)
        if classroom:
            if self._is_property_valid("教室"):
                properties["教室"] = {"select": {"name": classroom}}
            # User request: Add classroom to Tags as well (for Relation/Filter)
            tag_names.add(classroom)

        # Process input string tags
        if tags:
            raw_tags = tags.replace("　", " ").split(" ")
            for t in raw_tags:
                clean_tag = t.strip().lstrip("#")
                if clean_tag:
                    tag_names.add(clean_tag)

        # Add location tags to the general tag set as fallback/redundancy
        # (Only if not mapped to properties, or if we want them in both?
        # User asked for independent, but keeping them in tags too might be safe for now,
        # or we remove them if mapped. Let's keep them in tags only if specific props don't exist?
        # Simpler: just keep adding them to tags if location_tags is passed.
        # The importer will decide whether to pass them to both args.)
        if location_tags:
            for tag in location_tags:
                if tag:
                    tag_names.add(tag.strip())

        # Link to Keywords DB (Relation) - ONLY if tags_database_id is configured
        relation_used = False
        if self.tags_database_id:
            relation_ids = []
            for tag_name in tag_names:
                tag_id = self._get_or_create_tag_page(tag_name)
                if tag_id:
                    relation_ids.append({"id": tag_id})

            if relation_ids:
                # User wants "Tag" column to be the Relation.
                # Assuming user has set "タグ" as Relation type in Notion.
                properties["タグ"] = {"relation": relation_ids}
                relation_used = True

        # Fallback/Alternative: Write to Multi-select "タグ" property
        # Only if Relation mechanism wasn't used (to avoid overwriting/type error)
        if not relation_used and tag_names and self._is_property_valid("タグ"):
            ms_options = [{"name": t} for t in tag_names]
            properties["タグ"] = {"multi_select": ms_options}

        # Set the first image as the page cover for better Gallery View visibility
        page_cover = None
        if image_urls:
            page_cover = {"type": "external", "external": {"url": image_urls[0]}}

        response = self.client.pages.create(
            parent={"database_id": self.database_id},
            properties=properties,
            cover=page_cover,
        )

        logger.info(f"Created Notion page: {response['id']}")
        return response["id"]

    def get_posts_for_date(self, target_date: datetime) -> list[WorkItem]:
        """Get posts scheduled for a specific date."""
        date_str = target_date.strftime("%Y-%m-%d")

        response = self.client.request(
            path=f"databases/{self.database_id}/query",
            method="POST",
            body={
                "filter": {
                    "and": [
                        {
                            "property": "投稿予定日",
                            "date": {"equals": date_str},
                        },
                        {
                            "property": "スキップ",
                            "checkbox": {"equals": False}
                        },
                        {
                            "property": "Instagram投稿済",
                            "checkbox": {"equals": False}
                        },
                        {
                            "property": "X投稿済",
                            "checkbox": {"equals": False}
                        },
                    ]
                }
            },
        )

        return [self._parse_page(page) for page in response["results"]]

    def _parse_page(self, page: dict) -> WorkItem:
        """Parse a Notion page into a WorkItem."""
        props = page["properties"]

        # Extract title (作品名)
        work_name = ""
        if props.get("作品名", {}).get("title"):
            work_name = props["作品名"]["title"][0]["plain_text"] if props["作品名"]["title"] else ""

        # Extract select (生徒名)
        student_name = None
        if props.get("生徒名", {}).get("select"):
            student_name = props["生徒名"]["select"]["name"]

        # Extract files (画像)
        image_urls = []
        if props.get("画像", {}).get("files"):
            for file in props["画像"]["files"]:
                if file["type"] == "external":
                    image_urls.append(file["external"]["url"])
                elif file["type"] == "file":
                    image_urls.append(file["file"]["url"])

        # Extract date (投稿予定日)
        scheduled_date = None
        if props.get("投稿予定日", {}).get("date"):
            date_obj = props["投稿予定日"]["date"]
            if date_obj and date_obj.get("start"):
                scheduled_date = datetime.fromisoformat(date_obj["start"])

        # Extract checkboxes
        skip = props.get("スキップ", {}).get("checkbox", False)
        ig_posted = props.get("Instagram投稿済", {}).get("checkbox", False)
        x_posted = props.get("X投稿済", {}).get("checkbox", False)

        # Extract rich text fields
        caption = self._get_rich_text(props, "キャプション")
        tags = self._get_rich_text(props, "タグ")
        ig_post_id = self._get_rich_text(props, "Instagram投稿ID")
        x_post_id = self._get_rich_text(props, "X投稿ID")

        return WorkItem(
            page_id=page["id"],
            work_name=work_name,
            student_name=student_name,
            image_urls=image_urls,
            scheduled_date=scheduled_date,
            skip=skip,
            caption=caption,
            tags=tags,
            ig_posted=ig_posted,
            ig_post_id=ig_post_id,
            x_posted=x_posted,
            x_post_id=x_post_id,
        )

    def _get_rich_text(self, props: dict, key: str) -> str | None:
        """Extract plain text from a rich_text property."""
        if props.get(key, {}).get("rich_text"):
            texts = props[key]["rich_text"]
            if texts:
                return "".join(t["plain_text"] for t in texts)
        return None

    def update_post_status(
        self,
        page_id: str,
        ig_posted: bool | None = None,
        ig_post_id: str | None = None,
        x_posted: bool | None = None,
        x_post_id: str | None = None,
        error_log: str | None = None,
        posted_date: datetime | None = None,
    ):
        """Update the post status in Notion."""
        properties = {}

        if ig_posted is not None:
            properties["Instagram投稿済"] = {"checkbox": ig_posted}
        if ig_post_id is not None:
            properties["Instagram投稿ID"] = {"rich_text": [{"text": {"content": ig_post_id}}]}
        if x_posted is not None:
            properties["X投稿済"] = {"checkbox": x_posted}
        if x_post_id is not None:
            properties["X投稿ID"] = {"rich_text": [{"text": {"content": x_post_id}}]}

        if posted_date and self._is_property_valid("投稿日"):
            properties["投稿日"] = {"date": {"start": posted_date.strftime("%Y-%m-%d")}}

        if error_log is not None:
            # Append to existing error log
            page = self.client.pages.retrieve(page_id)
            current_log = self._get_rich_text(page["properties"], "エラーログ") or ""
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            new_entry = f"{timestamp} | {error_log}"
            updated_log = f"{current_log}\n{new_entry}" if current_log else new_entry
            properties["エラーログ"] = {"rich_text": [{"text": {"content": updated_log[:2000]}}]}

        if properties:
            self.client.pages.update(page_id=page_id, properties=properties)
            logger.info(f"Updated Notion page: {page_id}")


    def list_works(self, filter_student: str | None = None, only_unposted: bool = False) -> list[WorkItem]:
        """List all work items, optionally filtered."""
        filters = []

        if filter_student:
            filters.append({"property": "生徒名", "select": {"equals": filter_student}})

        if only_unposted:
            filters.append({
                "or": [
                    {"property": "Instagram投稿済", "checkbox": {"equals": False}},
                    {"property": "X投稿済", "checkbox": {"equals": False}},
                ]
            })

        query_params = {"database_id": self.database_id}
        if filters:
            query_params["filter"] = {"and": filters} if len(filters) > 1 else filters[0]

        response = self.client.request(
            path=f"databases/{self.database_id}/query",
            method="POST",
            body=query_params.get("filter") and {"filter": query_params["filter"]} or {}
        )
        return [self._parse_page(page) for page in response["results"]]

    def get_database_info(self) -> dict:
        """Get database schema information."""
        return self.client.databases.retrieve(self.database_id)

    def get_unscheduled_works(self, limit: int = 1) -> list[WorkItem]:
        """
        Get the oldest unposted works (by 完成日) that have no scheduled date.
        Used as fallback when no works are scheduled for today.

        Args:
            limit: Maximum number of works to return
        """
        response = self.client.request(
            path=f"databases/{self.database_id}/query",
            method="POST",
            body={
                "filter": {
                    "and": [
                        # No scheduled date
                        {
                            "property": "投稿予定日",
                            "date": {"is_empty": True},
                        },
                        # Not skipped
                        {
                            "property": "スキップ",
                            "checkbox": {"equals": False}
                        },
                        # Not yet posted
                        {
                            "property": "Instagram投稿済",
                            "checkbox": {"equals": False}
                        },
                        {
                            "property": "X投稿済",
                            "checkbox": {"equals": False}
                        },
                    ]
                },
                # Sort by 完成日 ascending (oldest first)
                "sorts": [
                    {"property": "完成日", "direction": "ascending"}
                ],
                "page_size": limit,
            },
        )

        return [self._parse_page(page) for page in response["results"]]

    def find_page_by_title(self, title: str) -> str | None:
        """
        Find a page ID by its exact title (Work Name) using Search API.
        Query API is causing 400 Bad Request for some reason, so we use Search + Filter.
        """
        try:
            # Search for the string (fuzzy match)
            response = self.client.search(
                query=title,
                filter={"property": "object", "value": "page"}
            )

            for result in response["results"]:
                # 1. Check if it belongs to OUR database
                parent = result.get("parent")
                if not parent or parent.get("type") != "database_id":
                    continue

                # Normalize dashes in IDs for comparison
                res_db_id = parent["database_id"].replace("-", "")
                target_db_id = self.database_id.replace("-", "")

                if res_db_id != target_db_id:
                    continue

                # 2. Check EXACT title match
                # Use _parse_page logic to safely extract title?
                work_item = self._parse_page(result)
                if work_item.work_name == title:
                    return result["id"]

        except Exception as e:
            logger.error(f"Error searching page by title '{title}': {e}")
        return None

    def update_work_location(self, page_id: str, classroom: str) -> None:
        """Update the location (Classroom) for an existing work."""
        properties = {}
        tag_names = set()

        # 1. Update Classroom Property
        if self._is_property_valid("教室"):
            properties["教室"] = {"select": {"name": classroom}}

        # 2. Add to Tags (Relation or Multi-select)
        tag_names.add(classroom)

        # Retrieve existing tags to preserve them?
        # Ideally yes, but merging relations is tricky without fetching first.
        # For now, let's Append to Relation if possible.
        # But Notion API "properties" update replaces the value.
        # So we really should fetch the page's current relation IDs first.

        # NOTE: To keep it simple for this specific fix (filling MISSING location),
        # we can just try to add the relation.
        # However, overwriting existing tags is risky if user manually added some.
        # Let's try to just update "教室" first, and "タグ" if empty?
        # Or better: Fetch page -> get current tags -> append -> update.

        # Fetch current page details
        page = self.client.pages.retrieve(page_id)
        current_relation_ids = []

        # Check current Relation
        # Assuming "タグ" is Relation property key
        # (This relies on property name being valid)
        if "タグ" in page["properties"] and page["properties"]["タグ"]["type"] == "relation":
             current_relation_ids = [{"id": r["id"]} for r in page["properties"]["タグ"]["relation"]]

        # Check Multi-select
        current_ms_names = set()
        if "タグ" in page["properties"] and page["properties"]["タグ"]["type"] == "multi_select":
             current_ms_names = {opt["name"] for opt in page["properties"]["タグ"]["multi_select"]}

        # Prepare new tag
        relation_used = False
        if self.tags_database_id:
            tag_id = self._get_or_create_tag_page(classroom)
            if tag_id:
                # Check if already exists
                if not any(r["id"] == tag_id for r in current_relation_ids):
                    current_relation_ids.append({"id": tag_id})

                properties["タグ"] = {"relation": current_relation_ids}
                relation_used = True

        # Fallback to Multi-select
        if not relation_used and self._is_property_valid("タグ"):
             current_ms_names.add(classroom)
             ms_options = [{"name": t} for t in current_ms_names]
             properties["タグ"] = {"multi_select": ms_options}

        if properties:
            self.client.pages.update(page_id=page_id, properties=properties)
            logger.info(f"Updated location for page {page_id}: {classroom}")
