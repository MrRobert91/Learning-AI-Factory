"""Text-to-speech behind a swappable provider interface, with segment cache.

Segments are cached by content hash so re-rendering a video only pays for
the narration that actually changed.
"""

import hashlib
from pathlib import Path
from typing import Protocol


class TTSProvider(Protocol):
    cache_key: str

    def synthesize(self, text: str) -> bytes:
        """Return MP3 bytes for the given text."""
        ...


class OpenAITTSProvider:
    """OpenAI TTS (gpt-4o-mini-tts) via the standard OpenAI API."""

    def __init__(self, api_key: str, voice: str = "nova", model: str = "gpt-4o-mini-tts"):
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY no está configurada (necesaria para TTS)")
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self.voice = voice
        self.model = model
        self.cache_key = f"openai:{model}:{voice}"

    def synthesize(self, text: str) -> bytes:
        response = self._client.audio.speech.create(
            model=self.model,
            voice=self.voice,
            input=text,
            response_format="mp3",
        )
        return response.content


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
