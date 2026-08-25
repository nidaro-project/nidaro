from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"
    database_url: str = "postgresql+psycopg://nidaro:nidaro@localhost:5432/nidaro"
    redis_url: str = "redis://localhost:6379/0"
    model: str | None = None
    logfire_token: str | None = None
    timezone: str = "Europe/Prague"

    model_config = SettingsConfigDict(
        env_prefix="NIDARO_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
