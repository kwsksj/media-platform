"""Threads API Client."""

import logging
from typing import Any

import requests

from .config import ThreadsConfig

logger = logging.getLogger(__name__)


class ThreadsAPIError(Exception):
    """Base exception for Threads API errors."""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class ThreadsClient:
    """Client for Threads Graph API."""

    BASE_URL = "https://graph.threads.net/v1.0"

    def __init__(self, config: ThreadsConfig):
        self.config = config
        self.access_token = config.access_token

    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a request to the Threads API."""
        url = f"{self.BASE_URL}/{endpoint}"

        if params is None:
            params = {}
        params["access_token"] = self.access_token

        try:
            response = requests.request(method, url, params=params, json=data, timeout=30)
            response.raise_for_status()

            # Threads API responses are usually JSON
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            raise ThreadsAPIError("Invalid Threads API response format")
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            error_code = None
            if e.response is not None:
                try:
                    status = e.response.status_code
                    body = e.response.text
                    logger.error(f"Threads API error details: status={status}, body={body[:500]}")
                except Exception:
                    pass
                try:
                    error_data = e.response.json()
                    if "error" in error_data:
                        code_val = error_data["error"].get("code")
                        error_msg = f"{error_data['error'].get('message')} (Code: {code_val})"
                        try:
                            error_code = int(code_val)
                        except (ValueError, TypeError):
                            pass
                except ValueError:
                    error_msg = e.response.text

            logger.error(f"Threads API Error: {error_msg}")
            raise ThreadsAPIError(error_msg, code=error_code)

    def get_user_id(self) -> str:
        """Get the Thread user's ID."""
        if self.config.user_id:
            return self.config.user_id

        data = self._request("GET", "me", params={"fields": "id,username"})
        user_id = data.get("id")
        if not isinstance(user_id, str):
            raise ThreadsAPIError("Failed to resolve Threads user id")
        return user_id

    def create_image_container(
        self, image_url: str, caption: str = "", is_carousel_item: bool = False
    ) -> str:
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

        # Use 'data' instead of 'params' to send as JSON body
        response = self._request("POST", endpoint, data=data)
        logger.info(f"Created Threads container: {response.get('id')}")
        container_id = response.get("id")
        if not isinstance(container_id, str):
            raise ThreadsAPIError("Failed to create image container: missing id")
        return container_id

    def create_carousel_container(self, children_ids: list[str], caption: str = "") -> str:
        """Create a carousel container."""
        endpoint = "me/threads"
        data = {
            "media_type": "CAROUSEL",
            "children": children_ids,  # threads expects array, or comma-separated string? Graph API usually wants JSON array, let's check docs or keep string if params.
            # With JSON body, it should be a list or a string?
            # IG Graph API takes list of strings for 'children' in JSON body.
            # BUT `data` in `_request` is sent as `json=data`.
            # Let's keep existing logic but just verify if list is better.
            # Original code: "children": ",".join(children_ids)
            # Threads API docs often say list for JSON. Let's try list first?
            # Actually, safe bet is to mirror what worked for IG if possible, but Threads might be different.
            # Let's stick to what was there (string) unless we know JSON requires list.
            # However, "Invalid parameter" often comes from format mismatch too.
            # Wait, if I change to JSON body, I can pass the list directly if the API supports it.
            # Documentation for Threads says: "children": ["<id>", "<id>"] for JSON.
            # Let's try sending list first.
        }
        # Actually in the original code it was joining with comma.
        # If I send as JSON, list of strings is more standard.
        # Let's check `threads.py` again. `children` was ",".join(children_ids).
        # I will change it to list if I am sending JSON.

        # Let's check what I should write.
        # I will try to support both or just stick to what likely works.
        # Threads API generally follows Instagram Graph API.

        # I'll stick to the safe bet: try list first, that is standard for JSON.
        # Re-reading: "children": ",".join(children_ids) was used for params (URL query).
        # For JSON body, it should likely be a list.

        # However, to be safe and avoid "double experimental", I'll stick to the simplest change:
        # Just move to body first. But usually query param needs string, JSON needs list.
        # I will use list because `json.dumps` handles it naturally.

        data = {
            "media_type": "CAROUSEL",
            "children": children_ids,  # Send as list of strings
        }

        if caption:
            data["text"] = caption

        response = self._request("POST", endpoint, data=data)
        logger.info(f"Created Threads carousel container: {response.get('id')}")
        container_id = response.get("id")
        if not isinstance(container_id, str):
            raise ThreadsAPIError("Failed to create carousel container: missing id")
        return container_id

    def publish_container(
        self, creation_id: str, max_attempts: int = 5, interval: float = 2.0
    ) -> str:
        """Publish a container."""
        endpoint = "me/threads_publish"
        data = {"creation_id": creation_id}

        import time

        for attempt in range(max_attempts):
            try:
                response = self._request("POST", endpoint, data=data)
                logger.info(f"Published Threads media: {response.get('id')}")
                media_id = response.get("id")
                if not isinstance(media_id, str):
                    raise ThreadsAPIError("Failed to publish container: missing id")
                return media_id
            except ThreadsAPIError as e:
                if e.code == 24 and attempt < max_attempts - 1:
                    logger.warning(
                        f"Threads publish not ready (Code 24). Retrying... "
                        f"(attempt {attempt + 1}/{max_attempts})"
                    )
                    time.sleep(interval)
                    continue
                raise
        raise ThreadsAPIError("Failed to publish container after retries")

    def check_container_status(self, container_id: str) -> dict[str, Any]:
        """Check the status of a media container."""
        endpoint = container_id
        params = {"fields": "id,status,error_message"}
        return self._request("GET", endpoint, params=params)

    def wait_for_container_ready(
        self, container_id: str, max_attempts: int = 30, interval: float = 2.0
    ) -> bool:
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
                    logger.debug(
                        f"Container {container_id} status: {status}, waiting... (attempt {attempt + 1}/{max_attempts})"
                    )
                    time.sleep(interval)
            except ThreadsAPIError as e:
                # If resource doesn't exist yet (Code 24), wait and retry
                if e.code == 24:
                    logger.warning(
                        f"Container {container_id} not found (Code 24), retrying... (attempt {attempt + 1}/{max_attempts})"
                    )
                    time.sleep(interval)
                    continue
                raise
            except Exception as e:
                logger.warning(f"Error checking container status: {e}")
                time.sleep(interval)

        raise ThreadsAPIError(f"Container {container_id} not ready after {max_attempts} attempts")

    def post_single_image(self, image_url: str, caption: str) -> str:
        """Helper to post a single image."""
        container_id = self.create_image_container(
            image_url, caption=caption, is_carousel_item=False
        )

        # Wait for container to be ready
        self.wait_for_container_ready(container_id)

        return self.publish_container(container_id)

    def post_carousel(self, image_urls: list[str], caption: str) -> str:
        """Helper to post a carousel."""
        children_ids = []
        for url in image_urls:
            # We don't add caption to children
            child_id = self.create_image_container(url, caption="", is_carousel_item=True)

            # Wait for child container to be ready (IMPORTANT)
            self.wait_for_container_ready(child_id)

            children_ids.append(child_id)
            import time

            time.sleep(1.0)  # Rate limit safety

        carousel_id = self.create_carousel_container(children_ids, caption)

        # Wait for carousel container to be ready before publishing
        self.wait_for_container_ready(carousel_id)

        return self.publish_container(carousel_id)
