import pytest
from factory_agents.tools.palette import (
    DEFAULT_SLIDE_PALETTE,
    PALETTE_PRESETS,
    apply_slide_palette,
    normalize_hex,
    normalize_palette,
    palette_contrast,
    palette_css,
)


def test_palette_normalizes_hex_and_rejects_incomplete_or_alpha_values():
    assert normalize_hex("abc") == "#AABBCC"
    assert normalize_hex("#f8f1e3") == "#F8F1E3"
    with pytest.raises(ValueError, match="inválido"):
        normalize_hex("#11223344")
    with pytest.raises(ValueError, match="Faltan"):
        normalize_palette({"background": "#FFFFFF"})


def test_each_preset_produces_stable_canonical_css():
    for name, palette in PALETTE_PRESETS.items():
        css = palette_css(palette)
        assert "factory-slide-palette:start" in css, name
        assert f"--factory-background: {palette['background']}" in css
        assert "section {" in css
        assert "pre code" in css


def test_applying_palette_replaces_previous_block_and_preserves_marp_canvas():
    source = "---\nmarp: true\ntheme: factory-vertical\nsize: 9:16\n---\n\n# Hola\n"
    first = apply_slide_palette(source, DEFAULT_SLIDE_PALETTE)
    second = apply_slide_palette(first, PALETTE_PRESETS["dark"])

    assert second.count("factory-slide-palette:start") == 1
    assert "theme: factory-vertical" in second
    assert "size: 9:16" in second
    assert "--factory-background: #111827" in second
    assert "# Hola" in second


def test_contrast_reports_wcag_thresholds():
    result = palette_contrast(PALETTE_PRESETS["high_contrast"])
    assert result["text"]["passes"] is True
    assert result["headings"]["minimum"] == 3.0
    assert result["code"]["ratio"] == 21.0
