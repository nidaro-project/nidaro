from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"
    database_url: str = "postgresql+psycopg://nidaro:nidaro@localhost:5432/nidaro"
    redis_url: str = "redis://localhost:6379/0"
    model: str | None = None
    logfire_token: str | None = None
    timezone: str = "Europe/Prague"
    # Connector secret encryption (Fernet). The previous keys stay decryptable
    # while a rotation is in flight — see docs/deployment.md.
    credential_key: str | None = None
    credential_previous_keys: str = ""
    # CDP endpoint of the persistent Chromium (see nidaro.chromium and
    # docs/deployment.md). The browser is reached over pod-localhost in prod
    # and over a 127.0.0.1-published port in development, so only the port
    # is configurable.
    chromium_cdp_port: int = 9222

    model_config = SettingsConfigDict(
        env_prefix="NIDARO_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
