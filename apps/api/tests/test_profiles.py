def test_agent_catalog(auth_client):
    resp = auth_client.get("/api/agents")
    assert resp.status_code == 200
    names = {a["name"] for a in resp.json()}
    assert {"ideation", "curator"} <= names


def test_default_profiles_seeded(auth_client):
    resp = auth_client.get("/api/agents/curator/profiles")
    assert resp.status_code == 200
    profiles = resp.json()
    assert len(profiles) >= 1
    assert any(p["is_default"] for p in profiles)
    assert profiles[0]["soul_md"]


def test_profile_crud_and_versioning(auth_client):
    resp = auth_client.post(
        "/api/agents/curator/profiles",
        json={"name": "Curador divulgativo", "soul_md": "Cercano", "agents_md": "- Breve"},
    )
    assert resp.status_code == 201
    profile = resp.json()
    assert profile["version"] == 1

    # Content change bumps version and snapshots it
    resp = auth_client.patch(
        f"/api/agents/profiles/{profile['id']}",
        json={"soul_md": "Cercano y con humor", "note": "más humor"},
    )
    assert resp.status_code == 200
    assert resp.json()["version"] == 2

    # Name-only change does not bump version
    resp = auth_client.patch(
        f"/api/agents/profiles/{profile['id']}", json={"name": "Curador pop"}
    )
    assert resp.json()["version"] == 2

    versions = auth_client.get(f"/api/agents/profiles/{profile['id']}/versions").json()
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["note"] == "más humor"

    # Make it default, then deleting is refused
    resp = auth_client.patch(
        f"/api/agents/profiles/{profile['id']}", json={"is_default": True}
    )
    assert resp.json()["is_default"] is True
    assert auth_client.delete(f"/api/agents/profiles/{profile['id']}").status_code == 409

    # Restore factory default and delete the custom one
    factory = [
        p
        for p in auth_client.get("/api/agents/curator/profiles").json()
        if p["id"] != profile["id"]
    ][0]
    auth_client.patch(f"/api/agents/profiles/{factory['id']}", json={"is_default": True})
    assert auth_client.delete(f"/api/agents/profiles/{profile['id']}").status_code == 204


def test_unknown_agent_type(auth_client):
    assert auth_client.get("/api/agents/nope/profiles").status_code == 404
