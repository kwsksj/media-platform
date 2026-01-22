"""Photo import functionality."""

import logging
import mimetypes
import glob
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
        self.notion = NotionDB(
            config.notion.token,
            config.notion.database_id,
            config.notion.tags_database_id
        )
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
        base_name = folder.name
        for group in groups:
            if not group.work_name:
                if len(groups) == 1:
                    group.work_name = base_name
                else:
                    group.work_name = f"{base_name} ({group.id})"

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



                    effective_student = student_name or group.student_name

                    # Prepare location info
                    classroom = None
                    if group.location:
                        classroom = group.location.classroom
                        # venue is removed as per user request

                    page_id = self.notion.add_work(
                        work_name=group.work_name,
                        image_urls=image_urls,
                        student_name=effective_student,
                        scheduled_date=current_date,
                        creation_date=group.timestamp,
                        classroom=classroom,
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
        print(f"\\nImport Complete:")
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

    def organize_folder(
        self,
        folder: Path,
        threshold_minutes: int = 10,
        dry_run: bool = False,
        copy: bool = False,
        output_folder: Path | None = None,
    ) -> dict:
        """
        Organize photos in a flat folder into timestamp-based subfolders.
        """
        import shutil

        photos = scan_photos(folder)
        # We don't limit max_per_group for organization, usually 1 group = 1 event = 1 folder
        groups = group_by_time(photos, threshold_minutes, max_per_group=999)

        stats = {"processed": 0, "folders_created": 0}
        action_name = "Copy" if copy else "Move"

        # Determine base output path
        base_output = output_folder if output_folder else folder
        missing_metadata_dir = base_output / "_MissingMetadata"

        print(f"\\nFound {len(photos)} photos, grouped into {len(groups)} sets.")
        print(f"Output to: {base_output} ({action_name})")

        if not dry_run and output_folder:
            output_folder.mkdir(parents=True, exist_ok=True)

        created_folders = set()

        # Let's iterate groups normally, but override destination for missing metadata photos
        for group in groups:
            # Determine group folder name (for valid photos)
            if group.timestamp:
                folder_name = group.timestamp.strftime("%Y-%m-%d_%H%M")
            else:
                folder_name = f"UnknownDate_{group.id}"

            group_target_dir = base_output / folder_name

            for photo in group.photos:
                if not photo.has_json:
                    target_dir = missing_metadata_dir
                else:
                    target_dir = group_target_dir

                # Create dir if needed
                if not dry_run:
                    target_dir.mkdir(exist_ok=True, parents=True)
                    if target_dir not in created_folders and target_dir != base_output:
                        created_folders.add(target_dir)
                        stats["folders_created"] += 1

                if dry_run:
                    print(f"[DRY RUN] {action_name}: {photo.path.name} -> {target_dir.name}/")
                else:
                    # Move/Copy photo
                    dest_path = target_dir / photo.path.name
                    processed = False

                    if copy:
                        if not dest_path.exists():
                            shutil.copy2(str(photo.path), str(dest_path))
                            stats["processed"] += 1
                            processed = True
                        elif dest_path.stat().st_size == photo.path.stat().st_size:
                             processed = True
                    else:
                        if photo.path != dest_path:
                            shutil.move(str(photo.path), str(dest_path))
                            stats["processed"] += 1
                            processed = True

                    # Move JSON sidecars
                    candidate_jsons = list(photo.path.parent.glob(f"{glob.escape(photo.path.name)}*.json"))

                    # Also look for original JSON if edited
                    stem = photo.path.stem
                    suffixes_to_strip = ["-edited", "-編集済み"]
                    original_stem = stem
                    is_edited = False
                    for s in suffixes_to_strip:
                        if stem.endswith(s):
                            original_stem = stem[:-len(s)]
                            is_edited = True
                            break

                    if is_edited:
                        original_candidates = list(photo.path.parent.glob(f"{glob.escape(original_stem)}*.json"))
                        candidate_jsons.extend(original_candidates)

                    # Check Truncated too logic?
                    # If we found it for timestamp, we should move it too!
                    # grouping.py has this logic, but here we are replicating finding candidates logic.
                    # We should probably consolidate or just be aggressive in finding.

                    if len(stem) > 40:
                         truncated_candidates = list(photo.path.parent.glob(f"{glob.escape(stem[:40])}*.json"))
                         for json_path in truncated_candidates:
                            if stem.startswith(json_path.stem):
                                if json_path not in candidate_jsons:
                                    candidate_jsons.append(json_path)

                    for json_path in candidate_jsons:
                        if json_path.exists():
                            dest_json = target_dir / json_path.name
                            if copy:
                                if not dest_json.exists():
                                    shutil.copy2(str(json_path), str(dest_json))
                            else:
                                if json_path != dest_json:
                                    shutil.move(str(json_path), str(dest_json))

                    # Also check base stem json (photo.json)
                    json_path_no_ext = photo.path.with_suffix(".json")
                    if json_path_no_ext.exists() and json_path_no_ext != photo.path:
                        if json_path_no_ext not in candidate_jsons:
                            dest_json = target_dir / json_path_no_ext.name
                            if copy:
                                if not dest_json.exists():
                                    shutil.copy2(str(json_path_no_ext), str(dest_json))
                            else:
                                if json_path_no_ext != dest_json:
                                    shutil.move(str(json_path_no_ext), str(dest_json))

        return stats

    def import_from_subfolders(
        self,
        root_folder: Path,
        student_name: str | None = None,
        start_date: datetime | None = None,
        dry_run: bool = False,
    ) -> dict:
        """
        Import works from subfolders, treating each subfolder as a separate work.
        """
        stats = {
            "groups_processed": 0,
            "photos_uploaded": 0,
            "notion_pages_created": 0,
            "errors": 0,
        }

        # Iterate over immediate subdirectories
        subfolders = sorted([p for p in root_folder.iterdir() if p.is_dir()])

        current_date = start_date

        print(f"Found {len(subfolders)} subfolders in {root_folder}")

        for folder in subfolders:
            logger.info(f"Processing folder: {folder.name}")

            folder_stats = self.import_direct(
                folder,
                threshold_minutes=99999, # Force single group
                max_per_group=999,
                student_name=student_name,
                start_date=current_date,
                dry_run=dry_run
            )

            stats["groups_processed"] += folder_stats["groups_processed"]
            stats["photos_uploaded"] += folder_stats["photos_uploaded"]
            stats["notion_pages_created"] += folder_stats["notion_pages_created"]
            stats["errors"] += folder_stats["errors"]

            if folder_stats["groups_processed"] > 0 and current_date:
                current_date = current_date + timedelta(days=1)

        return stats

    def import_from_subfolders_grouping(self, root_folder: Path) -> list[PhotoGroup]:
        """
        Scan subfolders and return a flat list of groups (one per subfolder).
        Used by update_locations command.
        """
        all_groups = []
        subfolders = sorted([p for p in root_folder.iterdir() if p.is_dir()])

        for folder in subfolders:
            photos = scan_photos(folder)
            # Force single group per folder to match import_from_subfolders logic
            groups = group_by_time(photos, threshold_minutes=99999, max_per_group=999)

            # Set default work name (FolderName)
            base_name = folder.name
            for group in groups:
                 if not group.work_name:
                     group.work_name = base_name # Matches imort_direct logic for single group

            all_groups.extend(groups)

        return all_groups

    def update_existing_locations(self, folder: Path, dry_run: bool = False):
        """
        Scan folder for works and update corresponding Notion pages with location data.
        """
        # Reuse the scanning logic
        # Note: cli.py called import_from_subfolders_grouping first, but didn't pass result.
        # So we scan again here? Or CLI logic was just weird?
        # Let's just scan here if groups match.

        print(f"Scanning {folder} for works to update...")
        groups = self.import_from_subfolders_grouping(folder)

        updated_count = 0
        skipped_count = 0
        not_found_count = 0

        for group in groups:
            if not group.location:
                skipped_count += 1
                continue

            classroom = group.location.classroom
            # Try to find page in Notion by Work Name
            # Work Name = Folder Name (set in import_from_subfolders_grouping)

            print(f"Checking '{group.work_name}' (Location: {classroom})...")

            if dry_run:
                print(f"[DRY RUN] Would update '{group.work_name}' -> Location: {classroom}")
                updated_count += 1
                continue

            page_id = self.notion.find_page_by_title(group.work_name)
            if page_id:
                try:
                    self.notion.update_work_location(page_id, classroom)
                    updated_count += 1
                except Exception as e:
                    logger.error(f"Failed to update page {page_id}: {e}")
            else:
                logger.warning(f"Page not found for work: {group.work_name}")
                not_found_count += 1

        print(f"\\nUpdate Complete:")
        print(f"  Works updated: {updated_count}")
        print(f"  Skipped (no location): {skipped_count}")
        print(f"  Not matched in Notion: {not_found_count}")
