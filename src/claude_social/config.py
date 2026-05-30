"""
Typed runtime configuration.

All secrets and toggles are declared here. `Settings()` reads from environment
variables (and from a local `.env` file in dev). If something required is
missing, we fail at startup with a clear error — never mid-run.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = parent of `src/`. Used to resolve default paths.
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Supabase ---
    supabase_url: str = Field(..., alias="SUPABASE_URL")
    supabase_service_key: str = Field(..., alias="SUPABASE_SERVICE_KEY")
    supabase_media_bucket: str = Field("media", alias="SUPABASE_MEDIA_BUCKET")
    supabase_reports_bucket: str = Field("reports", alias="SUPABASE_REPORTS_BUCKET")

    # --- Apify ---
    apify_token: str = Field(..., alias="APIFY_TOKEN")
    apify_instagram_actor: str = Field(
        "apify/instagram-scraper", alias="APIFY_INSTAGRAM_ACTOR"
    )
    apify_instagram_fallback_actor: str = Field(
        "get-leads/all-in-one-instagram-scraper",
        alias="APIFY_INSTAGRAM_FALLBACK_ACTOR",
    )
    instagram_cookies: str | None = Field(None, alias="INSTAGRAM_COOKIES")
    instagram_cookie_country: str = Field("SK", alias="INSTAGRAM_COOKIE_COUNTRY")
    instagram_cookies_backup: str | None = Field(None, alias="INSTAGRAM_COOKIES_BACKUP")
    instagram_cookie_country_backup: str = Field("SK", alias="INSTAGRAM_COOKIE_COUNTRY_BACKUP")
    # External residential proxy URL (provider-agnostic). Detailed format /
    # behaviour notes live in .env.example to avoid drift across two places.
    residential_proxy_url: str | None = Field(None, alias="RESIDENTIAL_PROXY_URL")

    # --- HikerAPI (managed instagrapi SaaS, posts only) ---
    # When set, becomes the top tier for Instagram post fetching. Empty =
    # legacy Apify-only flow (graceful degradation).
    hiker_api_key: str | None = Field(None, alias="HIKER_API_KEY")

    # --- AI ---
    gemini_api_key: str | None = Field(None, alias="GEMINI_API_KEY")
    gemini_model: str = Field("gemini-2.0-flash", alias="GEMINI_MODEL")
    openai_api_key: str | None = Field(None, alias="OPENAI_API_KEY")
    openai_model: str = Field("gpt-4o-mini", alias="OPENAI_MODEL")

    # --- Notifications ---
    telegram_bot_token: str | None = Field(None, alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str | None = Field(None, alias="TELEGRAM_CHAT_ID")

    # --- Runtime ---
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    clients_config_dir: Path = Field(
        REPO_ROOT / "config" / "clients", alias="CLIENTS_CONFIG_DIR"
    )

    def client_dir(self, slug: str) -> Path:
        """Return the config folder for a client slug, or raise if missing."""
        path = self.clients_config_dir / slug
        if not path.is_dir():
            raise FileNotFoundError(
                f"No client config directory found at {path}. "
                f"Create it with client.yaml, prompt.md, categories.yaml."
            )
        return path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor — same `Settings` instance for the whole process."""
    return Settings()  # type: ignore[call-arg]
