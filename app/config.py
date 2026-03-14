"""Configuration loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings


# Region presets: Yelp has no UAE coverage; Reddit unavailable in UAE
REGION_PRESETS = {
    "uae": {
        "place_sources_priority": ["google", "foursquare"],  # Yelp has no UAE coverage
        "reddit_enabled": False,  # Reddit API unavailable in UAE
        "reddit_subreddits": [],
        "google_region_code": "AE",
        "google_language_code": "en",
    },
    "default": {
        "place_sources_priority": ["google", "foursquare", "yelp"],
        "reddit_enabled": True,
        "reddit_subreddits": ["food", "restaurants", "AskNYC", "LosAngeles", "chicago", "sanfrancisco", "Seattle", "Austin"],
        "google_region_code": None,
        "google_language_code": "en",
    },
}


class Settings(BaseSettings):
    """Application settings from environment."""

    # API Keys - optional, clients gracefully degrade when missing
    google_places_api_key: str | None = None
    foursquare_api_key: str | None = None
    yelp_api_key: str | None = None
    besttime_api_key: str | None = None  # Live foot traffic (BestTime.app)
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str = "vibe-check/1.0"

    # AI / LLM (optional)
    claude_api_key: str | None = None

    # Region: "uae" for UAE/Dubai, "default" for global
    region: str = "uae"

    # Override Google language (e.g. "ar" for Arabic in UAE)
    google_language_code: str | None = None

    # Cache
    cache_ttl_seconds: int = 300  # 5 minutes

    # Override place sources (optional; region preset used if not set)
    place_sources_priority: list[str] | None = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    def get_place_sources_priority(self) -> list[str]:
        """Place discovery source order; region-aware (Yelp excluded for UAE)."""
        if self.place_sources_priority is not None:
            return self.place_sources_priority
        preset = REGION_PRESETS.get(self.region.lower(), REGION_PRESETS["default"])
        return preset["place_sources_priority"]

    def is_reddit_enabled(self) -> bool:
        """Whether to use Reddit for vibe data (disabled for UAE)."""
        preset = REGION_PRESETS.get(self.region.lower(), REGION_PRESETS["default"])
        return preset.get("reddit_enabled", True)

    def get_reddit_subreddits(self) -> list[str]:
        """Subreddits for social vibe; region-aware."""
        preset = REGION_PRESETS.get(self.region.lower(), REGION_PRESETS["default"])
        return preset.get("reddit_subreddits", [])

    def get_google_region_code(self) -> str | None:
        """Google Places regionCode (e.g. AE for UAE)."""
        preset = REGION_PRESETS.get(self.region.lower(), REGION_PRESETS["default"])
        return preset.get("google_region_code")

    def get_google_language_code(self) -> str:
        """Google Places languageCode (env override or region preset)."""
        if self.google_language_code:
            return self.google_language_code
        preset = REGION_PRESETS.get(self.region.lower(), REGION_PRESETS["default"])
        return preset.get("google_language_code", "en")


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()
