import json

from factory_agents.agents.analyst import AnalystResult, ImprovementProposalDraft
from test_pipeline import _patch_all
from test_runs import _create_project, _wait_for_job

FAKE_RESULT = AnalystResult(
    report_md="# Informe\n\nLas intros largas pierden retención.",
    proposals=[
        ImprovementProposalDraft(
            kind="wiki",
            title="Aprendizajes del canal",
            slug="canal-aprendizajes",
            proposed_content="- Las intros de <30s retienen mejor.",
            evidence="Retención media 42% vs 61% en vídeos con intro corta.",
        ),
        ImprovementProposalDraft(
            kind="agents_md",
            title="Limitar la introducción del guion a 30 segundos",
            agent_type="script",
            proposed_content="- Limita la introducción a 30 segundos.\n- Resto igual.",
            evidence="3 comentarios piden ir al grano; caída de retención en el minuto 1.",
        ),
    ],
)


def _patch_analyst(monkeypatch, connected=True):
    _patch_all(monkeypatch)
    monkeypatch.setattr(
        "factory_agents.agents.analyst.run_analyst",
        lambda task_input, **kw: FAKE_RESULT,
    )
    monkeypatch.setattr(
        "factory_api.youtube.fetch_videos_data",
        lambda token, cid, cs, ids: [
            {
                "video_id": v,
                "title": f"Vídeo {v}",
                "stats": {"viewCount": "100"},
                "analytics": {"averageViewPercentage": 42.0},
                "comments": ["Muy útil", "Id al grano por favor"],
            }
            for v in ids
        ],
    )


def _connect_youtube(auth_client):
    """Insert a fake OAuth token directly (the flow itself needs Google)."""
    from factory_api.db import SessionLocal
    from factory_api.models import OAuthToken, User

    with SessionLocal() as db:
        if not db.query(OAuthToken).filter_by(provider="google").first():
            user = db.query(User).first()
            db.add(
                OAuthToken(
                    user_id=user.id,
                    provider="google",
                    token_json=json.dumps({"token": "t", "refresh_token": "r"}),
                )
            )
            db.commit()


def _fake_uploaded_video(project_id):
    """Simulate a completed upload job so the analyst has something to analyze."""
    from factory_api.db import SessionLocal
    from factory_api.models import Job

    with SessionLocal() as db:
        db.add(
            Job(
                kind="youtube_upload",
                project_id=project_id,
                status="done",
                payload_json="{}",
                result_json=json.dumps({"video_id": "abc123", "url": "https://youtu.be/abc123"}),
            )
        )
        db.commit()


def _run_analysis(auth_client, project_id):
    job_id = auth_client.post(f"/api/projects/{project_id}/analytics-runs").json()["id"]
    return _wait_for_job(auth_client, job_id)


def test_analytics_requires_connection(auth_client, monkeypatch):
    _patch_analyst(monkeypatch)
    project = _create_project(auth_client)
    resp = auth_client.post(f"/api/projects/{project['id']}/analytics-runs")
    assert resp.status_code == 409


def test_analyst_produces_report_and_proposals(auth_client, monkeypatch):
    _patch_analyst(monkeypatch)
    _connect_youtube(auth_client)
    project = _create_project(auth_client)
    _fake_uploaded_video(project["id"])

    job = _run_analysis(auth_client, project["id"])
    assert job["status"] == "done", job["error"]
    assert len(job["result"]["proposal_ids"]) == 2

    report = auth_client.get(f"/api/artifacts/{job['result']['artifact_id']}").json()
    assert report["type"] == "performance_report"
    assert "retención" in report["content"]

    proposals = auth_client.get("/api/improvements").json()
    kinds = {p["kind"] for p in proposals}
    assert kinds == {"wiki", "agents_md"}


def test_approve_wiki_proposal_updates_channel_memory(auth_client, monkeypatch):
    _patch_analyst(monkeypatch)
    _connect_youtube(auth_client)
    project = _create_project(auth_client)
    _fake_uploaded_video(project["id"])
    _run_analysis(auth_client, project["id"])

    proposals = auth_client.get("/api/improvements").json()
    wiki_proposal = next(p for p in proposals if p["kind"] == "wiki")
    resp = auth_client.post(f"/api/improvements/{wiki_proposal['id']}/approve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"

    user_wiki = auth_client.get("/api/wiki").json()
    page = next(p for p in user_wiki if p["slug"] == "canal-aprendizajes")
    assert "intros de <30s" in page["content_md"]

    # Already reviewed → 409
    assert (
        auth_client.post(f"/api/improvements/{wiki_proposal['id']}/approve").status_code
        == 409
    )


def test_approve_agents_md_proposal_bumps_profile_version(auth_client, monkeypatch):
    _patch_analyst(monkeypatch)
    _connect_youtube(auth_client)
    project = _create_project(auth_client)
    _fake_uploaded_video(project["id"])
    _run_analysis(auth_client, project["id"])

    proposals = auth_client.get("/api/improvements").json()
    proposal = next(p for p in proposals if p["kind"] == "agents_md")

    before = next(
        p for p in auth_client.get("/api/agents/script/profiles").json() if p["is_default"]
    )
    current = auth_client.get(f"/api/improvements/{proposal['id']}/current").json()
    assert current["current"] == before["agents_md"]

    resp = auth_client.post(f"/api/improvements/{proposal['id']}/approve")
    assert resp.status_code == 200
    assert resp.json()["applied_profile_id"] == before["id"]

    after = auth_client.get(f"/api/agents/profiles/{before['id']}").json()
    assert after["version"] == before["version"] + 1
    assert "30 segundos" in after["agents_md"]

    versions = auth_client.get(f"/api/agents/profiles/{before['id']}/versions").json()
    assert versions[0]["note"].startswith("Mejora continua")


def test_reject_proposal(auth_client, monkeypatch):
    _patch_analyst(monkeypatch)
    _connect_youtube(auth_client)
    project = _create_project(auth_client)
    _fake_uploaded_video(project["id"])
    _run_analysis(auth_client, project["id"])

    proposal = auth_client.get("/api/improvements").json()[0]
    resp = auth_client.post(f"/api/improvements/{proposal['id']}/reject")
    assert resp.json()["status"] == "rejected"
    pending = auth_client.get("/api/improvements").json()
    assert all(p["id"] != proposal["id"] for p in pending)


def test_analyst_requires_published_videos(auth_client, monkeypatch):
    _patch_analyst(monkeypatch)
    _connect_youtube(auth_client)
    project = _create_project(auth_client)
    job = _run_analysis(auth_client, project["id"])
    assert job["status"] == "failed"
    assert "publicados" in job["error"]
