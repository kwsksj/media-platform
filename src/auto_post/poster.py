"""Main posting logic."""

import logging
import os
import time
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

import requests

from .config import Config
from .instagram import InstagramAPIError, InstagramClient
from .notion_db import NotionDB, WorkItem
from .r2_storage import R2Storage
from .threads import ThreadsAPIError, ThreadsClient
from .token_manager import TokenManager
from .x_twitter import XAPIError, XClient

logger = logging.getLogger(__name__)

# Wait time for Threads API to download images after publish
# Threads downloads images asynchronously after container is published
# Increased to 20s to ensure reliable image downloads for multiple posts
THREADS_IMAGE_DOWNLOAD_WAIT_SECONDS = 20

def _env_int(name: str, default: int) -> int:
    """Read integer from env with fallback."""
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    """Read float from env with fallback."""
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


POST_RETRY_MAX_ATTEMPTS = max(1, _env_int("POST_RETRY_MAX_ATTEMPTS", 3))
POST_RETRY_BASE_DELAY_SECONDS = max(0, _env_int("POST_RETRY_BASE_DELAY_SECONDS", 5))
POST_RETRY_BACKOFF_FACTOR = max(1.0, _env_float("POST_RETRY_BACKOFF_FACTOR", 2.0))
JST = ZoneInfo("Asia/Tokyo")


def _now_jst() -> datetime:
    """Return current time in Japan Standard Time."""
    return datetime.now(tz=JST)


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
        # Remove surrounding quotes if present
        tags = tags.strip().strip("'\"")

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
        # Remove surrounding quotes if present (from environment variable)
        default_tags = default_tags.strip().strip("'\"")

        for t in default_tags.replace("　", " ").split():
            t = t.strip()
            if t:
                if not t.startswith("#"):
                    t = f"#{t}"
                norm_dest_tags.append(t)
    default_tags_str = " ".join(norm_dest_tags)

    if default_tags_str:
        if combined_tags_str:
            # Default Tags FIRST, then Custom Tags (separate line)
            combined_tags_str = f"{default_tags_str}\n{combined_tags_str}"
        else:
            combined_tags_str = default_tags_str

    if caption:
        separator = "\n" if creation_date else "\n\n"
        return f"{caption}{separator}{combined_tags_str}"
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

    def _post_with_retry(
        self,
        platform: str,
        func: Callable[[], str],
        retry_exceptions: tuple[type[Exception], ...],
    ) -> str:
        """Retry wrapper for platform posting."""
        for attempt in range(1, POST_RETRY_MAX_ATTEMPTS + 1):
            try:
                return func()
            except retry_exceptions as e:
                if attempt >= POST_RETRY_MAX_ATTEMPTS:
                    raise
                wait_seconds = POST_RETRY_BASE_DELAY_SECONDS * (POST_RETRY_BACKOFF_FACTOR ** (attempt - 1))
                logger.warning(
                    f"{platform} post failed (attempt {attempt}/{POST_RETRY_MAX_ATTEMPTS}): {e}. "
                    f"Retrying in {wait_seconds:.1f}s"
                )
                time.sleep(wait_seconds)

    def run_daily_post(
        self,
        target_date: datetime | None = None,
        dry_run: bool = False,
        platforms: list[str] | None = None,
        basic_limit: int = 2,
        catchup_limit: int = 1,
    ) -> dict:
        """
        Run the daily posting job.

        Selection Order (Per Platform):
        1. Date Designated (投稿予定日 = target_date)
        2. Catch-up (Posted on other platforms but not target) - Limit catchup_limit
        3. Basic (Oldest unposted) - Limit basic_limit

        Args:
            target_date: Target date for posting (default: today)
            dry_run: If True, preview without posting
            platforms: List of platforms to post to
            basic_limit: Max number of basic posts per platform (default: 2)
            catchup_limit: Max number of catch-up posts per platform (default: 1)

        Returns:
            dict with 'processed', 'ig_success', 'x_success', 'errors' counts
        """
        if target_date is None:
            target_date = datetime.now()

        logger.info(f"Starting daily post for {target_date.strftime('%Y-%m-%d')}")

        # Platforms to process
        target_platforms = platforms if platforms else ["instagram", "x", "threads"]
        all_supported_platforms = ["instagram", "x", "threads"]

        # Queues per platform (stores page_ids)
        platform_queues = {p: [] for p in all_supported_platforms}
        # Central registry of WorkItems (page_id -> WorkItem)
        unique_works = {}

        # --- Phase 1: Selection ---

        # 1. Date Designated (Global fetch, then assign to relevant platforms)
        date_works = self.notion.get_posts_for_date(target_date)
        logger.info(f"Found {len(date_works)} date-designated posts for {target_date.strftime('%Y-%m-%d')}")

        for work in date_works:
            unique_works[work.page_id] = work
            for p in target_platforms:
                # Check if already posted on this platform
                is_posted = False
                if p == "instagram":
                    is_posted = work.ig_posted
                elif p == "x":
                    is_posted = work.x_posted
                elif p == "threads":
                    is_posted = work.threads_posted

                if not is_posted:
                    platform_queues[p].append(work.page_id)

        # 2 & 3. Per-Platform Selection (Catch-up & Basic)
        for p in target_platforms:
            # 2. Catch-up Post (Limit 1)
            other_platforms = [op for op in all_supported_platforms if op != p]
            # Fetch candidates (fetch a bit more to allow for skipping duplicates)
            catchup_candidates = self.notion.get_catchup_candidates(p, other_platforms, limit=5)

            added_count = 0
            for work in catchup_candidates:
                if work.page_id in platform_queues[p]:
                    continue # Already selected (e.g. by Date Designated)

                platform_queues[p].append(work.page_id)
                unique_works[work.page_id] = work
                added_count += 1
                if added_count >= catchup_limit:
                    break

            if added_count > 0:
                logger.info(f"[{p}] Added {added_count} catch-up posts")

            # 3. Basic Post (Limit 3)
            basic_candidates = self.notion.get_basic_candidates(p, limit=10)

            added_count = 0
            for work in basic_candidates:
                if work.page_id in platform_queues[p]:
                    continue # Already selected

                platform_queues[p].append(work.page_id)
                unique_works[work.page_id] = work
                added_count += 1
                if added_count >= basic_limit:
                    break

            if added_count > 0:
                logger.info(f"[{p}] Added {added_count} basic posts")


        # --- Phase 2: Processing ---

        results = {
            "processed": [],
            "ig_success": [],
            "x_success": [],
            "threads_success": [],
            "errors": []
        }

        # Iterate through unique works
        # Sort by creation date (optional, for log readability)
        sorted_works = sorted(
            unique_works.values(),
            key=lambda w: w.creation_date if w.creation_date else datetime.max
        )

        for work in sorted_works:
            # Determine which platforms this work is targeted for
            target_ps = [p for p, q in platform_queues.items() if work.page_id in q]

            if not target_ps:
                continue

            try:
                # Pass specific target platforms to _process_post
                post_results = self._process_post(work, dry_run=dry_run, platforms=target_ps)
                results["processed"].append(work.work_name)

                if post_results.get("instagram"):
                    results["ig_success"].append(work.work_name)
                if post_results.get("threads"):
                    results["threads_success"].append(work.work_name)
                if post_results.get("x"):
                    results["x_success"].append(work.work_name)
                if post_results.get("errors"):
                    for err in post_results["errors"]:
                        results["errors"].append(f"{work.work_name} ({err})")

                time.sleep(5)  # Global rate limit between works
            except Exception as e:
                logger.error(f"Failed to process post {work.work_name}: {e}")
                results["errors"].append(f"{work.work_name} ({e})")
                self.notion.update_post_status(work.page_id, error_log=f"Processing error: {e}")

        return results

    def run_catchup_post(self, limit: int = 1, dry_run: bool = False, platforms: list[str] | None = None) -> dict:
        """
        Run catch-up posting only.

        For each platform, select 'limit' number of posts that:
        - Are NOT posted on the target platform
        - ARE posted on at least one other platform
        """
        # Platforms to process
        target_platforms = platforms if platforms else ["instagram", "x", "threads"]
        all_supported_platforms = ["instagram", "x", "threads"]

        # Queues per platform
        platform_queues = {p: [] for p in all_supported_platforms}
        unique_works = {}

        logger.info(f"Starting catch-up post (Limit: {limit}, Platforms: {target_platforms})")

        for p in target_platforms:
            other_platforms = [op for op in all_supported_platforms if op != p]
            candidates = self.notion.get_catchup_candidates(p, other_platforms, limit=limit)

            added_count = 0
            for work in candidates:
                platform_queues[p].append(work.page_id)
                unique_works[work.page_id] = work
                added_count += 1

            if added_count > 0:
                logger.info(f"[{p}] Added {added_count} catch-up posts")

        # Process each work
        results = {
            "processed": [],
            "ig_success": [],
            "x_success": [],
            "threads_success": [],
            "errors": []
        }

        # Sort by creation date
        sorted_works = sorted(
            unique_works.values(),
            key=lambda w: w.creation_date if w.creation_date else datetime.max
        )

        for work in sorted_works:
            # Determine target platforms for this work
            target_ps = [p for p, q in platform_queues.items() if work.page_id in q]

            if not target_ps:
                continue

            try:
                post_results = self._process_post(work, dry_run=dry_run, platforms=target_ps)
                results["processed"].append(work.work_name)

                if post_results.get("instagram"):
                    results["ig_success"].append(work.work_name)
                if post_results.get("threads"):
                    results["threads_success"].append(work.work_name)
                if post_results.get("x"):
                    results["x_success"].append(work.work_name)
                if post_results.get("errors"):
                    for err in post_results["errors"]:
                        results["errors"].append(f"{work.work_name} ({err})")

                time.sleep(5)
            except Exception as e:
                logger.error(f"Failed to process post {work.work_name}: {e}")
                results["errors"].append(f"{work.work_name} ({e})")

        return results

    def _process_post(self, post: WorkItem, dry_run: bool = False, platforms: list[str] | None = None) -> dict:
        """Process a single post. Returns dict of success status by platform."""
        status = {"instagram": False, "x": False, "threads": False, "errors": []}

        if platforms is None:
            platforms = ["instagram", "threads", "x"]  # Default to all

        logger.info(f"Processing: {post.work_name} (Dry Run: {dry_run}, Platforms: {platforms})")

        if not post.image_urls:
            raise ValueError(f"No images for post: {post.work_name}")

        # Generate caption
        caption = generate_caption(
            post.work_name,
            post.caption,
            post.classroom,
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
                status["instagram"] = True
            else:
                try:
                    ig_post_id = self._post_with_retry(
                        "Instagram",
                        lambda: self._post_to_instagram(images_data, caption),
                        (InstagramAPIError,),
                    )
                    self.notion.update_post_status(
                        post.page_id,
                        ig_posted=True,
                        ig_post_id=ig_post_id,
                        posted_date=_now_jst()
                    )
                    status["instagram"] = True
                    logger.info(f"Instagram posted: {ig_post_id}")
                except InstagramAPIError as e:
                    logger.error(f"Instagram error: {e}")
                    self.notion.update_post_status(post.page_id, error_log=f"Instagram: {e}")
                    status["errors"].append(f"Instagram: {e}")
                    # status["instagram"] stays False

        # Post to X (if not already posted AND platform is requested)
        if "x" in platforms and not post.x_posted:
            if dry_run:
                logger.info("Dry Run: Would post to X")
                status["x"] = True
            else:
                try:
                    x_post_id = self._post_with_retry(
                        "X",
                        lambda: self._post_to_x(images_data, caption),
                        (XAPIError,),
                    )
                    self.notion.update_post_status(
                        post.page_id,
                        x_posted=True,
                        x_post_id=x_post_id,
                        posted_date=_now_jst()
                    )
                    status["x"] = True
                    logger.info(f"X posted: {x_post_id}")
                except XAPIError as e:
                    logger.error(f"X error: {e}")
                    self.notion.update_post_status(post.page_id, error_log=f"X: {e}")
                    status["errors"].append(f"X: {e}")

        # Post to Threads (if not already posted AND platform is requested)
        if "threads" in platforms and hasattr(post, 'threads_posted') and not post.threads_posted:
            if dry_run:
                logger.info("Dry Run: Would post to Threads")
                status["threads"] = True
            else:
                try:
                    threads_post_id = self._post_with_retry(
                        "Threads",
                        lambda: self._post_to_threads(images_data, caption),
                        (ThreadsAPIError,),
                    )
                    self.notion.update_post_status(
                        post.page_id,
                        threads_posted=True,
                        threads_post_id=threads_post_id,
                        posted_date=_now_jst()
                    )
                    status["threads"] = True
                    logger.info(f"Threads posted: {threads_post_id}")
                except ThreadsAPIError as e:
                    logger.error(f"Threads error: {e}")
                    self.notion.update_post_status(post.page_id, error_log=f"Threads: {e}")
                    status["errors"].append(f"Threads: {e}")

        return status

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

    def post_custom_images(
        self,
        images_data: list[tuple[bytes, str, str]],
        caption: str,
        dry_run: bool = False,
        platforms: list[str] | None = None,
    ) -> dict:
        """
        Post arbitrary image payloads directly to SNS.

        This path does not read/update Notion posting states.
        """
        status = {"instagram": False, "x": False, "threads": False, "post_ids": {}, "errors": []}

        if not images_data:
            raise ValueError("images_data must not be empty")

        target_platforms = platforms if platforms else ["instagram", "threads", "x"]
        target_platforms = [p for p in target_platforms if p in {"instagram", "threads", "x"}]
        if not target_platforms:
            raise ValueError("platforms must include at least one of: instagram, threads, x")

        if dry_run:
            logger.info("Dry Run: custom post preview")
            logger.info("  Platforms: %s", ", ".join(target_platforms))
            logger.info("  Images: %s", len(images_data))
            logger.info("  Caption:\n%s\n", caption)
            for platform in target_platforms:
                status[platform] = True
            return status

        if "instagram" in target_platforms:
            try:
                ig_post_id = self._post_with_retry(
                    "Instagram",
                    lambda: self._post_to_instagram(images_data, caption),
                    (InstagramAPIError,),
                )
                status["instagram"] = True
                status["post_ids"]["instagram"] = ig_post_id
                logger.info(f"Instagram posted: {ig_post_id}")
            except InstagramAPIError as e:
                logger.error(f"Instagram error: {e}")
                status["errors"].append(f"Instagram: {e}")

        if "x" in target_platforms:
            try:
                x_post_id = self._post_with_retry(
                    "X",
                    lambda: self._post_to_x(images_data, caption),
                    (XAPIError,),
                )
                status["x"] = True
                status["post_ids"]["x"] = x_post_id
                logger.info(f"X posted: {x_post_id}")
            except XAPIError as e:
                logger.error(f"X error: {e}")
                status["errors"].append(f"X: {e}")

        if "threads" in target_platforms:
            try:
                threads_post_id = self._post_with_retry(
                    "Threads",
                    lambda: self._post_to_threads(images_data, caption),
                    (ThreadsAPIError,),
                )
                status["threads"] = True
                status["post_ids"]["threads"] = threads_post_id
                logger.info(f"Threads posted: {threads_post_id}")
            except ThreadsAPIError as e:
                logger.error(f"Threads error: {e}")
                status["errors"].append(f"Threads: {e}")

        return status

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
            work.classroom,
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
