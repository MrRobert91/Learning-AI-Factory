"""Deterministic preflight and production helpers for full-course video exports."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from factory_agents.contracts import CoursePlan
from factory_agents.tools.video import (
    VideoToolError,
    concat_course_videos,
    ffmpeg_available,
    probe_media,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from factory_api.artifact_versions import artifact_metadata
from factory_api.config import get_settings
from factory_api.models import Artifact, Project

TRANSITION_SECONDS = {
    "none": 0.0,
    "fade_500ms": -0.5,
    "gap_500ms": 0.5,
}
VIDEO_PREFIX = "Vídeo — "
SUBTITLE_PREFIX = "Subtítulos — "
_SRT_RANGE = re.compile(
    r"^(?P<start>\d{2,}:\d{2}:\d{2},\d{3})\s+-->\s+"
    r"(?P<end>\d{2,}:\d{2}:\d{2},\d{3})$"
)


@dataclass
class CourseVideoInput:
    module_index: int
    lesson_index: int
    module_title: str
    lesson_title: str
    label: str
    video: Artifact
    video_path: Path
    media: dict[str, Any]
    subtitles: Artifact | None = None
    subtitles_path: Path | None = None


@dataclass
class CourseVideoPreflight:
    public: dict[str, Any]
    project: Project
    plan_artifact: Artifact | None
    plan: CoursePlan | None
    inputs: list[CourseVideoInput]


def _artifact_map(db: Session, project_id: str, type_: str, prefix: str) -> dict[str, Artifact]:
    artifacts = db.scalars(
        select(Artifact)
        .where(
            Artifact.project_id == project_id,
            Artifact.type == type_,
            Artifact.is_selected.is_(True),
        )
        .order_by(Artifact.created_at)
    ).all()
    return {artifact.title.removeprefix(prefix).strip(): artifact for artifact in artifacts}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _srt_seconds(value: str) -> float:
    hours, minutes, rest = value.split(":")
    seconds, milliseconds = rest.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(milliseconds) / 1000


def _format_srt_time(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"


def parse_srt(content: str) -> list[tuple[float, float, str]]:
    """Parse and validate monotonic SRT entries."""
    entries: list[tuple[float, float, str]] = []
    previous_start = -1.0
    blocks = re.split(r"\r?\n\s*\r?\n", content.strip())
    for block in blocks:
        if not block.strip():
            continue
        lines = block.splitlines()
        if len(lines) < 3:
            raise ValueError("bloque SRT incompleto")
        match = _SRT_RANGE.match(lines[1].strip())
        if match is None:
            raise ValueError(f"rango SRT inválido: {lines[1].strip()}")
        start = _srt_seconds(match.group("start"))
        end = _srt_seconds(match.group("end"))
        if end <= start:
            raise ValueError("un subtítulo termina antes de empezar")
        if start + 0.001 < previous_start:
            raise ValueError("los timestamps SRT no son monótonos")
        text = "\n".join(lines[2:]).strip()
        if not text:
            raise ValueError("un subtítulo no contiene texto")
        entries.append((start, end, text))
        previous_start = start
    if not entries:
        raise ValueError("el SRT está vacío")
    return entries


def timeline_offsets(durations: list[float], transition: str) -> tuple[list[float], float]:
    if transition not in TRANSITION_SECONDS:
        raise ValueError(f"Transición desconocida: {transition}")
    offsets: list[float] = []
    cursor = 0.0
    delta = TRANSITION_SECONDS[transition]
    for index, duration in enumerate(durations):
        offsets.append(cursor)
        cursor += duration
        if index < len(durations) - 1:
            cursor += delta
    return offsets, max(0.0, cursor)


def combine_subtitles(inputs: list[CourseVideoInput], offsets: list[float]) -> str:
    shifted: list[tuple[float, float, str]] = []
    for item, offset in zip(inputs, offsets, strict=True):
        if item.subtitles_path is None:
            raise ValueError(f"Faltan subtítulos para {item.label}")
        shifted.extend(
            (start + offset, end + offset, text)
            for start, end, text in parse_srt(
                item.subtitles_path.read_text(encoding="utf-8")
            )
        )
    shifted.sort(key=lambda entry: (entry[0], entry[1]))

    lines: list[str] = []
    for index, (start, end, text) in enumerate(shifted, start=1):
        lines.extend(
            [
                str(index),
                f"{_format_srt_time(start)} --> {_format_srt_time(end)}",
                text,
                "",
            ]
        )
    return "\n".join(lines)


def build_chapter_manifest(
    inputs: list[CourseVideoInput],
    offsets: list[float],
    output_duration: float,
) -> dict[str, Any]:
    lesson_chapters: list[dict[str, Any]] = []
    for index, (item, start) in enumerate(zip(inputs, offsets, strict=True)):
        end = offsets[index + 1] if index + 1 < len(offsets) else output_duration
        lesson_chapters.append(
            {
                "title": item.label,
                "type": "lesson",
                "module_index": item.module_index,
                "lesson_index": item.lesson_index,
                "start_seconds": start,
                "duration_seconds": max(0.0, end - start),
                "end_seconds": end,
                "artifact_id": item.video.id,
            }
        )

    module_chapters: list[dict[str, Any]] = []
    module_starts = [
        index
        for index, item in enumerate(inputs)
        if index == 0 or item.module_index != inputs[index - 1].module_index
    ]
    for position, input_index in enumerate(module_starts):
        item = inputs[input_index]
        start = offsets[input_index]
        end = (
            offsets[module_starts[position + 1]]
            if position + 1 < len(module_starts)
            else output_duration
        )
        module_chapters.append(
            {
                "title": f"Módulo {item.module_index}: {item.module_title}",
                "type": "module",
                "module_index": item.module_index,
                "start_seconds": start,
                "duration_seconds": max(0.0, end - start),
                "end_seconds": end,
                "artifact_id": None,
            }
        )
    return {
        "duration_seconds": output_duration,
        "chapters": sorted(
            [*module_chapters, *lesson_chapters],
            key=lambda item: (
                item["start_seconds"],
                0 if item["type"] == "module" else 1,
            ),
        ),
        "embedded_chapters": lesson_chapters,
    }


def _issue(code: str, detail: str, lesson: str | None = None) -> dict[str, Any]:
    return {"code": code, "lesson": lesson, "detail": detail}


def build_preflight(
    db: Session,
    project: Project,
    *,
    include_subtitles: bool | None,
    include_chapters: bool,
    transition: str,
) -> CourseVideoPreflight:
    settings = get_settings()
    issues: list[dict[str, Any]] = []
    subtitle_errors: dict[str, str] = {}
    inputs: list[CourseVideoInput] = []
    lessons_public: list[dict[str, Any]] = []
    available = ffmpeg_available()
    if not available:
        issues.append(
            _issue(
                "ffmpeg_unavailable",
                "ffmpeg y ffprobe deben estar instalados para generar el vídeo completo.",
            )
        )

    plan_artifact = db.scalars(
        select(Artifact)
        .where(
            Artifact.project_id == project.id,
            Artifact.type == "course_plan",
            Artifact.is_selected.is_(True),
        )
        .order_by(Artifact.created_at.desc())
        .limit(1)
    ).first()
    plan: CoursePlan | None = None
    if plan_artifact is None:
        issues.append(
            _issue("missing_course_plan", "Falta el course_plan seleccionado del proyecto.")
        )
    else:
        plan_path = settings.data_dir / plan_artifact.path
        try:
            plan = CoursePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            issues.append(_issue("invalid_course_plan", f"El course_plan no es válido: {exc}"))

    videos = _artifact_map(db, project.id, "video", VIDEO_PREFIX)
    subtitles = _artifact_map(db, project.id, "subtitles", SUBTITLE_PREFIX)
    if plan is not None:
        for module_index, lesson_index, module, lesson in plan.iter_lessons():
            label = f"{module_index}.{lesson_index} {lesson.title}"
            video = videos.get(label)
            subtitle = subtitles.get(label)
            public = {
                "module_index": module_index,
                "lesson_index": lesson_index,
                "module_title": module.title,
                "lesson_title": lesson.title,
                "label": label,
                "video_artifact_id": video.id if video else None,
                "video_version": video.version if video else None,
                "subtitles_artifact_id": subtitle.id if subtitle else None,
                "duration_seconds": None,
                "orientation": None,
            }
            lessons_public.append(public)
            if video is None:
                issues.append(_issue("missing_video", "No hay un vídeo seleccionado.", label))
                continue
            video_path = settings.data_dir / video.path
            if not video_path.is_file():
                issues.append(_issue("missing_video_file", "El fichero de vídeo no existe.", label))
                continue
            metadata = artifact_metadata(video)
            media: dict[str, Any] = {
                "duration_seconds": float(metadata.get("duration_seconds") or 0),
                "width": int(metadata.get("width") or 0),
                "height": int(metadata.get("height") or 0),
            }
            if available:
                try:
                    media = probe_media(video_path)
                except (OSError, ValueError, VideoToolError, json.JSONDecodeError) as exc:
                    issues.append(
                        _issue("invalid_video", f"ffprobe no puede leer el fichero: {exc}", label)
                    )
                    continue
            orientation = (
                "vertical"
                if int(media.get("height") or 0) > int(media.get("width") or 0)
                else "horizontal"
            )
            public["duration_seconds"] = float(media.get("duration_seconds") or 0)
            public["orientation"] = orientation

            subtitle_path = settings.data_dir / subtitle.path if subtitle else None
            if subtitle_path is not None and subtitle_path.is_file():
                try:
                    entries = parse_srt(subtitle_path.read_text(encoding="utf-8"))
                    if entries[-1][1] > float(media.get("duration_seconds") or 0) + 0.75:
                        raise ValueError("un timestamp supera la duración del vídeo")
                except (OSError, UnicodeError, ValueError) as exc:
                    subtitle_errors[label] = f"El SRT seleccionado no es válido: {exc}"
                    subtitle_path = None
            else:
                subtitle_path = None

            inputs.append(
                CourseVideoInput(
                    module_index=module_index,
                    lesson_index=lesson_index,
                    module_title=module.title,
                    lesson_title=lesson.title,
                    label=label,
                    video=video,
                    video_path=video_path,
                    media=media,
                    subtitles=subtitle if subtitle_path else None,
                    subtitles_path=subtitle_path,
                )
            )

    subtitles_available = bool(inputs) and all(item.subtitles_path is not None for item in inputs)
    effective_subtitles = subtitles_available if include_subtitles is None else include_subtitles
    if effective_subtitles:
        for item in inputs:
            if item.subtitles_path is None:
                issues.append(
                    _issue(
                        (
                            "invalid_subtitles"
                            if item.label in subtitle_errors
                            else "missing_subtitles"
                        ),
                        subtitle_errors.get(item.label)
                        or ("Falta un SRT seleccionado; desactiva los subtítulos o genera el SRT."),
                        item.label,
                    )
                )

    if inputs:
        reference = inputs[0]
        compatibility_fields = (
            ("width", "resolución"),
            ("height", "resolución"),
            ("video_codec", "codec de vídeo"),
            ("audio_codec", "codec de audio"),
            ("frame_rate", "frame rate"),
            ("time_base", "timebase"),
            ("audio_sample_rate", "frecuencia de audio"),
            ("audio_channels", "canales de audio"),
            ("audio_channel_layout", "distribución de canales"),
        )
        for item in inputs[1:]:
            differences = sorted(
                {
                    label
                    for field, label in compatibility_fields
                    if item.media.get(field) != reference.media.get(field)
                }
            )
            if differences:
                issues.append(
                    _issue(
                        "incompatible_video",
                        "No coincide con el primer vídeo en: " + ", ".join(differences) + ".",
                        item.label,
                    )
                )

    durations = [float(item.media.get("duration_seconds") or 0) for item in inputs]
    if transition == "fade_500ms" and len(durations) > 1:
        for item, duration in zip(inputs, durations, strict=True):
            if duration <= 0.5:
                issues.append(
                    _issue(
                        "video_too_short_for_fade",
                        "El vídeo debe durar más de 0,5 s para aplicar el fundido.",
                        item.label,
                    )
                )
    offsets, output_duration = timeline_offsets(durations, transition)
    orientation = (
        "vertical"
        if inputs
        and int(inputs[0].media.get("height") or 0) > int(inputs[0].media.get("width") or 0)
        else "horizontal"
        if inputs
        else None
    )
    width = int(inputs[0].media.get("width") or 0) if inputs else None
    height = int(inputs[0].media.get("height") or 0) if inputs else None

    input_signature = None
    if plan_artifact is not None and plan is not None and len(inputs) == len(lessons_public):
        signature_payload = {
            "plan": {
                "id": plan_artifact.id,
                "version": plan_artifact.version,
                "sha256": file_sha256(settings.data_dir / plan_artifact.path),
            },
            "videos": [
                {
                    "id": item.video.id,
                    "version": item.video.version,
                    "sha256": file_sha256(item.video_path),
                    "subtitles_id": item.subtitles.id
                    if effective_subtitles and item.subtitles
                    else None,
                    "subtitles_sha256": (
                        file_sha256(item.subtitles_path)
                        if effective_subtitles and item.subtitles_path
                        else None
                    ),
                }
                for item in inputs
            ],
            "options": {
                "include_subtitles": effective_subtitles,
                "include_chapters": include_chapters,
                "transition": transition,
            },
        }
        input_signature = hashlib.sha256(
            json.dumps(signature_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

    if inputs:
        required_space = max(
            50 * 1024 * 1024,
            sum(item.video_path.stat().st_size for item in inputs) * 2,
        )
        free_space = shutil.disk_usage(settings.data_dir).free
        if free_space < required_space:
            issues.append(
                _issue(
                    "insufficient_space",
                    "Espacio insuficiente: se necesitan aproximadamente "
                    f"{required_space} bytes libres y hay {free_space}.",
                )
            )

    public = {
        "ready": not issues and len(inputs) == len(lessons_public) and bool(inputs),
        "ffmpeg_available": available,
        "include_subtitles": effective_subtitles,
        "include_chapters": include_chapters,
        "transition": transition,
        "subtitles_available": subtitles_available,
        "total_duration_seconds": sum(durations),
        "output_duration_seconds": output_duration,
        "orientation": orientation,
        "width": width,
        "height": height,
        "input_signature": input_signature,
        "lessons": lessons_public,
        "issues": issues,
        "_offsets": offsets,
    }
    return CourseVideoPreflight(
        public=public,
        project=project,
        plan_artifact=plan_artifact,
        plan=plan,
        inputs=inputs,
    )


def public_preflight(preflight: CourseVideoPreflight) -> dict[str, Any]:
    return {key: value for key, value in preflight.public.items() if not key.startswith("_")}


def input_snapshot(preflight: CourseVideoPreflight) -> dict[str, Any]:
    settings = get_settings()
    plan = preflight.plan_artifact
    return {
        "course_plan": (
            {
                "id": plan.id,
                "version": plan.version,
                "logical_key": plan.logical_key,
                "sha256": file_sha256(settings.data_dir / plan.path),
            }
            if plan is not None
            else None
        ),
        "videos": [
            {
                "id": item.video.id,
                "version": item.video.version,
                "logical_key": item.video.logical_key,
                "sha256": file_sha256(item.video_path),
                "subtitles_id": item.subtitles.id if item.subtitles else None,
                "subtitles_version": item.subtitles.version if item.subtitles else None,
                "subtitles_sha256": (
                    file_sha256(item.subtitles_path) if item.subtitles_path else None
                ),
            }
            for item in preflight.inputs
        ],
    }


def find_cached_export(db: Session, project_id: str, signature: str) -> Artifact | None:
    candidates = db.scalars(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.type == "course_video")
        .order_by(Artifact.created_at.desc())
    ).all()
    settings = get_settings()
    for artifact in candidates:
        metadata = artifact_metadata(artifact)
        path = settings.data_dir / artifact.path
        if metadata.get("input_signature") != signature or not path.is_file():
            continue
        try:
            expected_sha256 = str(metadata["sha256"])
            if not expected_sha256 or file_sha256(path) != expected_sha256:
                continue
            duration = float(metadata["duration_seconds"])
            verify_course_video(
                path,
                expected_duration=duration,
                width=int(metadata["width"]),
                height=int(metadata["height"]),
            )
            options = dict(metadata.get("options") or {})
            if options.get("include_subtitles"):
                subtitles = db.get(Artifact, metadata.get("course_subtitles_id"))
                if (
                    subtitles is None
                    or subtitles.project_id != project_id
                    or subtitles.type != "course_subtitles"
                ):
                    continue
                subtitle_path = settings.data_dir / subtitles.path
                if file_sha256(subtitle_path) != metadata.get(
                    "course_subtitles_sha256"
                ):
                    continue
                subtitle_entries = parse_srt(subtitle_path.read_text(encoding="utf-8"))
                if subtitle_entries[-1][1] > duration + 0.75:
                    continue
            if options.get("include_chapters"):
                manifest = db.get(Artifact, metadata.get("chapter_manifest_id"))
                if (
                    manifest is None
                    or manifest.project_id != project_id
                    or manifest.type != "course_video_manifest"
                ):
                    continue
                manifest_path = settings.data_dir / manifest.path
                if file_sha256(manifest_path) != metadata.get(
                    "chapter_manifest_sha256"
                ):
                    continue
                manifest_value = json.loads(manifest_path.read_text(encoding="utf-8"))
                chapters = manifest_value.get("chapters")
                if not isinstance(chapters, list) or not chapters:
                    continue
                previous_start = -1.0
                valid_chapters = True
                for chapter in chapters:
                    start = float(chapter["start_seconds"])
                    end = float(chapter["end_seconds"])
                    if (
                        start < previous_start
                        or end < start
                        or end > duration + 0.01
                    ):
                        valid_chapters = False
                        break
                    previous_start = start
                if not valid_chapters:
                    continue
        except (
            json.JSONDecodeError,
            KeyError,
            OSError,
            TypeError,
            UnicodeError,
            ValueError,
            VideoToolError,
        ):
            continue
        return artifact
    return None


def verify_course_video(
    path: Path,
    *,
    expected_duration: float,
    width: int,
    height: int,
) -> dict[str, Any]:
    media = probe_media(path)
    tolerance = max(1.0, expected_duration * 0.02)
    if abs(float(media["duration_seconds"]) - expected_duration) > tolerance:
        raise VideoToolError(
            "La duración verificada no coincide con la esperada "
            f"({media['duration_seconds']:.3f}s frente a {expected_duration:.3f}s)."
        )
    if media["width"] != width or media["height"] != height:
        raise VideoToolError(
            f"La salida mide {media['width']}x{media['height']} y se esperaba {width}x{height}."
        )
    return media


__all__ = [
    "CourseVideoInput",
    "CourseVideoPreflight",
    "build_chapter_manifest",
    "build_preflight",
    "combine_subtitles",
    "concat_course_videos",
    "find_cached_export",
    "file_sha256",
    "input_snapshot",
    "parse_srt",
    "public_preflight",
    "timeline_offsets",
    "verify_course_video",
]
