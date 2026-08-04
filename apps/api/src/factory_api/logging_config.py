"""Human-readable console logging for API requests and background work."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime
from typing import TextIO

_STANDARD_FIELDS = set(logging.makeLogRecord({}).__dict__) | {
    "asctime",
    "category",
    "full_ids",
    "message",
}
_FIELD_ALIASES = {
    "artifact_id": "artifact",
    "job_id": "job",
    "job_kind": "kind",
    "job_status": "status",
    "profile_id": "profile",
    "profile_version": "profile_version",
    "project_id": "project",
    "request_id": "request",
    "status_code": "status",
}
_IDENTIFIER_FIELDS = {
    "artifact_id",
    "job_id",
    "profile_id",
    "project_id",
    "request_id",
}
_SENSITIVE_FIELD_PARTS = {
    "api_key",
    "authorization",
    "base64",
    "binary",
    "cookie",
    "document",
    "oauth",
    "payload",
    "prompt",
    "refresh_token",
    "response",
    "secret",
    "session",
    "text_content",
    "tts_text",
}
_MESSAGE_REDACTIONS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\b(?:sk|key)-[A-Za-z0-9_-]{8,}\b"),
    re.compile(
        r'(?i)(["\']?(?:api[_-]?key|authorization|cookie|secret|token)["\']?\s*[:=]\s*)'
        r'(["\']?)[^,\s"\']+\2'
    ),
    re.compile(r"(?i)([?&](?:access_token|api_key|key|token)=)[^&\s]+"),
)


def _is_sensitive_field(key: str) -> bool:
    normalized = key.lower()
    return any(part in normalized for part in _SENSITIVE_FIELD_PARTS)


def _sanitize_text(value: object) -> str:
    text = str(value)
    text = _MESSAGE_REDACTIONS[0].sub("Bearer [redacted]", text)
    text = _MESSAGE_REDACTIONS[1].sub("[redacted]", text)
    text = _MESSAGE_REDACTIONS[2].sub(r"\1[redacted]", text)
    text = _MESSAGE_REDACTIONS[3].sub(r"\1[redacted]", text)
    return text


def _redact_nested(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): (
                "[redacted]" if _is_sensitive_field(str(key)) else _redact_nested(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_redact_nested(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    return value


def _render_value(value: object) -> str:
    safe_value = _redact_nested(value)
    if isinstance(safe_value, str):
        if safe_value and not any(char.isspace() or char in '"|=' for char in safe_value):
            return safe_value
        return json.dumps(safe_value, ensure_ascii=False)
    if isinstance(safe_value, bool):
        return str(safe_value).lower()
    if isinstance(safe_value, (int, float)):
        return str(safe_value)
    return json.dumps(safe_value, ensure_ascii=False, default=str, sort_keys=True)


def _category_for(record: logging.LogRecord) -> str:
    explicit = getattr(record, "category", "")
    if explicit:
        return str(explicit).upper()
    name = record.name.lower()
    if name == "httpx" or name.startswith(("uvicorn.access", "httpcore")):
        return "HTTP"
    if ".tools.tts" in name:
        return "TTS"
    if ".tools.images" in name:
        return "IMAGE"
    if ".tools.marp" in name:
        return "SLIDE"
    if name.startswith("factory_api.runner"):
        return "JOB"
    if name.startswith("factory_api.routers.artifacts"):
        return "ARTIFACT"
    if name.startswith("factory_api.usage"):
        return "USAGE"
    return "APP"


def _identifier(value: object, *, full: bool) -> str:
    rendered = str(value)
    if full or len(rendered) <= 12:
        return rendered
    return rendered[:8]


class HumanReadableFormatter(logging.Formatter):
    """Render stable, compact lines while redacting sensitive structured fields."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).astimezone().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        message = _sanitize_text(record.getMessage()).replace("\r", " ").replace("\n", " ↩ ")
        prefix = (
            f"{timestamp} | {record.levelname:<7} | "
            f"{_category_for(record):<8} | {message}"
        )
        fields: list[str] = []
        show_full_ids = bool(getattr(record, "full_ids", False)) or record.levelno >= logging.ERROR
        for key, value in record.__dict__.items():
            if (
                key in _STANDARD_FIELDS
                or key.startswith("_")
                or value is None
                or _is_sensitive_field(key)
            ):
                continue
            label = _FIELD_ALIASES.get(key, key)
            if key in _IDENTIFIER_FIELDS:
                value = _identifier(value, full=show_full_ids)
            fields.append(f"{label}={_render_value(value)}")
        line = prefix + (" | " + " | ".join(fields) if fields else "")
        if record.exc_info:
            exception = _sanitize_text(self.formatException(record.exc_info))
            line += "\n" + exception
        return line


def configure_logging(level: str = "INFO", *, stream: TextIO | None = None) -> None:
    """Configure one console sink and suppress duplicate Uvicorn access lines."""
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(HumanReadableFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.disabled = False
        uvicorn_logger.propagate = True

    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.disabled = True
    access_logger.propagate = False

    for name in ("httpx", "httpcore"):
        dependency_logger = logging.getLogger(name)
        dependency_logger.handlers.clear()
        dependency_logger.disabled = False
        dependency_logger.propagate = True
