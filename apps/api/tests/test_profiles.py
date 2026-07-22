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
    slides = auth_client.get("/api/agents/slides/profiles").json()
    videos = auth_client.get("/api/agents/video/profiles").json()
    assert slides[0]["orientation"] == "horizontal"
    assert slides[0]["images_enabled"] is False
    assert slides[0]["image_model"] == "bytedance-seed/seedream-4.5"
    assert slides[0]["image_style"] == "editorial_vector"
    assert videos[0]["orientation"] == "horizontal"
    assert slides[0]["automatic_review_enabled"] is False
    assert slides[0]["max_automatic_regenerations"] == 0


def test_slide_profile_image_configuration_is_versioned(auth_client):
    options = auth_client.get("/api/agents/image-options")
    assert options.status_code == 200
    assert len(options.json()["models"]) == 4
    assert len(options.json()["styles"]) == 5  # Four presets plus custom.

    response = auth_client.post(
        "/api/agents/slides/profiles",
        json={
            "name": "Slides ilustradas",
            "images_enabled": True,
            "image_model": "bytedance-seed/seedream-4.5",
            "image_style": "custom",
            "image_style_prompt": "Paper collage with cobalt and coral shapes",
        },
    )
    assert response.status_code == 201
    profile = response.json()
    assert profile["images_enabled"] is True
    assert profile["image_style"] == "custom"

    updated = auth_client.patch(
        f"/api/agents/profiles/{profile['id']}",
        json={"image_style": "isometric_3d", "image_style_prompt": "", "note": "3D"},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["image_style"] == "isometric_3d"

    invalid = auth_client.patch(
        f"/api/agents/profiles/{profile['id']}",
        json={"image_style": "custom", "image_style_prompt": ""},
    )
    assert invalid.status_code == 422


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


def test_automatic_review_policy_is_validated_and_versioned(auth_client):
    response = auth_client.post(
        "/api/agents/planner/profiles",
        json={
            "name": "Planner con revisión",
            "automatic_review_enabled": True,
            "max_automatic_regenerations": 5,
        },
    )
    assert response.status_code == 201
    profile = response.json()
    assert profile["automatic_review_enabled"] is True
    assert profile["max_automatic_regenerations"] == 5

    response = auth_client.patch(
        f"/api/agents/profiles/{profile['id']}",
        json={
            "automatic_review_enabled": False,
            "max_automatic_regenerations": 0,
            "note": "Desactivar revisión",
        },
    )
    assert response.status_code == 200
    assert response.json()["version"] == 2

    versions = auth_client.get(
        f"/api/agents/profiles/{profile['id']}/versions"
    ).json()
    assert versions[0]["automatic_review_enabled"] is False
    assert versions[0]["max_automatic_regenerations"] == 0
    assert versions[1]["automatic_review_enabled"] is True
    assert versions[1]["max_automatic_regenerations"] == 5

    assert (
        auth_client.patch(
            f"/api/agents/profiles/{profile['id']}",
            json={"max_automatic_regenerations": 6},
        ).status_code
        == 422
    )


def test_unknown_agent_type(auth_client):
    assert auth_client.get("/api/agents/nope/profiles").status_code == 404
