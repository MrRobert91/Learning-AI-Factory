"""Canonical logo injection for Marp slide decks."""

from __future__ import annotations

import html
import re

LOGO_BLOCK_START = "<!-- factory-logo:start -->"
LOGO_BLOCK_END = "<!-- factory-logo:end -->"
LOGO_BLOCK_RE = re.compile(
    rf"{re.escape(LOGO_BLOCK_START)}.*?{re.escape(LOGO_BLOCK_END)}\s*",
    re.DOTALL,
)
LOGO_IMAGE_RE = re.compile(r"\n?<img\s+class=\"factory-logo[^\"]*\"[^>]*>\s*", re.I)

_SIZE_PERCENT = {
    "horizontal": {"small": 8, "medium": 12, "large": 16},
    "vertical": {"small": 14, "medium": 19, "large": 24},
}


def _split_frontmatter(markdown: str) -> tuple[str, str]:
    normalized = markdown.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        return "", normalized
    match = re.search(r"\n---\s*\n", normalized[4:])
    if match is None:
        return "", normalized
    end = 4 + match.end()
    return normalized[:end].rstrip(), normalized[end:].strip()


def remove_slide_logo(markdown: str) -> str:
    """Remove only canonical logo markup, preserving all user-authored content."""
    return LOGO_IMAGE_RE.sub("", LOGO_BLOCK_RE.sub("", markdown)).rstrip() + "\n"


def apply_slide_logo(
    markdown: str,
    markdown_path: str,
    *,
    orientation: str,
    placement: str,
    size: str,
    margin_px: int,
    opacity: float,
    visibility: dict[str, bool],
    alt: str = "Logo de marca",
) -> str:
    """Inject one deterministic, portable logo into the selected slide kinds."""
    if orientation not in _SIZE_PERCENT:
        raise ValueError("Orientaci\u00f3n de logo desconocida")
    if placement not in {"top-left", "top-right", "bottom-left", "bottom-right"}:
        raise ValueError("Posici\u00f3n de logo desconocida")
    if size not in _SIZE_PERCENT[orientation]:
        raise ValueError("Tama\u00f1o de logo desconocido")
    if not 0 <= margin_px <= 128:
        raise ValueError("El margen del logo debe estar entre 0 y 128 px")
    if not 0 <= opacity <= 1:
        raise ValueError("La opacidad del logo debe estar entre 0 y 1")

    clean = remove_slide_logo(markdown)
    frontmatter, body = _split_frontmatter(clean)
    width = _SIZE_PERCENT[orientation][size]
    vertical, horizontal = placement.split("-")
    css = (
        f"{LOGO_BLOCK_START}\n<style>\n"
        ".factory-logo { position: absolute; z-index: 20; object-fit: contain; "
        "pointer-events: none; }\n"
        f".factory-logo {{ width: {width}%; max-height: {width}%; opacity: {opacity:.3f}; "
        f"{vertical}: {margin_px}px; {horizontal}: {margin_px}px; }}\n"
        "</style>\n"
        f"{LOGO_BLOCK_END}"
    )
    slides = re.split(r"(?m)^---\s*$", body)
    visible_slides: list[str] = []
    last = len(slides) - 1
    for index, slide in enumerate(slides):
        kind = "cover" if index == 0 else "summary" if index == last else "content"
        if visibility.get(kind, True):
            image = (
                f'<img class="factory-logo factory-logo-{placement}" '
                f'src="{html.escape(markdown_path, quote=True)}" '
                f'alt="{html.escape(alt, quote=True)}">'
            )
            slide = slide.rstrip() + "\n\n" + image + "\n"
        visible_slides.append(slide.strip())
    result = "\n\n".join(part for part in [frontmatter, css] if part)
    if visible_slides:
        result += "\n\n" + "\n\n---\n\n".join(visible_slides)
    return result.rstrip() + "\n"
