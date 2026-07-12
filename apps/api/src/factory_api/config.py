from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Single shared password protecting the whole app (simple local auth).
    app_password: str = "changeme"
    # Signs session cookies. Must be overridden outside local dev.
    secret_key: str = "dev-secret-change-me"

    database_url: str = "sqlite:///./data/db/factory.sqlite"
    data_dir: Path = Path("./data")

    session_cookie_name: str = "factory_session"
    session_max_age_seconds: int = 60 * 60 * 24 * 30

    default_user_email: str = "owner@localhost"
    default_user_name: str = "Owner"


@lru_cache
def get_settings() -> Settings:
    return Settings()
