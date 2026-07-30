import base64
from pathlib import Path
from types import SimpleNamespace

import httpx
from factory_agents.tools import images, marp
from factory_agents.tools.images import GeneratedImage
from factory_agents.tools.marp import (
    inline_local_images,
    normalize_marp_canvas,
    prepared_marp_source,
    vertical_theme_path,
)


def _marker(prompt: str, layout: str = "right") -> str:
    return (
        '<!-- factory-image {"prompt":"'
        + prompt
        + '","layout":"'
        + layout
        + '","alt":"Concepto"} -->'
    )


def test_parse_image_slots_limits_cost_and_keeps_one_per_slide():
    slides = ["# Portada"]
    slides.append(f"# Uno\n{_marker('first')}\n{_marker('ignored duplicate')}")
    slides.extend(f"# Slide {index}\n{_marker(f'prompt {index}')}" for index in range(2, 9))
    deck = "---\nmarp: true\n---\n\n" + "\n---\n".join(slides)

    slots = images.parse_image_slots(deck)

    assert len(slots) == 6
    assert slots[0].slide_number == 2
    assert slots[0].prompt == "first"
    assert len({slot.slide_number for slot in slots}) == 6


def test_parse_image_slots_normalizes_background_and_invalid_layouts():
    deck = (
        "---\nmarp: true\n---\n\n"
        f"# Fondo\n{_marker('background request', 'background')}\n"
        "---\n"
        f"# Inválido\n{_marker('invalid request', 'center')}\n"
        "---\n"
        f"# Izquierda\n{_marker('left request', 'left')}\n"
    )

    slots = images.parse_image_slots(deck)

    assert [(slot.requested_layout, slot.layout) for slot in slots] == [
        ("background", "right"),
        ("center", "right"),
        ("left", "left"),
    ]


def test_generate_image_retries_twice_and_uses_supported_orientation(monkeypatch):
    monkeypatch.setattr(images.time, "sleep", lambda _seconds: None)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {
                        "b64_json": base64.b64encode(b"\x89PNG image").decode(),
                        "media_type": "image/png",
                    }
                ],
                "usage": {"cost": 0.04},
            }

    class FakeClient:
        def __init__(self):
            self.calls = []

        def post(self, _url, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) < 3:
                raise httpx.ConnectError("temporary failure")
            return FakeResponse()

    client = FakeClient()
    result = images.generate_image(
        "A concept",
        api_key="test",
        model="sourceful/riverflow-v2.5-fast",
        orientation="vertical",
        seed=123,
        client=client,
    )

    assert result.content.startswith(b"\x89PNG")
    assert result.cost_usd == 0.04
    assert len(client.calls) == 3
    assert "aspect_ratio" not in client.calls[-1]["json"]
    assert "seed" not in client.calls[-1]["json"]


def test_generate_image_keeps_default_seedream_payload_openrouter_compatible():
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {
                        "b64_json": base64.b64encode(b"\x89PNG image").decode(),
                        "media_type": "image/png",
                    }
                ],
                "usage": {"cost": 0.04},
            }

    class FakeClient:
        def post(self, _url, **kwargs):
            captured.update(kwargs["json"])
            return FakeResponse()

    images.generate_image(
        "A vertical slide concept",
        api_key="test",
        orientation="vertical",
        seed=123,
        client=FakeClient(),
    )

    assert captured == {
        "model": images.DEFAULT_IMAGE_MODEL,
        "prompt": "A vertical slide concept",
        "n": 1,
        "resolution": "1K",
        "seed": 123,
    }


def test_generate_deck_images_persists_assets_and_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(
        images,
        "generate_image",
        lambda *args, **kwargs: GeneratedImage(b"\x89PNG image", "image/png", 0.04),
    )
    deck = "---\nmarp: true\n---\n\n# Portada\n---\n# Concepto\n" + _marker(
        "A network of connected ideas"
    )

    updated, records = images.generate_deck_images(
        deck,
        api_key="test",
        model=images.DEFAULT_IMAGE_MODEL,
        style=images.DEFAULT_IMAGE_STYLE,
        custom_style_prompt="",
        orientation="horizontal",
        deck_identity="course:lesson",
        output_dir=tmp_path / "assets",
        markdown_asset_dir="assets",
        storage_asset_dir="artifacts/project/assets",
    )

    assert "factory-image-id: slide-2" in updated
    assert "![bg right:42%](assets/slide-2.png)" in updated
    assert "factory-side-image-layout:start" in updated
    assert "_class: factory-side-image factory-side-image-right" in updated
    assert "--factory-side-image-width: 42%" in updated
    assert records[0]["path"] == "artifacts/project/assets/slide-2.png"
    assert records[0]["prompt"] == "A network of connected ideas"
    assert records[0]["requested_layout"] == "right"
    assert records[0]["effective_layout"] == "right"
    assert (tmp_path / "assets" / "slide-2.png").is_file()


def test_vertical_generated_image_uses_narrower_panel_and_preserves_alt_metadata(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        images,
        "generate_image",
        lambda *args, **kwargs: GeneratedImage(b"\x89PNG image", "image/png", None),
    )
    deck = (
        "---\nmarp: true\ntheme: factory-vertical\nsize: 9:16\n---\n\n"
        f"# Concepto\n{_marker('A vertical concept', 'left')}"
    )

    updated, records = images.generate_deck_images(
        deck,
        api_key="test",
        model=images.DEFAULT_IMAGE_MODEL,
        style=images.DEFAULT_IMAGE_STYLE,
        custom_style_prompt="",
        orientation="vertical",
        deck_identity="course:vertical",
        output_dir=tmp_path / "assets",
        markdown_asset_dir="assets",
        storage_asset_dir="artifacts/project/assets",
    )

    assert "![bg left:32%](assets/slide-1.png)" in updated
    assert "--factory-side-image-width: 32%" in updated
    assert "padding-left: calc(" in updated
    assert "object-fit: cover" in updated
    assert "font-size: 1.55em" in updated
    assert records[0]["alt"] == "Concepto"


def test_explicit_historical_background_remains_unchanged():
    legacy = (
        "---\nmarp: true\n---\n\n# Histórico\n"
        "![bg brightness:0.42](legacy-background.jpg)\n"
    )

    assert images.strip_unprocessed_markers(legacy) == legacy
    assert "![bg brightness:0.42]" in images.apply_side_image_layout(
        legacy, "horizontal"
    )


def test_replacing_generated_image_keeps_one_side_directive_and_normalizes_background():
    deck = (
        "---\nmarp: true\n---\n\n# Concepto\n"
        "<!-- factory-image-id: slide-1 -->\n"
        "![bg brightness:0.42](old.png)\n"
    )

    updated = images.replace_generated_image(
        deck,
        "slide-1",
        "assets/new.png",
        layout="background",
        orientation="vertical",
    )
    updated = images.replace_generated_image(
        updated,
        "slide-1",
        "assets/newer.png",
        layout="right",
        orientation="vertical",
    )

    assert "brightness:0.42" not in updated
    assert "![bg right:32%](assets/newer.png)" in updated
    assert updated.count("_class: factory-side-image") == 1
    assert updated.count("factory-side-image-layout:start") == 1


def test_inline_local_images_makes_html_source_portable(tmp_path):
    image = tmp_path / "visual.png"
    image.write_bytes(b"\x89PNG image")

    result = inline_local_images("![bg right](visual.png)", tmp_path)

    assert "data:image/png;base64," in result
    assert "visual.png" not in result


def test_legacy_vertical_canvas_is_normalized_without_mutating_source(tmp_path):
    source = tmp_path / "legacy.md"
    legacy = (
        "---\nmarp: true\ntheme: default\nsize: 1080px 1920px\n---\n\n# Vertical\n"
    )
    source.write_text(legacy, encoding="utf-8")

    normalized = normalize_marp_canvas(legacy)
    assert "size: 1080px 1920px" not in normalized
    assert "theme: factory-vertical" in normalized
    assert "size: 9:16" in normalized
    theme = vertical_theme_path().read_text(encoding="utf-8")
    assert "@size 9:16 1080px 1920px" in theme
    assert "font-size: 42px" in theme

    with prepared_marp_source(source) as prepared:
        assert prepared != source
        assert "factory-vertical-canvas:start" in prepared.read_text(encoding="utf-8")
    assert source.read_text(encoding="utf-8") == legacy
    assert not list(tmp_path.glob(".*-render.md"))


def test_render_deck_registers_vertical_theme_and_marks_legacy_render_current(
    tmp_path, monkeypatch
):
    source = tmp_path / "legacy.md"
    legacy = "---\nmarp: true\nsize: 1080px 1920px\n---\n\n# Vertical\n"
    source.write_text(legacy, encoding="utf-8")
    commands = []
    prepared_sources = []
    monkeypatch.setattr(marp, "marp_available", lambda: True)

    def fake_run(command, **_kwargs):
        commands.append(command)
        prepared_sources.append(Path(command[1]).read_text(encoding="utf-8"))
        Path(command[command.index("-o") + 1]).write_bytes(b"render")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(marp.subprocess, "run", fake_run)
    rendered = marp.render_deck(source)

    assert set(rendered) == {"html", "pdf", "pptx"}
    assert all("--theme-set" in command for command in commands)
    assert all("theme: factory-vertical" in content for content in prepared_sources)
    assert marp.legacy_vertical_render_is_current(source)
    assert source.read_text(encoding="utf-8") == legacy


def test_failed_image_is_removed_from_deck_and_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(
        images,
        "generate_image",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            images.ImageGenerationError("provider unavailable")
        ),
    )
    events = []
    deck = "---\nmarp: true\n---\n\n# Concepto\n" + _marker("A visual")

    updated, records = images.generate_deck_images(
        deck,
        api_key="test",
        model=images.DEFAULT_IMAGE_MODEL,
        style=images.DEFAULT_IMAGE_STYLE,
        custom_style_prompt="",
        orientation="horizontal",
        deck_identity="course:lesson",
        output_dir=tmp_path / "assets",
        markdown_asset_dir="assets",
        storage_asset_dir="artifacts/project/assets",
        on_event=lambda *event: events.append(event),
    )

    assert records[0]["status"] == "failed"
    assert "factory-image-failed: slide-1" in updated
    assert any(event[0] == "warning" for event in events)
