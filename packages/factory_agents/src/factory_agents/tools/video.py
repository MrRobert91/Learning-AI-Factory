"""Video production: slide images + narration segments → MP4 (+ SRT).

Static-slide composition: each slide PNG is shown for the duration of its
narration segment; segments are encoded individually and concatenated.
"""

import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from factory_agents.tools.marp import prepared_marp_source, vertical_theme_path

FFMPEG_TIMEOUT = 600
FFMPEG_POLL_SECONDS = 0.25
FFMPEG_TERMINATE_TIMEOUT = 5.0
VIDEO_SIZES = {
    "horizontal": (1920, 1080),
    "vertical": (1080, 1920),
}
X264_PRESETS = {
    "ultrafast",
    "superfast",
    "veryfast",
    "faster",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
}


class VideoToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class FFmpegPolicy:
    threads: int = 1
    filter_threads: int = 1
    filter_complex_threads: int = 1
    preset: str = "veryfast"
    crf: int = 23

    def __post_init__(self) -> None:
        for name in ("threads", "filter_threads", "filter_complex_threads"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} debe ser un entero positivo")
        if self.preset not in X264_PRESETS:
            raise ValueError(f"preset x264 no admitido: {self.preset}")
        if isinstance(self.crf, bool) or not isinstance(self.crf, int) or not 0 <= self.crf <= 51:
            raise ValueError("crf debe estar entre 0 y 51")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object] | None = None) -> "FFmpegPolicy":
        return cls(**dict(value or {}))

    def as_dict(self) -> dict:
        return asdict(self)


def _terminate_process_group(
    process: subprocess.Popen,
    *,
    grace_seconds: float = FFMPEG_TERMINATE_TIMEOUT,
) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGTERM)
    except (AttributeError, OSError, ProcessLookupError):
        process.terminate()
    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=grace_seconds,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError, subprocess.SubprocessError):
        process.kill()
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        process.kill()


def _run(
    cmd: list[str],
    timeout: int | float = FFMPEG_TIMEOUT,
    *,
    control_check: Callable[[], None] | None = None,
) -> subprocess.CompletedProcess:
    process_kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
    }
    if os.name == "nt":
        process_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        process_kwargs["start_new_session"] = True
    process = subprocess.Popen(cmd, **process_kwargs)
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _terminate_process_group(process)
            raise VideoToolError(f"{cmd[0]} excedió el timeout de {timeout:g} segundos")
        try:
            stdout, stderr = process.communicate(timeout=min(FFMPEG_POLL_SECONDS, remaining))
            break
        except subprocess.TimeoutExpired:
            if control_check is None:
                continue
            try:
                control_check()
            except BaseException:
                _terminate_process_group(process)
                raise
    result = subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
    if result.returncode != 0:
        raise VideoToolError(f"{cmd[0]} falló ({result.returncode}): {result.stderr[-800:]}")
    return result


def _run_with_control(
    cmd: list[str],
    *,
    timeout: int | float = FFMPEG_TIMEOUT,
    control_check: Callable[[], None] | None = None,
) -> subprocess.CompletedProcess:
    if control_check is None:
        return _run(cmd, timeout=timeout)
    return _run(cmd, timeout=timeout, control_check=control_check)


def _policy(value: FFmpegPolicy | Mapping[str, object] | None) -> FFmpegPolicy:
    if isinstance(value, FFmpegPolicy):
        return value
    return FFmpegPolicy.from_mapping(value)


def _filtered_ffmpeg_command(policy: FFmpegPolicy) -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-filter_threads",
        str(policy.filter_threads),
        "-filter_complex_threads",
        str(policy.filter_complex_threads),
    ]


def _x264_args(policy: FFmpegPolicy) -> list[str]:
    return [
        "-c:v",
        "libx264",
        "-threads",
        str(policy.threads),
        "-preset",
        policy.preset,
        "-crf",
        str(policy.crf),
    ]


def _temporary_media_path(path: Path) -> Path:
    return path.with_name(f".{path.stem}-{uuid.uuid4().hex}.tmp{path.suffix}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}-{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def render_slide_images(deck_md_path: str | Path, out_dir: str | Path) -> list[Path]:
    """Render every slide of a Marp deck to PNG. Returns paths in slide order."""
    if shutil.which("marp") is None:
        raise VideoToolError("marp-cli no está instalado (necesario para renderizar slides)")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "slide.png"
    with prepared_marp_source(deck_md_path) as source:
        _run(
            [
                "marp",
                str(source),
                "--images",
                "png",
                "--image-scale",
                "2",
                "--theme-set",
                str(vertical_theme_path()),
                "--allow-local-files",
                "-o",
                str(target),
            ]
        )
    images = sorted(out_dir.glob("slide.*.png"))
    if not images:
        raise VideoToolError("marp no produjo imágenes de slides")
    return images


def probe_duration(media_path: str | Path) -> float:
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media_path),
        ],
        timeout=60,
    )
    return float(result.stdout.strip())


def probe_media(media_path: str | Path) -> dict:
    """Return the normalized audio/video properties required for safe concatenation."""
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(media_path),
        ],
        timeout=60,
    )
    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if video is None or audio is None:
        raise VideoToolError("el fichero debe contener una pista de vídeo y una de audio")
    try:
        duration = float(payload.get("format", {}).get("duration"))
    except (TypeError, ValueError) as exc:
        raise VideoToolError("ffprobe no devolvió una duración válida") from exc
    if duration <= 0:
        raise VideoToolError("la duración debe ser mayor que cero")
    return {
        "duration_seconds": duration,
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "video_codec": str(video.get("codec_name") or ""),
        "audio_codec": str(audio.get("codec_name") or ""),
        "frame_rate": str(video.get("avg_frame_rate") or video.get("r_frame_rate") or ""),
        "time_base": str(video.get("time_base") or ""),
        "audio_sample_rate": int(audio.get("sample_rate") or 0),
        "audio_channels": int(audio.get("channels") or 0),
        "audio_channel_layout": str(audio.get("channel_layout") or ""),
    }


def probe_image_size(image_path: str | Path) -> tuple[int, int]:
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(image_path),
        ],
        timeout=60,
    )
    try:
        stream = json.loads(result.stdout)["streams"][0]
        width = int(stream["width"])
        height = int(stream["height"])
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise VideoToolError("ffprobe no devolvió dimensiones de imagen válidas") from exc
    if width <= 0 or height <= 0:
        raise VideoToolError("las dimensiones de la imagen deben ser positivas")
    return width, height


def _validated_video(path: Path, *, width: int | None = None, height: int | None = None) -> dict:
    media = probe_media(path)
    if media["video_codec"] != "h264" or media["audio_codec"] != "aac":
        raise VideoToolError("el vídeo debe contener H.264 y AAC")
    if width is not None and media["width"] != width:
        raise VideoToolError(f"ancho inesperado: {media['width']} (esperado {width})")
    if height is not None and media["height"] != height:
        raise VideoToolError(f"alto inesperado: {media['height']} (esperado {height})")
    return media


def _concat_file_entry(path: Path) -> str:
    """Return one ffmpeg concat-demuxer file entry for a possibly quoted path."""
    escaped = path.as_posix().replace("'", "'\\''")
    return f"file '{escaped}'\n"


def _ffmetadata_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("=", "\\=")
        .replace(";", "\\;")
        .replace("#", "\\#")
        .replace("\n", " ")
    )


def write_chapter_metadata(chapters: list[dict], path: str | Path) -> Path:
    """Write non-overlapping lesson chapters as ffmetadata."""
    lines = [";FFMETADATA1"]
    for chapter in chapters:
        start_ms = max(0, int(round(float(chapter["start_seconds"]) * 1000)))
        end_ms = max(start_ms + 1, int(round(float(chapter["end_seconds"]) * 1000)))
        lines.extend(
            [
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={start_ms}",
                f"END={end_ms}",
                f"title={_ffmetadata_escape(str(chapter['title']))}",
            ]
        )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def concat_course_videos(
    inputs: list[str | Path],
    out_path: str | Path,
    workdir: str | Path,
    *,
    transition: str = "none",
    durations: list[float] | None = None,
    chapters: list[dict] | None = None,
    policy: FFmpegPolicy | Mapping[str, object] | None = None,
    control_check: Callable[[], None] | None = None,
) -> Path:
    """Concatenate compatible lesson videos and optionally apply a 500 ms transition."""
    if not ffmpeg_available():
        raise VideoToolError("ffmpeg/ffprobe no están instalados")
    paths = [Path(value) for value in inputs]
    if not paths:
        raise VideoToolError("no hay vídeos para concatenar")
    if transition not in {"none", "fade_500ms", "gap_500ms"}:
        raise VideoToolError(f"Transición desconocida: {transition}")
    if transition != "none" and (durations is None or len(durations) != len(paths)):
        raise VideoToolError("las transiciones requieren la duración de cada vídeo")
    if len(paths) == 1:
        transition = "none"

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    effective_policy = _policy(policy)
    temporary_output = _temporary_media_path(out_path)
    metadata_path = (
        write_chapter_metadata(chapters, workdir / "chapters.ffmeta") if chapters else None
    )

    try:
        if transition == "none":
            concat_list = workdir / "course-concat.txt"
            concat_list.write_text(
                "".join(_concat_file_entry(path.resolve()) for path in paths),
                encoding="utf-8",
            )
            cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
            ]
            if metadata_path:
                cmd.extend(["-i", str(metadata_path), "-map_metadata", "1", "-map_chapters", "1"])
            cmd.extend(["-c", "copy", "-movflags", "+faststart", str(temporary_output)])
            _run_with_control(cmd, control_check=control_check)
            _validated_video(temporary_output)
            temporary_output.replace(out_path)
            return out_path

        cmd = _filtered_ffmpeg_command(effective_policy)
        for path in paths:
            cmd.extend(["-i", str(path)])
        if metadata_path:
            cmd.extend(["-i", str(metadata_path)])

        if transition == "fade_500ms":
            filters: list[str] = []
            video_label = "0:v:0"
            audio_label = "0:a:0"
            timeline_duration = float(durations[0])
            for index in range(1, len(paths)):
                next_video = f"vfade{index}"
                next_audio = f"afade{index}"
                offset = max(0.0, timeline_duration - 0.5)
                filters.append(
                    f"[{video_label}][{index}:v:0]xfade=transition=fade:"
                    f"duration=0.5:offset={offset:.3f}[{next_video}]"
                )
                filters.append(
                    f"[{audio_label}][{index}:a:0]acrossfade=d=0.5:"
                    f"c1=tri:c2=tri[{next_audio}]"
                )
                video_label = next_video
                audio_label = next_audio
                timeline_duration += float(durations[index]) - 0.5
            filter_graph = ";".join(filters)
        else:
            filters = []
            concat_inputs: list[str] = []
            for index, path in enumerate(paths):
                concat_inputs.extend([f"[{index}:v:0]", f"[{index}:a:0]"])
                if index >= len(paths) - 1:
                    continue
                media = probe_media(path)
                gap_video = f"gapv{index}"
                gap_audio = f"gapa{index}"
                rate = media["frame_rate"] or "30"
                channel_layout = media.get("audio_channel_layout") or (
                    "mono" if media["audio_channels"] == 1 else "stereo"
                )
                filters.append(
                    f"color=c=black:s={media['width']}x{media['height']}:"
                    f"r={rate}:d=0.5[{gap_video}]"
                )
                filters.append(
                    f"anullsrc=r={media['audio_sample_rate'] or 44100}:"
                    f"cl={channel_layout}:d=0.5[{gap_audio}]"
                )
                concat_inputs.extend([f"[{gap_video}]", f"[{gap_audio}]"])
            segment_count = len(paths) * 2 - 1
            filters.append(
                "".join(concat_inputs) + f"concat=n={segment_count}:v=1:a=1[vout][aout]"
            )
            filter_graph = ";".join(filters)
            video_label = "vout"
            audio_label = "aout"

        cmd.extend(
            [
                "-filter_complex",
                filter_graph,
                "-map",
                f"[{video_label}]",
                "-map",
                f"[{audio_label}]",
            ]
        )
        if metadata_path:
            metadata_index = len(paths)
            cmd.extend(
                [
                    "-map_metadata",
                    str(metadata_index),
                    "-map_chapters",
                    str(metadata_index),
                ]
            )
        cmd.extend(_x264_args(effective_policy))
        cmd.extend(
            [
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(temporary_output),
            ]
        )
        timeout = max(FFMPEG_TIMEOUT, int(sum(durations or []) * 2))
        _run_with_control(cmd, timeout=timeout, control_check=control_check)
        _validated_video(temporary_output)
        temporary_output.replace(out_path)
        return out_path
    finally:
        temporary_output.unlink(missing_ok=True)


def _segment_signature(
    image: Path,
    audio: Path,
    *,
    orientation: str,
    width: int,
    height: int,
    policy: FFmpegPolicy,
) -> tuple[str, dict]:
    payload = {
        "schema_version": 1,
        "image_sha256": _sha256(image),
        "audio_sha256": _sha256(audio),
        "orientation": orientation,
        "width": width,
        "height": height,
        "ffmpeg_policy": policy.as_dict(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest(), payload


def _cached_segment_evidence(
    segment: Path,
    manifest_path: Path,
    *,
    signature: str,
    width: int,
    height: int,
) -> dict | None:
    if not segment.is_file() or not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("signature") != signature:
            return None
        if manifest.get("sha256") != _sha256(segment):
            return None
        media = _validated_video(segment, width=width, height=height)
    except (OSError, ValueError, json.JSONDecodeError, VideoToolError):
        return None
    return {**manifest, "media": media, "reused": True}


def _prepare_static_canvas(
    image: Path,
    *,
    width: int,
    height: int,
    workdir: Path,
    policy: FFmpegPolicy,
    control_check: Callable[[], None] | None,
) -> tuple[Path, str]:
    image_width, image_height = probe_image_size(image)
    if (image_width, image_height) == (width, height):
        return image, "direct"

    prepared_dir = workdir / "prepared"
    prepared_dir.mkdir(parents=True, exist_ok=True)
    identity = hashlib.sha256(f"{_sha256(image)}:{width}x{height}".encode()).hexdigest()[:24]
    prepared = prepared_dir / f"canvas-{identity}.png"
    if prepared.is_file():
        try:
            if probe_image_size(prepared) == (width, height):
                return prepared, "precomposed"
        except VideoToolError:
            prepared.unlink(missing_ok=True)

    temporary = _temporary_media_path(prepared)
    filter_graph = (
        "[0:v]split=2[background][foreground];"
        f"[background]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},boxblur=20:2[background_blurred];"
        f"[foreground]scale={width}:{height}:force_original_aspect_ratio=decrease"
        "[foreground_scaled];"
        "[background_blurred][foreground_scaled]"
        "overlay=(W-w)/2:(H-h)/2,format=rgb24[canvas]"
    )
    cmd = _filtered_ffmpeg_command(policy)
    cmd.extend(
        [
            "-i",
            str(image),
            "-filter_complex",
            filter_graph,
            "-map",
            "[canvas]",
            "-frames:v",
            "1",
            "-threads",
            str(policy.threads),
            str(temporary),
        ]
    )
    try:
        _run_with_control(cmd, timeout=120, control_check=control_check)
        if probe_image_size(temporary) != (width, height):
            raise VideoToolError("la precomposición no produjo el canvas esperado")
        temporary.replace(prepared)
    finally:
        temporary.unlink(missing_ok=True)
    return prepared, "precomposed"


def compose_video(
    pairs: list[tuple[Path, Path]],
    out_path: str | Path,
    workdir: str | Path,
    orientation: str = "horizontal",
    *,
    policy: FFmpegPolicy | Mapping[str, object] | None = None,
    control_check: Callable[[], None] | None = None,
    on_segment_complete: Callable[[int, dict], None] | None = None,
) -> Path:
    """Compose and atomically cache validated slide/audio MP4 segments."""
    if not ffmpeg_available():
        raise VideoToolError("ffmpeg/ffprobe no están instalados")
    if orientation not in VIDEO_SIZES:
        raise VideoToolError(f"Orientación de vídeo desconocida: {orientation}")
    width, height = VIDEO_SIZES[orientation]
    effective_policy = _policy(policy)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    segment_paths: list[Path] = []
    for index, (image, audio) in enumerate(pairs):
        image = Path(image)
        audio = Path(audio)
        segment = workdir / f"segment-{index:03d}.mp4"
        manifest_path = segment.with_suffix(".json")
        signature, signature_payload = _segment_signature(
            image,
            audio,
            orientation=orientation,
            width=width,
            height=height,
            policy=effective_policy,
        )
        evidence = _cached_segment_evidence(
            segment,
            manifest_path,
            signature=signature,
            width=width,
            height=height,
        )
        if evidence is not None:
            segment_paths.append(segment)
            if on_segment_complete:
                on_segment_complete(index, evidence)
            continue

        segment.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)
        prepared_image, composition = _prepare_static_canvas(
            image,
            width=width,
            height=height,
            workdir=workdir,
            policy=effective_policy,
            control_check=control_check,
        )
        temporary_segment = _temporary_media_path(segment)
        cmd = _filtered_ffmpeg_command(effective_policy)
        cmd.extend(
            [
                "-loop",
                "1",
                "-i",
                str(prepared_image),
                "-i",
                str(audio),
                "-tune",
                "stillimage",
            ]
        )
        cmd.extend(_x264_args(effective_policy))
        cmd.extend(
            [
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-ar",
                "44100",
                "-shortest",
                str(temporary_segment),
            ]
        )
        try:
            _run_with_control(cmd, control_check=control_check)
            media = _validated_video(temporary_segment, width=width, height=height)
            temporary_segment.replace(segment)
        finally:
            temporary_segment.unlink(missing_ok=True)
        evidence = {
            "schema_version": 1,
            "signature": signature,
            "signature_inputs": signature_payload,
            "sha256": _sha256(segment),
            "size_bytes": segment.stat().st_size,
            "media": media,
            "composition": composition,
            "prepared_image": str(prepared_image),
            "reused": False,
        }
        _write_json_atomic(manifest_path, evidence)
        segment_paths.append(segment)
        if on_segment_complete:
            on_segment_complete(index, evidence)

    concat_list = workdir / "concat.txt"
    concat_list.write_text("".join(_concat_file_entry(p) for p in segment_paths), encoding="utf-8")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = _temporary_media_path(out_path)
    try:
        _run_with_control(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c",
                "copy",
                str(temporary_output),
            ],
            control_check=control_check,
        )
        _validated_video(temporary_output, width=width, height=height)
        temporary_output.replace(out_path)
    finally:
        temporary_output.unlink(missing_ok=True)
    return out_path


def burn_subtitles(
    video_path: str | Path,
    subtitles_path: str | Path,
    out_path: str | Path,
    *,
    orientation: str = "horizontal",
    logo_metadata: dict | None = None,
    policy: FFmpegPolicy | Mapping[str, object] | None = None,
    control_check: Callable[[], None] | None = None,
) -> tuple[Path, dict]:
    """Burn readable subtitles while avoiding the lower logo safe area."""

    if not ffmpeg_available():
        raise VideoToolError("ffmpeg/ffprobe no están instalados")
    if orientation not in VIDEO_SIZES:
        raise VideoToolError(f"Orientación de vídeo desconocida: {orientation}")
    logo = logo_metadata or {}
    bottom_logo = str(logo.get("placement", "")).startswith("bottom")
    font_size = 28 if orientation == "horizontal" else 22
    margin_v = 72 if orientation == "horizontal" else 140
    if bottom_logo:
        size = {"small": 80, "medium": 130, "large": 190}.get(str(logo.get("size", "small")), 80)
        margin_v += int(logo.get("margin_px", 32) or 32) + size
    style = {
        "font": "Arial",
        "font_size": font_size,
        "primary_color": "&H00FFFFFF",
        "outline_color": "&H00111111",
        "outline": 3,
        "shadow": 1,
        "alignment": 2,
        "margin_v": margin_v,
    }
    force_style = (
        f"FontName={style['font']},FontSize={font_size},"
        f"PrimaryColour={style['primary_color']},"
        f"OutlineColour={style['outline_color']},"
        f"Outline={style['outline']},Shadow={style['shadow']},"
        f"Alignment={style['alignment']},MarginV={margin_v}"
    )
    subtitle_filter_path = (
        Path(subtitles_path)
        .resolve()
        .as_posix()
        .replace("\\", "/")
        .replace(":", r"\:")
        .replace("'", r"\'")
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    effective_policy = _policy(policy)
    temporary_output = _temporary_media_path(out_path)
    cmd = _filtered_ffmpeg_command(effective_policy)
    cmd.extend(
        [
            "-i",
            str(video_path),
            "-vf",
            f"subtitles='{subtitle_filter_path}':force_style='{force_style}'",
        ]
    )
    cmd.extend(_x264_args(effective_policy))
    cmd.extend(
        [
            "-c:a",
            "copy",
            str(temporary_output),
        ]
    )
    try:
        _run_with_control(cmd, control_check=control_check)
        width, height = VIDEO_SIZES[orientation]
        _validated_video(temporary_output, width=width, height=height)
        temporary_output.replace(out_path)
    finally:
        temporary_output.unlink(missing_ok=True)
    return out_path, style


def _format_srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(segments: list[tuple[str, float]]) -> str:
    """Build SRT content from (text, duration_seconds) per segment."""
    lines: list[str] = []
    cursor = 0.0
    for i, (text, duration) in enumerate(segments, start=1):
        start = cursor
        end = cursor + duration
        cursor = end
        lines.append(str(i))
        lines.append(f"{_format_srt_time(start)} --> {_format_srt_time(end)}")
        lines.append(text.strip())
        lines.append("")
    return "\n".join(lines)
