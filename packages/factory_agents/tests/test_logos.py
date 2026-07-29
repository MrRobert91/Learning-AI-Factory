import pytest
from factory_agents.tools.logos import (
    apply_slide_logo,
    remove_slide_logo,
)

DECK = """---
marp: true
---

# Portada

---

## Contenido

---

## Resumen
"""


def test_apply_slide_logo_respects_visibility_and_safe_configuration():
    result = apply_slide_logo(
        DECK,
        "slide-assets/logo.png",
        orientation="vertical",
        placement="bottom-left",
        size="medium",
        margin_px=40,
        opacity=0.75,
        visibility={"cover": True, "content": False, "summary": True},
    )
    assert result.count('class="factory-logo') == 2
    assert "width: 19% !important" in result
    assert "bottom: 40px !important; left: 40px !important" in result
    assert "section.factory-has-logo > img.factory-logo" in result
    assert "inset: auto !important" in result
    assert result.count("factory-has-logo") >= 2
    assert "slide-assets/logo.png" in result


def test_reapplying_logo_replaces_canonical_markup():
    first = apply_slide_logo(
        DECK,
        "old.png",
        orientation="horizontal",
        placement="top-right",
        size="small",
        margin_px=32,
        opacity=1,
        visibility={"cover": True, "content": True, "summary": True},
    )
    second = apply_slide_logo(
        first,
        "new.png",
        orientation="horizontal",
        placement="top-left",
        size="large",
        margin_px=12,
        opacity=0.5,
        visibility={"cover": True, "content": True, "summary": True},
    )
    assert "old.png" not in second
    assert second.count("factory-logo:start") == 1
    assert second.count('class="factory-logo') == 3
    assert "new.png" in second
    assert "factory-logo" not in remove_slide_logo(second)


def test_logo_remains_canvas_anchored_with_side_image_layout():
    deck = DECK.replace(
        "## Contenido",
        (
            "<!-- _class: factory-side-image factory-side-image-right -->\n"
            "## Contenido\n\n![bg right:42%](side.png)"
        ),
    )
    result = apply_slide_logo(
        deck,
        "logo.png",
        orientation="horizontal",
        placement="bottom-right",
        size="small",
        margin_px=24,
        opacity=1,
        visibility={"cover": True, "content": True, "summary": True},
    )
    assert "factory-side-image-right" in result
    assert "position: absolute !important" in result
    assert "bottom: 24px !important; right: 24px !important" in result
    assert "z-index: 30 !important" in result
    assert (
        "_class: factory-side-image factory-side-image-right factory-has-logo"
        in result
    )
    assert 'data-marpit-advanced-background="pseudo"' in result


@pytest.mark.parametrize(
    ("placement", "position"),
    [
        ("top-left", "top: 16px !important; left: 16px !important"),
        ("top-right", "top: 16px !important; right: 16px !important"),
        ("bottom-left", "bottom: 16px !important; left: 16px !important"),
        ("bottom-right", "bottom: 16px !important; right: 16px !important"),
    ],
)
def test_all_logo_corners_are_explicitly_anchored(placement, position):
    result = apply_slide_logo(
        DECK,
        "logo.png",
        orientation="horizontal",
        placement=placement,
        size="small",
        margin_px=16,
        opacity=1,
        visibility={"cover": True, "content": True, "summary": True},
    )
    assert position in result


def test_hidden_side_slide_does_not_enable_full_canvas_logo_layer():
    deck = DECK.replace(
        "## Contenido",
        (
            "<!-- _class: factory-side-image factory-side-image-left -->\n"
            "## Contenido\n\n![bg left:42%](side.png)"
        ),
    )
    result = apply_slide_logo(
        deck,
        "logo.png",
        orientation="horizontal",
        placement="top-left",
        size="small",
        margin_px=16,
        opacity=1,
        visibility={"cover": True, "content": False, "summary": True},
    )
    content_slide = result.split("\n---\n")[2]
    assert "_class: factory-side-image factory-side-image-left -->" in content_slide
    assert "factory-has-logo" not in content_slide
