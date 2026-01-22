"""Cloudflare R2 storage integration."""

import io
import logging
import time
from contextlib import contextmanager

import boto3
from botocore.config import Config as BotoConfig

from .config import R2Config

logger = logging.getLogger(__name__)
print(f"DEBUG: Loaded r2_storage from {__file__}")



class R2Storage:
    """Cloudflare R2 storage client using boto3."""

    def __init__(self, config: R2Config):
        self.config = config
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = self._create_client()
        return self._client

    def _create_client(self):
        return boto3.client(
            "s3",
            endpoint_url=self.config.endpoint_url,
            aws_access_key_id=self.config.access_key_id,
            aws_secret_access_key=self.config.secret_access_key,
            config=BotoConfig(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "adaptive"},
            ),
        )

    def upload(self, content: bytes, key: str, content_type: str) -> str:
        """Upload content to R2 and return the key."""
        # Create fresh client for every request to avoid session issues
        client = self._create_client()

        client.upload_fileobj(
            io.BytesIO(content),
            self.config.bucket_name,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        logger.info(f"Uploaded to R2: {key}")
        return key

    def generate_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Generate a presigned URL for an object."""
        url = self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.config.bucket_name, "Key": key},
            ExpiresIn=expires_in,
        )
        logger.debug(f"Generated presigned URL for {key}")
        return url

    def delete(self, key: str):
        """Delete an object from R2."""
        self.client.delete_object(Bucket=self.config.bucket_name, Key=key)
        logger.info(f"Deleted from R2: {key}")

    def upload_and_get_url(
        self, content: bytes, filename: str, content_type: str, expires_in: int = 3600
    ) -> tuple[str, str]:
        """Upload content and return (key, presigned_url)."""
        key = f"temp/{int(time.time())}_{filename}"
        self.upload(content, key, content_type)
        url = self.generate_presigned_url(key, expires_in)
        return key, url

    @contextmanager
    def temporary_upload(
        self, content: bytes, filename: str, content_type: str, expires_in: int = 3600
    ):
        """Context manager that uploads content and deletes it after use."""
        key, url = self.upload_and_get_url(content, filename, content_type, expires_in)
        try:
            yield url
        finally:
            try:
                self.delete(key)
            except Exception as e:
                logger.warning(f"Failed to delete temporary file {key}: {e}")
