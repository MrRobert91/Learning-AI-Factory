import base64

import httpx
from factory_agents.tools import images
from factory_agents.tools.images import GeneratedImage
from factory_agents.tools.marp import inline_local_images


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


def test_generate_image_retries_twice_and_uses_orientation(monkeypatch):
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
        orientation="vertical",
        seed=123,
        client=client,
    )

    assert result.content.startswith(b"\x89PNG")
    assert result.cost_usd == 0.04
    assert len(client.calls) == 3
    assert client.calls[-1]["json"]["aspect_ratio"] == "9:16"
    assert client.calls[-1]["json"]["seed"] == 123


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
    assert records[0]["path"] == "artifacts/project/assets/slide-2.png"
    assert records[0]["prompt"] == "A network of connected ideas"
    assert (tmp_path / "assets" / "slide-2.png").is_file()


def test_inline_local_images_makes_html_source_portable(tmp_path):
    image = tmp_path / "visual.png"
    image.write_bytes(b"\x89PNG image")

    result = inline_local_images("![bg right](visual.png)", tmp_path)

    assert "data:image/png;base64," in result
    assert "visual.png" not in result


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
