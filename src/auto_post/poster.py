"""Main posting logic."""

import logging
import time
from datetime import datetime

import requests

from .config import Config
from .instagram import InstagramAPIError, InstagramClient
from .notion_db import NotionDB, WorkItem
from .r2_storage import R2Storage
from .token_manager import TokenManager
from .x_twitter import XAPIError, XClient
from .threads import ThreadsClient, ThreadsAPIError

logger = logging.getLogger(__name__)

# Wait time for Threads API to download images after publish
# Threads downloads images asynchronously after container is published
THREADS_IMAGE_DOWNLOAD_WAIT_SECONDS = 10


def generate_caption(
    work_name: str,
    custom_caption: str | None,
    tags: str | None,
    default_tags: str,
    creation_date: datetime | None = None
) -> str:
    """Generate caption from work name and tags."""
    # Build caption: {作品名} の木彫りです！\n{キャプション}\n\n完成日: ...
    lines = []

    if work_name and work_name.strip():
        lines.append(f"{work_name.strip()} の木彫りです！")

    if custom_caption and custom_caption.strip():
        lines.append(custom_caption.strip())

    if creation_date:
        date_str = creation_date.strftime("%Y年%m月%d日")
        lines.append("")  # 空行
        lines.append(f"完成日: {date_str}")

    caption = "\n".join(lines)

    custom_tags = []
    if tags:
        # Split by Space (or ideographic space) to handle multiple tags in string
        for t in tags.replace("　", " ").split():
            t = t.strip()
            if t:
                # Add # if missing
                if not t.startswith("#"):
                    t = f"#{t}"
                custom_tags.append(t)

    # Combine Custom Tags + Default Tags
    # Use a set to avoid duplicates if needed, but ordered list is better for display
    combined_tags_str = " ".join(custom_tags)

    # Normalize Default Tags (ensure # prefix)
    norm_dest_tags = []
    if default_tags:
         for t in default_tags.replace("　", " ").split():
            t = t.strip()
            if t:
                if not t.startswith("#"):
                    t = f"#{t}"
                norm_dest_tags.append(t)
    default_tags_str = " ".join(norm_dest_tags)

    if default_tags_str:
        if combined_tags_str:
            # Default Tags FIRST, then Custom Tags
            combined_tags_str = f"{default_tags_str}\n\n{combined_tags_str}"
        else:
            combined_tags_str = default_tags_str

    if caption:
        return f"{caption}\n\n{combined_tags_str}"
    return combined_tags_str


def download_image_from_url(url: str) -> tuple[bytes, str]:
    """Download image from URL. Returns (content, filename)."""
    response = requests.get(url, timeout=60)
    response.raise_for_status()

    # Extract filename from URL or use default
    filename = url.split("/")[-1].split("?")[0]
    if not filename or "." not in filename:
        filename = "image.jpg"

    return response.content, filename


class Poster:
    """Main posting orchestrator."""

    def __init__(self, config: Config):
        self.config = config
        self.notion = NotionDB(config.notion.token, config.notion.database_id)
        self.r2 = R2Storage(config.r2)

        # Token Management
        self.token_manager = TokenManager(self.r2, config.instagram)
        valid_token = self.token_manager.get_valid_token()

        # Update config with valid token
        config.instagram.access_token = valid_token

        self.instagram = InstagramClient(config.instagram)

        # Threads Token Management
        # We need a compatible config object for TokenManager if using generic approach.
        # But TokenManager expects InstagramConfig typed hints (though duck typing works).
        # We also need a different key for R2 storage.
        self.threads_token_manager = TokenManager(
            self.r2,
            config.threads, # Duck typing: ThreadsConfig has same fields
            token_file_key="config/threads_token.json",
            base_url="https://graph.threads.net",
            api_version=None,
            grant_type="th_refresh_token",
            exchange_param="access_token",
            token_endpoint="refresh_access_token",
            include_client_credentials=False,
            fallback_grant_type="th_exchange_token",
            fallback_exchange_param="access_token",
            fallback_token_endpoint="oauth/access_token",
            fallback_include_client_credentials=True,
        )
        valid_threads_token = self.threads_token_manager.get_valid_token()
        config.threads.access_token = valid_threads_token
        self.threads = ThreadsClient(config.threads)

        self.x = XClient(config.x)

    def run_daily_post(self, target_date: datetime | None = None, dry_run: bool = False, platforms: list[str] | None = None) -> dict:
        """
        Run the daily posting job.

        Priority:
        1. Posts scheduled for today (投稿予定日 = target_date)
        2. If none, oldest unposted work by 完成日 (1 per day)

        Returns:
            dict with 'processed', 'ig_success', 'x_success', 'errors' counts
        """
        if target_date is None:
            target_date = datetime.now()

        logger.info(f"Starting daily post for {target_date.strftime('%Y-%m-%d')}")

        target_count = 3  # Target number of posts per day (User requested 3)

        # Priority 1: Get posts scheduled for today
        posts = self.notion.get_posts_for_date(target_date)
        logger.info(f"Found {len(posts)} posts scheduled for {target_date.strftime('%Y-%m-%d')}")

        # Priority 2: Fill remaining slots with unscheduled works
        remaining_slots = target_count - len(posts)
        if remaining_slots > 0:
            logger.info(f"Filling {remaining_slots} slots with unscheduled works...")
            unscheduled_works = self.notion.get_unscheduled_works(limit=remaining_slots, platforms=platforms)
            if unscheduled_works:
                posts.extend(unscheduled_works)
                logger.info(f"Added {len(unscheduled_works)} unscheduled works")
            else:
                logger.info("No more unscheduled works available")
        else:
            logger.info("Daily target met with scheduled posts")

        stats = {"processed": 0, "ig_success": 0, "x_success": 0, "errors": 0}

        for post in posts:
            try:
                self._process_post(post, stats, dry_run=dry_run, platforms=platforms)
                stats["processed"] += 1
                time.sleep(2)  # Rate limit between posts
            except Exception as e:
                logger.error(f"Failed to process post {post.work_name}: {e}")
                stats["errors"] += 1
                self.notion.update_post_status(post.page_id, error_log=f"Processing error: {e}")

        logger.info(
            f"Daily post complete: {stats['processed']} processed, "
            f"{stats['ig_success']} IG, {stats.get('threads_success', 0)} Threads, {stats['x_success']} X, {stats['errors']} errors"
        )

        return stats

    def _process_post(self, post: WorkItem, stats: dict, dry_run: bool = False, platforms: list[str] | None = None):
        """Process a single post."""
        if platforms is None:
            platforms = ["instagram", "threads"]  # X is excluded by default

        logger.info(f"Processing: {post.work_name} (Dry Run: {dry_run}, Platforms: {platforms})")

        if not post.image_urls:
            raise ValueError(f"No images for post: {post.work_name}")

        # Generate caption
        caption = generate_caption(
            post.work_name,
            post.caption,
            post.tags,
            self.config.default_tags,
            creation_date=post.creation_date,
        )

        # In dry-run mode, show caption preview
        if dry_run:
            logger.info(f"  Images: {len(post.image_urls)}")
            logger.info(f"  Caption:\n{caption}\n")

        # Download images from URLs
        images_data = []
        for url in post.image_urls:
            content, filename = download_image_from_url(url)
            # Determine mime type from filename
            mime_type = "image/jpeg"
            if filename.lower().endswith(".png"):
                mime_type = "image/png"
            elif filename.lower().endswith(".gif"):
                mime_type = "image/gif"
            images_data.append((content, filename, mime_type))
            logger.debug(f"Downloaded: {filename}")

        # Post to Instagram (if not already posted AND platform is requested)
        if "instagram" in platforms and not post.ig_posted:
            if dry_run:
                logger.info("Dry Run: Would post to Instagram")
                stats["ig_success"] += 1
            else:
                try:
                    ig_post_id = self._post_to_instagram(images_data, caption)
                    self.notion.update_post_status(
                        post.page_id,
                        ig_posted=True,
                        ig_post_id=ig_post_id,
                        posted_date=datetime.now()
                    )
                    stats["ig_success"] += 1
                    logger.info(f"Instagram posted: {ig_post_id}")
                except InstagramAPIError as e:
                    logger.error(f"Instagram error: {e}")
                    self.notion.update_post_status(post.page_id, error_log=f"Instagram: {e}")
                    stats["errors"] += 1

        # Post to X (if not already posted AND platform is requested)
        if "x" in platforms and not post.x_posted:
            if dry_run:
                logger.info("Dry Run: Would post to X")
                stats["x_success"] += 1
            else:
                try:
                    x_post_id = self._post_to_x(images_data, caption)
                    self.notion.update_post_status(
                        post.page_id,
                        x_posted=True,
                        x_post_id=x_post_id,
                        posted_date=datetime.now()
                    )
                    stats["x_success"] += 1
                    logger.info(f"X posted: {x_post_id}")
                except XAPIError as e:
                    logger.error(f"X error: {e}")
                    self.notion.update_post_status(post.page_id, error_log=f"X: {e}")
                    stats["errors"] += 1

        # Post to Threads (if not already posted AND platform is requested)
        if "threads" in platforms and hasattr(post, 'threads_posted') and not post.threads_posted:
            if dry_run:
                logger.info("Dry Run: Would post to Threads")
                stats.setdefault("threads_success", 0)
                stats["threads_success"] += 1
            else:
                try:
                    threads_post_id = self._post_to_threads(images_data, caption)
                    self.notion.update_post_status(
                        post.page_id,
                        threads_posted=True,
                        threads_post_id=threads_post_id,
                        posted_date=datetime.now()
                    )
                    stats.setdefault("threads_success", 0)
                    stats["threads_success"] += 1
                    logger.info(f"Threads posted: {threads_post_id}")
                except ThreadsAPIError as e:
                    logger.error(f"Threads error: {e}")
                    self.notion.update_post_status(post.page_id, error_log=f"Threads: {e}")
                    stats["errors"] += 1

    def _post_to_instagram(self, images_data: list[tuple[bytes, str, str]], caption: str) -> str:
        """Post images to Instagram."""
        # Upload images to R2 and get presigned URLs
        r2_keys = []
        image_urls = []

        try:
            for content, filename, mime_type in images_data:
                key, url = self.r2.upload_and_get_url(content, filename, mime_type)
                r2_keys.append(key)
                image_urls.append(url)

            # Post to Instagram
            # Note: Instagram's post_* methods already wait for media to be FINISHED before publishing,
            # so no additional wait is needed before deleting R2 files
            if len(image_urls) == 1:
                return self.instagram.post_single_image(image_urls[0], caption)
            else:
                return self.instagram.post_carousel(image_urls, caption)

        finally:
            # Clean up R2 files
            for key in r2_keys:
                try:
                    self.r2.delete(key)
                except Exception as e:
                    logger.warning(f"Failed to delete R2 file {key}: {e}")

    def _post_to_threads(self, images_data: list[tuple[bytes, str, str]], caption: str) -> str:
        """Post images to Threads."""
        # Upload images to R2 and get presigned URLs
        r2_keys = []
        image_urls = []

        try:
            for content, filename, mime_type in images_data:
                key, url = self.r2.upload_and_get_url(content, filename, mime_type)
                r2_keys.append(key)
                image_urls.append(url)

            # Post to Threads
            if len(image_urls) == 1:
                post_id = self.threads.post_single_image(image_urls[0], caption)
            else:
                post_id = self.threads.post_carousel(image_urls, caption)

            # Wait for Threads to finish downloading images before deleting R2 files
            # Threads API downloads images asynchronously after publish, even after container is FINISHED
            logger.info(f"Waiting {THREADS_IMAGE_DOWNLOAD_WAIT_SECONDS}s for Threads to download images...")
            time.sleep(THREADS_IMAGE_DOWNLOAD_WAIT_SECONDS)

            return post_id

        finally:
            # Clean up R2 files
            for key in r2_keys:
                try:
                    self.r2.delete(key)
                except Exception as e:
                    logger.warning(f"Failed to delete R2 file {key}: {e}")

    def _post_to_x(self, images_data: list[tuple[bytes, str, str]], caption: str) -> str:
        """Post images to X."""
        # X accepts direct uploads, no need for R2
        image_contents = [(content, filename) for content, filename, _ in images_data]
        return self.x.post_with_images(caption, image_contents)

    def list_works(self, student: str | None = None, only_unposted: bool = False) -> list[WorkItem]:
        """List work items from Notion."""
        return self.notion.list_works(filter_student=student, only_unposted=only_unposted)

    def test_post(self, page_id: str, platform: str = "all") -> dict:
        """
        Test post a specific work item.

        Args:
            page_id: Notion page ID
            platform: 'instagram', 'x', 'threads', or 'all'

        Returns:
            dict with post IDs
        """
        # Get work items and find the one with matching page_id
        works = self.notion.list_works()
        work = next((w for w in works if w.page_id == page_id), None)

        if work is None:
            raise ValueError(f"Work not found: {page_id}")

        if not work.image_urls:
            raise ValueError(f"No images for work: {work.work_name}")

        # Download images
        images_data = []
        for url in work.image_urls:
            content, filename = download_image_from_url(url)
            mime_type = "image/jpeg"
            if filename.lower().endswith(".png"):
                mime_type = "image/png"
            images_data.append((content, filename, mime_type))

        caption = generate_caption(
            work.work_name,
            work.caption,
            work.tags,
            self.config.default_tags,
            creation_date=work.creation_date,
        )

        result = {}

        if platform in ("instagram", "all"):
            ig_post_id = self._post_to_instagram(images_data, caption)
            result["instagram_post_id"] = ig_post_id
            self.notion.update_post_status(page_id, ig_posted=True, ig_post_id=ig_post_id)

        if platform in ("x", "all"):
            x_post_id = self._post_to_x(images_data, caption)
            result["x_post_id"] = x_post_id
            self.notion.update_post_status(page_id, x_posted=True, x_post_id=x_post_id)

        if platform in ("threads", "all"):
            threads_post_id = self._post_to_threads(images_data, caption)
            result["threads_post_id"] = threads_post_id
            self.notion.update_post_status(page_id, threads_posted=True, threads_post_id=threads_post_id)

        return result
