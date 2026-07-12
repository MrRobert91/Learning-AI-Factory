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

    # LLM provider (OpenRouter, OpenAI-compatible API)
    openrouter_api_key: str = ""
    openrouter_model: str = "deepseek/deepseek-v4-flash"

    # Research search (optional; DuckDuckGo fallback when empty)
    tavily_api_key: str = ""

    # TTS narration (OpenAI TTS)
    openai_api_key: str = ""
    tts_voice: str = "nova"
    tts_model: str = "gpt-4o-mini-tts"

    # YouTube publishing (Google OAuth; see docs/YOUTUBE.md)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:3000/api/youtube/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()
