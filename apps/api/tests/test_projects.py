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
