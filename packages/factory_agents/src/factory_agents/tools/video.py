"""Video production: slide images + narration segments → MP4 (+ SRT).

Static-slide composition: each slide PNG is shown for the duration of its
narration segment; segments are encoded individually and concatenated.
"""

import json
import shutil
import subprocess
from pathlib import Path

from factory_agents.tools.marp import prepared_marp_source, vertical_theme_path

FFMPEG_TIMEOUT = 600
VIDEO_SIZES = {
    "horizontal": (1920, 1080),
    "vertical": (1080, 1920),
}


class VideoToolError(RuntimeError):
    pass


def _run(cmd: list[str], timeout: int = FFMPEG_TIMEOUT) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise VideoToolError(f"{cmd[0]} falló ({result.returncode}): {result.stderr[-800:]}")
    return result


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
    metadata_path = (
        write_chapter_metadata(chapters, workdir / "chapters.ffmeta") if chapters else None
    )

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
        cmd.extend(["-c", "copy", "-movflags", "+faststart", str(out_path)])
        _run(cmd)
        return out_path

    cmd = ["ffmpeg", "-y"]
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
                f"[{audio_label}][{index}:a:0]acrossfade=d=0.5:c1=tri:c2=tri[{next_audio}]"
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
                f"color=c=black:s={media['width']}x{media['height']}:r={rate}:d=0.5[{gap_video}]"
            )
            filters.append(
                f"anullsrc=r={media['audio_sample_rate'] or 44100}:"
                f"cl={channel_layout}:d=0.5[{gap_audio}]"
            )
            concat_inputs.extend([f"[{gap_video}]", f"[{gap_audio}]"])
        segment_count = len(paths) * 2 - 1
        filters.append("".join(concat_inputs) + f"concat=n={segment_count}:v=1:a=1[vout][aout]")
        filter_graph = ";".join(filters)
        video_label = "vout"
        audio_label = "aout"

    cmd.extend(
        ["-filter_complex", filter_graph, "-map", f"[{video_label}]", "-map", f"[{audio_label}]"]
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
    cmd.extend(
        [
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(out_path),
        ]
    )
    timeout = max(FFMPEG_TIMEOUT, int(sum(durations or []) * 2))
    _run(cmd, timeout=timeout)
    return out_path


def compose_video(
    pairs: list[tuple[Path, Path]],
    out_path: str | Path,
    workdir: str | Path,
    orientation: str = "horizontal",
) -> Path:
    """Compose slide/audio pairs, preserving the full slide on either canvas."""
    if not ffmpeg_available():
        raise VideoToolError("ffmpeg/ffprobe no están instalados")
    if orientation not in VIDEO_SIZES:
        raise VideoToolError(f"Orientación de vídeo desconocida: {orientation}")
    width, height = VIDEO_SIZES[orientation]
    filter_graph = (
        "[0:v]split=2[background][foreground];"
        f"[background]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},boxblur=20:2[background_blurred];"
        f"[foreground]scale={width}:{height}:force_original_aspect_ratio=decrease"
        "[foreground_scaled];"
        "[background_blurred][foreground_scaled]"
        "overlay=(W-w)/2:(H-h)/2,format=yuv420p[video]"
    )
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    segment_paths: list[Path] = []
    for i, (image, audio) in enumerate(pairs):
        segment = workdir / f"segment-{i:03d}.mp4"
        _run(
            [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-i",
                str(image),
                "-i",
                str(audio),
                "-c:v",
                "libx264",
                "-tune",
                "stillimage",
                "-filter_complex",
                filter_graph,
                "-map",
                "[video]",
                "-map",
                "1:a",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-ar",
                "44100",
                "-shortest",
                str(segment),
            ]
        )
        segment_paths.append(segment)

    concat_list = workdir / "concat.txt"
    concat_list.write_text("".join(_concat_file_entry(p) for p in segment_paths), encoding="utf-8")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
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
            str(out_path),
        ]
    )
    return out_path


def burn_subtitles(
    video_path: str | Path,
    subtitles_path: str | Path,
    out_path: str | Path,
    *,
    orientation: str = "horizontal",
    logo_metadata: dict | None = None,
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
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"subtitles='{subtitle_filter_path}':force_style='{force_style}'",
            "-c:v",
            "libx264",
            "-c:a",
            "copy",
            str(out_path),
        ]
    )
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
