import json
from types import SimpleNamespace

import pytest
from factory_agents.agents.voice import run_voice
from factory_agents.contracts import VoiceScript
from factory_agents.tools.tts import synthesize_cached
from factory_agents.tools.video import _format_srt_time, build_srt, compose_video


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        message = SimpleNamespace(content=self._responses.pop(0), tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


VALID_VOICE = json.dumps(
    {
        "lesson_title": "1.1 Qué es un LLM",
        "language": "es",
        "segments": [
            {"slide": 1, "text": "Bienvenidos a la lección."},
            {"slide": 2, "text": "Un modelo de lenguaje predice el siguiente token."},
        ],
    }
)


def test_voice_adapter_parses_and_validates():
    client = FakeClient([VALID_VOICE])
    result = run_voice("guion", client=client, model="m")
    assert isinstance(result, VoiceScript)
    assert len(result.segments) == 2
    assert result.segments[0].slide == 1


def test_voice_adapter_retries_then_fails():
    client = FakeClient(["no json", "tampoco", "nada"])
    with pytest.raises(RuntimeError, match="voz"):
        run_voice("guion", client=client, model="m")


class CountingProvider:
    cache_key = "fake:v1"

    def __init__(self):
        self.calls = 0

    def synthesize(self, text: str) -> bytes:
        self.calls += 1
        return f"AUDIO:{text}".encode()


def test_tts_cache_avoids_resynthesis(tmp_path):
    provider = CountingProvider()
    p1 = synthesize_cached(provider, "hola mundo", tmp_path)
    p2 = synthesize_cached(provider, "hola mundo", tmp_path)
    p3 = synthesize_cached(provider, "otro texto", tmp_path)
    assert provider.calls == 2
    assert p1 == p2 != p3
    assert p1.read_bytes() == b"AUDIO:hola mundo"


def test_tts_cache_varies_by_provider_config(tmp_path):
    a = CountingProvider()
    b = CountingProvider()
    b.cache_key = "fake:v2"
    p1 = synthesize_cached(a, "hola", tmp_path)
    p2 = synthesize_cached(b, "hola", tmp_path)
    assert p1 != p2


def test_srt_time_format():
    assert _format_srt_time(0) == "00:00:00,000"
    assert _format_srt_time(3661.5) == "01:01:01,500"


def test_build_srt_accumulates_timings():
    srt = build_srt([("Primera frase.", 2.0), ("Segunda frase.", 3.5)])
    assert "1\n00:00:00,000 --> 00:00:02,000\nPrimera frase." in srt
    assert "2\n00:00:02,000 --> 00:00:05,500\nSegunda frase." in srt


def test_vertical_video_uses_blurred_background_without_cropping_foreground(
    monkeypatch, tmp_path
):
    commands = []
    monkeypatch.setattr("factory_agents.tools.video.ffmpeg_available", lambda: True)

    def fake_run(command, timeout=600):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("factory_agents.tools.video._run", fake_run)
    compose_video(
        [(tmp_path / "slide.png", tmp_path / "audio.mp3")],
        tmp_path / "video.mp4",
        tmp_path / "segments",
        orientation="vertical",
    )
    filter_graph = commands[0][commands[0].index("-filter_complex") + 1]
    assert "scale=1080:1920:force_original_aspect_ratio=increase" in filter_graph
    assert "scale=1080:1920:force_original_aspect_ratio=decrease" in filter_graph
    assert "boxblur" in filter_graph
    assert "overlay=(W-w)/2:(H-h)/2" in filter_graph
