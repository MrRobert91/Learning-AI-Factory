import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from factory_agents.agents.voice import run_voice
from factory_agents.contracts import VoiceScript
from factory_agents.tools import video as video_tools
from factory_agents.tools.tts import synthesize_cached
from factory_agents.tools.video import (
    FFmpegPolicy,
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
        Path(command[-1]).write_bytes(b"video")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("factory_agents.tools.video._run", fake_run)
    monkeypatch.setattr(
        "factory_agents.tools.video._validated_video",
        lambda _path, **_kwargs: {"video_codec": "h264", "audio_codec": "aac"},
    )
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
        Path(command[-1]).write_bytes(b"video")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("factory_agents.tools.video._run", fake_run)
    monkeypatch.setattr(
        "factory_agents.tools.video._validated_video",
        lambda _path, **_kwargs: {"video_codec": "h264", "audio_codec": "aac"},
    )
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
    image = tmp_path / "slide.png"
    audio = tmp_path / "audio.mp3"
    image.write_bytes(b"slide")
    audio.write_bytes(b"audio")

    def fake_probe_image(path):
        return (1920, 1080) if Path(path) == image else (1080, 1920)

    def fake_run(command, timeout=600):
        commands.append(command)
        Path(command[-1]).write_bytes(b"media")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("factory_agents.tools.video._run", fake_run)
    monkeypatch.setattr("factory_agents.tools.video.probe_image_size", fake_probe_image)
    monkeypatch.setattr(
        "factory_agents.tools.video._validated_video",
        lambda _path, **_kwargs: {
            "video_codec": "h264",
            "audio_codec": "aac",
            "width": 1080,
            "height": 1920,
        },
    )
    compose_video(
        [(image, audio)],
        tmp_path / "video.mp4",
        tmp_path / "segments",
        orientation="vertical",
    )
    filter_graph = commands[0][commands[0].index("-filter_complex") + 1]
    assert "scale=1080:1920:force_original_aspect_ratio=increase" in filter_graph
    assert "scale=1080:1920:force_original_aspect_ratio=decrease" in filter_graph
    assert "boxblur" in filter_graph
    assert "overlay=(W-w)/2:(H-h)/2" in filter_graph
    segment_command = next(command for command in commands if "-loop" in command)
    assert "-filter_complex" not in segment_command
    assert all("boxblur" not in value for value in segment_command)


def test_ffmpeg_policy_defaults_overrides_and_validation():
    assert FFmpegPolicy() == FFmpegPolicy(
        threads=1,
        filter_threads=1,
        filter_complex_threads=1,
        preset="veryfast",
        crf=23,
    )
    assert FFmpegPolicy.from_mapping(
        {
            "threads": 2,
            "filter_threads": 3,
            "filter_complex_threads": 4,
            "preset": "fast",
            "crf": 18,
        }
    ).threads == 2
    with pytest.raises(ValueError, match="entero positivo"):
        FFmpegPolicy(threads=0)
    with pytest.raises(ValueError, match="entre 0 y 51"):
        FFmpegPolicy(crf=52)
    with pytest.raises(ValueError, match="preset"):
        FFmpegPolicy(preset="turbo")


def test_reencoding_commands_receive_policy_but_stream_copy_does_not(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr("factory_agents.tools.video.ffmpeg_available", lambda: True)
    monkeypatch.setattr(
        "factory_agents.tools.video._validated_video",
        lambda _path, **_kwargs: {"video_codec": "h264", "audio_codec": "aac"},
    )

    def fake_run(command, timeout=600):
        commands.append(command)
        Path(command[-1]).write_bytes(b"video")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("factory_agents.tools.video._run", fake_run)
    policy = FFmpegPolicy(
        threads=2,
        filter_threads=3,
        filter_complex_threads=4,
        preset="fast",
        crf=19,
    )
    concat_course_videos(
        [tmp_path / "one.mp4", tmp_path / "two.mp4"],
        tmp_path / "reencoded.mp4",
        tmp_path / "reencoded-work",
        transition="fade_500ms",
        durations=[2.0, 3.0],
        policy=policy,
    )
    reencode = commands[-1]
    for option, value in (
        ("-threads", "2"),
        ("-filter_threads", "3"),
        ("-filter_complex_threads", "4"),
        ("-preset", "fast"),
        ("-crf", "19"),
    ):
        assert reencode[reencode.index(option) + 1] == value

    commands.clear()
    concat_course_videos(
        [tmp_path / "one.mp4", tmp_path / "two.mp4"],
        tmp_path / "copied.mp4",
        tmp_path / "copied-work",
        policy=policy,
    )
    stream_copy = commands[-1]
    assert stream_copy[stream_copy.index("-c") + 1] == "copy"
    assert "-threads" not in stream_copy
    assert "-preset" not in stream_copy
    assert "-crf" not in stream_copy


def test_matching_canvas_skips_blur_and_segment_cache_is_reused(monkeypatch, tmp_path):
    commands = []
    completed = []
    image = tmp_path / "slide.png"
    audio = tmp_path / "audio.wav"
    image.write_bytes(b"slide")
    audio.write_bytes(b"audio")
    monkeypatch.setattr("factory_agents.tools.video.ffmpeg_available", lambda: True)
    monkeypatch.setattr(
        "factory_agents.tools.video.probe_image_size",
        lambda _path: (1920, 1080),
    )
    monkeypatch.setattr(
        "factory_agents.tools.video._validated_video",
        lambda _path, **_kwargs: {
            "video_codec": "h264",
            "audio_codec": "aac",
            "width": 1920,
            "height": 1080,
        },
    )

    def fake_run(command, timeout=600):
        commands.append(command)
        Path(command[-1]).write_bytes(b"video")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("factory_agents.tools.video._run", fake_run)
    kwargs = {
        "pairs": [(image, audio)],
        "out_path": tmp_path / "lesson.mp4",
        "workdir": tmp_path / "segments",
        "on_segment_complete": lambda index, evidence: completed.append((index, evidence)),
    }
    compose_video(**kwargs)
    compose_video(**kwargs)

    segment_commands = [command for command in commands if "-loop" in command]
    assert len(segment_commands) == 1
    assert all("boxblur" not in value for command in commands for value in command)
    assert completed[0][1]["reused"] is False
    assert completed[1][1]["reused"] is True
    manifest = json.loads((tmp_path / "segments" / "segment-000.json").read_text())
    assert manifest["signature_inputs"]["width"] == 1920
    assert manifest["signature_inputs"]["ffmpeg_policy"]["threads"] == 1

    compose_video(**kwargs, policy=FFmpegPolicy(threads=2))
    assert len([command for command in commands if "-loop" in command]) == 2
    audio.write_bytes(b"changed-audio")
    compose_video(**kwargs, policy=FFmpegPolicy(threads=2))
    assert len([command for command in commands if "-loop" in command]) == 3


def test_corrupt_cached_segment_is_regenerated_in_isolation(monkeypatch, tmp_path):
    commands = []
    image = tmp_path / "slide.png"
    audio = tmp_path / "audio.wav"
    image.write_bytes(b"slide")
    audio.write_bytes(b"audio")
    monkeypatch.setattr("factory_agents.tools.video.ffmpeg_available", lambda: True)
    monkeypatch.setattr(
        "factory_agents.tools.video.probe_image_size",
        lambda _path: (1920, 1080),
    )
    monkeypatch.setattr(
        "factory_agents.tools.video._validated_video",
        lambda _path, **_kwargs: {
            "video_codec": "h264",
            "audio_codec": "aac",
            "width": 1920,
            "height": 1080,
        },
    )

    def fake_run(command, timeout=600):
        commands.append(command)
        Path(command[-1]).write_bytes(b"video")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("factory_agents.tools.video._run", fake_run)
    workdir = tmp_path / "segments"
    compose_video([(image, audio)], tmp_path / "lesson.mp4", workdir)
    (workdir / "segment-000.mp4").write_bytes(b"corrupt")
    compose_video([(image, audio)], tmp_path / "lesson.mp4", workdir)
    assert len([command for command in commands if "-loop" in command]) == 2


def test_pause_after_segment_keeps_atomic_cache_and_resumes(monkeypatch, tmp_path):
    image = tmp_path / "slide.png"
    audio = tmp_path / "audio.wav"
    image.write_bytes(b"slide")
    audio.write_bytes(b"audio")
    monkeypatch.setattr("factory_agents.tools.video.ffmpeg_available", lambda: True)
    monkeypatch.setattr(
        "factory_agents.tools.video.probe_image_size",
        lambda _path: (1920, 1080),
    )
    monkeypatch.setattr(
        "factory_agents.tools.video._validated_video",
        lambda _path, **_kwargs: {
            "video_codec": "h264",
            "audio_codec": "aac",
            "width": 1920,
            "height": 1080,
        },
    )
    commands = []

    def fake_run(command, timeout=600):
        commands.append(command)
        Path(command[-1]).write_bytes(b"video")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("factory_agents.tools.video._run", fake_run)
    workdir = tmp_path / "segments"

    def pause_after_first(_index, _evidence):
        raise RuntimeError("paused")

    with pytest.raises(RuntimeError, match="paused"):
        compose_video(
            [(image, audio)],
            tmp_path / "lesson.mp4",
            workdir,
            on_segment_complete=pause_after_first,
        )
    assert (workdir / "segment-000.mp4").is_file()
    assert (workdir / "segment-000.json").is_file()
    assert not (tmp_path / "lesson.mp4").exists()
    assert not list(workdir.glob("*.tmp.mp4"))

    completed = []
    compose_video(
        [(image, audio)],
        tmp_path / "lesson.mp4",
        workdir,
        on_segment_complete=lambda index, evidence: completed.append((index, evidence)),
    )
    assert completed[0][1]["reused"] is True
    assert len([command for command in commands if "-loop" in command]) == 1


def test_real_multisegment_compose_reuses_valid_segments(monkeypatch, tmp_path):
    if not ffmpeg_available():
        pytest.skip("ffmpeg/ffprobe no están disponibles")
    monkeypatch.setitem(video_tools.VIDEO_SIZES, "horizontal", (320, 180))
    images = []
    audios = []
    for index, size in enumerate(("320x180", "180x320")):
        image = tmp_path / f"slide-{index}.png"
        audio = tmp_path / f"audio-{index}.wav"
        _run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={'blue' if index == 0 else 'green'}:s={size}",
                "-frames:v",
                "1",
                str(image),
            ],
            timeout=60,
        )
        _run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={440 + index * 100}:sample_rate=44100:duration=0.4",
                str(audio),
            ],
            timeout=60,
        )
        images.append(image)
        audios.append(audio)

    completed = []
    pairs = list(zip(images, audios, strict=True))
    workdir = tmp_path / "segments"
    output = compose_video(
        pairs,
        tmp_path / "lesson.mp4",
        workdir,
        on_segment_complete=lambda index, evidence: completed.append((index, evidence)),
    )
    media = probe_media(output)
    assert (media["width"], media["height"]) == (320, 180)
    assert media["video_codec"] == "h264"
    assert media["audio_codec"] == "aac"
    assert media["frame_rate"] == "25/1"
    assert all(evidence["reused"] is False for _index, evidence in completed)
    assert json.loads((workdir / "segment-000.json").read_text())["composition"] == "direct"
    assert (
        json.loads((workdir / "segment-001.json").read_text())["composition"]
        == "precomposed"
    )

    completed.clear()
    compose_video(
        pairs,
        tmp_path / "lesson.mp4",
        workdir,
        on_segment_complete=lambda index, evidence: completed.append((index, evidence)),
    )
    assert len(completed) == 2
    assert all(evidence["reused"] is True for _index, evidence in completed)


def test_control_check_terminates_active_process_group():
    started = time.monotonic()

    def stop() -> None:
        raise RuntimeError("stop requested")

    with pytest.raises(RuntimeError, match="stop requested"):
        _run(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=30,
            control_check=stop,
        )
    assert time.monotonic() - started < 10


def test_burned_subtitles_raise_safe_area_for_bottom_logo(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr("factory_agents.tools.video.ffmpeg_available", lambda: True)

    def fake_run(command, timeout=600):
        commands.append(command)
        Path(command[-1]).write_bytes(b"video")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("factory_agents.tools.video._run", fake_run)
    monkeypatch.setattr(
        "factory_agents.tools.video._validated_video",
        lambda _path, **_kwargs: {"video_codec": "h264", "audio_codec": "aac"},
    )
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
