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
    # Google Calendar OAuth web flow, from Google Cloud Console credentials.
    # Without a client id/secret the connector stays dormant: no account can
    # connect, everything else keeps working. See docs/deployment.md.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8100/api/v1/connectors/google-calendar/callback"

    model_config = SettingsConfigDict(
        env_prefix="NIDARO_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
