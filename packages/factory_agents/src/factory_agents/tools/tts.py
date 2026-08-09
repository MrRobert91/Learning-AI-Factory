"""Versioned text-to-speech catalog, providers and segment cache."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import time
import wave
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

OPENAI_TTS_MODEL = "gpt-4o-mini-tts"
OPENAI_VOICES = (
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "fable",
    "nova",
    "onyx",
    "sage",
    "shimmer",
    "verse",
    "marin",
    "cedar",
)
GEMINI_VOICES = (
    "Zephyr",
    "Puck",
    "Charon",
    "Kore",
    "Fenrir",
    "Leda",
    "Orus",
    "Aoede",
    "Callirrhoe",
    "Autonoe",
    "Enceladus",
    "Iapetus",
    "Umbriel",
    "Algieba",
    "Despina",
    "Erinome",
    "Algenib",
    "Rasalgethi",
    "Laomedeia",
    "Achernar",
    "Alnilam",
    "Schedar",
    "Gacrux",
    "Pulcherrima",
    "Achird",
    "Zubenelgenubi",
    "Vindemiatrix",
    "Sadachbia",
    "Sadaltager",
    "Sulafat",
)

_LANGUAGE_ALIASES = {
    "es": "es-ES",
    "en": "en-US",
    "fr": "fr-FR",
    "pt": "pt-BR",
    "it": "it-IT",
    "hi": "hi-IN",
    "ja": "ja-JP",
    "zh": "zh-CN",
}

TTS_MODEL_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "provider": "openai",
        "provider_label": "OpenAI directo",
        "model": OPENAI_TTS_MODEL,
        "label": "OpenAI GPT-4o mini TTS",
        "languages": (
            "inherit",
            "es-ES",
            "en-US",
            "fr-FR",
            "pt-BR",
            "it-IT",
            "de-DE",
            "ja-JP",
        ),
        "voices_by_language": {"*": OPENAI_VOICES},
        "default_voice": "nova",
        "request_formats": ("mp3",),
        "preferred_format": "mp3",
        "response_mime_type": "audio/mpeg",
        "output_format": "mp3",
        "output_mime_type": "audio/mpeg",
        "sample_rate_hz": None,
        "channels": None,
        "streaming": False,
        "provider_options": (),
        "capabilities": {
            "speed": {"min": 0.25, "max": 4.0, "step": 0.05},
            "instructions": True,
            "styles": (),
            "style_degree": None,
            "inline_tags": (),
            "pronunciation": False,
        },
        "max_characters": None,
        "status": "stable",
        "price_per_million_characters_usd": None,
        "price_hint": "Coste registrado como desconocido si la respuesta no informa precio.",
    },
    {
        "provider": "openrouter",
        "provider_label": "OpenRouter",
        "model": "hexgrad/kokoro-82m",
        "label": "Kokoro 82M",
        "languages": (
            "inherit",
            "es-ES",
            "en-US",
            "en-GB",
            "fr-FR",
            "hi-IN",
            "it-IT",
            "pt-BR",
            "ja-JP",
            "zh-CN",
        ),
        "voices_by_language": {
            "es-ES": ("ef_dora", "em_alex", "em_santa"),
            "en-US": ("af_heart", "af_bella", "am_michael", "am_puck"),
            "en-GB": ("bf_emma", "bf_isabella", "bm_george", "bm_lewis"),
            "fr-FR": ("ff_siwis",),
            "hi-IN": ("hf_alpha", "hf_beta", "hm_omega", "hm_psi"),
            "it-IT": ("if_sara", "im_nicola"),
            "pt-BR": ("pf_dora", "pm_alex", "pm_santa"),
            "ja-JP": ("jf_alpha", "jf_gongitsune", "jf_nezumi", "jm_kumo"),
            "zh-CN": ("zf_xiaobei", "zf_xiaoxiao", "zm_yunxi", "zm_yunyang"),
        },
        "default_voice": "ef_dora",
        "request_formats": ("mp3",),
        "preferred_format": "mp3",
        "response_mime_type": "audio/mpeg",
        "output_format": "mp3",
        "output_mime_type": "audio/mpeg",
        "sample_rate_hz": None,
        "channels": None,
        "streaming": False,
        "provider_options": (),
        "capabilities": {
            "speed": None,
            "instructions": False,
            "styles": (),
            "style_degree": None,
            "inline_tags": (),
            "pronunciation": False,
        },
        "max_characters": None,
        "status": "stable",
        "price_per_million_characters_usd": 0.62,
        "price_hint": "$0.62 por millón de caracteres (estimación de catálogo).",
    },
    {
        "provider": "openrouter",
        "provider_label": "OpenRouter",
        "model": "google/gemini-3.1-flash-tts-preview",
        "label": "Gemini 3.1 Flash TTS Preview",
        "languages": (
            "inherit",
            "es-ES",
            "en-US",
            "fr-FR",
            "pt-BR",
            "it-IT",
            "de-DE",
            "ja-JP",
            "ko-KR",
            "ar-SA",
            "hi-IN",
        ),
        "voices_by_language": {"*": GEMINI_VOICES},
        "default_voice": "Kore",
        "request_formats": ("pcm",),
        "preferred_format": "pcm",
        "response_mime_type": "audio/pcm",
        "output_format": "wav",
        "output_mime_type": "audio/wav",
        "sample_rate_hz": 24000,
        "channels": 1,
        "sample_width_bytes": 2,
        "streaming": False,
        "provider_options": (),
        "capabilities": {
            "speed": None,
            "instructions": True,
            "styles": (),
            "style_degree": None,
            "inline_tags": ("[pause]", "[emphasis]"),
            "pronunciation": False,
        },
        "max_characters": None,
        "status": "preview",
        "price_per_million_characters_usd": None,
        "price_hint": "Preview multimodal; el coste se registra si el proveedor lo informa.",
    },
    {
        "provider": "openrouter",
        "provider_label": "OpenRouter",
        "model": "microsoft/mai-voice-2",
        "label": "Microsoft MAI-Voice-2",
        "languages": ("inherit", "es-ES", "es-MX", "en-US", "fr-FR"),
        "voices_by_language": {
            "es-ES": ("es-ES-Marta:MAI-Voice-2",),
            "es-MX": (
                "es-MX-Alejo:MAI-Voice-2",
                "es-MX-Valeria:MAI-Voice-2",
            ),
            "en-US": (
                "en-US-Iris:MAI-Voice-2",
                "en-US-Jasper:MAI-Voice-2",
                "en-US-Olivia:MAI-Voice-2",
            ),
            "fr-FR": ("fr-FR-Marc:MAI-Voice-2",),
        },
        "default_voice": "es-ES-Marta:MAI-Voice-2",
        "request_formats": ("mp3",),
        "preferred_format": "mp3",
        "response_mime_type": "audio/mpeg",
        "output_format": "mp3",
        "output_mime_type": "audio/mpeg",
        "sample_rate_hz": None,
        "channels": None,
        "streaming": False,
        "provider_options": ("style", "styledegree"),
        "capabilities": {
            "speed": {"min": 0.5, "max": 2.0, "step": 0.05},
            "instructions": False,
            "styles": ("cheerful", "sad", "angry", "excited"),
            "style_degree": {"min": 0.01, "max": 2.0, "step": 0.05},
            "inline_tags": (),
            "pronunciation": False,
        },
        "max_characters": None,
        "status": "stable",
        "price_per_million_characters_usd": 22.0,
        "price_hint": "$22 por millón de caracteres (estimación de catálogo).",
    },
)

TTS_MODEL_CATALOG += (
    {
        **deepcopy(TTS_MODEL_CATALOG[0]),
        "model": "gpt-4o-mini-tts-2025-12-15",
        "label": "OpenAI GPT-4o mini TTS (2025-12-15)",
    },
    {
        **deepcopy(TTS_MODEL_CATALOG[0]),
        "model": "tts-1",
        "label": "OpenAI TTS-1",
        "capabilities": {
            **deepcopy(TTS_MODEL_CATALOG[0]["capabilities"]),
            "instructions": False,
        },
    },
    {
        **deepcopy(TTS_MODEL_CATALOG[0]),
        "model": "tts-1-hd",
        "label": "OpenAI TTS-1 HD",
        "capabilities": {
            **deepcopy(TTS_MODEL_CATALOG[0]["capabilities"]),
            "instructions": False,
        },
    },
    {
        **deepcopy(TTS_MODEL_CATALOG[3]),
        "model": "microsoft/mai-voice-2-flash",
        "label": "Microsoft MAI-Voice-2 Flash",
        "price_per_million_characters_usd": 15.0,
        "price_hint": "$15 por millón de caracteres (snapshot OpenRouter).",
    },
    {
        "provider": "openrouter",
        "provider_label": "OpenRouter",
        "model": "x-ai/grok-voice-tts-1.0",
        "label": "xAI Grok Voice TTS 1.0",
        "languages": (
            "inherit",
            "es-ES",
            "en-US",
            "fr-FR",
            "pt-BR",
            "it-IT",
            "de-DE",
            "ja-JP",
        ),
        "voices_by_language": {"*": ("eve", "ara", "rex", "sal", "leo")},
        "default_voice": "eve",
        "request_formats": ("mp3",),
        "preferred_format": "mp3",
        "response_mime_type": "audio/mpeg",
        "output_format": "mp3",
        "output_mime_type": "audio/mpeg",
        "sample_rate_hz": None,
        "channels": None,
        "streaming": False,
        "provider_options": ("instructions",),
        "capabilities": {
            "speed": None,
            "instructions": True,
            "styles": (),
            "style_degree": None,
            "inline_tags": ("[pause]", "[emphasis]", "[pitch]", "[speed]", "[style]"),
            "pronunciation": False,
        },
        "max_characters": 15000,
        "status": "stable",
        "price_per_million_characters_usd": 15.0,
        "price_hint": "$15 por millón de caracteres (snapshot OpenRouter).",
    },
    {
        "provider": "openrouter",
        "provider_label": "OpenRouter",
        "model": "deepgram/aura-2",
        "label": "Deepgram Aura-2",
        "languages": (
            "inherit",
            "es-ES",
            "es-MX",
            "en-US",
            "en-GB",
            "fr-FR",
            "de-DE",
            "it-IT",
            "ja-JP",
            "nl-NL",
        ),
        "voices_by_language": {
            "es-ES": (
                "aura-2-nestor-es",
                "aura-2-carina-es",
                "aura-2-alvaro-es",
                "aura-2-silvia-es",
            ),
            "es-MX": ("aura-2-estrella-es", "aura-2-sirio-es"),
            "en-US": ("aura-2-thalia-en",),
            "fr-FR": ("aura-2-agathe-fr", "aura-2-hector-fr"),
        },
        "default_voice": "aura-2-nestor-es",
        "request_formats": ("mp3",),
        "preferred_format": "mp3",
        "response_mime_type": "audio/mpeg",
        "output_format": "mp3",
        "output_mime_type": "audio/mpeg",
        "sample_rate_hz": None,
        "channels": None,
        "streaming": False,
        "provider_options": ("pronunciation",),
        "capabilities": {
            "speed": {"min": 0.5, "max": 2.0, "step": 0.05},
            "instructions": False,
            "styles": (),
            "style_degree": None,
            "inline_tags": (),
            "pronunciation": True,
        },
        "max_characters": None,
        "status": "stable",
        "price_per_million_characters_usd": 30.0,
        "price_hint": "$30 por millón de caracteres (snapshot OpenRouter).",
    },
    {
        "provider": "openrouter",
        "provider_label": "OpenRouter",
        "model": "mistralai/voxtral-mini-tts-2603",
        "label": "Mistral Voxtral Mini TTS",
        "languages": ("inherit", "en-US", "en-GB", "fr-FR"),
        "voices_by_language": {
            "en-US": ("en_paul_neutral", "en_paul_happy", "en_paul_confident"),
            "en-GB": ("gb_oliver_neutral", "gb_jane_curious"),
            "fr-FR": ("fr_marie_neutral", "fr_marie_happy"),
        },
        "default_voice": "en_paul_neutral",
        "request_formats": ("mp3",),
        "preferred_format": "mp3",
        "response_mime_type": "audio/mpeg",
        "output_format": "mp3",
        "output_mime_type": "audio/mpeg",
        "sample_rate_hz": None,
        "channels": None,
        "streaming": False,
        "provider_options": (),
        "capabilities": {
            "speed": None,
            "instructions": False,
            "styles": (),
            "style_degree": None,
            "inline_tags": (),
            "pronunciation": False,
        },
        "max_characters": None,
        "status": "preview",
        "price_per_million_characters_usd": 16.0,
        "price_hint": "$16 por millón de caracteres (snapshot OpenRouter).",
    },
)

TTS_CATALOG_SCHEMA_VERSION = 1
TTS_CATALOG_TTL_SECONDS = 6 * 60 * 60
_GENERIC_CAPABILITIES = {
    "speed": None,
    "instructions": False,
    "styles": (),
    "style_degree": None,
    "inline_tags": (),
    "pronunciation": False,
}


def _safe_text(value: Any, *, limit: int = 300) -> str:
    return str(value or "").replace("<", "").replace(">", "").strip()[:limit]


def _voice_language(model: str, voice: str) -> str:
    lower = voice.lower()
    if model == "hexgrad/kokoro-82m" and len(lower) >= 2:
        return {
            "af": "en-US",
            "am": "en-US",
            "bf": "en-GB",
            "bm": "en-GB",
            "ef": "es-ES",
            "em": "es-ES",
            "ff": "fr-FR",
            "hf": "hi-IN",
            "hm": "hi-IN",
            "if": "it-IT",
            "im": "it-IT",
            "jf": "ja-JP",
            "jm": "ja-JP",
            "pf": "pt-BR",
            "pm": "pt-BR",
            "zf": "zh-CN",
            "zm": "zh-CN",
        }.get(lower[:2], "*")
    if model == "deepgram/aura-2":
        return {
            "es": "es-ES",
            "en": "en-US",
            "fr": "fr-FR",
            "de": "de-DE",
            "it": "it-IT",
            "ja": "ja-JP",
            "nl": "nl-NL",
        }.get(lower.rsplit("-", 1)[-1], "*")
    if model.startswith("microsoft/") and len(voice) >= 5 and voice[2] == "-":
        return voice[:5]
    if model == "mistralai/voxtral-mini-tts-2603":
        return {"en": "en-US", "gb": "en-GB", "fr": "fr-FR"}.get(
            lower.split("_", 1)[0], "*"
        )
    return "*"


def _voices_by_language(model: str, voices: list[str]) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for voice in voices[:500]:
        safe_voice = _safe_text(voice, limit=120)
        if safe_voice:
            grouped.setdefault(_voice_language(model, safe_voice), []).append(safe_voice)
    return {
        language: tuple(dict.fromkeys(values))
        for language, values in grouped.items()
        if values
    }


def _static_entry(model: str) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in TTS_MODEL_CATALOG
            if item["provider"] == "openrouter" and item["model"] == model
        ),
        None,
    )


def _live_catalog_entry(item: dict[str, Any], updated_at: str) -> dict[str, Any] | None:
    model = _safe_text(item.get("id"), limit=160)
    architecture = item.get("architecture")
    if (
        not model
        or not isinstance(architecture, dict)
        or "speech" not in architecture.get("output_modalities", [])
    ):
        return None
    raw_voices = item.get("supported_voices")
    if not isinstance(raw_voices, list) or not raw_voices:
        return None
    voices = _voices_by_language(model, raw_voices)
    if not voices:
        return None
    fallback = _static_entry(model)
    if fallback:
        result = deepcopy(fallback)
        fallback_voices = result.get("voices_by_language", {})
        voices = {
            language: tuple(
                dict.fromkeys(
                    [
                        *fallback_voices.get(language, ()),
                        *discovered,
                    ]
                )
            )
            for language, discovered in {
                **fallback_voices,
                **voices,
            }.items()
        }
        existing_languages = [
            value for value in result.get("languages", ()) if value != "inherit"
        ]
        discovered_languages = [value for value in voices if value != "*"]
        result["languages"] = tuple(
            ["inherit", *dict.fromkeys([*existing_languages, *discovered_languages])]
        )
    else:
        result = {
            "provider": "openrouter",
            "provider_label": "OpenRouter",
            "model": model,
            "label": _safe_text(item.get("name") or model),
            "languages": tuple(["inherit", *[value for value in voices if value != "*"]]),
            "default_voice": next(iter(next(iter(voices.values())))),
            "request_formats": ("mp3",),
            "preferred_format": "mp3",
            "response_mime_type": "audio/mpeg",
            "output_format": "mp3",
            "output_mime_type": "audio/mpeg",
            "sample_rate_hz": None,
            "channels": None,
            "streaming": False,
            "provider_options": (),
            "capabilities": deepcopy(_GENERIC_CAPABILITIES),
            "max_characters": item.get("context_length"),
            "status": "preview",
            "price_per_million_characters_usd": None,
            "price_hint": "Precio obtenido del catálogo dinámico de OpenRouter.",
        }
    result["voices_by_language"] = voices
    if result.get("default_voice") not in {
        voice for values in voices.values() for voice in values
    }:
        preferred = voices.get("es-ES") or voices.get("*") or next(iter(voices.values()))
        result["default_voice"] = preferred[0]
    pricing = item.get("pricing")
    prompt_price = pricing.get("prompt") if isinstance(pricing, dict) else None
    try:
        price = float(prompt_price) * 1_000_000
    except (TypeError, ValueError):
        price = result.get("price_per_million_characters_usd")
    result["price_per_million_characters_usd"] = price
    if price is not None:
        result["price_hint"] = (
            f"${price:g} por millón de caracteres (catálogo OpenRouter)."
        )
    result.update(
        {
            "available": True,
            "catalog_source": "openrouter_models_api",
            "catalog_updated_at": updated_at,
        }
    )
    return result


def _public_entry(item: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(item)
    for key in ("languages", "request_formats", "provider_options"):
        result[key] = list(result.get(key, ()))
    result["voices_by_language"] = {
        key: list(value) for key, value in result.get("voices_by_language", {}).items()
    }
    capabilities = deepcopy(result.get("capabilities") or _GENERIC_CAPABILITIES)
    capabilities["styles"] = list(capabilities.get("styles") or ())
    capabilities["inline_tags"] = list(capabilities.get("inline_tags") or ())
    result["capabilities"] = capabilities
    result.setdefault("available", True)
    result.setdefault("catalog_source", "bundled_fallback")
    result.setdefault("catalog_updated_at", None)
    return result


def _fallback_catalog_state(*, error: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": TTS_CATALOG_SCHEMA_VERSION,
        "source": "bundled_fallback",
        "updated_at": None,
        "stale": True,
        "error": error,
        "models": [_public_entry(item) for item in TTS_MODEL_CATALOG],
    }


def _read_catalog_snapshot(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != TTS_CATALOG_SCHEMA_VERSION
        or not isinstance(payload.get("models"), list)
    ):
        return None
    return payload


def cached_tts_catalog(snapshot_path: str | Path) -> dict[str, Any]:
    """Read the last valid snapshot without performing network I/O."""

    cached = _read_catalog_snapshot(Path(snapshot_path))
    return (
        {**cached, "stale": True, "error": None}
        if cached is not None
        else _fallback_catalog_state()
    )


def load_tts_catalog(
    snapshot_path: str | Path,
    *,
    refresh: bool = False,
    ttl_seconds: int = TTS_CATALOG_TTL_SECONDS,
) -> dict[str, Any]:
    """Load the persistent OpenRouter model snapshot, refreshing it when stale."""

    path = Path(snapshot_path)
    cached = _read_catalog_snapshot(path)
    now = datetime.now(UTC)
    if cached and not refresh:
        try:
            age = (now - datetime.fromisoformat(cached["updated_at"])).total_seconds()
        except (KeyError, TypeError, ValueError):
            age = ttl_seconds + 1
        if age <= ttl_seconds:
            return {**cached, "stale": False, "error": None}
    try:
        response = httpx.get(
            "https://openrouter.ai/api/v1/models",
            params={"output_modalities": "speech"},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        raw_models = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(raw_models, list) or len(raw_models) > 500:
            raise ValueError("payload de modelos TTS inválido")
        updated_at = now.isoformat()
        models = [
            model
            for item in raw_models
            if isinstance(item, dict)
            and (model := _live_catalog_entry(item, updated_at)) is not None
        ]
        openai_models = [
            _public_entry(item)
            for item in TTS_MODEL_CATALOG
            if item["provider"] == "openai"
        ]
        state = {
            "schema_version": TTS_CATALOG_SCHEMA_VERSION,
            "source": "openrouter_models_api",
            "updated_at": updated_at,
            "stale": False,
            "error": None,
            "models": [*openai_models, *[_public_entry(item) for item in models]],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)
        return state
    except (httpx.HTTPError, OSError, ValueError) as exc:
        logger.warning("No se pudo actualizar el catálogo TTS: %s", exc)
        if cached:
            return {**cached, "stale": True, "error": _safe_text(exc)}
        return _fallback_catalog_state(error=_safe_text(exc))


class TTSProvider(Protocol):
    cache_key: str
    last_generation_id: str | None
    audio_format: str
    file_extension: str
    mime_type: str

    def synthesize(self, text: str) -> bytes:
        """Return normalized, playable audio bytes for the given text."""
        ...


class TTSError(RuntimeError):
    """Readable provider or catalog error."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        provider_code: str | None = None,
        field: str | None = None,
        generation_id: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.provider_code = provider_code
        self.field = field
        self.generation_id = generation_id


def normalize_language(language: str) -> str:
    value = str(language or "").strip()
    return _LANGUAGE_ALIASES.get(value.lower(), value)


def _catalog_entry(
    provider: str,
    model: str,
    catalog: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in (catalog if catalog is not None else TTS_MODEL_CATALOG)
            if item["provider"] == provider and item["model"] == model
        ),
        None,
    )


def _all_voices(entry: dict[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    for voices in entry["voices_by_language"].values():
        values.extend(voices)
    return tuple(dict.fromkeys(values))


def voices_for(entry: dict[str, Any], language: str) -> tuple[str, ...]:
    wildcard = entry["voices_by_language"].get("*")
    if wildcard:
        return tuple(wildcard)
    if language == "inherit":
        return _all_voices(entry)
    return tuple(entry["voices_by_language"].get(normalize_language(language), ()))


def resolve_tts_config(
    config: dict[str, Any],
    *,
    project_language: str | None = None,
    catalog: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> dict[str, Any]:
    """Validate a closed provider/model/language/voice combination."""

    provider = str(config.get("tts_provider") or "")
    model = str(config.get("tts_model") or "")
    language = str(config.get("tts_language") or "inherit")
    entry = _catalog_entry(provider, model, catalog)
    frozen_entry = config.get("tts_catalog_entry")
    if (
        catalog is None
        and isinstance(frozen_entry, dict)
        and frozen_entry.get("provider") == provider
        and frozen_entry.get("model") == model
    ):
        entry = frozen_entry
    if entry is None or entry.get("available") is False:
        raise ValueError("La combinación de proveedor y modelo TTS ya no está disponible")
    if language not in entry["languages"]:
        raise ValueError(f"El idioma {language!r} no está disponible para {model}")
    effective_language = (
        normalize_language(project_language or "") if language == "inherit" else language
    )
    validation_language = effective_language or language
    voice = str(config.get("tts_voice") or entry["default_voice"])
    allowed = voices_for(entry, validation_language)
    if not allowed or voice not in allowed:
        raise ValueError(
            f"La voz {voice!r} no está disponible para {model} / "
            f"{validation_language or language}"
        )
    requested_format = str(config.get("tts_format") or "")
    if requested_format not in entry["request_formats"]:
        requested_format = entry["preferred_format"]
    capabilities = deepcopy(entry.get("capabilities") or _GENERIC_CAPABILITIES)
    speed = float(config.get("tts_speed", 1.0) or 1.0)
    speed_range = capabilities.get("speed")
    if speed_range:
        if not float(speed_range["min"]) <= speed <= float(speed_range["max"]):
            raise ValueError(
                f"La velocidad debe estar entre {speed_range['min']} y "
                f"{speed_range['max']} para {model}"
            )
    elif speed != 1.0:
        raise ValueError(f"{model} no admite control de velocidad")
    instructions = str(config.get("tts_instructions") or "").strip()
    if instructions and not capabilities.get("instructions"):
        raise ValueError(f"{model} no admite instrucciones expresivas")
    if len(instructions) > 1000:
        raise ValueError("Las instrucciones TTS no pueden superar 1000 caracteres")
    style = str(config.get("tts_style") or "").strip() or None
    styles = tuple(capabilities.get("styles") or ())
    if style and (not styles or style not in styles):
        raise ValueError(f"El estilo {style!r} no está disponible para {model}")
    raw_style_degree = config.get("tts_style_degree")
    style_degree = (
        float(raw_style_degree)
        if raw_style_degree is not None and raw_style_degree != ""
        else None
    )
    style_degree_range = capabilities.get("style_degree")
    if style_degree is not None:
        if not style_degree_range:
            raise ValueError(f"{model} no admite intensidad de estilo")
        if not float(style_degree_range["min"]) <= style_degree <= float(
            style_degree_range["max"]
        ):
            raise ValueError(
                f"La intensidad debe estar entre {style_degree_range['min']} y "
                f"{style_degree_range['max']} para {model}"
            )
    advanced = config.get("tts_advanced_options") or {}
    if not isinstance(advanced, dict):
        raise ValueError("Las opciones TTS avanzadas deben ser un objeto")
    if len(advanced) > 20 or len(json.dumps(advanced, ensure_ascii=False)) > 4000:
        raise ValueError("Las opciones TTS avanzadas superan el tamaño permitido")
    unknown_advanced = set(advanced) - set(entry.get("provider_options") or ())
    if unknown_advanced:
        raise ValueError(
            "Opciones TTS no admitidas para el modelo: "
            + ", ".join(sorted(unknown_advanced))
        )
    return {
        "tts_provider": provider,
        "tts_model": model,
        "tts_language": language,
        "tts_language_effective": effective_language or language,
        "tts_voice": voice,
        "tts_format": requested_format,
        "tts_request_formats": list(entry["request_formats"]),
        "tts_response_mime_type": entry["response_mime_type"],
        "tts_output_format": entry["output_format"],
        "tts_mime_type": entry["output_mime_type"],
        "tts_sample_rate_hz": entry["sample_rate_hz"],
        "tts_channels": entry["channels"],
        "tts_sample_width_bytes": entry.get("sample_width_bytes", 2),
        "tts_streaming": entry["streaming"],
        "tts_provider_options": list(entry["provider_options"]),
        "tts_speed": speed,
        "tts_instructions": instructions,
        "tts_style": style,
        "tts_style_degree": style_degree,
        "tts_advanced_options": deepcopy(advanced),
        "tts_capabilities": {
            **capabilities,
            "styles": list(capabilities.get("styles") or ()),
            "inline_tags": list(capabilities.get("inline_tags") or ()),
        },
        "tts_catalog_source": config.get("tts_catalog_source")
        or entry.get("catalog_source", "bundled_fallback"),
        "tts_catalog_updated_at": config.get("tts_catalog_updated_at")
        or entry.get("catalog_updated_at"),
        "tts_model_status": entry.get("status", "stable"),
        "tts_max_characters": entry.get("max_characters"),
        "tts_catalog_entry": _public_entry(entry),
        "price_per_million_characters_usd": entry[
            "price_per_million_characters_usd"
        ],
        "price_hint": entry["price_hint"],
    }


def default_tts_config(
    *,
    provider: str = "openai",
    model: str = OPENAI_TTS_MODEL,
    voice: str = "nova",
) -> dict[str, Any]:
    entry = _catalog_entry(provider, model) or TTS_MODEL_CATALOG[0]
    chosen_voice = voice if voice in _all_voices(entry) else entry["default_voice"]
    return {
        "tts_provider": entry["provider"],
        "tts_model": entry["model"],
        "tts_language": "inherit",
        "tts_voice": chosen_voice,
        "tts_speed": 1.0,
        "tts_instructions": "",
        "tts_style": None,
        "tts_style_degree": None,
        "tts_advanced_options": {},
    }


def normalize_tts_selection(
    config: dict[str, Any],
    *,
    changed_fields: set[str] | None = None,
    catalog: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> dict[str, Any]:
    """Replace an incompatible voice after model/language changes."""

    changed_fields = changed_fields or set()
    provider = str(config.get("tts_provider") or "")
    model = str(config.get("tts_model") or "")
    entry = _catalog_entry(provider, model, catalog)
    if entry is None or entry.get("available") is False:
        raise ValueError("Proveedor o modelo TTS no permitido")
    language = str(config.get("tts_language") or "inherit")
    if language not in entry["languages"]:
        language = "inherit"
        config["tts_language"] = language
    allowed = voices_for(entry, language)
    voice = str(config.get("tts_voice") or "")
    if voice not in allowed:
        if "tts_voice" in changed_fields and voice:
            raise ValueError("La voz seleccionada no es compatible con el modelo o idioma")
        config["tts_voice"] = (
            entry["default_voice"]
            if entry["default_voice"] in allowed
            else allowed[0]
        )
    capabilities = entry.get("capabilities") or _GENERIC_CAPABILITIES
    if not capabilities.get("speed") and "tts_speed" not in changed_fields:
        config["tts_speed"] = 1.0
    if not capabilities.get("instructions") and "tts_instructions" not in changed_fields:
        config["tts_instructions"] = ""
    styles = capabilities.get("styles") or ()
    if config.get("tts_style") not in styles and "tts_style" not in changed_fields:
        config["tts_style"] = None
        config["tts_style_degree"] = None
    allowed_options = set(entry.get("provider_options") or ())
    if "tts_advanced_options" not in changed_fields:
        config["tts_advanced_options"] = {
            key: value
            for key, value in (config.get("tts_advanced_options") or {}).items()
            if key in allowed_options
        }
    resolve_tts_config(config, catalog=catalog)
    return config


def tts_options(
    snapshot_path: str | Path | None = None,
    *,
    refresh: bool = False,
) -> dict[str, Any]:
    state = (
        load_tts_catalog(snapshot_path, refresh=refresh)
        if snapshot_path is not None
        else _fallback_catalog_state()
    )
    return {**state, "default": default_tts_config()}


def estimated_tts_cost(config: dict[str, Any], characters: int) -> float | None:
    price = config.get("price_per_million_characters_usd")
    if price is None:
        entry = _catalog_entry(
            str(config.get("tts_provider") or ""),
            str(config.get("tts_model") or ""),
        )
        price = entry["price_per_million_characters_usd"] if entry else None
    return None if price is None else max(characters, 0) * float(price) / 1_000_000


def _content_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def _looks_like_mp3(audio: bytes) -> bool:
    return audio.startswith(b"ID3") or (
        len(audio) >= 2 and audio[0] == 0xFF and audio[1] & 0xE0 == 0xE0
    )


def _pcm_to_wav(
    audio: bytes,
    *,
    sample_rate_hz: int,
    channels: int,
    sample_width_bytes: int = 2,
) -> bytes:
    frame_size = channels * sample_width_bytes
    if not audio or len(audio) % frame_size:
        raise TTSError(
            "OpenRouter TTS devolvió PCM vacío o con una longitud de frame inválida",
            status_code=502,
        )
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(channels)
        target.setsampwidth(sample_width_bytes)
        target.setframerate(sample_rate_hz)
        target.writeframes(audio)
    return output.getvalue()


def _validate_wav(
    audio: bytes,
    *,
    sample_rate_hz: int | None = None,
    channels: int | None = None,
) -> bool:
    try:
        with wave.open(io.BytesIO(audio), "rb") as source:
            return (
                source.getnframes() > 0
                and (sample_rate_hz is None or source.getframerate() == sample_rate_hz)
                and (channels is None or source.getnchannels() == channels)
            )
    except (EOFError, wave.Error):
        return False


def _valid_audio_bytes(
    audio: bytes,
    audio_format: str,
    *,
    sample_rate_hz: int | None = None,
    channels: int | None = None,
) -> bool:
    if audio_format == "mp3":
        return _looks_like_mp3(audio)
    if audio_format == "wav":
        return _validate_wav(
            audio,
            sample_rate_hz=sample_rate_hz,
            channels=channels,
        )
    return bool(audio)


class OpenAITTSProvider:
    """OpenAI TTS via the standard OpenAI API."""

    def __init__(
        self,
        api_key: str,
        voice: str = "nova",
        model: str = OPENAI_TTS_MODEL,
        language: str = "inherit",
        speed: float = 1.0,
        instructions: str = "",
    ):
        if not api_key:
            raise TTSError("OPENAI_API_KEY no está configurada para el perfil de audio")
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self.voice = voice
        self.model = model
        self.language = language
        self.speed = speed
        self.instructions = instructions
        self.last_generation_id: str | None = None
        self.audio_format = "mp3"
        self.file_extension = "mp3"
        self.mime_type = "audio/mpeg"
        expressive_hash = hashlib.sha256(instructions.encode()).hexdigest()[:16]
        self.cache_key = (
            f"openai:{model}:{language}:{voice}:mp3:{speed:g}:{expressive_hash}"
        )

    def synthesize(self, text: str) -> bytes:
        request: dict[str, Any] = {
            "model": self.model,
            "voice": self.voice,
            "input": text,
            "response_format": "mp3",
            "speed": self.speed,
        }
        if self.instructions:
            request["instructions"] = self.instructions
        response = self._client.audio.speech.create(
            **request,
        )
        self.last_generation_id = getattr(response, "_request_id", None)
        return response.content


class OpenRouterTTSProvider:
    """OpenRouter's OpenAI-compatible raw-audio TTS endpoint."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str,
        voice: str,
        language: str = "inherit",
        request_format: str = "mp3",
        response_mime_type: str = "audio/mpeg",
        output_format: str = "mp3",
        output_mime_type: str = "audio/mpeg",
        sample_rate_hz: int | None = None,
        channels: int | None = None,
        sample_width_bytes: int = 2,
        provider_options: dict[str, Any] | None = None,
        speed: float | None = None,
        instructions: str = "",
        base_url: str = "https://openrouter.ai/api/v1",
        timeout_seconds: float = 60,
        max_retries: int = 2,
    ):
        if not api_key:
            raise TTSError("OPENROUTER_API_KEY no está configurada para el perfil de audio")
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.language = language
        self.request_format = request_format
        self.response_mime_type = response_mime_type
        self.audio_format = output_format
        self.file_extension = output_format
        self.mime_type = output_mime_type
        self.sample_rate_hz = sample_rate_hz
        self.channels = channels
        self.sample_width_bytes = sample_width_bytes
        self.provider_options = provider_options or {}
        self.speed = speed
        self.instructions = instructions
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.last_generation_id: str | None = None
        expressive = json.dumps(
            {
                "speed": speed,
                "instructions": instructions,
                "provider_options": self.provider_options,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        expressive_hash = hashlib.sha256(expressive.encode()).hexdigest()[:20]
        self.cache_key = (
            f"openrouter:{model}:{language}:{voice}:"
            f"{request_format}:{output_format}:{sample_rate_hz or '-'}:"
            f"{channels or '-'}:{sample_width_bytes}:{expressive_hash}"
        )

    @staticmethod
    def _error_details(
        response: httpx.Response,
    ) -> tuple[str, str | None, str | None]:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:400] or response.reason_phrase, None, None
        error = payload.get("error", payload) if isinstance(payload, dict) else payload
        if isinstance(error, dict):
            message = str(error.get("message") or error.get("code") or error)
            code = error.get("code")
            field = error.get("param") or error.get("field")
            metadata = error.get("metadata")
            if isinstance(metadata, dict):
                field = field or metadata.get("param") or metadata.get("field")
            return (
                message[:400],
                str(code)[:100] if code is not None else None,
                str(field)[:100] if field is not None else None,
            )
        return str(error)[:400], None, None

    def _normalize_response(self, response: httpx.Response) -> bytes:
        content_type = _content_type(response.headers.get("content-type", ""))
        audio = response.content
        generation_id = response.headers.get("x-generation-id")
        if self.request_format == "pcm":
            if content_type == "audio/wav" and _validate_wav(
                audio,
                sample_rate_hz=self.sample_rate_hz,
                channels=self.channels,
            ):
                return audio
            if content_type not in {"audio/pcm", "audio/l16"}:
                raise TTSError(
                    "OpenRouter TTS devolvió "
                    f"{content_type or 'un tipo desconocido'} al solicitar PCM",
                    status_code=502,
                    generation_id=generation_id,
                )
            if self.sample_rate_hz is None or self.channels is None:
                raise TTSError(
                    "Faltan sample rate o canales para normalizar la respuesta PCM",
                    status_code=500,
                )
            return _pcm_to_wav(
                audio,
                sample_rate_hz=self.sample_rate_hz,
                channels=self.channels,
                sample_width_bytes=self.sample_width_bytes,
            )
        if content_type not in {"audio/mpeg", "audio/mp3"}:
            raise TTSError(
                "OpenRouter TTS devolvió "
                f"{content_type or 'un tipo desconocido'} al solicitar MP3",
                status_code=502,
                generation_id=generation_id,
            )
        if not _looks_like_mp3(audio):
            raise TTSError(
                "OpenRouter TTS devolvió audio MP3 vacío o corrupto",
                status_code=502,
                generation_id=generation_id,
            )
        return audio

    def synthesize(self, text: str) -> bytes:
        payload = {
            "model": self.model,
            "input": text,
            "voice": self.voice,
            "response_format": self.request_format,
        }
        if self.speed is not None:
            payload["speed"] = self.speed
        if self.provider_options:
            payload["provider"] = {"options": self.provider_options}
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = httpx.post(
                    f"{self.base_url}/audio/speech",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self.timeout_seconds,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(0.25 * (2**attempt))
                    continue
                raise TTSError(
                    f"OpenRouter TTS no respondió: {exc}",
                    status_code=504,
                ) from exc
            if response.status_code >= 400:
                message, code, field = self._error_details(response)
                generation_id = response.headers.get("x-generation-id")
                if self.api_key:
                    message = message.replace(self.api_key, "[redacted]")
                logger.warning(
                    "OpenRouter TTS request failed status=%s model=%s voice=%s "
                    "format=%s code=%s field=%s generation_id=%s",
                    response.status_code,
                    self.model,
                    self.voice,
                    self.request_format,
                    code,
                    field,
                    generation_id,
                )
                if response.status_code in {408, 429} or response.status_code >= 500:
                    last_error = TTSError(
                        message,
                        status_code=response.status_code,
                        provider_code=code,
                        field=field,
                        generation_id=generation_id,
                    )
                    if attempt < self.max_retries:
                        time.sleep(0.25 * (2**attempt))
                        continue
                detail = message
                if code:
                    detail += f" (código {code})"
                if field:
                    detail += f" · campo {field}"
                raise TTSError(
                    f"OpenRouter TTS devolvió {response.status_code}: {detail}",
                    status_code=response.status_code,
                    provider_code=code,
                    field=field,
                    generation_id=generation_id,
                )
            self.last_generation_id = response.headers.get("x-generation-id")
            normalized = self._normalize_response(response)
            if not _valid_audio_bytes(
                normalized,
                self.audio_format,
                sample_rate_hz=self.sample_rate_hz,
                channels=self.channels,
            ):
                raise TTSError(
                    "OpenRouter TTS devolvió audio vacío o corrupto",
                    status_code=502,
                    generation_id=self.last_generation_id,
                )
            return normalized
        raise TTSError(f"OpenRouter TTS falló: {last_error}", status_code=502)


def build_tts_provider(
    config: dict[str, Any],
    *,
    openai_api_key: str,
    openrouter_api_key: str,
) -> TTSProvider:
    resolved = resolve_tts_config(
        config,
        project_language=(
            config.get("tts_language_effective")
            if config.get("tts_language") == "inherit"
            else None
        ),
    )
    if resolved["tts_provider"] == "openai":
        return OpenAITTSProvider(
            openai_api_key,
            voice=resolved["tts_voice"],
            model=resolved["tts_model"],
            language=resolved["tts_language_effective"],
            speed=resolved["tts_speed"],
            instructions=resolved["tts_instructions"],
        )
    expressive_options = dict(resolved["tts_advanced_options"])
    if resolved["tts_instructions"]:
        expressive_options.setdefault("instructions", resolved["tts_instructions"])
    if resolved["tts_style"]:
        expressive_options["style"] = resolved["tts_style"]
    if resolved["tts_style_degree"] is not None:
        expressive_options["styledegree"] = resolved["tts_style_degree"]
    option_namespace = (
        "azure"
        if resolved["tts_model"].startswith("microsoft/")
        else (
            "google"
            if resolved["tts_model"].startswith("google/")
            else (
                "xai"
                if resolved["tts_model"].startswith("x-ai/")
                else "openai"
            )
        )
    )
    provider_options = (
        {option_namespace: expressive_options} if expressive_options else {}
    )
    return OpenRouterTTSProvider(
        openrouter_api_key,
        model=resolved["tts_model"],
        voice=resolved["tts_voice"],
        language=resolved["tts_language_effective"],
        request_format=resolved["tts_format"],
        response_mime_type=resolved["tts_response_mime_type"],
        output_format=resolved["tts_output_format"],
        output_mime_type=resolved["tts_mime_type"],
        sample_rate_hz=resolved["tts_sample_rate_hz"],
        channels=resolved["tts_channels"],
        sample_width_bytes=resolved["tts_sample_width_bytes"],
        speed=(
            resolved["tts_speed"]
            if resolved["tts_capabilities"].get("speed") is not None
            else None
        ),
        instructions=resolved["tts_instructions"],
        provider_options=provider_options,
    )


def synthesize_cached(provider: TTSProvider, text: str, cache_dir: str | Path) -> Path:
    """Synthesize a segment, reusing the cache when the text hasn't changed."""
    path, _cache_hit = synthesize_cached_with_status(provider, text, cache_dir)
    return path


def is_valid_audio_file(provider: TTSProvider, path: str | Path) -> bool:
    """Validate a cached provider output before treating it as reusable."""

    path = Path(path)
    if not path.is_file():
        return False
    try:
        audio = path.read_bytes()
    except OSError:
        return False
    audio_format = getattr(provider, "audio_format", None)
    if not audio_format:
        return bool(audio)
    return _valid_audio_bytes(
        audio,
        audio_format,
        sample_rate_hz=getattr(provider, "sample_rate_hz", None),
        channels=getattr(provider, "channels", None),
    )


def synthesize_cached_with_status(
    provider: TTSProvider, text: str, cache_dir: str | Path
) -> tuple[Path, bool]:
    """Synthesize one segment and expose whether provider work was avoided."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(f"{provider.cache_key}\x00{text}".encode()).hexdigest()[:32]
    audio_format = getattr(provider, "audio_format", None)
    extension = getattr(provider, "file_extension", None) or audio_format or "mp3"
    path = cache_dir / f"{digest}.{extension}"
    cache_hit = path.is_file()
    if cache_hit:
        cache_hit = is_valid_audio_file(provider, path)
        if not cache_hit:
            path.unlink(missing_ok=True)
    if not cache_hit:
        audio = provider.synthesize(text)
        if audio_format and not _valid_audio_bytes(
            audio,
            audio_format,
            sample_rate_hz=getattr(provider, "sample_rate_hz", None),
            channels=getattr(provider, "channels", None),
        ):
            raise TTSError("El proveedor TTS devolvió audio vacío o corrupto")
        path.write_bytes(audio)
    return path, cache_hit
