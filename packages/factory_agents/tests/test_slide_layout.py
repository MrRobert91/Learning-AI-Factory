import base64
from pathlib import Path

import pytest
from factory_agents.agents.slides import apply_slide_orientation
from factory_agents.tools.images import apply_side_image_layout
from factory_agents.tools.logos import apply_slide_logo
from factory_agents.tools.slide_layout import (
    SlideMeasurement,
    SlideOverflowError,
    apply_slide_safe_area,
    fit_and_validate_slide_deck,
    slide_layout_available,
)


def _measurement(slide_number: int, overflow: float = 0) -> SlideMeasurement:
    return SlideMeasurement(
        slide_number=slide_number,
        available_height=500,
        content_height=500 + overflow,
        overflow_px=overflow,
    )


def test_safe_area_is_canonical_and_orientation_specific():
    deck = "---\nmarp: true\n---\n\n# Hola\n"
    horizontal = apply_slide_safe_area(deck, "horizontal")
    vertical = apply_slide_safe_area(horizontal, "vertical")

    assert horizontal.count("factory-safe-area:start") == 1
    assert "--factory-safe-bottom: 88px" in horizontal
    assert vertical.count("factory-safe-area:start") == 1
    assert "--factory-safe-bottom: 160px" in vertical
    assert "--factory-safe-bottom: 88px" not in vertical


def test_overflow_uses_fit_levels_before_splitting(tmp_path: Path):
    source = tmp_path / "deck.md"
    source.write_text("---\nmarp: true\n---\n\n# Título\n\nTexto\n", encoding="utf-8")

    def measure(path: Path) -> list[SlideMeasurement]:
        markdown = path.read_text(encoding="utf-8")
        overflow = 0 if "<!-- _class: factory-fit-2 -->" in markdown else 25
        return [_measurement(1, overflow)]

    result = fit_and_validate_slide_deck(
        source, orientation="horizontal", measure=measure
    )

    assert "factory-fit-2" in result.markdown
    assert result.metadata["adjustments"] == [
        {
            "slide": 1,
            "action": "font_fit",
            "fit_level": 2,
            "font_size_px": 25,
        }
    ]


def test_long_list_splits_between_items_after_minimum_fit(tmp_path: Path):
    source = tmp_path / "deck.md"
    source.write_text(
        "---\nmarp: true\n---\n\n# Pasos\n\n- Uno\n- Dos\n- Tres\n",
        encoding="utf-8",
    )

    def measure(path: Path) -> list[SlideMeasurement]:
        markdown = path.read_text(encoding="utf-8")
        body = markdown.split("factory-safe-area:end -->", 1)[1]
        slides = body.split("\n---\n")
        measurements = []
        for index, slide in enumerate(slides, 1):
            item_count = slide.count("\n- ")
            overflow = 20 if item_count > 1 else 0
            measurements.append(_measurement(index, overflow))
        return measurements

    result = fit_and_validate_slide_deck(
        source, orientation="horizontal", measure=measure
    )

    assert result.metadata["slides_before"] == 1
    assert result.metadata["slides_after"] == 3
    assert "Pasos (continuación 2)" in result.markdown
    assert "Pasos (continuación 3)" in result.markdown


def test_indivisible_code_block_fails_with_actionable_slide(tmp_path: Path):
    source = tmp_path / "deck.md"
    source.write_text(
        "---\nmarp: true\n---\n\n# Código\n\n```python\nprint('x')\n```\n",
        encoding="utf-8",
    )

    def measure(_path: Path) -> list[SlideMeasurement]:
        return [_measurement(1, 10)]

    with pytest.raises(SlideOverflowError, match="slide 1.*código"):
        fit_and_validate_slide_deck(
            source, orientation="horizontal", measure=measure
        )


@pytest.mark.skipif(not slide_layout_available(), reason="Marp/Chromium unavailable")
def test_real_marp_measurement_keeps_short_deck_inside_safe_area(tmp_path: Path):
    source = tmp_path / "deck.md"
    source.write_text(
        "---\nmarp: true\ntheme: default\nsize: 16:9\n---\n\n"
        "# Área segura real\n\n- Uno\n- Dos\n",
        encoding="utf-8",
    )

    result = fit_and_validate_slide_deck(source, orientation="horizontal")

    assert result.metadata["status"] == "passed"
    assert result.metadata["measurements"][0]["overflow_px"] <= 1


@pytest.mark.skipif(not slide_layout_available(), reason="Marp/Chromium unavailable")
def test_real_marp_measurement_splits_dense_list_without_clipping(tmp_path: Path):
    source = tmp_path / "dense.md"
    bullets = "\n".join(
        f"- Punto {index}: explicación suficientemente extensa para ocupar espacio vertical."
        for index in range(1, 25)
    )
    source.write_text(
        "---\nmarp: true\ntheme: default\nsize: 16:9\n---\n\n"
        f"# Lista densa\n\n{bullets}\n",
        encoding="utf-8",
    )

    result = fit_and_validate_slide_deck(source, orientation="horizontal")

    assert result.metadata["slides_after"] > 1
    assert all(item["overflow_px"] <= 1 for item in result.metadata["measurements"])
    assert "continuación" in result.markdown


@pytest.mark.parametrize("orientation", ["horizontal", "vertical"])
@pytest.mark.skipif(not slide_layout_available(), reason="Marp/Chromium unavailable")
def test_real_measurement_preserves_side_image_and_bottom_logo(
    tmp_path: Path, orientation: str
):
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUB"
        "AScY42YAAAAASUVORK5CYII="
    )
    (tmp_path / "visual.png").write_bytes(png)
    (tmp_path / "logo.png").write_bytes(png)
    deck = apply_slide_orientation(
        "---\nmarp: true\n---\n\n"
        "<!-- _class: factory-side-image factory-side-image-right -->\n"
        "![bg right:42%](visual.png)\n\n"
        "# Diseño seguro\n\n- Texto visible\n- Otro punto\n",
        orientation,
    )
    deck = apply_side_image_layout(deck, orientation)
    deck = apply_slide_logo(
        deck,
        "logo.png",
        orientation=orientation,
        placement="bottom-left",
        size="small",
        margin_px=24,
        opacity=1,
        visibility={"cover": True, "content": True, "summary": True},
    )
    source = tmp_path / f"{orientation}.md"
    source.write_text(deck, encoding="utf-8")

    result = fit_and_validate_slide_deck(source, orientation=orientation)

    assert len(result.metadata["measurements"]) == 1
    assert result.metadata["measurements"][0]["overflow_px"] <= 1
    assert "factory-side-image-right" in result.markdown
    assert "factory-logo-bottom" in result.markdown
