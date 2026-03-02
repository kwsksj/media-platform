"""Tests for X (Twitter) client behavior."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
import tweepy

from auto_post.config import XConfig
from auto_post.x_twitter import XAPIError, XClient


class _FakeResponse:
    """Minimal response object compatible with tweepy.HTTPException."""

    def __init__(
        self,
        *,
        status_code: int,
        reason: str,
        text: str,
        json_data: dict | None = None,
    ):
        self.status_code = status_code
        self.reason = reason
        self.text = text
        self._json_data = json_data

    def json(self) -> dict:
        if self._json_data is None:
            raise requests.JSONDecodeError("Expecting value", "", 0)
        return self._json_data


def _make_client() -> XClient:
    return XClient(
        XConfig(
            api_key="dummy",
            api_key_secret="dummy",
            access_token="dummy",
            access_token_secret="dummy",
        )
    )


def test_post_with_images_uses_first_image_only(monkeypatch):
    client = _make_client()
    client._client = Mock()

    monkeypatch.setattr("auto_post.x_twitter.time.sleep", lambda _seconds: None)

    uploaded_filenames: list[str] = []

    def _fake_upload(_content: bytes, filename: str) -> str:
        uploaded_filenames.append(filename)
        return f"media-{filename}"

    monkeypatch.setattr(client, "upload_media", _fake_upload)
    client._client.create_tweet.return_value = SimpleNamespace(data={"id": "tweet-123"})

    result = client.post_with_images(
        "caption",
        [
            (b"image-1", "one.jpg"),
            (b"image-2", "two.jpg"),
            (b"image-3", "three.jpg"),
        ],
    )

    assert result == "tweet-123"
    assert uploaded_filenames == ["one.jpg"]
    client._client.create_tweet.assert_called_once_with(
        text="caption",
        media_ids=["media-one.jpg"],
    )


def test_post_with_images_falls_back_to_v1_on_cloudflare_403(monkeypatch):
    client = _make_client()
    client._client = Mock()
    client._api = Mock()

    monkeypatch.setattr("auto_post.x_twitter.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(client, "upload_media", lambda _content, _filename: "media-1")

    cloudflare_html = "<!DOCTYPE html><html><head><title>Just a moment...</title></head></html>"
    forbidden = tweepy.Forbidden(
        _FakeResponse(
            status_code=403,
            reason="Forbidden",
            text=cloudflare_html,
        )
    )
    client._client.create_tweet.side_effect = forbidden
    client._api.update_status.return_value = SimpleNamespace(id_str="tweet-fallback-1")

    result = client.post_with_images("caption", [(b"image-1", "one.jpg")])

    assert result == "tweet-fallback-1"
    client._api.update_status.assert_called_once_with(
        status="caption",
        media_ids=["media-1"],
    )


def test_post_with_images_raises_for_non_cloudflare_403(monkeypatch):
    client = _make_client()
    client._client = Mock()
    client._api = Mock()

    monkeypatch.setattr("auto_post.x_twitter.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(client, "upload_media", lambda _content, _filename: "media-1")

    forbidden = tweepy.Forbidden(
        _FakeResponse(
            status_code=403,
            reason="Forbidden",
            text='{"title":"Forbidden"}',
            json_data={"errors": [{"message": "Forbidden"}]},
        )
    )
    client._client.create_tweet.side_effect = forbidden

    with pytest.raises(XAPIError, match="status 403"):
        client.post_with_images("caption", [(b"image-1", "one.jpg")])

    client._api.update_status.assert_not_called()
