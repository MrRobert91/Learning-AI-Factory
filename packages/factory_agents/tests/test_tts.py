import io
import wave

import httpx
import pytest
from factory_agents.tools.tts import (
    OpenRouterTTSProvider,
    TTSError,
    build_tts_provider,
    load_tts_catalog,
    resolve_tts_config,
    synthesize_cached_with_status,
)
from factory_agents.tools.video import probe_duration


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
    assert provider.cache_key.startswith(
        "openrouter:microsoft/mai-voice-2:"
        "es-ES:es-ES-Marta:MAI-Voice-2:mp3:mp3:-:-:2"
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


def test_tts_catalog_persists_live_voices_and_falls_back_to_snapshot(
    monkeypatch, tmp_path
):
    live_payload = {
        "data": [
            {
                "id": "x-ai/grok-voice-tts-1.0",
                "name": "xAI: Grok Voice TTS 1.0",
                "architecture": {"output_modalities": ["speech"]},
                "supported_voices": ["eve", "ara"],
                "pricing": {"prompt": "0.000015"},
                "context_length": 15000,
            }
        ]
    }

    class CatalogResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return live_payload

    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: CatalogResponse())
    path = tmp_path / "tts-catalog.json"
    first = load_tts_catalog(path, refresh=True)
    grok = next(item for item in first["models"] if item["model"].startswith("x-ai/"))
    assert grok["voices_by_language"]["*"][:2] == ["eve", "ara"]
    assert "leo" in grok["voices_by_language"]["*"]
    assert grok["price_per_million_characters_usd"] == 15
    assert first["source"] == "openrouter_models_api"
    assert path.is_file()
    frozen = resolve_tts_config(
        {
            "tts_provider": "openrouter",
            "tts_model": grok["model"],
            "tts_language": "inherit",
            "tts_voice": "eve",
        },
        catalog=first["models"],
    )
    assert resolve_tts_config(frozen)["tts_voice"] == "eve"
    with pytest.raises(ValueError, match="ya no está disponible"):
        resolve_tts_config(
            {
                "tts_provider": "openrouter",
                "tts_model": grok["model"],
                "tts_language": "inherit",
                "tts_voice": "eve",
            },
            catalog=[],
        )

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ConnectError("offline")),
    )
    fallback = load_tts_catalog(path, refresh=True)
    assert fallback["stale"] is True
    assert fallback["updated_at"] == first["updated_at"]
    assert fallback["models"] == first["models"]


def test_expressive_options_are_validated_sent_and_part_of_cache_key(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs["json"])
        return _response(
            200,
            content=b"ID3expressive",
            headers={"content-type": "audio/mpeg"},
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    resolved = resolve_tts_config(
        {
            "tts_provider": "openrouter",
            "tts_model": "microsoft/mai-voice-2",
            "tts_language": "es-ES",
            "tts_voice": "es-ES-Marta:MAI-Voice-2",
            "tts_speed": 1.2,
            "tts_style": "cheerful",
            "tts_style_degree": 1.4,
        }
    )
    provider = build_tts_provider(
        resolved,
        openai_api_key="",
        openrouter_api_key="secret",
    )
    provider.synthesize("Hola")
    assert calls[0]["speed"] == 1.2
    assert calls[0]["provider"]["options"] == {
        "azure": {"style": "cheerful", "styledegree": 1.4},
    }
    default_provider = build_tts_provider(
        {
            **resolved,
            "tts_speed": 1.0,
            "tts_style": None,
            "tts_style_degree": None,
        },
        openai_api_key="",
        openrouter_api_key="secret",
    )
    assert provider.cache_key != default_provider.cache_key

    with pytest.raises(ValueError, match="instrucciones"):
        resolve_tts_config(
            {
                "tts_provider": "openrouter",
                "tts_model": "hexgrad/kokoro-82m",
                "tts_language": "es-ES",
                "tts_voice": "ef_dora",
                "tts_instructions": "Habla con alegría",
            }
        )


def test_gemini_capabilities_request_pcm_and_normalize_to_playable_wav(
    monkeypatch, tmp_path
):
    calls = []
    pcm = b"\x00\x00\x10\x00" * 2400

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return _response(
            200,
            content=pcm,
            headers={
                "content-type": "audio/pcm",
                "x-generation-id": "gen-gemini",
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    resolved = resolve_tts_config(
        {
            "tts_provider": "openrouter",
            "tts_model": "google/gemini-3.1-flash-tts-preview",
            "tts_language": "es-ES",
            "tts_voice": "Kore",
            "tts_format": "mp3",
        }
    )
    assert resolved["tts_format"] == "pcm"
    assert resolved["tts_output_format"] == "wav"
    assert resolved["tts_mime_type"] == "audio/wav"
    assert resolved["tts_sample_rate_hz"] == 24000
    assert resolved["tts_channels"] == 1

    provider = build_tts_provider(
        resolved,
        openai_api_key="",
        openrouter_api_key="secret",
    )
    path, cache_hit = synthesize_cached_with_status(provider, "Hola", tmp_path)
    assert cache_hit is False
    assert path.suffix == ".wav"
    assert calls[0][1]["json"]["response_format"] == "pcm"
    assert calls[0][1]["json"] == {
        "model": "google/gemini-3.1-flash-tts-preview",
        "input": "Hola",
        "voice": "Kore",
        "response_format": "pcm",
    }
    with wave.open(io.BytesIO(path.read_bytes()), "rb") as audio:
        assert audio.getframerate() == 24000
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getnframes() > 0
    assert probe_duration(path) == pytest.approx(0.2, abs=0.01)
    second, second_hit = synthesize_cached_with_status(provider, "Hola", tmp_path)
    assert second == path
    assert second_hit is True
    assert provider.last_generation_id == "gen-gemini"
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("content", "content_type", "message"),
    [
        (b"not-mp3", "audio/mpeg", "corrupto"),
        (b"ID3audio", "application/json", "application/json"),
    ],
)
def test_openrouter_tts_rejects_corrupt_or_mislabeled_audio(
    monkeypatch, content, content_type, message
):
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: _response(
            200,
            content=content,
            headers={"content-type": content_type},
        ),
    )
    provider = OpenRouterTTSProvider(
        "secret",
        model="hexgrad/kokoro-82m",
        voice="ef_dora",
    )
    with pytest.raises(TTSError, match=message):
        provider.synthesize("Hola")


def test_openrouter_tts_does_not_retry_deterministic_400(monkeypatch):
    calls = 0

    def fake_post(*args, **kwargs):
        nonlocal calls
        calls += 1
        return _response(
            400,
            json_body={
                "error": {
                    "message": "response_format no admitido",
                    "code": "invalid_request",
                    "param": "response_format",
                }
            },
            headers={"x-generation-id": "gen-error"},
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = OpenRouterTTSProvider(
        "secret",
        model="google/gemini-3.1-flash-tts-preview",
        voice="Kore",
        request_format="pcm",
        response_mime_type="audio/pcm",
        output_format="wav",
        output_mime_type="audio/wav",
        sample_rate_hz=24000,
        channels=1,
    )
    with pytest.raises(TTSError, match="response_format.*invalid_request") as exc_info:
        provider.synthesize("Hola")
    assert calls == 1
    assert exc_info.value.status_code == 400
    assert exc_info.value.field == "response_format"
    assert exc_info.value.generation_id == "gen-error"


def test_corrupt_cached_audio_is_not_reused(monkeypatch, tmp_path):
    calls = 0

    def fake_post(*args, **kwargs):
        nonlocal calls
        calls += 1
        return _response(
            200,
            content=b"ID3valid",
            headers={"content-type": "audio/mpeg"},
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = OpenRouterTTSProvider(
        "secret",
        model="hexgrad/kokoro-82m",
        voice="ef_dora",
    )
    path, first_hit = synthesize_cached_with_status(provider, "Hola", tmp_path)
    assert first_hit is False
    path.write_bytes(b"")
    repaired, repaired_hit = synthesize_cached_with_status(provider, "Hola", tmp_path)
    assert repaired == path
    assert repaired_hit is False
    assert repaired.read_bytes() == b"ID3valid"
    assert calls == 2
