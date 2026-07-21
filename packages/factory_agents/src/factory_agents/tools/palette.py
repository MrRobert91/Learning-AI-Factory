"""Canonical slide palette validation, accessibility checks, and Marp CSS."""

from __future__ import annotations

import re
from collections.abc import Mapping

PALETTE_KEYS = (
    "background",
    "text",
    "headings",
    "primary",
    "secondary",
    "code_background",
    "code_text",
    "links",
)

PALETTE_PRESETS: dict[str, dict[str, str]] = {
    "factory": {
        "background": "#F8F1E3",
        "text": "#241D18",
        "headings": "#B23A26",
        "primary": "#B23A26",
        "secondary": "#2F6F5E",
        "code_background": "#2A2119",
        "code_text": "#F8F1E3",
        "links": "#8F2E1F",
    },
    "neutral_light": {
        "background": "#FFFFFF",
        "text": "#1F2937",
        "headings": "#111827",
        "primary": "#2563EB",
        "secondary": "#0F766E",
        "code_background": "#111827",
        "code_text": "#F9FAFB",
        "links": "#1D4ED8",
    },
    "dark": {
        "background": "#111827",
        "text": "#F9FAFB",
        "headings": "#FFFFFF",
        "primary": "#60A5FA",
        "secondary": "#34D399",
        "code_background": "#0B1020",
        "code_text": "#E5E7EB",
        "links": "#93C5FD",
    },
    "high_contrast": {
        "background": "#FFFFFF",
        "text": "#000000",
        "headings": "#000000",
        "primary": "#D00000",
        "secondary": "#005BBB",
        "code_background": "#000000",
        "code_text": "#FFFFFF",
        "links": "#0000EE",
    },
    "warm": {
        "background": "#FFF7ED",
        "text": "#292524",
        "headings": "#9A3412",
        "primary": "#EA580C",
        "secondary": "#0F766E",
        "code_background": "#292524",
        "code_text": "#FAFAF9",
        "links": "#C2410C",
    },
}

DEFAULT_SLIDE_PALETTE = PALETTE_PRESETS["factory"]
PRESET_LABELS = {
    "factory": "Factory",
    "neutral_light": "Neutro claro",
    "dark": "Oscuro",
    "high_contrast": "Alto contraste",
    "warm": "Cálido",
}

PALETTE_START = "<!-- factory-slide-palette:start -->"
PALETTE_END = "<!-- factory-slide-palette:end -->"
PALETTE_RE = re.compile(
    rf"{re.escape(PALETTE_START)}.*?{re.escape(PALETTE_END)}\s*",
    re.DOTALL,
)
HEX_RE = re.compile(r"^#?(?P<value>[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def normalize_hex(value: str) -> str:
    """Normalize three/six digit colors to uppercase six-digit HEX."""
    match = HEX_RE.fullmatch(str(value).strip())
    if match is None:
        raise ValueError(f"Color HEX inválido: {value!r}")
    raw = match.group("value")
    if len(raw) == 3:
        raw = "".join(char * 2 for char in raw)
    return f"#{raw.upper()}"


def normalize_palette(value: Mapping[str, str] | None) -> dict[str, str]:
    """Validate a complete palette; missing historical values use Factory."""
    if value is None:
        return dict(DEFAULT_SLIDE_PALETTE)
    missing = [key for key in PALETTE_KEYS if key not in value]
    extra = sorted(set(value) - set(PALETTE_KEYS))
    if missing:
        raise ValueError("Faltan colores de paleta: " + ", ".join(missing))
    if extra:
        raise ValueError("Colores de paleta desconocidos: " + ", ".join(extra))
    return {key: normalize_hex(value[key]) for key in PALETTE_KEYS}


def palette_preset_name(palette: Mapping[str, str]) -> str:
    normalized = normalize_palette(palette)
    return next(
        (name for name, preset in PALETTE_PRESETS.items() if preset == normalized),
        "custom",
    )


def _relative_luminance(color: str) -> float:
    raw = normalize_hex(color)[1:]
    channels = [int(raw[index : index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [
        channel / 12.92
        if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground: str, background: str) -> float:
    lighter, darker = sorted(
        (_relative_luminance(foreground), _relative_luminance(background)),
        reverse=True,
    )
    return round((lighter + 0.05) / (darker + 0.05), 2)


def palette_contrast(palette: Mapping[str, str]) -> dict[str, dict[str, object]]:
    normalized = normalize_palette(palette)
    checks = {
        "text": (normalized["text"], normalized["background"], 4.5),
        "headings": (normalized["headings"], normalized["background"], 3.0),
        "links": (normalized["links"], normalized["background"], 4.5),
        "code": (normalized["code_text"], normalized["code_background"], 4.5),
    }
    return {
        key: {
            "ratio": (ratio := contrast_ratio(foreground, background)),
            "minimum": minimum,
            "passes": ratio >= minimum,
        }
        for key, (foreground, background, minimum) in checks.items()
    }


def palette_warnings(palette: Mapping[str, str]) -> list[str]:
    labels = {
        "text": "texto sobre fondo",
        "headings": "títulos sobre fondo",
        "links": "enlaces sobre fondo",
        "code": "texto de código sobre fondo de código",
    }
    return [
        f"Contraste insuficiente para {labels[key]}: {check['ratio']}:1 "
        f"(mínimo {check['minimum']}:1)"
        for key, check in palette_contrast(palette).items()
        if not check["passes"]
    ]


def palette_css(palette: Mapping[str, str]) -> str:
    colors = normalize_palette(palette)
    variables = "\n".join(
        f"  --factory-{key.replace('_', '-')}: {value};"
        for key, value in colors.items()
    )
    return f"""{PALETTE_START}
<style>
:root {{
{variables}
}}
section {{
  background-color: var(--factory-background);
  color: var(--factory-text);
}}
h1, h2, h3, h4, h5, h6 {{ color: var(--factory-headings); }}
strong, mark {{ color: var(--factory-primary); }}
em, blockquote {{ color: var(--factory-secondary); }}
a, a:visited {{ color: var(--factory-links); }}
code {{
  background-color: var(--factory-code-background);
  color: var(--factory-code-text);
}}
pre {{ background-color: var(--factory-code-background); }}
pre code {{ background-color: transparent; color: var(--factory-code-text); }}
</style>
{PALETTE_END}"""


def apply_slide_palette(markdown: str, palette: Mapping[str, str]) -> str:
    """Insert or replace the canonical palette block in Marp Markdown."""
    clean = PALETTE_RE.sub("", markdown.replace("\r\n", "\n")).strip()
    lines = clean.splitlines()
    if lines and lines[0].strip() == "---":
        try:
            end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
        except StopIteration:
            end = -1
        if end > 0:
            frontmatter = "\n".join(lines[: end + 1])
            body = "\n".join(lines[end + 1 :]).strip()
            result = frontmatter + "\n\n" + palette_css(palette)
            if body:
                result += "\n\n" + body
            return result.rstrip() + "\n"
    return (palette_css(palette) + "\n\n" + clean).rstrip() + "\n"


def palette_options() -> dict:
    return {
        "default": dict(DEFAULT_SLIDE_PALETTE),
        "presets": [
            {"id": name, "label": PRESET_LABELS[name], "colors": dict(colors)}
            for name, colors in PALETTE_PRESETS.items()
        ],
    }
