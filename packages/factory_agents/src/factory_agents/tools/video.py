"""Video production: slide images + narration segments → MP4 (+ SRT).

Static-slide composition: each slide PNG is shown for the duration of its
narration segment; segments are encoded individually and concatenated.
"""

import shutil
import subprocess
from pathlib import Path

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
        raise VideoToolError(
            f"{cmd[0]} falló ({result.returncode}): {result.stderr[-800:]}"
        )
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
    _run(
        [
            "marp",
            str(deck_md_path),
            "--images",
            "png",
            "--image-scale",
            "2",
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
    concat_list.write_text(
        "".join(f"file '{p.as_posix()}'\n" for p in segment_paths), encoding="utf-8"
    )
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
