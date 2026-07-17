import io
import zipfile
from pathlib import Path

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
