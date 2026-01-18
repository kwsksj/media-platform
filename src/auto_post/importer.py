"""Photo import functionality."""

import logging
import mimetypes
from datetime import datetime, timedelta
from pathlib import Path

from .config import Config
from .grouping import (
    PhotoGroup,
    export_grouping,
    group_by_time,
    import_grouping,
    print_grouping_summary,
    scan_photos,
)
from .notion_db import NotionDB
from .r2_storage import R2Storage

logger = logging.getLogger(__name__)


class Importer:
    """Handles importing photos from local folders to R2 and Notion."""

    def __init__(self, config: Config):
        self.config = config
        self.notion = NotionDB(config.notion.token, config.notion.database_id)
        self.r2 = R2Storage(config.r2)

    def preview_groups(
        self,
        folder: Path,
        threshold_minutes: int = 10,
        max_per_group: int = 10,
    ) -> list[PhotoGroup]:
        """
        Scan a folder and preview how photos would be grouped.

        Args:
            folder: Path to folder containing photos
            threshold_minutes: Time gap threshold for grouping
            max_per_group: Maximum photos per group

        Returns:
            List of PhotoGroup objects
        """
        photos = scan_photos(folder)
        groups = group_by_time(photos, threshold_minutes, max_per_group)
        print_grouping_summary(groups)
        return groups

    def export_preview(
        self,
        folder: Path,
        output_path: Path,
        threshold_minutes: int = 10,
        max_per_group: int = 10,
    ) -> list[PhotoGroup]:
        """
        Scan a folder and export grouping data to a JSON file for editing.

        Args:
            folder: Path to folder containing photos
            output_path: Path to save grouping JSON
            threshold_minutes: Time gap threshold for grouping
            max_per_group: Maximum photos per group

        Returns:
            List of PhotoGroup objects
        """
        photos = scan_photos(folder)
        groups = group_by_time(photos, threshold_minutes, max_per_group)

        # Set default work names
        for group in groups:
            if not group.work_name:
                group.work_name = f"Work_{group.id:03d}"

        export_grouping(groups, output_path)
        print_grouping_summary(groups)
        return groups

    def import_from_file(
        self,
        grouping_file: Path,
        student_name: str | None = None,
        start_date: datetime | None = None,
        dry_run: bool = False,
    ) -> dict:
        """
        Import photos using a previously exported grouping file.

        Args:
            grouping_file: Path to grouping JSON file
            student_name: Optional student name for all imported works
            start_date: Start date for scheduling (increments by 1 day per group)
            dry_run: If True, don't actually upload or create entries

        Returns:
            dict with import statistics
        """
        groups = import_grouping(grouping_file)
        return self._import_groups(groups, student_name, start_date, dry_run)

    def import_direct(
        self,
        folder: Path,
        threshold_minutes: int = 10,
        max_per_group: int = 10,
        student_name: str | None = None,
        start_date: datetime | None = None,
        dry_run: bool = False,
    ) -> dict:
        """
        Directly import photos from a folder without manual review.

        Args:
            folder: Path to folder containing photos
            threshold_minutes: Time gap threshold for grouping
            max_per_group: Maximum photos per group
            student_name: Optional student name for all imported works
            start_date: Start date for scheduling (increments by 1 day per group)
            dry_run: If True, don't actually upload or create entries

        Returns:
            dict with import statistics
        """
        photos = scan_photos(folder)
        groups = group_by_time(photos, threshold_minutes, max_per_group)

        # Set default work names
        for group in groups:
            if not group.work_name:
                group.work_name = f"Work_{group.id:03d}"

        return self._import_groups(groups, student_name, start_date, dry_run)

    def _import_groups(
        self,
        groups: list[PhotoGroup],
        student_name: str | None = None,
        start_date: datetime | None = None,
        dry_run: bool = False,
    ) -> dict:
        """
        Import photo groups to R2 and Notion.

        Args:
            groups: List of PhotoGroup objects
            student_name: Optional student name
            start_date: Start date for scheduling
            dry_run: If True, don't actually upload or create entries

        Returns:
            dict with import statistics
        """
        stats = {
            "groups_processed": 0,
            "photos_uploaded": 0,
            "notion_pages_created": 0,
            "errors": 0,
        }

        current_date = start_date

        for group in groups:
            try:
                logger.info(f"Processing group {group.id}: {group.work_name} ({group.photo_count} photos)")

                if dry_run:
                    print(f"[DRY RUN] Would import: {group.work_name} ({group.photo_count} photos)")
                    if current_date:
                        print(f"  Scheduled: {current_date.strftime('%Y-%m-%d')}")
                    stats["groups_processed"] += 1
                    stats["photos_uploaded"] += group.photo_count
                    stats["notion_pages_created"] += 1
                else:
                    # Upload photos to R2
                    image_urls = []
                    for photo in group.photos:
                        url = self._upload_photo_to_r2(photo.path)
                        image_urls.append(url)
                        stats["photos_uploaded"] += 1

                    # Create Notion entry
                    effective_student = student_name or group.student_name
                    page_id = self.notion.add_work(
                        work_name=group.work_name,
                        image_urls=image_urls,
                        student_name=effective_student,
                        scheduled_date=current_date,
                    )
                    stats["notion_pages_created"] += 1
                    logger.info(f"Created Notion page: {page_id}")

                stats["groups_processed"] += 1

                # Increment date for next group
                if current_date:
                    current_date = current_date + timedelta(days=1)

            except Exception as e:
                logger.error(f"Failed to import group {group.id}: {e}")
                stats["errors"] += 1

        # Print summary
        print(f"\nImport Complete:")
        print(f"  Groups processed: {stats['groups_processed']}")
        print(f"  Photos uploaded: {stats['photos_uploaded']}")
        print(f"  Notion pages created: {stats['notion_pages_created']}")
        print(f"  Errors: {stats['errors']}")

        return stats

    def _upload_photo_to_r2(self, photo_path: Path) -> str:
        """
        Upload a photo to R2 and return its public URL.

        Args:
            photo_path: Path to the photo file

        Returns:
            Public URL of the uploaded photo
        """
        # Read file content
        content = photo_path.read_bytes()

        # Determine content type
        mime_type, _ = mimetypes.guess_type(str(photo_path))
        if not mime_type:
            mime_type = "image/jpeg"

        # Generate unique key
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        key = f"photos/{timestamp}_{photo_path.name}"

        # Upload to R2
        self.r2.upload(content, key, mime_type)
        logger.debug(f"Uploaded: {key}")

        # Return public URL
        if self.config.r2.public_url:
            return f"{self.config.r2.public_url}/{key}"
        else:
            # Use presigned URL if no public URL configured
            return self.r2.generate_presigned_url(key, expires_in=365 * 24 * 3600)
