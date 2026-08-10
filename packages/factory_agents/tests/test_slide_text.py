import pytest
from factory_agents.tools.images import apply_side_image_layout
from factory_agents.tools.logos import apply_slide_logo
from factory_agents.tools.palette import DEFAULT_SLIDE_PALETTE, apply_slide_palette
from factory_agents.tools.slide_layout import apply_slide_safe_area
from factory_agents.tools.slide_text import (
    extract_editable_slides,
    replace_editable_slides,
    validate_slide_text,
)


def _decorated_deck() -> str:
    deck = """---
marp: true
theme: default
---

# Portada

Texto inicial.

---

<!-- _class: factory-side-image factory-side-image-right -->

## Concepto

- Punto uno
- Punto dos

<!-- factory-image-id: slide-2 -->
![bg right:42%](assets/slide-2.png)
"""
    deck = apply_slide_palette(deck, DEFAULT_SLIDE_PALETTE)
    deck = apply_side_image_layout(deck, "horizontal")
    deck = apply_slide_safe_area(deck, "horizontal")
    return apply_slide_logo(
        deck,
        "assets/logo.png",
        orientation="horizontal",
        placement="top-right",
        size="small",
        margin_px=32,
        opacity=1,
        visibility={"cover": True, "content": True, "summary": True},
    )


def test_extract_editable_slides_hides_marp_styles_assets_and_directives():
    slides = extract_editable_slides(_decorated_deck())

    assert [slide.index for slide in slides] == [1, 2]
    assert slides[0].content == "# Portada\n\nTexto inicial."
    assert slides[1].content == "## Concepto\n\n- Punto uno\n- Punto dos"
    assert all("factory-" not in slide.content for slide in slides)
    assert all("<style>" not in slide.content for slide in slides)
    assert all("assets/" not in slide.content for slide in slides)


def test_replace_editable_slides_preserves_protected_deck_fragments():
    original = _decorated_deck()
    updated = replace_editable_slides(
        original,
        ["# Portada editada\n\nNuevo texto.", "## Concepto editado\n\n- Único punto"],
    )

    assert "# Portada editada" in updated
    assert "## Concepto editado" in updated
    assert "Texto inicial" not in updated
    assert updated.count("factory-slide-palette:start") == 1
    assert updated.count("factory-safe-area:start") == 1
    assert updated.count("factory-side-image-layout:start") == 1
    assert updated.count("factory-logo:start") == 1
    assert "assets/slide-2.png" in updated
    assert "assets/logo.png" in updated
    assert len(extract_editable_slides(updated)) == 2


@pytest.mark.parametrize(
    "content",
    [
        "# Título\n\n---\n\nOtra slide",
        "# Título\n\n<style>section { color: red; }</style>",
        "# Título\n\n<!-- _class: lead -->",
        '# Título\n\n<img src="logo.png">',
    ],
)
def test_validate_slide_text_rejects_marp_control_syntax(content):
    with pytest.raises(ValueError):
        validate_slide_text(content)
