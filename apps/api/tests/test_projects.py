def test_projects_require_auth(client):
    assert client.get("/api/projects").status_code == 401


def test_project_crud(auth_client):
    payload = {
        "title": "Intro a los LLMs",
        "topic": "Modelos de lenguaje",
        "audience": "Perfiles técnicos",
        "level": "intermedio",
        "language": "es",
        "style": "práctico",
        "output_format": "video",
        "duration_spec": {
            "preset": "standard",
            "module_count": 99,
            "videos_per_module": 99,
            "target_minutes_per_video": 99,
        },
    }
    resp = auth_client.post("/api/projects", json=payload)
    assert resp.status_code == 201
    project = resp.json()
    project_id = project["id"]
    assert project["title"] == payload["title"]
    assert project["status"] == "draft"
    assert project["duration_spec"]["module_count"] == 3
    assert project["duration_spec"]["total_videos"] == 12

    resp = auth_client.get("/api/projects")
    assert resp.status_code == 200
    assert any(p["id"] == project_id for p in resp.json())

    resp = auth_client.patch(f"/api/projects/{project_id}", json={"level": "avanzado"})
    assert resp.status_code == 200
    assert resp.json()["level"] == "avanzado"
    assert resp.json()["title"] == payload["title"]

    resp = auth_client.get(f"/api/projects/{project_id}")
    assert resp.status_code == 200

    resp = auth_client.delete(f"/api/projects/{project_id}")
    assert resp.status_code == 204
    assert auth_client.get(f"/api/projects/{project_id}").status_code == 404


def test_create_project_requires_title(auth_client):
    resp = auth_client.post("/api/projects", json={"title": ""})
    assert resp.status_code == 422


def test_selected_workflow_persists_per_project(auth_client):
    first = auth_client.post("/api/projects", json={"title": "Proyecto uno"}).json()
    second = auth_client.post("/api/projects", json={"title": "Proyecto dos"}).json()
    workflows = auth_client.get("/api/workflows").json()
    full_video = next(
        workflow
        for workflow in workflows
        if workflow["name"] == "Curso completo con vídeo"
    )
    research = next(
        workflow for workflow in workflows if workflow["name"] == "Investigación y plan"
    )

    assert first["selected_workflow_id"] is None
    assert second["selected_workflow_id"] is None

    response = auth_client.patch(
        f"/api/projects/{first['id']}",
        json={"selected_workflow_id": full_video["id"]},
    )
    assert response.status_code == 200
    assert response.json()["selected_workflow_id"] == full_video["id"]

    # Repeating the same selection is idempotent.
    repeated = auth_client.patch(
        f"/api/projects/{first['id']}",
        json={"selected_workflow_id": full_video["id"]},
    )
    assert repeated.status_code == 200
    assert repeated.json()["selected_workflow_id"] == full_video["id"]

    auth_client.patch(
        f"/api/projects/{second['id']}",
        json={"selected_workflow_id": research["id"]},
    )
    projects = {
        project["id"]: project for project in auth_client.get("/api/projects").json()
    }
    assert projects[first["id"]]["selected_workflow_id"] == full_video["id"]
    assert projects[second["id"]]["selected_workflow_id"] == research["id"]


def test_selected_workflow_validates_format_availability_and_deletion(auth_client):
    project = auth_client.post(
        "/api/projects", json={"title": "Preferencia de workflow"}
    ).json()

    invalid = auth_client.patch(
        f"/api/projects/{project['id']}",
        json={"selected_workflow_id": "not-an-id"},
    )
    assert invalid.status_code == 422

    missing = auth_client.patch(
        f"/api/projects/{project['id']}",
        json={"selected_workflow_id": "f" * 32},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Workflow no encontrado"

    custom = auth_client.post(
        "/api/workflows",
        json={"name": "Workflow eliminable", "steps": [{"agent": "curator"}]},
    ).json()
    selected = auth_client.patch(
        f"/api/projects/{project['id']}",
        json={"selected_workflow_id": custom["id"]},
    )
    assert selected.status_code == 200
    assert selected.json()["selected_workflow_id"] == custom["id"]

    assert auth_client.delete(f"/api/workflows/{custom['id']}").status_code == 204
    assert (
        auth_client.get(f"/api/projects/{project['id']}").json()[
            "selected_workflow_id"
        ]
        is None
    )
