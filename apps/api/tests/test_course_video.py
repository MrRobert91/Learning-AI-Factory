import json
import time
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from factory_agents.contracts import CoursePlan
from factory_agents.tools.video import VideoToolError
from factory_api.artifact_versions import add_artifact_version
from factory_api.config import get_settings
from factory_api.db import SessionLocal
from factory_api.models import Artifact, UsageRecord
from sqlalchemy import select
from test_runs import _create_project, _wait_for_job

PLAN = CoursePlan(
    course_title="Curso completo",
    modules=[
        {
            "title": "Fundamentos",
            "lessons": [
                {"title": "Introducción", "objective": "Entender"},
                {"title": "Prompting", "objective": "Practicar"},
            ],
        },
        {
            "title": "Calidad",
            "lessons": [
                {"title": "Evaluación", "objective": "Evaluar"},
            ],
        },
    ],
)
DURATIONS = [2.0, 3.0, 4.0]
COURSE_VIDEO_OUTPUT_TYPES = {
    "course_video",
    "course_subtitles",
    "course_video_manifest",
}


def _seed_inputs(auth_client, *, video_count=3, with_subtitles=True):
    project = _create_project(auth_client)
    settings = get_settings()
    root = settings.data_dir / "course-video-fixtures" / project["id"]
    root.mkdir(parents=True, exist_ok=True)
    plan_path = root / "course-plan.json"
    plan_path.write_text(PLAN.model_dump_json(indent=2), encoding="utf-8")

    with SessionLocal() as db:
        add_artifact_version(
            db,
            project_id=project["id"],
            type_="course_plan",
            format_="json",
            title="Plan del curso — Curso completo",
            path=str(plan_path.relative_to(settings.data_dir)),
        )
        for index, (module_index, lesson_index, _module, lesson) in enumerate(
            PLAN.iter_lessons()
        ):
            if index >= video_count:
                break
            label = f"{module_index}.{lesson_index} {lesson.title}"
            video_path = root / f"lesson-{index}.mp4"
            video_path.write_bytes(f"VIDEO-{index}".encode())
            subtitle_id = None
            if with_subtitles:
                srt_path = root / f"lesson-{index}.srt"
                srt_path.write_text(
                    "1\n"
                    f"00:00:00,000 --> 00:00:0{int(DURATIONS[index])},000\n"
                    f"Texto {index}\n",
                    encoding="utf-8",
                )
                subtitle = add_artifact_version(
                    db,
                    project_id=project["id"],
                    type_="subtitles",
                    format_="text",
                    title=f"Subtítulos — {label}",
                    path=str(srt_path.relative_to(settings.data_dir)),
                )
                subtitle_id = subtitle.id
            add_artifact_version(
                db,
                project_id=project["id"],
                type_="video",
                format_="video",
                title=f"Vídeo — {label}",
                path=str(video_path.relative_to(settings.data_dir)),
                metadata={
                    "duration_seconds": DURATIONS[index],
                    "orientation": "horizontal",
                    "width": 1920,
                    "height": 1080,
                    "subtitles_id": subtitle_id,
                },
            )
        db.commit()
    return project


def _media(duration, *, width=1920, height=1080, video_codec="h264"):
    return {
        "duration_seconds": duration,
        "width": width,
        "height": height,
        "video_codec": video_codec,
        "audio_codec": "aac",
        "frame_rate": "30/1",
        "time_base": "1/15360",
        "audio_sample_rate": 44100,
        "audio_channels": 2,
        "audio_channel_layout": "stereo",
    }


def _patch_media(monkeypatch, *, output_duration=9.0, overrides=None):
    overrides = overrides or {}

    def fake_probe(path):
        name = Path(path).name
        if name == "course-video.mp4" or name.startswith("course_video-"):
            return _media(output_duration)
        index = int(name.removeprefix("lesson-").removesuffix(".mp4"))
        override = overrides.get(index)
        if isinstance(override, Exception):
            raise override
        return {**_media(DURATIONS[index]), **(override or {})}

    monkeypatch.setattr("factory_api.course_video.ffmpeg_available", lambda: True)
    monkeypatch.setattr("factory_api.course_video.probe_media", fake_probe)
    return fake_probe


def test_preflight_uses_course_plan_order_and_defaults_subtitles(auth_client, monkeypatch):
    project = _seed_inputs(auth_client)
    _patch_media(monkeypatch)

    response = auth_client.get(
        f"/api/projects/{project['id']}/course-video/preflight"
    )
    assert response.status_code == 200
    preflight = response.json()
    assert preflight["ready"] is True
    assert preflight["include_subtitles"] is True
    assert preflight["subtitles_available"] is True
    assert [lesson["label"] for lesson in preflight["lessons"]] == [
        "1.1 Introducción",
        "1.2 Prompting",
        "2.1 Evaluación",
    ]
    assert preflight["total_duration_seconds"] == 9
    assert preflight["output_duration_seconds"] == 9
    assert preflight["input_signature"]


def test_preflight_reports_missing_corrupt_and_incompatible_inputs(
    auth_client, monkeypatch
):
    missing = _seed_inputs(auth_client, video_count=2, with_subtitles=False)
    _patch_media(monkeypatch)
    response = auth_client.post(
        f"/api/projects/{missing['id']}/course-video",
        json={
            "include_subtitles": False,
            "include_chapters": True,
            "transition": "none",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["issues"][0]["code"] == "missing_video"

    incompatible = _seed_inputs(auth_client, with_subtitles=False)
    _patch_media(
        monkeypatch,
        overrides={
            1: {"width": 1080, "height": 1920},
            2: {"video_codec": "hevc"},
        },
    )
    preflight = auth_client.get(
        f"/api/projects/{incompatible['id']}/course-video/preflight",
        params={"include_subtitles": "false"},
    ).json()
    assert preflight["ready"] is False
    assert [issue["code"] for issue in preflight["issues"]].count(
        "incompatible_video"
    ) == 2

    corrupt = _seed_inputs(auth_client, with_subtitles=False)
    _patch_media(
        monkeypatch,
        overrides={1: VideoToolError("fichero corrupto")},
    )
    preflight = auth_client.get(
        f"/api/projects/{corrupt['id']}/course-video/preflight",
        params={"include_subtitles": "false"},
    ).json()
    assert any(issue["code"] == "invalid_video" for issue in preflight["issues"])


@pytest.mark.parametrize(
    ("transition", "expected_offsets", "expected_duration"),
    [
        ("none", [0.0, 2.0, 5.0], 9.0),
        ("gap_500ms", [0.0, 2.5, 6.0], 10.0),
        ("fade_500ms", [0.0, 1.5, 4.0], 8.0),
    ],
)
def test_timeline_offsets(transition, expected_offsets, expected_duration):
    from factory_api.course_video import timeline_offsets

    offsets, duration = timeline_offsets(DURATIONS, transition)
    assert offsets == expected_offsets
    assert duration == expected_duration


def test_combined_subtitles_keep_fade_offsets_and_sort_overlapping_cues(tmp_path):
    from factory_api.course_video import combine_subtitles, parse_srt

    first = tmp_path / "first.srt"
    first.write_text(
        "1\n00:00:01,800 --> 00:00:02,000\nFinal de la primera\n",
        encoding="utf-8",
    )
    second = tmp_path / "second.srt"
    second.write_text(
        "1\n00:00:00,000 --> 00:00:00,700\nInicio de la segunda\n",
        encoding="utf-8",
    )

    combined = combine_subtitles(
        [
            SimpleNamespace(label="1.1", subtitles_path=first),
            SimpleNamespace(label="1.2", subtitles_path=second),
        ],
        [0.0, 1.5],
    )

    entries = parse_srt(combined)
    assert [entry[0] for entry in entries] == [1.5, 1.8]
    assert [entry[2] for entry in entries] == [
        "Inicio de la segunda",
        "Final de la primera",
    ]


def test_course_video_job_publishes_associated_files_and_reuses_cache(
    auth_client, monkeypatch
):
    project = _seed_inputs(auth_client)
    _patch_media(monkeypatch, output_duration=10.0)
    concat_calls = []

    def fake_concat(inputs, out_path, workdir, **kwargs):
        concat_calls.append(
            {
                "inputs": [Path(value).name for value in inputs],
                **kwargs,
            }
        )
        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"COURSE-VIDEO")
        return target

    monkeypatch.setattr("factory_api.course_video.concat_course_videos", fake_concat)
    options = {
        "include_subtitles": True,
        "include_chapters": True,
        "transition": "gap_500ms",
    }
    created = auth_client.post(
        f"/api/projects/{project['id']}/course-video",
        json=options,
    )
    assert created.status_code == 201, created.text
    job = _wait_for_job(auth_client, created.json()["id"])
    assert job["status"] == "done", job["error"]
    assert job["result"]["cache_hit"] is False
    assert len(concat_calls) == 1
    assert concat_calls[0]["inputs"] == [
        "lesson-0.mp4",
        "lesson-1.mp4",
        "lesson-2.mp4",
    ]

    video = auth_client.get(
        f"/api/artifacts/{job['result']['artifact_id']}"
    ).json()
    assert video["type"] == "course_video"
    assert video["metadata"]["options"] == options
    assert video["metadata"]["duration_seconds"] == 10
    assert [item["version"] for item in video["metadata"]["inputs"]["videos"]] == [
        1,
        1,
        1,
    ]
    assert video["metadata"]["sha256"]

    subtitles = auth_client.get(
        f"/api/artifacts/{job['result']['course_subtitles_id']}"
    ).json()
    assert "00:00:02,500 --> 00:00:05,500" in subtitles["content"]
    assert "00:00:06,000 --> 00:00:10,000" in subtitles["content"]

    manifest = auth_client.get(
        f"/api/artifacts/{job['result']['chapter_manifest_id']}"
    ).json()
    chapters = json.loads(manifest["content"])["chapters"]
    assert [item["type"] for item in chapters].count("module") == 2
    assert [item["type"] for item in chapters].count("lesson") == 3
    assert [item["artifact_id"] for item in chapters if item["type"] == "lesson"]

    with SessionLocal() as db:
        db.get(Artifact, video["id"]).is_selected = False
        db.commit()
    second = auth_client.post(
        f"/api/projects/{project['id']}/course-video",
        json=options,
    )
    second_job = _wait_for_job(auth_client, second.json()["id"])
    assert second_job["status"] == "done", second_job["error"]
    assert second_job["result"]["cache_hit"] is True
    assert second_job["result"]["artifact_id"] == video["id"]
    assert len(concat_calls) == 1
    assert any(
        "Cache hit" in event["summary"] for event in second_job["events"]
    )
    selected = auth_client.get(
        f"/api/projects/{project['id']}/artifacts"
    ).json()
    assert any(item["id"] == video["id"] for item in selected)

    with SessionLocal() as db:
        usage = list(
            db.scalars(
                select(UsageRecord).where(UsageRecord.job_id == job["id"])
            ).all()
        )
        assert usage
        assert {record.artifact_id for record in usage} == {video["id"]}
        stored = db.get(Artifact, video["id"])
        assert stored is not None
        stored_video = get_settings().data_dir / stored.path
    stored_video.write_bytes(b"CORRUPTED")
    third = auth_client.post(
        f"/api/projects/{project['id']}/course-video",
        json=options,
    )
    third_job = _wait_for_job(auth_client, third.json()["id"])
    assert third_job["status"] == "done", third_job["error"]
    assert third_job["result"]["cache_hit"] is False
    assert len(concat_calls) == 2


def test_invalid_options_are_rejected(auth_client):
    project = _create_project(auth_client)
    response = auth_client.post(
        f"/api/projects/{project['id']}/course-video",
        json={
            "include_subtitles": False,
            "include_chapters": True,
            "transition": "spin",
        },
    )
    assert response.status_code == 422


def test_course_video_pauses_after_ffmpeg_and_resumes_without_reencoding(
    auth_client, monkeypatch
):
    project = _seed_inputs(auth_client, with_subtitles=False)
    _patch_media(monkeypatch, output_duration=9.0)
    concat_started = Event()
    concat_release = Event()
    calls = 0

    def slow_concat(inputs, out_path, workdir, **kwargs):
        nonlocal calls
        calls += 1
        concat_started.set()
        assert concat_release.wait(5)
        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"COURSE-VIDEO")
        return target

    monkeypatch.setattr("factory_api.course_video.concat_course_videos", slow_concat)
    created = auth_client.post(
        f"/api/projects/{project['id']}/course-video",
        json={
            "include_subtitles": False,
            "include_chapters": True,
            "transition": "none",
        },
    ).json()
    assert concat_started.wait(3)
    pause = auth_client.post(f"/api/runs/{created['id']}/pause")
    assert pause.status_code == 200
    assert pause.json()["status"] == "pausing"
    concat_release.set()

    deadline = time.time() + 5
    while time.time() < deadline:
        paused = auth_client.get(f"/api/runs/{created['id']}").json()
        if paused["status"] == "paused":
            break
        time.sleep(0.05)
    assert paused["status"] == "paused"
    artifacts = auth_client.get(
        f"/api/projects/{project['id']}/artifacts"
    ).json()
    assert not any(item["type"] == "course_video" for item in artifacts)

    resumed = auth_client.post(f"/api/runs/{created['id']}/resume")
    assert resumed.status_code == 200
    finished = _wait_for_job(auth_client, created["id"])
    assert finished["status"] == "done", finished["error"]
    assert calls == 1
    assert finished["result"]["artifact_id"]


def test_course_video_cancel_cleans_temporary_output_without_artifacts(
    auth_client, monkeypatch
):
    project = _seed_inputs(auth_client, with_subtitles=False)
    _patch_media(monkeypatch, output_duration=9.0)
    concat_started = Event()
    concat_release = Event()

    def slow_concat(inputs, out_path, workdir, **kwargs):
        concat_started.set()
        assert concat_release.wait(5)
        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"COURSE-VIDEO")
        return target

    monkeypatch.setattr("factory_api.course_video.concat_course_videos", slow_concat)
    created = auth_client.post(
        f"/api/projects/{project['id']}/course-video",
        json={
            "include_subtitles": False,
            "include_chapters": True,
            "transition": "none",
        },
    ).json()
    assert concat_started.wait(3)
    canceled = auth_client.post(f"/api/runs/{created['id']}/cancel")
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "canceling"
    concat_release.set()

    deadline = time.time() + 5
    while time.time() < deadline:
        job = auth_client.get(f"/api/runs/{created['id']}").json()
        if job["status"] == "canceled":
            break
        time.sleep(0.05)
    assert job["status"] == "canceled"
    artifacts = auth_client.get(
        f"/api/projects/{project['id']}/artifacts"
    ).json()
    assert not any(item["type"] in COURSE_VIDEO_OUTPUT_TYPES for item in artifacts)
    workdir = (
        get_settings().data_dir / "runs" / created["id"] / "course-video"
    )
    assert not workdir.exists()


def test_course_video_publication_rolls_back_every_related_artifact(
    auth_client, monkeypatch
):
    import factory_api.runner as runner_module

    project = _seed_inputs(auth_client)
    _patch_media(monkeypatch, output_duration=9.0)

    def fake_concat(inputs, out_path, workdir, **kwargs):
        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"COURSE-VIDEO")
        return target

    original_add = runner_module.add_artifact_version

    def fail_on_video(*args, **kwargs):
        if kwargs.get("type_") == "course_video":
            raise RuntimeError("fallo simulado durante la publicación")
        return original_add(*args, **kwargs)

    monkeypatch.setattr("factory_api.course_video.concat_course_videos", fake_concat)
    monkeypatch.setattr(runner_module, "add_artifact_version", fail_on_video)
    created = auth_client.post(
        f"/api/projects/{project['id']}/course-video",
        json={
            "include_subtitles": True,
            "include_chapters": True,
            "transition": "none",
        },
    ).json()
    failed = _wait_for_job(auth_client, created["id"])
    assert failed["status"] == "failed"
    assert "fallo simulado" in failed["error"]
    artifacts = auth_client.get(
        f"/api/projects/{project['id']}/artifacts"
    ).json()
    assert not any(item["type"] in COURSE_VIDEO_OUTPUT_TYPES for item in artifacts)
    artifact_dir = get_settings().data_dir / "artifacts" / project["id"]
    assert not list(artifact_dir.glob(f"course_*-{created['id']}-*"))
