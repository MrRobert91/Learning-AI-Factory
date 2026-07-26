import httpx
import pytest
from factory_agents.tools.tts import (
    OpenRouterTTSProvider,
    TTSError,
    resolve_tts_config,
)


def _response(status: int, *, content: bytes = b"", json_body=None, headers=None):
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/audio/speech")
    if json_body is not None:
        return httpx.Response(status, json=json_body, headers=headers, request=request)
    return httpx.Response(status, content=content, headers=headers, request=request)


def test_openrouter_tts_reads_binary_audio_and_generation_id(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return _response(
            200,
            content=b"ID3audio",
            headers={
                "content-type": "audio/mpeg",
                "x-generation-id": "gen-123",
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = OpenRouterTTSProvider(
        "secret",
        model="microsoft/mai-voice-2",
        voice="es-ES-Marta:MAI-Voice-2",
        language="es-ES",
    )
    assert provider.synthesize("Hola") == b"ID3audio"
    assert provider.last_generation_id == "gen-123"
    assert calls[0][0].endswith("/audio/speech")
    assert calls[0][1]["json"]["response_format"] == "mp3"
    assert "secret" not in str(calls[0][1]["json"])


def test_openrouter_tts_retries_transient_json_error(monkeypatch):
    responses = iter(
        [
            _response(503, json_body={"error": {"message": "ocupado"}}),
            _response(
                200,
                content=b"ID3ok",
                headers={"content-type": "audio/mpeg"},
            ),
        ]
    )
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr("factory_agents.tools.tts.time.sleep", lambda *_: None)
    provider = OpenRouterTTSProvider(
        "secret",
        model="hexgrad/kokoro-82m",
        voice="ef_dora",
        max_retries=2,
    )
    assert provider.synthesize("Hola") == b"ID3ok"


def test_openrouter_tts_retries_timeout(monkeypatch):
    calls = 0

    def fake_post(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("timeout")
        return _response(
            200,
            content=b"ID3after-timeout",
            headers={"content-type": "audio/mpeg"},
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr("factory_agents.tools.tts.time.sleep", lambda *_: None)
    provider = OpenRouterTTSProvider(
        "secret",
        model="hexgrad/kokoro-82m",
        voice="ef_dora",
    )
    assert provider.synthesize("Hola") == b"ID3after-timeout"
    assert calls == 2


def test_openrouter_tts_surfaces_readable_json_error(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: _response(
            422,
            json_body={"error": {"message": "voz no compatible"}},
        ),
    )
    provider = OpenRouterTTSProvider(
        "secret",
        model="hexgrad/kokoro-82m",
        voice="ef_dora",
    )
    with pytest.raises(TTSError, match="voz no compatible"):
        provider.synthesize("Hola")


def test_tts_catalog_rejects_arbitrary_combinations_and_cache_key_is_complete():
    config = resolve_tts_config(
        {
            "tts_provider": "openrouter",
            "tts_model": "microsoft/mai-voice-2",
            "tts_language": "inherit",
            "tts_voice": "es-ES-Marta:MAI-Voice-2",
        },
        project_language="es",
    )
    assert config["tts_language_effective"] == "es-ES"
    provider = OpenRouterTTSProvider(
        "secret",
        model=config["tts_model"],
        voice=config["tts_voice"],
        language=config["tts_language_effective"],
    )
    assert provider.cache_key == (
        "openrouter:microsoft/mai-voice-2:"
        "es-ES:es-ES-Marta:MAI-Voice-2:mp3"
    )
    with pytest.raises(ValueError, match="no está disponible"):
        resolve_tts_config(
            {
                "tts_provider": "openrouter",
                "tts_model": "microsoft/mai-voice-2",
                "tts_language": "es-ES",
                "tts_voice": "ef_dora",
            }
        )
