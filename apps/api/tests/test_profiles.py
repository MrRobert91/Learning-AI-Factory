import io

import pytest
from factory_agents.tools.images import GeneratedImage
from PIL import Image


def _logo_png(color=(178, 58, 38, 255)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (64, 48), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _logo_raster(format_: str) -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGBA", (64, 48), (178, 58, 38, 255))
    if format_ == "JPEG":
        image = image.convert("RGB")
    image.save(buffer, format=format_)
    return buffer.getvalue()


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
    assert slides[0]["slide_palette"]["background"] == "#F8F1E3"
    assert slides[0]["slide_palette"]["primary"] == "#B23A26"
    assert slides[0]["logo_mode"] == "none"
    assert slides[0]["active_logo_id"] is None
    assert slides[0]["logo_placement"] == "top-right"
    assert slides[0]["logo_candidates"] == []
    assert videos[0]["orientation"] == "horizontal"
    assert slides[0]["automatic_review_enabled"] is False
    assert slides[0]["max_automatic_regenerations"] == 0
    assert slides[0]["human_review_enabled"] is False


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


def test_slide_palette_is_normalized_and_versioned(auth_client):
    options = auth_client.get("/api/agents/palette-options")
    assert options.status_code == 200
    assert len(options.json()["presets"]) == 5
    palette = dict(options.json()["default"])
    palette["background"] = "abc"

    response = auth_client.post(
        "/api/agents/slides/profiles",
        json={"name": "Slides cálidas", "slide_palette": palette},
    )
    assert response.status_code == 201
    profile = response.json()
    assert profile["slide_palette"]["background"] == "#AABBCC"

    updated_palette = dict(profile["slide_palette"])
    updated_palette["primary"] = "#123456"
    updated = auth_client.patch(
        f"/api/agents/profiles/{profile['id']}",
        json={"slide_palette": updated_palette, "note": "Nueva marca"},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    versions = auth_client.get(
        f"/api/agents/profiles/{profile['id']}/versions"
    ).json()
    assert versions[0]["slide_palette"]["primary"] == "#123456"

    invalid = dict(updated_palette)
    invalid["links"] = "#12345678"
    assert (
        auth_client.patch(
            f"/api/agents/profiles/{profile['id']}",
            json={"slide_palette": invalid},
        ).status_code
        == 422
    )


def test_uploaded_logo_is_sanitized_versioned_and_protected(auth_client):
    profile = auth_client.post(
        "/api/agents/slides/profiles", json={"name": "Slides con marca"}
    ).json()
    uploaded = auth_client.post(
        f"/api/agents/profiles/{profile['id']}/logos/upload",
        files={"file": ("marca.png", _logo_png(), "image/png")},
        data={"name": "Marca principal"},
    )
    assert uploaded.status_code == 200, uploaded.text
    profile = uploaded.json()
    assert profile["version"] == 2
    assert len(profile["logo_candidates"]) == 1
    logo = profile["logo_candidates"][0]
    assert logo["source"] == "uploaded"
    assert logo["width"] == 64
    assert logo["height"] == 48
    assert len(logo["sha256"]) == 64

    thumbnail = auth_client.get(
        f"/api/agents/profiles/{profile['id']}/logos/{logo['id']}?thumbnail=true"
    )
    assert thumbnail.status_code == 200
    assert thumbnail.headers["content-type"].startswith("image/png")

    selected = auth_client.patch(
        f"/api/agents/profiles/{profile['id']}",
        json={
            "logo_mode": "uploaded",
            "active_logo_id": logo["id"],
            "logo_placement": "bottom-left",
            "logo_size": "large",
            "logo_margin_px": 40,
            "logo_opacity": 0.65,
            "logo_visibility": {"cover": True, "content": False, "summary": True},
            "note": "Activar marca",
        },
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["version"] == 3
    assert selected.json()["logo_mode"] == "uploaded"

    protected = auth_client.delete(
        f"/api/agents/profiles/{profile['id']}/logos/{logo['id']}"
    )
    assert protected.status_code == 409
    versions = auth_client.get(
        f"/api/agents/profiles/{profile['id']}/versions"
    ).json()
    assert versions[0]["active_logo_id"] == logo["id"]
    assert versions[0]["logo_visibility"]["content"] is False


@pytest.mark.parametrize(
    ("filename", "format_", "media_type"),
    [
        ("marca.png", "PNG", "image/png"),
        ("marca.webp", "WEBP", "image/webp"),
        ("marca.jpg", "JPEG", "image/jpeg"),
        ("marca.jpeg", "JPEG", "image/jpeg"),
    ],
)
def test_all_raster_logo_extensions_are_detected_from_content(
    auth_client, filename, format_, media_type
):
    profile = auth_client.post(
        "/api/agents/slides/profiles", json={"name": f"Slides {filename}"}
    ).json()
    response = auth_client.post(
        f"/api/agents/profiles/{profile['id']}/logos/upload",
        files={"file": (filename, _logo_raster(format_), media_type)},
    )
    assert response.status_code == 200, response.text
    assert response.json()["logo_candidates"][0]["media_type"] == media_type


def test_svg_logo_removes_active_content_and_unreferenced_candidate_can_be_deleted(
    auth_client,
):
    profile = auth_client.post(
        "/api/agents/slides/profiles", json={"name": "Slides SVG"}
    ).json()
    svg = b"""<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80"
      onclick="alert(1)"><script>alert(1)</script><image href="https://bad.test/x.png"/>
      <rect width="120" height="80" fill="#B23A26"/></svg>"""
    uploaded = auth_client.post(
        f"/api/agents/profiles/{profile['id']}/logos/upload",
        files={"file": ("marca.svg", svg, "image/svg+xml")},
    )
    assert uploaded.status_code == 200, uploaded.text
    logo = uploaded.json()["logo_candidates"][0]
    stored = auth_client.get(
        f"/api/agents/profiles/{profile['id']}/logos/{logo['id']}"
    )
    assert stored.status_code == 200
    assert b"script" not in stored.content.lower()
    assert b"onclick" not in stored.content.lower()
    assert b"https://bad.test" not in stored.content

    deleted = auth_client.delete(
        f"/api/agents/profiles/{profile['id']}/logos/{logo['id']}"
    )
    assert deleted.status_code == 200
    assert deleted.json()["logo_candidates"] == []


def test_generated_logo_uses_selected_model_without_changing_active_candidate(
    auth_client, monkeypatch
):
    calls = []

    def fake_generate(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return GeneratedImage(_logo_png(), "image/png", 0.031)

    monkeypatch.setattr("factory_api.routers.agents.generate_image", fake_generate)
    profile = auth_client.post(
        "/api/agents/slides/profiles",
        json={
            "name": "Slides logo IA",
            "image_model": "bytedance-seed/seedream-4.5",
        },
    ).json()
    generated = auth_client.post(
        f"/api/agents/profiles/{profile['id']}/logos/generate",
        json={"prompt": "Un faro geom\u00e9trico", "name": "Faro"},
    )
    assert generated.status_code == 200, generated.text
    candidate = generated.json()["logo_candidates"][0]
    assert candidate["source"] == "generated"
    assert candidate["model"] == "bytedance-seed/seedream-4.5"
    assert candidate["cost_usd"] == 0.031
    assert generated.json()["active_logo_id"] is None
    assert calls[0][1]["model"] == "bytedance-seed/seedream-4.5"


def test_logo_validation_rejects_mismatch_and_non_slide_configuration(auth_client):
    profile = auth_client.post(
        "/api/agents/slides/profiles", json={"name": "Slides logos inv\u00e1lidos"}
    ).json()
    mismatch = auth_client.post(
        f"/api/agents/profiles/{profile['id']}/logos/upload",
        files={"file": ("marca.jpg", _logo_png(), "image/jpeg")},
    )
    assert mismatch.status_code == 422
    curator = auth_client.post(
        "/api/agents/curator/profiles",
        json={"name": "Curador sin logo", "logo_mode": "none"},
    )
    assert curator.status_code == 422


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
            "human_review_enabled": True,
        },
    )
    assert response.status_code == 201
    profile = response.json()
    assert profile["automatic_review_enabled"] is True
    assert profile["max_automatic_regenerations"] == 5
    assert profile["human_review_enabled"] is True

    response = auth_client.patch(
        f"/api/agents/profiles/{profile['id']}",
        json={
            "automatic_review_enabled": False,
            "max_automatic_regenerations": 0,
            "human_review_enabled": False,
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
    assert versions[0]["human_review_enabled"] is False
    assert versions[1]["automatic_review_enabled"] is True
    assert versions[1]["max_automatic_regenerations"] == 5
    assert versions[1]["human_review_enabled"] is True

    assert (
        auth_client.patch(
            f"/api/agents/profiles/{profile['id']}",
            json={"max_automatic_regenerations": 6},
        ).status_code
        == 422
    )


def test_tts_catalog_and_voice_profile_configuration_are_closed_and_versioned(
    auth_client,
):
    options = auth_client.get("/api/agents/tts-options")
    assert options.status_code == 200
    models = options.json()["models"]
    assert {
        (item["provider"], item["model"])
        for item in models
    } == {
        ("openai", "gpt-4o-mini-tts"),
        ("openrouter", "hexgrad/kokoro-82m"),
        ("openrouter", "google/gemini-3.1-flash-tts-preview"),
        ("openrouter", "microsoft/mai-voice-2"),
    }

    response = auth_client.post(
        "/api/agents/voice/profiles",
        json={
            "name": "Narración económica",
            "tts_provider": "openrouter",
            "tts_model": "hexgrad/kokoro-82m",
            "tts_language": "es-ES",
            "tts_voice": "ef_dora",
        },
    )
    assert response.status_code == 201, response.text
    profile = response.json()
    assert profile["tts_available"] is True
    assert profile["tts_voice"] == "ef_dora"

    changed = auth_client.patch(
        f"/api/agents/profiles/{profile['id']}",
        json={
            "tts_model": "microsoft/mai-voice-2",
            "tts_language": "es-ES",
            "note": "Cambiar a MAI",
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["version"] == 2
    assert changed.json()["tts_voice"] == "es-ES-Marta:MAI-Voice-2"

    invalid = auth_client.patch(
        f"/api/agents/profiles/{profile['id']}",
        json={"tts_voice": "id-arbitrario"},
    )
    assert invalid.status_code == 422

    non_voice = auth_client.post(
        "/api/agents/curator/profiles",
        json={
            "name": "Curator inválido",
            "tts_provider": "openrouter",
        },
    )
    assert non_voice.status_code == 422

    versions = auth_client.get(
        f"/api/agents/profiles/{profile['id']}/versions"
    ).json()
    assert versions[0]["tts_model"] == "microsoft/mai-voice-2"
    assert versions[1]["tts_model"] == "hexgrad/kokoro-82m"


def test_video_subtitles_mode_defaults_to_none_and_is_versioned(auth_client):
    profile = auth_client.post(
        "/api/agents/video/profiles",
        json={"name": "Vídeo sin subtítulos"},
    ).json()
    assert profile["subtitles_mode"] == "none"

    updated = auth_client.patch(
        f"/api/agents/profiles/{profile['id']}",
        json={"subtitles_mode": "burned_and_srt", "note": "Activar subtítulos"},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["subtitles_mode"] == "burned_and_srt"

    versions = auth_client.get(
        f"/api/agents/profiles/{profile['id']}/versions"
    ).json()
    assert [item["subtitles_mode"] for item in versions] == [
        "burned_and_srt",
        "none",
    ]
    assert (
        auth_client.post(
            "/api/agents/voice/profiles",
            json={"name": "Voice inválido", "subtitles_mode": "srt"},
        ).status_code
        == 422
    )


def test_tts_preview_returns_audio_without_creating_a_profile_version(
    auth_client, monkeypatch
):
    class FakeProvider:
        last_generation_id = "gen-preview"

        def synthesize(self, text):
            assert text == "Hola desde la muestra"
            return b"ID3preview"

    monkeypatch.setattr(
        "factory_api.routers.agents.build_tts_provider",
        lambda *args, **kwargs: FakeProvider(),
    )
    profile = auth_client.post(
        "/api/agents/voice/profiles",
        json={"name": "Preview de voz"},
    ).json()
    response = auth_client.post(
        f"/api/agents/profiles/{profile['id']}/tts-preview",
        json={
            "text": "Hola desde la muestra",
            "tts_provider": "openai",
            "tts_model": "gpt-4o-mini-tts",
            "tts_language": "inherit",
            "tts_voice": "nova",
        },
    )
    assert response.status_code == 200, response.text
    assert response.content == b"ID3preview"
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert response.headers["x-generation-id"] == "gen-preview"
    assert (
        len(
            auth_client.get(
                f"/api/agents/profiles/{profile['id']}/versions"
            ).json()
        )
        == 1
    )


def test_unknown_agent_type(auth_client):
    assert auth_client.get("/api/agents/nope/profiles").status_code == 404
