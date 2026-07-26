"""Versioned text-to-speech catalog, providers and segment cache."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Protocol

import httpx

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
        "price_per_million_characters_usd": 22.0,
        "price_hint": "$22 por millón de caracteres (estimación de catálogo).",
    },
)


class TTSProvider(Protocol):
    cache_key: str
    last_generation_id: str | None

    def synthesize(self, text: str) -> bytes:
        """Return MP3 bytes for the given text."""
        ...


class TTSError(RuntimeError):
    """Readable provider or catalog error."""


def normalize_language(language: str) -> str:
    value = str(language or "").strip()
    return _LANGUAGE_ALIASES.get(value.lower(), value)


def _catalog_entry(provider: str, model: str) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in TTS_MODEL_CATALOG
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
) -> dict[str, Any]:
    """Validate a closed provider/model/language/voice combination."""

    provider = str(config.get("tts_provider") or "")
    model = str(config.get("tts_model") or "")
    language = str(config.get("tts_language") or "inherit")
    entry = _catalog_entry(provider, model)
    if entry is None:
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
    return {
        "tts_provider": provider,
        "tts_model": model,
        "tts_language": language,
        "tts_language_effective": effective_language or language,
        "tts_voice": voice,
        "tts_format": "mp3",
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
) -> dict[str, str]:
    entry = _catalog_entry(provider, model) or TTS_MODEL_CATALOG[0]
    chosen_voice = voice if voice in _all_voices(entry) else entry["default_voice"]
    return {
        "tts_provider": entry["provider"],
        "tts_model": entry["model"],
        "tts_language": "inherit",
        "tts_voice": chosen_voice,
    }


def normalize_tts_selection(
    config: dict[str, Any],
    *,
    changed_fields: set[str] | None = None,
) -> dict[str, Any]:
    """Replace an incompatible voice after model/language changes."""

    changed_fields = changed_fields or set()
    provider = str(config.get("tts_provider") or "")
    model = str(config.get("tts_model") or "")
    entry = _catalog_entry(provider, model)
    if entry is None:
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
    resolve_tts_config(config)
    return config


def tts_options() -> dict[str, Any]:
    return {
        "default": default_tts_config(),
        "models": [
            {
                **{key: value for key, value in item.items() if key != "voices_by_language"},
                "languages": list(item["languages"]),
                "voices_by_language": {
                    key: list(value) for key, value in item["voices_by_language"].items()
                },
            }
            for item in TTS_MODEL_CATALOG
        ],
    }


def estimated_tts_cost(config: dict[str, Any], characters: int) -> float | None:
    entry = _catalog_entry(
        str(config.get("tts_provider") or ""),
        str(config.get("tts_model") or ""),
    )
    price = entry["price_per_million_characters_usd"] if entry else None
    return None if price is None else max(characters, 0) * float(price) / 1_000_000


class OpenAITTSProvider:
    """OpenAI TTS via the standard OpenAI API."""

    def __init__(
        self,
        api_key: str,
        voice: str = "nova",
        model: str = OPENAI_TTS_MODEL,
        language: str = "inherit",
    ):
        if not api_key:
            raise TTSError("OPENAI_API_KEY no está configurada para el perfil de voz")
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self.voice = voice
        self.model = model
        self.language = language
        self.last_generation_id: str | None = None
        self.cache_key = f"openai:{model}:{language}:{voice}:mp3"

    def synthesize(self, text: str) -> bytes:
        response = self._client.audio.speech.create(
            model=self.model,
            voice=self.voice,
            input=text,
            response_format="mp3",
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
        base_url: str = "https://openrouter.ai/api/v1",
        timeout_seconds: float = 60,
        max_retries: int = 2,
    ):
        if not api_key:
            raise TTSError("OPENROUTER_API_KEY no está configurada para el perfil de voz")
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.language = language
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.last_generation_id: str | None = None
        self.cache_key = f"openrouter:{model}:{language}:{voice}:mp3"

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:400] or response.reason_phrase
        error = payload.get("error", payload) if isinstance(payload, dict) else payload
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or error)
        return str(error)

    def synthesize(self, text: str) -> bytes:
        payload = {
            "model": self.model,
            "input": text,
            "voice": self.voice,
            "response_format": "mp3",
        }
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
                raise TTSError(f"OpenRouter TTS no respondió: {exc}") from exc
            if response.status_code >= 400:
                message = self._error_message(response)
                if response.status_code in {408, 429} or response.status_code >= 500:
                    last_error = TTSError(message)
                    if attempt < self.max_retries:
                        time.sleep(0.25 * (2**attempt))
                        continue
                raise TTSError(f"OpenRouter TTS devolvió {response.status_code}: {message}")
            content_type = response.headers.get("content-type", "").lower()
            if "audio/" not in content_type or not response.content:
                raise TTSError("OpenRouter TTS devolvió una respuesta sin audio MP3")
            self.last_generation_id = response.headers.get("x-generation-id")
            return response.content
        raise TTSError(f"OpenRouter TTS falló: {last_error}")


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
        )
    return OpenRouterTTSProvider(
        openrouter_api_key,
        model=resolved["tts_model"],
        voice=resolved["tts_voice"],
        language=resolved["tts_language_effective"],
    )


def synthesize_cached(provider: TTSProvider, text: str, cache_dir: str | Path) -> Path:
    """Synthesize a segment, reusing the cache when the text hasn't changed."""
    path, _cache_hit = synthesize_cached_with_status(provider, text, cache_dir)
    return path


def synthesize_cached_with_status(
    provider: TTSProvider, text: str, cache_dir: str | Path
) -> tuple[Path, bool]:
    """Synthesize one segment and expose whether provider work was avoided."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(f"{provider.cache_key}\x00{text}".encode()).hexdigest()[:32]
    path = cache_dir / f"{digest}.mp3"
    cache_hit = path.is_file()
    if not cache_hit:
        path.write_bytes(provider.synthesize(text))
    return path, cache_hit
