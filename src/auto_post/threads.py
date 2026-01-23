"""Threads API Client."""

import logging
import requests
from typing import Any

from .config import ThreadsConfig

logger = logging.getLogger(__name__)


class ThreadsAPIError(Exception):
    """Base exception for Threads API errors."""
    pass


class ThreadsClient:
    """Client for Threads Graph API."""

    BASE_URL = "https://graph.threads.net/v1.0"

    def __init__(self, config: ThreadsConfig):
        self.config = config
        self.access_token = config.access_token

    def _request(self, method: str, endpoint: str, params: dict | None = None, data: dict | None = None) -> Any:
        """Make a request to the Threads API."""
        url = f"{self.BASE_URL}/{endpoint}"

        if params is None:
            params = {}
        params["access_token"] = self.access_token

        try:
            response = requests.request(method, url, params=params, json=data, timeout=30)
            response.raise_for_status()

            # Threads API responses are usually JSON
            return response.json()
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            if e.response is not None:
                try:
                    error_data = e.response.json()
                    if "error" in error_data:
                        error_msg = f"{error_data['error'].get('message')} (Code: {error_data['error'].get('code')})"
                except ValueError:
                    error_msg = e.response.text

            logger.error(f"Threads API Error: {error_msg}")
            raise ThreadsAPIError(error_msg)

    def get_user_id(self) -> str:
        """Get the Thread user's ID."""
        if self.config.user_id:
            return self.config.user_id

        data = self._request("GET", "me", params={"fields": "id,username"})
        return data["id"]

    def create_image_container(self, image_url: str, caption: str = "", is_carousel_item: bool = False) -> str:
        """
        Create an image container (Item container).

        For single post: Use this, then publish.
        For carousel: Use this for each item (is_carousel_item=True), then create carousel container.
        """
        endpoint = "me/threads"
        data = {
            "media_type": "IMAGE",
            "image_url": image_url,
        }

        # If it's a single post, we add text here.
        # If it's a carousel item, usually text is added to the CAROUSEL container, not the child.
        if not is_carousel_item and caption:
            data["text"] = caption

        # Note: Threads API might behave like IG where text is allowed on children but usually top level.
        # Docs say: For Carousel, 'text' should be on the Carousel Container.

        response = self._request("POST", endpoint, params=data)
        logger.info(f"Created Threads container: {response.get('id')}")
        return response["id"]

    def create_carousel_container(self, children_ids: list[str], caption: str = "") -> str:
        """Create a carousel container."""
        endpoint = "me/threads"
        data = {
            "media_type": "CAROUSEL",
            "children": ",".join(children_ids),
        }

        if caption:
            data["text"] = caption

        response = self._request("POST", endpoint, params=data)
        logger.info(f"Created Threads carousel container: {response.get('id')}")
        return response["id"]

    def publish_container(self, creation_id: str) -> str:
        """Publish a container."""
        endpoint = "me/threads_publish"
        params = {
            "creation_id": creation_id
        }

        response = self._request("POST", endpoint, params=params)
        logger.info(f"Published Threads media: {response.get('id')}")
        return response["id"]

    def check_container_status(self, container_id: str) -> dict:
        """Check the status of a media container."""
        endpoint = container_id
        params = {
            "fields": "id,status,error_message"
        }
        return self._request("GET", endpoint, params=params)

    def wait_for_container_ready(self, container_id: str, max_attempts: int = 30, interval: float = 2.0) -> bool:
        """
        Wait for container to be ready for publishing.

        Returns True if ready, raises ThreadsAPIError if failed.
        """
        import time

        for attempt in range(max_attempts):
            try:
                status_data = self.check_container_status(container_id)
                status = status_data.get("status", "UNKNOWN")

                if status == "FINISHED":
                    logger.debug(f"Container {container_id} is ready (FINISHED)")
                    return True
                elif status == "ERROR":
                    error_msg = status_data.get("error_message", "Unknown error")
                    raise ThreadsAPIError(f"Container processing failed: {error_msg}")
                elif status in ("EXPIRED", "DELETED"):
                    raise ThreadsAPIError(f"Container status is {status}")
                else:
                    # IN_PROGRESS or other transient states
                    logger.debug(f"Container {container_id} status: {status}, waiting... (attempt {attempt + 1}/{max_attempts})")
                    time.sleep(interval)
            except ThreadsAPIError:
                raise
            except Exception as e:
                logger.warning(f"Error checking container status: {e}")
                time.sleep(interval)

        raise ThreadsAPIError(f"Container {container_id} not ready after {max_attempts} attempts")

    def post_single_image(self, image_url: str, caption: str) -> str:
        """Helper to post a single image."""
        container_id = self.create_image_container(image_url, caption=caption, is_carousel_item=False)

        # Wait for container to be ready
        self.wait_for_container_ready(container_id)

        return self.publish_container(container_id)

    def post_carousel(self, image_urls: list[str], caption: str) -> str:
        """Helper to post a carousel."""
        children_ids = []
        for url in image_urls:
            # We don't add caption to children
            child_id = self.create_image_container(url, caption="", is_carousel_item=True)
            children_ids.append(child_id)

        carousel_id = self.create_carousel_container(children_ids, caption)

        # Wait for carousel container to be ready before publishing
        self.wait_for_container_ready(carousel_id)

        return self.publish_container(carousel_id)
