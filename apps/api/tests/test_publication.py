from pathlib import Path

from factory_agents.contracts.publication import PublicationPackage
from factory_api.artifact_versions import add_artifact_version
from factory_api.config import get_settings
from factory_api.db import SessionLocal
from factory_api.runner import extract_srt_timestamps
from test_media_pipeline import _patch_media, _prepare_slides, _run

FAKE_PACKAGE = PublicationPackage(
    video_title="Qué es un LLM — explicado con código",
    description="Aprende qué es un LLM.\n\nCapítulos:\n00:00 Intro",
    tags=["llm", "ia"],
    chapters=["00:00 Intro", "00:02 Concepto"],
    thumbnail_title="¿Qué es un LLM?",
    thumbnail_subtitle="Con código real",
)


def _patch_publication(monkeypatch, thumbnail_ok=True):
    _patch_media(monkeypatch)
    monkeypatch.setattr(
        "factory_agents.agents.publisher.run_publisher",
        lambda task_input, **kw: FAKE_PACKAGE,
    )

    def fake_thumbnail(title, subtitle, badge, out_path):
        if not thumbnail_ok:
            return None
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"PNG-THUMB")
        return out

    monkeypatch.setattr(
        "factory_agents.tools.thumbnail.render_thumbnail", fake_thumbnail
    )
    # Video stage mocks (reused from media tests)
    class FakeProvider:
        cache_key = "fake"

        def __init__(self, *a, **kw):
            pass

        def synthesize(self, text):
            return b"ID3"

    def fake_images(deck_path, out_dir):
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        paths = []
        for i in (1, 2):
            p = out / f"slide.{i:03d}.png"
            p.write_bytes(b"PNG")
            paths.append(p)
        return paths

    def fake_compose(pairs, out_path, workdir, orientation="horizontal", **_kwargs):
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"MP4")
        return out

    monkeypatch.setattr("factory_agents.tools.tts.OpenAITTSProvider", FakeProvider)
    monkeypatch.setattr("factory_agents.tools.video.render_slide_images", fake_images)
    monkeypatch.setattr("factory_agents.tools.video.compose_video", fake_compose)
    monkeypatch.setattr("factory_agents.tools.video.probe_duration", lambda p: 2.0)


def _project_with_video(auth_client, monkeypatch):
    project = _prepare_slides(auth_client, monkeypatch)
    for agent in ("script", "voice", "audio", "video"):
        job = _run(auth_client, project["id"], agent)
        assert job["status"] == "done", job["error"]
    return project


def _project_with_course_video(auth_client, monkeypatch):
    project = _project_with_video(auth_client, monkeypatch)
    settings = get_settings()
    relative = f"artifacts/{project['id']}/course-video.mp4"
    path = settings.data_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"COURSE-MP4")
    with SessionLocal() as db:
        add_artifact_version(
            db,
            project_id=project["id"],
            type_="course_video",
            format_="video",
            title="Vídeo completo",
            path=relative,
            metadata={"duration_seconds": 4.0},
        )
        db.commit()
    return project


def test_srt_timestamp_extraction():
    srt = (
        "1\n00:00:00,000 --> 00:00:02,000\nHola.\n\n"
        "2\n00:00:02,000 --> 01:02:03,500\nAdiós.\n"
    )
    assert extract_srt_timestamps(srt) == ["00:00", "00:02"]


def test_publisher_run_embeds_thumbnail_in_package(auth_client, monkeypatch):
    _patch_publication(monkeypatch)
    project = _project_with_course_video(auth_client, monkeypatch)

    job = _run(auth_client, project["id"], "publisher")
    assert job["status"] == "done", job["error"]

    artifacts = auth_client.get(f"/api/projects/{project['id']}/artifacts").json()
    packages = [a for a in artifacts if a["type"] == "publication_package"]
    thumbnails = [a for a in artifacts if a["type"] == "thumbnail"]
    assert len(packages) == 1 and thumbnails == []

    package = auth_client.get(f"/api/artifacts/{packages[0]['id']}").json()
    assert "video_title" in package["content"]
    assert package["metadata"]["video_artifact_id"]
    assert package["metadata"]["thumbnail"]["media_type"] == "image/png"
    thumbnail = auth_client.get(f"/api/artifacts/{package['id']}/thumbnail")
    assert thumbnail.status_code == 200
    assert thumbnail.content == b"PNG-THUMB"


def test_publisher_requires_video(auth_client, monkeypatch):
    _patch_publication(monkeypatch)
    from test_runs import _create_project

    project = _create_project(auth_client)
    response = auth_client.post(
        f"/api/projects/{project['id']}/agent-runs", json={"agent": "publisher"}
    )
    assert response.status_code == 409
    assert "course_video" in response.json()["detail"]


def test_youtube_status_and_publish_guardrails(auth_client, monkeypatch):
    _patch_publication(monkeypatch)
    # Other tests may have connected a fake token; disconnect for isolation.
    auth_client.delete("/api/youtube/connection")
    status = auth_client.get("/api/youtube/status").json()
    assert status == {"configured": False, "connected": False}

    # Publishing without configuration is refused
    project = _project_with_course_video(auth_client, monkeypatch)
    _run(auth_client, project["id"], "publisher")
    artifacts = auth_client.get(f"/api/projects/{project['id']}/artifacts").json()
    package = next(a for a in artifacts if a["type"] == "publication_package")
    resp = auth_client.post(
        "/api/youtube/publish", json={"package_artifact_id": package["id"]}
    )
    assert resp.status_code == 503

    # auth-url also requires configuration
    assert auth_client.get("/api/youtube/auth-url").status_code == 503


def test_wiki_crud(auth_client):
    from test_runs import _create_project

    project = _create_project(auth_client)
    assert auth_client.get(f"/api/projects/{project['id']}/wiki").json() == []

    resp = auth_client.put(
        f"/api/projects/{project['id']}/wiki/glosario",
        json={"title": "Glosario", "content_md": "- LLM: modelo grande de lenguaje"},
    )
    assert resp.status_code == 200
    assert resp.json()["slug"] == "glosario"

    # Upsert overwrites
    auth_client.put(
        f"/api/projects/{project['id']}/wiki/glosario",
        json={"title": "Glosario", "content_md": "- LLM: modelo de lenguaje grande"},
    )
    pages = auth_client.get(f"/api/projects/{project['id']}/wiki").json()
    assert len(pages) == 1
    assert "lenguaje grande" in pages[0]["content_md"]

    # User-level memory is separate
    auth_client.put(
        "/api/wiki/preferencias", json={"title": "Preferencias", "content_md": "- Español"}
    )
    user_slugs = {p["slug"] for p in auth_client.get("/api/wiki").json()}
    assert "preferencias" in user_slugs and "glosario" not in user_slugs
    assert len(auth_client.get(f"/api/projects/{project['id']}/wiki").json()) == 1

    assert (
        auth_client.delete(f"/api/projects/{project['id']}/wiki/glosario").status_code
        == 204
    )
    assert auth_client.get(f"/api/projects/{project['id']}/wiki").json() == []


def test_librarian_updates_wiki_after_job(auth_client, monkeypatch):
    from factory_agents.memory import WikiPageUpdate
    from factory_api.config import get_settings

    _patch_publication(monkeypatch)
    real = get_settings()
    monkeypatch.setattr(
        "factory_api.runner.get_settings",
        lambda: real.model_copy(update={"openrouter_api_key": "test-key"}),
    )
    monkeypatch.setattr("factory_agents.llm.get_llm_client", lambda key: object())
    monkeypatch.setattr(
        "factory_agents.memory.run_librarian",
        lambda client, model, pages, summary, excerpt: [
            WikiPageUpdate(
                slug="glosario", title="Glosario", content_md="- Token: unidad de texto"
            )
        ],
    )

    from test_runs import _create_project

    project = _create_project(auth_client)
    job = _run(auth_client, project["id"], "curator")
    assert job["status"] == "done"
    assert any(e["type"] == "memory" for e in job["events"])

    pages = auth_client.get(f"/api/projects/{project['id']}/wiki").json()
    assert pages and pages[0]["slug"] == "glosario"
    assert "Token" in pages[0]["content_md"]
