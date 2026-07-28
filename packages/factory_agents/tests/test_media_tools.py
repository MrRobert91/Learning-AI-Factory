import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from factory_agents.agents.voice import run_voice
from factory_agents.contracts import VoiceScript
from factory_agents.tools.tts import synthesize_cached
from factory_agents.tools.video import (
    _concat_file_entry,
    _format_srt_time,
    _run,
    build_srt,
    burn_subtitles,
    compose_video,
    concat_course_videos,
    ffmpeg_available,
    probe_media,
    render_slide_images,
)


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        result = self._responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        message = SimpleNamespace(content=result, tool_calls=None)
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


def test_voice_adapter_retries_malformed_provider_response():
    error = json.JSONDecodeError("Expecting value", "", 0)
    client = FakeClient([error, VALID_VOICE])

    result = run_voice("guion", client=client, model="m")

    assert isinstance(result, VoiceScript)
    assert len(client.requests) == 2
    assert client.requests[0]["messages"] == client.requests[1]["messages"]


def test_voice_adapter_reports_repeated_malformed_provider_responses():
    errors = [json.JSONDecodeError("Expecting value", "", 0) for _ in range(3)]
    client = FakeClient(errors)

    with pytest.raises(RuntimeError, match="respuesta válida del proveedor"):
        run_voice("guion", client=client, model="m")

    assert len(client.requests) == 3


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


def test_concat_file_entry_escapes_single_quotes():
    path = Path(
        "/tmp/La metáfora del océano: entendiendo "
        "'sustancia' y 'modos/segment-000.mp4"
    )

    entry = _concat_file_entry(path)

    assert entry == (
        "file '/tmp/La metáfora del océano: entendiendo "
        "'\\''sustancia'\\'' y '\\''modos/segment-000.mp4'\n"
    )


@pytest.mark.parametrize(
    ("transition", "expected_filters"),
    [
        ("fade_500ms", ("xfade=transition=fade", "acrossfade=d=0.5")),
        ("gap_500ms", ("color=c=black", "anullsrc", "cl=mono", "concat=n=3")),
    ],
)
def test_course_video_transitions_build_controlled_filter_graphs(
    monkeypatch, tmp_path, transition, expected_filters
):
    commands = []
    monkeypatch.setattr("factory_agents.tools.video.ffmpeg_available", lambda: True)
    monkeypatch.setattr(
        "factory_agents.tools.video.probe_media",
        lambda _path: {
            "width": 1920,
            "height": 1080,
            "frame_rate": "30/1",
            "audio_sample_rate": 44100,
            "audio_channels": 1,
            "audio_channel_layout": "mono",
        },
    )

    def fake_run(command, timeout=600):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("factory_agents.tools.video._run", fake_run)
    concat_course_videos(
        [tmp_path / "one.mp4", tmp_path / "two.mp4"],
        tmp_path / "course.mp4",
        tmp_path / "work",
        transition=transition,
        durations=[2.0, 3.0],
    )
    filter_graph = commands[0][commands[0].index("-filter_complex") + 1]
    assert all(value in filter_graph for value in expected_filters)


def test_course_video_without_transition_prefers_stream_copy_and_chapters(
    monkeypatch, tmp_path
):
    commands = []
    monkeypatch.setattr("factory_agents.tools.video.ffmpeg_available", lambda: True)

    def fake_run(command, timeout=600):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("factory_agents.tools.video._run", fake_run)
    concat_course_videos(
        [tmp_path / "one.mp4", tmp_path / "two.mp4"],
        tmp_path / "course.mp4",
        tmp_path / "work",
        chapters=[
            {
                "title": "1.1 Inicio",
                "start_seconds": 0,
                "end_seconds": 2,
            },
            {
                "title": "1.2 Final",
                "start_seconds": 2,
                "end_seconds": 5,
            },
        ],
    )
    command = commands[0]
    assert command[command.index("-c") + 1] == "copy"
    assert "-map_chapters" in command
    assert (tmp_path / "work" / "chapters.ffmeta").is_file()


@pytest.mark.parametrize(
    ("size", "transition", "expected_duration"),
    [
        ("320x180", "none", 1.2),
        ("180x320", "none", 1.2),
        ("320x180", "gap_500ms", 1.7),
        ("320x180", "fade_500ms", 0.7),
    ],
)
def test_real_course_video_concat_for_orientations_and_transitions(
    tmp_path, size, transition, expected_duration
):
    if not ffmpeg_available():
        pytest.skip("ffmpeg/ffprobe no están disponibles")
    inputs = []
    for index in range(2):
        path = tmp_path / f"lesson-{index}.mp4"
        _run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={'blue' if index == 0 else 'green'}:s={size}:r=25:d=0.6",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=44100:duration=0.6",
                "-shortest",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(path),
            ],
            timeout=60,
        )
        inputs.append(path)
    output = concat_course_videos(
        inputs,
        tmp_path / "course.mp4",
        tmp_path / "work-real",
        transition=transition,
        durations=[0.6, 0.6],
        chapters=[
            {
                "title": "1.1",
                "start_seconds": 0,
                "end_seconds": expected_duration - 0.6,
            },
            {
                "title": "1.2",
                "start_seconds": expected_duration - 0.6,
                "end_seconds": expected_duration,
            },
        ],
    )
    media = probe_media(output)
    width, height = (int(value) for value in size.split("x"))
    assert media["width"] == width
    assert media["height"] == height
    assert media["video_codec"] == "h264"
    assert media["audio_codec"] == "aac"
    assert media["duration_seconds"] == pytest.approx(expected_duration, abs=0.2)


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


def test_burned_subtitles_raise_safe_area_for_bottom_logo(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr("factory_agents.tools.video.ffmpeg_available", lambda: True)

    def fake_run(command, timeout=600):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("factory_agents.tools.video._run", fake_run)
    output, style = burn_subtitles(
        tmp_path / "video.mp4",
        tmp_path / "lesson.srt",
        tmp_path / "burned.mp4",
        orientation="vertical",
        logo_metadata={
            "placement": "bottom-right",
            "size": "large",
            "margin_px": 40,
        },
    )
    assert output == tmp_path / "burned.mp4"
    assert style["font_size"] == 22
    assert style["margin_v"] == 370
    subtitle_filter = commands[0][commands[0].index("-vf") + 1]
    assert "Outline=3" in subtitle_filter
    assert "MarginV=370" in subtitle_filter


def test_video_render_upgrades_legacy_vertical_canvas(monkeypatch, tmp_path):
    deck = tmp_path / "vertical.md"
    legacy = "---\nmarp: true\nsize: 1080px 1920px\n---\n\n# Vertical\n"
    deck.write_text(legacy, encoding="utf-8")
    rendered_sources = []
    commands = []

    monkeypatch.setattr("factory_agents.tools.video.shutil.which", lambda _name: "marp")

    def fake_run(command, timeout=600):
        commands.append(command)
        rendered_sources.append(Path(command[1]).read_text(encoding="utf-8"))
        output = Path(command[command.index("-o") + 1])
        output.with_name("slide.001.png").write_bytes(b"png")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("factory_agents.tools.video._run", fake_run)
    images = render_slide_images(deck, tmp_path / "slides")

    assert len(images) == 1
    assert "theme: factory-vertical" in rendered_sources[0]
    assert "size: 9:16" in rendered_sources[0]
    assert "--theme-set" in commands[0]
    assert deck.read_text(encoding="utf-8") == legacy
