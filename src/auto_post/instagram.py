"""Instagram Graph API integration."""

import logging
import time
from datetime import datetime, timedelta

import requests

from .config import InstagramConfig

logger = logging.getLogger(__name__)

API_BASE = "https://graph.facebook.com/v18.0"


class InstagramAPIError(Exception):
    """Instagram API error."""

    pass


class InstagramClient:
    """Instagram Graph API client."""

    def __init__(self, config: InstagramConfig):
        self.config = config

    def _request(
        self, method: str, endpoint: str, params: dict | None = None, data: dict | None = None
    ) -> dict:
        """Make an API request."""
        url = f"{API_BASE}/{endpoint}"
        params = params or {}
        params["access_token"] = self.config.access_token

        response = requests.request(method, url, params=params, data=data, timeout=60)

        result = response.json()
        if "error" in result:
            raise InstagramAPIError(result["error"].get("message", str(result["error"])))

        return result

    def post_single_image(self, image_url: str, caption: str) -> str:
        """Post a single image and return the post ID."""
        # Create media container
        container_id = self._create_media_container(image_url, caption)

        # Wait for processing
        self._wait_for_media_ready(container_id)

        # Publish
        return self._publish_media(container_id)

    def post_carousel(self, image_urls: list[str], caption: str) -> str:
        """Post a carousel (multiple images) and return the post ID."""
        if len(image_urls) == 1:
            return self.post_single_image(image_urls[0], caption)

        # Create child containers
        child_ids = []
        for url in image_urls:
            child_id = self._create_carousel_item(url)
            self._wait_for_media_ready(child_id)
            child_ids.append(child_id)
            time.sleep(1)  # Rate limit

        # Create carousel container
        carousel_id = self._create_carousel_container(child_ids, caption)
        self._wait_for_media_ready(carousel_id)

        # Publish
        return self._publish_media(carousel_id)

    def _create_media_container(self, image_url: str, caption: str) -> str:
        """Create a media container for a single image."""
        result = self._request(
            "POST",
            f"{self.config.business_account_id}/media",
            data={"image_url": image_url, "caption": caption},
        )
        logger.info(f"Created media container: {result['id']}")
        return result["id"]

    def _create_carousel_item(self, image_url: str) -> str:
        """Create a carousel item (child container)."""
        result = self._request(
            "POST",
            f"{self.config.business_account_id}/media",
            data={"image_url": image_url, "is_carousel_item": "true"},
        )
        logger.info(f"Created carousel item: {result['id']}")
        return result["id"]

    def _create_carousel_container(self, child_ids: list[str], caption: str) -> str:
        """Create a carousel container."""
        result = self._request(
            "POST",
            f"{self.config.business_account_id}/media",
            data={
                "media_type": "CAROUSEL",
                "children": ",".join(child_ids),
                "caption": caption,
            },
        )
        logger.info(f"Created carousel container: {result['id']}")
        return result["id"]

    def _get_media_status(self, container_id: str) -> str:
        """Get the status of a media container."""
        result = self._request("GET", container_id, params={"fields": "status_code"})
        return result.get("status_code", "IN_PROGRESS")

    def _wait_for_media_ready(self, container_id: str, max_wait_seconds: int = 60):
        """Wait for media processing to complete."""
        start_time = time.time()

        while time.time() - start_time < max_wait_seconds:
            status = self._get_media_status(container_id)
            logger.debug(f"Media status for {container_id}: {status}")

            if status == "FINISHED":
                return
            if status == "ERROR":
                raise InstagramAPIError(f"Media processing error: {container_id}")

            time.sleep(2)

        raise InstagramAPIError(f"Media processing timeout: {container_id}")

    def _publish_media(self, container_id: str) -> str:
        """Publish a media container."""
        logger.info(f"Publishing media container: {container_id}")
        result = self._request(
            "POST",
            f"{self.config.business_account_id}/media_publish",
            data={"creation_id": container_id},
        )
        post_id = result.get("id")
        if not post_id:
             raise InstagramAPIError(f"Failed to publish media: {result}")

        logger.info(f"Published media: {post_id}")
        return post_id

    def refresh_token(self) -> tuple[str, datetime]:
        """Refresh the access token. Returns (new_token, expiry_date)."""
        url = f"{API_BASE}/oauth/access_token"
        params = {
            "grant_type": "fb_exchange_token",
            "client_id": self.config.app_id,
            "client_secret": self.config.app_secret,
            "fb_exchange_token": self.config.access_token,
        }

        response = requests.get(url, params=params, timeout=30)
        result = response.json()

        if "error" in result:
            raise InstagramAPIError(f"Token refresh failed: {result['error'].get('message')}")

        new_token = result["access_token"]
        # Long-lived tokens are valid for 60 days
        expiry = datetime.now() + timedelta(days=60)

        logger.info(f"Token refreshed, new expiry: {expiry.strftime('%Y-%m-%d')}")
        return new_token, expiry

    def check_token_expiry(self, expiry_date: datetime | None, refresh_days_before: int = 15) -> bool:
        """Check if token needs refresh. Returns True if refreshed."""
        if expiry_date is None:
            logger.warning("Token expiry date not set")
            return False

        days_until_expiry = (expiry_date - datetime.now()).days
        logger.info(f"Days until token expiry: {days_until_expiry}")

        if days_until_expiry <= refresh_days_before:
            logger.info("Token refresh needed")
            return True

        return False
