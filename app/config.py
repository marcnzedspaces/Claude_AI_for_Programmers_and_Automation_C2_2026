from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


# All application settings in one place. Values are read from environment
# variables (or the .env file) and validated by Pydantic at startup, so a
# bad or missing setting fails early instead of in the middle of a request.
class Settings(BaseSettings):
    # Application configuration loaded from environment variables.

    # Required (no default): the app will not start without APP_NAME.
    app_name: str = Field(..., env="APP_NAME")
    # Name of the environment (development, production, ...); shown in the startup log.
    app_env: str = "development"

    # These remain optional until the Claude integration phase.
    # Optional here so the app can start without them; ClaudeService checks
    # that they are set before it calls the API. SecretStr hides the key
    # in logs and reprs.
    anthropic_api_key: SecretStr | None = None
    claude_model: str | None = None
    # How long to wait for Claude (seconds). Must be > 0 and at most 120.
    claude_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        le=120,
    )
    # How many times the SDK retries a failed request (0-5). More retries
    # mean better resilience but also more latency and possible cost.
    claude_max_retries: int = Field(
        default=2,
        ge=0,
        le=5,
    )
    # Prices used to estimate the cost of each Claude call, in USD per million tokens.
    # Set these to match the published pricing of the model you use.
    claude_input_cost_per_million_usd: float = Field(
        default=3.0,
        ge=0,
    )
    claude_output_cost_per_million_usd: float = Field(
        default=15.0,
        ge=0,
    )
    # Log level name, for example INFO or DEBUG.
    log_level: str = "INFO"
    # Settings for the in-memory FAQ search cache (see app/core/cache.py).
    faq_cache_enabled: bool = True
    faq_cache_ttl_seconds: float = Field(
        default=60.0,
        gt=0,
        le=3600,
    )
    faq_cache_max_entries: int = Field(
        default=100,
        ge=1,
        le=1000,
    )

    # MongoDB configuration enters the application in Phase 4.
    mongodb_uri: SecretStr = SecretStr("mongodb://localhost:27017")
    mongodb_database: str = "supportops_ai"

    # Where to load settings from: a .env file in the working directory.
    # extra="ignore" skips unknown variables instead of raising an error.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# lru_cache makes this build Settings only once; every later call returns
# the same object, so .env is read a single time.
@lru_cache
def get_settings() -> Settings:
    # Return one cached settings object for the process.
    return Settings()
