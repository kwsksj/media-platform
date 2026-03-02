"""X (Twitter) API integration using tweepy."""

import logging
import time

import tweepy  # type: ignore[import-untyped]

from .config import X_MAX_IMAGES, XConfig

logger = logging.getLogger(__name__)


def _extract_tweepy_error_info(
    e: tweepy.TweepyException,
) -> tuple[int | None, object | None, str | None]:
    """Extract status/errors/body from TweepyException when available."""
    status = None
    api_errors = None
    body = None

    response = getattr(e, "response", None)
    if response is not None:
        try:
            status = response.status_code
            body = response.text
        except Exception:
            pass

    if hasattr(e, "api_errors"):
        api_errors = e.api_errors
    elif hasattr(e, "errors"):
        api_errors = e.errors

    return status, api_errors, body


def _is_cloudflare_challenge(body: str | None) -> bool:
    """Return True when an HTTP body appears to be a Cloudflare challenge page."""
    if not body:
        return False

    lowered = body.lower()
    markers = (
        "<title>just a moment...</title>",
        "cf-browser-verification",
        "challenges.cloudflare.com",
    )
    return any(marker in lowered for marker in markers)


class XAPIError(Exception):
    """X API error."""

    pass


class XClient:
    """X (Twitter) API client using tweepy."""

    def __init__(self, config: XConfig):
        self.config = config
        self._client = None
        self._api = None

    @property
    def client(self) -> tweepy.Client:
        """Get tweepy Client (v2 API)."""
        if self._client is None:
            self._client = tweepy.Client(
                consumer_key=self.config.api_key,
                consumer_secret=self.config.api_key_secret,
                access_token=self.config.access_token,
                access_token_secret=self.config.access_token_secret,
            )
        return self._client

    @property
    def api(self) -> tweepy.API:
        """Get tweepy API (v1.1 API for media upload)."""
        if self._api is None:
            auth = tweepy.OAuth1UserHandler(
                consumer_key=self.config.api_key,
                consumer_secret=self.config.api_key_secret,
                access_token=self.config.access_token,
                access_token_secret=self.config.access_token_secret,
            )
            self._api = tweepy.API(auth)
        return self._api

    def upload_media(self, content: bytes, filename: str) -> str:
        """Upload media and return media_id."""
        # tweepy requires a file-like object
        import io

        try:
            media = self.api.media_upload(filename=filename, file=io.BytesIO(content))
        except tweepy.TweepyException as e:
            status, api_errors, body = _extract_tweepy_error_info(e)
            detail_parts = []
            if status is not None:
                detail_parts.append(f"status={status}")
            if api_errors:
                detail_parts.append(f"api_errors={api_errors}")
            if body:
                detail_parts.append(f"body={body[:500]}")
            if detail_parts:
                logger.error(f"X media upload error details: {', '.join(detail_parts)}")
            msg = f"Failed to upload media: {e}"
            if status is not None:
                msg += f" (status {status})"
            raise XAPIError(msg) from e
        media_id = str(getattr(media, "media_id_string", "") or "")
        if not media_id:
            raise XAPIError("Failed to upload media: missing media_id_string")
        logger.info(f"Uploaded media: {media_id}")
        return media_id

    def post_with_images(self, text: str, image_contents: list[tuple[bytes, str]]) -> str:
        """
        Post a tweet with images.

        Args:
            text: Tweet text
            image_contents: List of (content_bytes, filename) tuples

        Returns:
            Tweet ID
        """
        # Repository policy currently posts only one image to X.
        images_to_post = image_contents[:X_MAX_IMAGES]

        if len(image_contents) > X_MAX_IMAGES:
            logger.warning(
                f"X only allows {X_MAX_IMAGES} images per tweet, "
                f"posting first {X_MAX_IMAGES} of {len(image_contents)}"
            )

        # Upload images
        media_ids = []
        for content, filename in images_to_post:
            media_id = self.upload_media(content, filename)
            media_ids.append(media_id)
            time.sleep(0.5)  # Rate limit

        # Post tweet (v2 API first)
        try:
            response = self.client.create_tweet(text=text, media_ids=media_ids)
            data = getattr(response, "data", None)
            tweet_id = ""
            if isinstance(data, dict):
                tweet_id = str(data.get("id") or "")
            if not tweet_id:
                raise XAPIError("Failed to post tweet: missing tweet id in response")
            logger.info(f"Posted tweet: {tweet_id}")
            return tweet_id
        except tweepy.TweepyException as e:
            status, api_errors, body = _extract_tweepy_error_info(e)
            detail_parts = []
            if status is not None:
                detail_parts.append(f"status={status}")
            if api_errors:
                detail_parts.append(f"api_errors={api_errors}")
            if body:
                detail_parts.append(f"body={body[:500]}")
            if detail_parts:
                logger.error(f"X post error details: {', '.join(detail_parts)}")
            if status == 403 and _is_cloudflare_challenge(body):
                logger.warning(
                    "X v2 create_tweet returned a Cloudflare challenge (403); "
                    "retrying with v1.1 update_status"
                )
                return self._post_with_images_v1(text, media_ids)
            msg = f"Failed to post tweet: {e}"
            if status is not None:
                msg += f" (status {status})"
            raise XAPIError(msg) from e

    def _post_with_images_v1(self, text: str, media_ids: list[str]) -> str:
        """Fallback posting via v1.1 statuses/update when v2 is blocked."""
        try:
            status_obj = self.api.update_status(status=text, media_ids=media_ids)
        except tweepy.TweepyException as e:
            status, api_errors, body = _extract_tweepy_error_info(e)
            detail_parts = []
            if status is not None:
                detail_parts.append(f"status={status}")
            if api_errors:
                detail_parts.append(f"api_errors={api_errors}")
            if body:
                detail_parts.append(f"body={body[:500]}")
            if detail_parts:
                logger.error(f"X v1.1 fallback error details: {', '.join(detail_parts)}")
            msg = f"Failed to post tweet via v1.1 fallback: {e}"
            if status is not None:
                msg += f" (status {status})"
            raise XAPIError(msg) from e

        tweet_id = str(getattr(status_obj, "id_str", "") or getattr(status_obj, "id", "") or "")
        if not tweet_id:
            raise XAPIError("Failed to post tweet via v1.1 fallback: missing tweet id")
        logger.info(f"Posted tweet via v1.1 fallback: {tweet_id}")
        return tweet_id

    def post_text_only(self, text: str) -> str:
        """Post a text-only tweet."""
        try:
            response = self.client.create_tweet(text=text)
            data = getattr(response, "data", None)
            tweet_id = ""
            if isinstance(data, dict):
                tweet_id = str(data.get("id") or "")
            if not tweet_id:
                raise XAPIError("Failed to post tweet: missing tweet id in response")
            logger.info(f"Posted tweet: {tweet_id}")
            return tweet_id
        except tweepy.TweepyException as e:
            raise XAPIError(f"Failed to post tweet: {e}") from e
