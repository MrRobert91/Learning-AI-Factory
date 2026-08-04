import base64
import binascii
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from factory_agents.tools.sandbox import SandboxMode
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["local", "production"] = "local"
    # Exact browser origins allowed to perform cookie-authenticated mutations.
    app_origins: str = "http://localhost:3000"
    # Comma-separated proxy IPs allowed to supply X-Forwarded-For/X-Real-IP.
    trusted_proxy_ips: str = ""

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
    session_touch_interval_seconds: int = 300

    login_window_seconds: int = 15 * 60
    login_max_attempts_per_ip: int = 10
    login_max_attempts_global: int = 50
    login_failure_delay_seconds: float = Field(default=0.05, ge=0, le=2)

    # Ordered key ring: the first key encrypts new values; remaining keys only
    # decrypt old values during rotation. Format: kid:urlsafe-base64-32-bytes.
    credential_encryption_keys: str = (
        "local:" + base64.urlsafe_b64encode(b"local-development-key-32-bytes!!").decode()
    )

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

    # YouTube publishing (Google OAuth; see docs/YOUTUBE.md)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:3000/api/youtube/callback"

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        return tuple(
            origin.strip().rstrip("/") for origin in self.app_origins.split(",") if origin.strip()
        )

    @property
    def trusted_proxy_networks(self) -> tuple[str, ...]:
        return tuple(value.strip() for value in self.trusted_proxy_ips.split(",") if value.strip())

    @property
    def effective_session_cookie_name(self) -> str:
        return (
            "__Host-factory_session" if self.app_env == "production" else self.session_cookie_name
        )

    @model_validator(mode="after")
    def validate_deployment_policy(self) -> "Settings":
        if not 60 <= self.session_max_age_seconds <= 60 * 60 * 24 * 365:
            raise ValueError("SESSION_MAX_AGE_SECONDS must be between 60 seconds and 365 days")
        if not self.allowed_origins:
            raise ValueError("APP_ORIGINS must contain at least one exact origin")
        if self.app_env != "production":
            return self

        weak_passwords = {"", "changeme", "password", "admin", "test-password"}
        if self.app_password.lower() in weak_passwords or len(self.app_password) < 12:
            raise ValueError(
                "Production requires APP_PASSWORD with at least 12 non-example characters"
            )
        if (
            self.secret_key in {"", "dev-secret-change-me", "test-secret"}
            or len(self.secret_key) < 32
            or len(set(self.secret_key)) < 8
        ):
            raise ValueError(
                "Production requires SECRET_KEY with at least 32 non-example characters"
            )
        if any(not origin.startswith("https://") for origin in self.allowed_origins):
            raise ValueError("Production APP_ORIGINS must contain only HTTPS origins")
        for origin in self.allowed_origins:
            parsed = urlsplit(origin)
            if not parsed.netloc or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
                raise ValueError("APP_ORIGINS entries must be exact origins without paths")
        if not self.credential_encryption_keys or self.credential_encryption_keys.startswith(
            "local:"
        ):
            raise ValueError(
                "Production requires a non-default CREDENTIAL_ENCRYPTION_KEYS key ring"
            )
        seen_key_ids: set[str] = set()
        for entry in self.credential_encryption_keys.split(","):
            try:
                key_id, encoded = entry.strip().split(":", 1)
                decoded = base64.urlsafe_b64decode(encoded)
            except (ValueError, binascii.Error) as exc:
                raise ValueError("CREDENTIAL_ENCRYPTION_KEYS has an invalid key ring") from exc
            if not key_id or key_id in seen_key_ids or len(decoded) != 32:
                raise ValueError("Credential key ids must be unique and keys must be 32 bytes")
            seen_key_ids.add(key_id)
        if self.google_client_id and not self.google_redirect_uri.startswith("https://"):
            raise ValueError("Production GOOGLE_REDIRECT_URI must use HTTPS")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
