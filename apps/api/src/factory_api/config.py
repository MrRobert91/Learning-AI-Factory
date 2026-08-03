from functools import lru_cache
from pathlib import Path
from typing import Literal

from factory_agents.tools.sandbox import SandboxMode
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Single shared password protecting the whole app (simple local auth).
    app_password: str = "changeme"
    # Signs session cookies. Must be overridden outside local dev.
    secret_key: str = "dev-secret-change-me"

    database_url: str = "sqlite:///./data/db/factory.sqlite"
    # Structured backend logging (DEBUG, INFO, WARNING or ERROR).
    log_level: str = "INFO"

    data_dir: Path = Path("./data")
    # Disabled is the safe local default. Docker explicitly selects isolated.
    python_sandbox_mode: SandboxMode = SandboxMode.DISABLED

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

    # Bounded FFmpeg policy for every libx264 encoding path.
    ffmpeg_threads: int = Field(default=1, ge=1)
    ffmpeg_filter_threads: int = Field(default=1, ge=1)
    ffmpeg_filter_complex_threads: int = Field(default=1, ge=1)
    ffmpeg_preset: Literal[
        "ultrafast",
        "superfast",
        "veryfast",
        "faster",
        "fast",
        "medium",
        "slow",
        "slower",
        "veryslow",
    ] = "veryfast"
    ffmpeg_crf: int = Field(default=23, ge=0, le=51)

    # Max LangGraph super-steps per task-agent run (agent node + tool node
    # count as 2 steps per ReAct loop, so this caps the model↔tool round trips
    # at roughly half this value). Bounds runaway loops; raise it for agents
    # that iterate a lot (e.g. lessons verifying every code block).
    agent_recursion_limit: int = 200

    # Per-run spend firewall (rough estimate from token counts; 0 disables)
    budget_usd_per_run: float = 5.0
    budget_price_per_mtok_usd: float = 0.6

    # Continuous-improvement scheduler (days between automatic analyses;
    # 0 = only on demand)
    analytics_interval_days: int = 0

    # Incremental persisted-event delivery. Idle SSE clients wait on the local
    # broker; this timeout only emits a comment to keep proxies from closing.
    job_event_batch_size: int = Field(default=200, ge=1, le=1000)
    job_event_keepalive_seconds: int = Field(default=20, ge=5, le=60)

    # YouTube publishing (Google OAuth; see docs/YOUTUBE.md)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:3000/api/youtube/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()
