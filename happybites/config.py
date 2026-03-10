from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # App
    app_name: str = "HappyBites"
    environment: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"

    # Database
    database_url: str = "sqlite:///./happybites.db"

    # Anthropic
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"

    # Reddit API
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "HappyBites/0.1 (portfolio project)"

    # Ingestion
    ingest_interval_seconds: int = 7200
    max_deals_per_run: int = 100

    # Ranking weights
    weight_discount: float = 0.40
    weight_freshness: float = 0.35
    weight_quality: float = 0.25
    freshness_halflife_hours: float = 48.0


settings = Settings()
