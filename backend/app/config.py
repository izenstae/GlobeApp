from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://globe:globe@localhost:5432/globe"
    redis_url: str = "redis://localhost:6379/0"
    credential_encryption_key: str = ""

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: list[str] = ["http://localhost:5173"]
    scheduler_enabled: bool = True

    # Ingest cadences (seconds)
    acled_interval: int = 6 * 3600
    gdelt_interval: int = 15 * 60
    firms_interval: int = 3 * 3600

    # Proactive credential refresh
    credential_refresh_interval: int = 15 * 60
    credential_refresh_threshold: int = 2 * 3600  # refresh when expiry is closer than this

    # ACLED re-pull window: records are revised after publication
    acled_window_days: int = 14

    sse_redis_channel: str = "events:new"


@lru_cache
def get_settings() -> Settings:
    return Settings()
