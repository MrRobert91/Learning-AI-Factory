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
    assert "width: 19%" in result
    assert "bottom: 40px; left: 40px" in result
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
