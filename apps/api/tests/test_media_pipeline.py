from pathlib import Path

from factory_agents.contracts import VoiceScript
from test_pipeline import _patch_all
from test_runs import _create_project, _wait_for_job

FAKE_SCRIPT = "# Guion: 1.1\n\n## Slide 1\nBienvenidos.\n\n## Slide 2\nUn LLM predice tokens.\n"

FAKE_VOICE = VoiceScript(
    lesson_title="1.1",
    language="es",
    segments=[
        {"slide": 1, "text": "Bienvenidos."},
        {"slide": 2, "text": "Un modelo de lenguaje predice tokens."},
    ],
)


def _patch_media(monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr(
        "factory_agents.agents.script.run_script", lambda task_input, **kw: FAKE_SCRIPT
    )
    monkeypatch.setattr(
        "factory_agents.agents.voice.run_voice", lambda task_input, **kw: FAKE_VOICE
    )


def _run(auth_client, project_id, agent):
    job_id = auth_client.post(
        f"/api/projects/{project_id}/agent-runs", json={"agent": agent}
    ).json()["id"]
    return _wait_for_job(auth_client, job_id)


def _prepare_slides(auth_client, monkeypatch):
    """Project with slides via the faked content pipeline."""
    project = _create_project(auth_client)
    for agent in ("curator", "planner", "lessons", "slides"):
        job = _run(auth_client, project["id"], agent)
        assert job["status"] == "done", job["error"]
    return project


def test_script_and_voice_chain(auth_client, monkeypatch):
    _patch_media(monkeypatch)
    project = _prepare_slides(auth_client, monkeypatch)

    script_job = _run(auth_client, project["id"], "script")
    assert script_job["status"] == "done"
    assert len(script_job["result"]["artifact_ids"]) == 2  # one per lesson deck

    artifacts = auth_client.get(f"/api/projects/{project['id']}/artifacts").json()
    scripts = [a for a in artifacts if a["type"] == "teaching_script"]
    assert all(a["title"].startswith("Guion — ") for a in scripts)

    voice_job = _run(auth_client, project["id"], "voice")
    assert voice_job["status"] == "done"
    voice_artifact_id = voice_job["result"]["artifact_ids"][0]
    voice = auth_client.get(f"/api/artifacts/{voice_artifact_id}").json()
    assert voice["type"] == "voice_script"
    assert "segments" in voice["content"]


def test_script_requires_slides(auth_client, monkeypatch):
    _patch_media(monkeypatch)
    project = _create_project(auth_client)
    job = _run(auth_client, project["id"], "script")
    assert job["status"] == "failed"
    assert "slide_deck" in job["error"]


def test_video_job_with_mocked_media_tools(auth_client, monkeypatch, tmp_path):
    _patch_media(monkeypatch)

    class FakeProvider:
        cache_key = "fake"

        def __init__(self, *a, **kw):
            pass

        def synthesize(self, text):
            return b"ID3fakeaudio"

    def fake_images(deck_path, out_dir):
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        paths = []
        for i in (1, 2):
            p = out / f"slide.{i:03d}.png"
            p.write_bytes(b"PNG")
            paths.append(p)
        return paths

    def fake_compose(pairs, out_path, workdir):
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"MP4" + str(len(pairs)).encode())
        return out

    monkeypatch.setattr("factory_agents.tools.tts.OpenAITTSProvider", FakeProvider)
    monkeypatch.setattr(
        "factory_agents.tools.video.render_slide_images", fake_images
    )
    monkeypatch.setattr("factory_agents.tools.video.compose_video", fake_compose)
    monkeypatch.setattr(
        "factory_agents.tools.video.probe_duration", lambda path: 2.5
    )

    project = _prepare_slides(auth_client, monkeypatch)
    assert _run(auth_client, project["id"], "script")["status"] == "done"
    assert _run(auth_client, project["id"], "voice")["status"] == "done"

    video_job = _run(auth_client, project["id"], "video")
    assert video_job["status"] == "done", video_job["error"]
    assert len(video_job["result"]["artifact_ids"]) == 2

    artifacts = auth_client.get(f"/api/projects/{project['id']}/artifacts").json()
    videos = [a for a in artifacts if a["type"] == "video"]
    subtitles = [a for a in artifacts if a["type"] == "subtitles"]
    assert len(videos) == 2 and len(subtitles) == 2

    srt = auth_client.get(f"/api/artifacts/{subtitles[0]['id']}").json()
    assert "00:00:00,000 --> 00:00:02,500" in srt["content"]

    download = auth_client.get(f"/api/artifacts/{videos[0]['id']}/download")
    assert download.status_code == 200
    assert download.content.startswith(b"MP4")


def test_video_requires_voice_script(auth_client, monkeypatch):
    _patch_media(monkeypatch)
    project = _create_project(auth_client)
    job = _run(auth_client, project["id"], "video")
    assert job["status"] == "failed"
    assert "voice_script" in job["error"]
