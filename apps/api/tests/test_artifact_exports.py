import io
import json
import zipfile
from pathlib import Path

from factory_agents.tools.images import GeneratedImage
from factory_api.config import get_settings
from factory_api.db import SessionLocal
from factory_api.models import Artifact
from factory_api.pdf_exports import LessonDocument, lessons_pdf
from pypdf import PdfReader
from test_runs import _create_project


def _upload(auth_client, project_id, type_, title, content):
    response = auth_client.post(
        f"/api/projects/{project_id}/artifacts",
        files={"file": ("artifact.md", content.encode("utf-8"), "text/markdown")},
        data={"type": type_, "title": title},
    )
    assert response.status_code == 201
    return response.json()


def test_artifact_edit_creates_version_and_lesson_pdf_exports(auth_client):
    project = _create_project(auth_client)
    original = _upload(
        auth_client,
        project["id"],
        "lesson_content",
        "1.1 Introduccion",
        """# Introduccion

Parrafo original.""",
    )

    fence = chr(96) * 3
    response = auth_client.patch(
        f"/api/artifacts/{original['id']}",
        json={
            "content": f"""# Introduccion

Parrafo editado que debe mantenerse completo.

{fence}python
print('hola')
{fence}
"""
        },
    )
    assert response.status_code == 200
    edited = response.json()
    assert edited["id"] != original["id"]
    assert edited["version"] == 2
    assert edited["is_selected"] is True
    assert len(edited["versions"]) == 2

    historical = auth_client.get(f"/api/artifacts/{original['id']}").json()
    assert historical["version"] == 1
    assert "Parrafo original" in historical["content"]
    assert historical["is_selected"] is False

    selected = auth_client.get(f"/api/projects/{project['id']}/artifacts").json()
    assert [item["id"] for item in selected] == [edited["id"]]

    pdf = auth_client.get(f"/api/artifacts/{edited['id']}/render/pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert len(PdfReader(io.BytesIO(pdf.content)).pages) >= 1

    _upload(
        auth_client,
        project["id"],
        "lesson_content",
        "1.2 Practica",
        """# Practica

Segundo contenido.""",
    )
    combined = auth_client.get(f"/api/projects/{project['id']}/exports/lessons.pdf")
    assert combined.status_code == 200
    assert len(PdfReader(io.BytesIO(combined.content)).pages) >= 2

    zipped = auth_client.get(f"/api/projects/{project['id']}/exports/lessons.zip")
    assert zipped.status_code == 200
    with zipfile.ZipFile(io.BytesIO(zipped.content)) as archive:
        names = archive.namelist()
        assert len(names) == 2
        assert all(name.endswith(".pdf") for name in names)


def test_slide_preview_and_bulk_exports_use_marp_renders(auth_client, monkeypatch):
    def fake_render(source):
        path = Path(source)
        outputs = {
            "html": path.with_suffix(".html"),
            "pdf": path.with_suffix(".pdf"),
            "pptx": path.with_suffix(".pptx"),
        }
        outputs["html"].write_text(
            "<html><body><section>Marp exact preview</section></body></html>",
            encoding="utf-8",
        )
        outputs["pdf"].write_bytes(lessons_pdf([LessonDocument(title="Slide", markdown="# Slide")]))
        outputs["pptx"].write_bytes(b"PPTX")
        return {format_: str(output) for format_, output in outputs.items()}

    monkeypatch.setattr("factory_api.routers.artifacts.render_deck", fake_render)

    project = _create_project(auth_client)
    first = _upload(
        auth_client,
        project["id"],
        "slide_deck",
        "1.1 Slides",
        """---
marp: true
---

# Primera""",
    )
    _upload(
        auth_client,
        project["id"],
        "slide_deck",
        "1.2 Slides",
        """---
marp: true
    assert preview.headers["content-disposition"].startswith("inline")
---

# Segunda""",
    )

    preview = auth_client.get(f"/api/artifacts/{first['id']}/render/html")
    assert preview.status_code == 200
    assert "Marp exact preview" in preview.text

    combined_pdf = auth_client.get(f"/api/projects/{project['id']}/exports/slides.pdf")
    assert combined_pdf.status_code == 200
    assert len(PdfReader(io.BytesIO(combined_pdf.content)).pages) == 2

    combined_pptx = auth_client.get(f"/api/projects/{project['id']}/exports/slides.pptx")
    assert combined_pptx.status_code == 200
    assert combined_pptx.content == b"PPTX"

    zipped = auth_client.get(f"/api/projects/{project['id']}/exports/slides.zip")
    assert zipped.status_code == 200
    with zipfile.ZipFile(io.BytesIO(zipped.content)) as archive:
        names = archive.namelist()
        assert len([name for name in names if name.endswith(".md")]) == 2
        assert len([name for name in names if name.endswith(".pdf")]) == 2
        assert len([name for name in names if name.endswith(".pptx")]) == 2

    assert auth_client.delete(f"/api/artifacts/{first['id']}").status_code == 204


def test_mixed_slide_orientations_block_combined_pptx(auth_client, monkeypatch):
    monkeypatch.setattr("factory_api.routers.artifacts.render_deck", lambda _path: {})
    project = _create_project(auth_client)
    _upload(
        auth_client,
        project["id"],
        "slide_deck",
        "Slides horizontales",
        "---\nmarp: true\nsize: 16:9\n---\n\n# Horizontal\n",
    )
    vertical = _upload(
        auth_client,
        project["id"],
        "slide_deck",
        "Slides verticales",
        "---\nmarp: true\nsize: 1080px 1920px\n---\n\n# Vertical\n",
    )
    with SessionLocal() as db:
        artifact = db.get(Artifact, vertical["id"])
        artifact.metadata_json = json.dumps(
            {"orientation": "vertical", "width": 1080, "height": 1920}
        )
        db.commit()

    response = auth_client.get(f"/api/projects/{project['id']}/exports/slides.pptx")

    assert response.status_code == 422
    assert "horizontales y verticales" in response.json()["detail"]
    assert "PDF o ZIP" in response.json()["detail"]


def test_legacy_vertical_markdown_download_uses_real_9_16_canvas(
    auth_client, monkeypatch
):
    monkeypatch.setattr("factory_api.routers.artifacts.render_deck", lambda _path: {})
    project = _create_project(auth_client)
    artifact = _upload(
        auth_client,
        project["id"],
        "slide_deck",
        "Slides verticales",
        "---\nmarp: true\nsize: 1080px 1920px\n---\n\n# Vertical\n",
    )
    with SessionLocal() as db:
        stored = db.get(Artifact, artifact["id"])
        stored.metadata_json = json.dumps(
            {"orientation": "vertical", "width": 1080, "height": 1920}
        )
        db.commit()

    response = auth_client.get(f"/api/artifacts/{artifact['id']}/download")

    assert response.status_code == 200
    assert "size: 1080px 1920px" not in response.text
    assert "theme: factory-vertical" in response.text
    assert "size: 9:16" in response.text

    zipped = auth_client.get(f"/api/projects/{project['id']}/exports/slides.zip")
    assert zipped.status_code == 200
    with zipfile.ZipFile(io.BytesIO(zipped.content)) as archive:
        assert "factory-vertical.css" in archive.namelist()
        theme = archive.read("factory-vertical.css").decode("utf-8")
        assert "@size 9:16 1080px 1920px" in theme


def test_regenerating_one_slide_image_creates_self_contained_deck_version(
    auth_client, monkeypatch
):
    monkeypatch.setattr("factory_api.routers.artifacts.render_deck", lambda _path: {})
    monkeypatch.setattr(
        "factory_api.routers.artifacts.generate_image",
        lambda *args, **kwargs: GeneratedImage(b"new-image", "image/jpeg", 0.04),
    )
    project = _create_project(auth_client)
    artifact = _upload(
        auth_client,
        project["id"],
        "slide_deck",
        "Slides — 1.1 Images",
        "---\nmarp: true\n---\n\n# Concepto\n",
    )
    settings = get_settings()
    asset_dir = settings.data_dir / "artifacts" / project["id"] / "slide-assets-test"
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / "slide-1.jpg").write_bytes(b"old-image")
    with SessionLocal() as db:
        stored = db.get(Artifact, artifact["id"])
        source = settings.data_dir / stored.path
        source.write_text(
            "---\nmarp: true\n---\n\n# Concepto\n"
            "<!-- factory-image-id: slide-1 -->\n"
            "![bg right:42%](slide-assets-test/slide-1.jpg)\n",
            encoding="utf-8",
        )
        stored.metadata_json = json.dumps(
            {
                "orientation": "horizontal",
                "images": [
                    {
                        "id": "slide-1",
                        "slide": 1,
                        "prompt": "Old prompt",
                        "layout": "right",
                        "alt": "Concept",
                        "model": "bytedance-seed/seedream-4.5",
                        "style": "editorial_vector",
                        "style_prompt": "Editorial vector style",
                        "seed": 42,
                        "path": (
                            f"artifacts/{project['id']}/slide-assets-test/slide-1.jpg"
                        ),
                        "markdown_path": "slide-assets-test/slide-1.jpg",
                        "media_type": "image/jpeg",
                        "status": "generated",
                    }
                ],
                "image_generation": {
                    "enabled": True,
                    "model": "bytedance-seed/seedream-4.5",
                    "style": "editorial_vector",
                },
            }
        )
        db.commit()

    response = auth_client.post(
        f"/api/artifacts/{artifact['id']}/images/slide-1/regenerate",
        json={"prompt": "A new visual metaphor"},
    )
    assert response.status_code == 200, response.text
    regenerated = response.json()
    assert regenerated["id"] != artifact["id"]
    assert regenerated["version"] == 2
    assert regenerated["metadata"]["images"][0]["prompt"] == "A new visual metaphor"
    assert "slide-assets-regen-" in regenerated["content"]

    new_image = auth_client.get(
        f"/api/artifacts/{regenerated['id']}/images/slide-1"
    )
    old_image = auth_client.get(f"/api/artifacts/{artifact['id']}/images/slide-1")
    assert new_image.content == b"new-image"
    assert old_image.content == b"old-image"
