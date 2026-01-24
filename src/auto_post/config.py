"""Configuration management."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class InstagramConfig:
    """Instagram API configuration."""

    app_id: str
    app_secret: str
    access_token: str
    business_account_id: str

    @classmethod
    def from_env(cls) -> "InstagramConfig":
        return cls(
            app_id=os.environ["INSTAGRAM_APP_ID"],
            app_secret=os.environ["INSTAGRAM_APP_SECRET"],
            access_token=os.environ["INSTAGRAM_ACCESS_TOKEN"],
            business_account_id=os.environ.get(
                "INSTAGRAM_BUSINESS_ACCOUNT_ID", "17841422021372550"
            ),
        )


@dataclass
class XConfig:
    """X (Twitter) API configuration."""

    api_key: str
    api_key_secret: str
    access_token: str
    access_token_secret: str

    @classmethod
    def from_env(cls) -> "XConfig":
        return cls(
            api_key=os.environ["X_API_KEY"],
            api_key_secret=os.environ["X_API_KEY_SECRET"],
            access_token=os.environ["X_ACCESS_TOKEN"],
            access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
        )
@dataclass
class ThreadsConfig:
    """Threads API configuration."""

    app_id: str
    app_secret: str
    access_token: str
    user_id: str | None

    @classmethod
    def from_env(cls) -> "ThreadsConfig":
        return cls(
            app_id=os.environ.get("THREADS_APP_ID", "").strip(),
            app_secret=os.environ.get("THREADS_APP_SECRET", "").strip(),
            access_token=os.environ.get("THREADS_ACCESS_TOKEN", "").strip(),
            user_id=(os.environ.get("THREADS_USER_ID") or "").strip() or None,
        )

@dataclass
class R2Config:
    """Cloudflare R2 configuration."""

    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket_name: str
    public_url: str | None  # For public bucket access

    @classmethod
    def from_env(cls) -> "R2Config":
        return cls(
            account_id=os.environ["R2_ACCOUNT_ID"],
            access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            bucket_name=os.environ.get("R2_BUCKET_NAME", "instagram-temp"),
            public_url=os.environ.get("R2_PUBLIC_URL"),
        )

    @property
    def endpoint_url(self) -> str:
        return f"https://{self.account_id}.r2.cloudflarestorage.com"


@dataclass
class NotionConfig:
    """Notion API configuration."""

    token: str
    database_id: str
    tags_database_id: str | None = None

    @classmethod
    def from_env(cls) -> "NotionConfig":
        return cls(
            token=os.environ["NOTION_TOKEN"],
            database_id=os.environ["NOTION_DATABASE_ID"],
            tags_database_id=os.environ.get("TAGS_DATABASE_ID"),
        )


@dataclass
class Config:
    """Application configuration."""

    instagram: InstagramConfig
    x: XConfig
    r2: R2Config
    notion: NotionConfig
    threads: ThreadsConfig
    default_tags: str

    @classmethod
    def load(cls, env_file: Path | None = None) -> "Config":
        """Load configuration from environment variables."""
        if env_file:
            load_dotenv(env_file, override=True)
        else:
            load_dotenv(override=True)

        return cls(
            instagram=InstagramConfig.from_env(),
            x=XConfig.from_env(),
            r2=R2Config.from_env(),
            notion=NotionConfig.from_env(),
            threads=ThreadsConfig.from_env(),
            default_tags=os.environ.get("DEFAULT_TAGS")
            or "木彫り教室生徒作品 studentwork 木彫り woodcarving 彫刻 handcarved woodart ハンドメイド",
        )


# Constants
INSTAGRAM_MAX_CAROUSEL = 10
X_MAX_IMAGES = 4
