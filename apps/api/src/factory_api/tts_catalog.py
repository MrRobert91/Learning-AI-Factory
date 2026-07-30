"""Persistent TTS catalog access for API validation and execution snapshots."""

from __future__ import annotations

from typing import Any

from factory_agents.tools.tts import (
    cached_tts_catalog,
    normalize_tts_selection,
    resolve_tts_config,
    tts_options,
)

from factory_api.config import get_settings


def snapshot_path():
    return get_settings().data_dir / "cache" / "tts-catalog.json"


def catalog_state(*, refresh: bool = False) -> dict[str, Any]:
    return tts_options(snapshot_path(), refresh=refresh)


def cached_catalog_models() -> list[dict[str, Any]]:
    return cached_tts_catalog(snapshot_path())["models"]


def normalize_current_tts_selection(
    config: dict[str, Any],
    *,
    changed_fields: set[str] | None = None,
) -> dict[str, Any]:
    return normalize_tts_selection(
        config,
        changed_fields=changed_fields,
        catalog=cached_catalog_models(),
    )


def resolve_current_tts_config(
    config: dict[str, Any],
    *,
    project_language: str | None = None,
) -> dict[str, Any]:
    return resolve_tts_config(
        config,
        project_language=project_language,
        catalog=cached_catalog_models(),
    )
