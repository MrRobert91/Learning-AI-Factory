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
LOCAL_CLASS_RE = re.compile(
    r"<!--\s*_class:\s*(?P<classes>[^>]*?)\s*-->", re.I
)
LOGO_SLIDE_CLASS = "factory-has-logo"

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
    clean = LOGO_IMAGE_RE.sub("", LOGO_BLOCK_RE.sub("", markdown))

    def remove_logo_class(match: re.Match[str]) -> str:
        classes = [
            item
            for item in match.group("classes").split()
            if item != LOGO_SLIDE_CLASS
        ]
        return f"<!-- _class: {' '.join(classes)} -->" if classes else ""

    return LOCAL_CLASS_RE.sub(remove_logo_class, clean).rstrip() + "\n"


def _mark_logo_slide(slide: str) -> str:
    match = LOCAL_CLASS_RE.search(slide)
    if match is not None:
        classes = match.group("classes").split()
        if LOGO_SLIDE_CLASS not in classes:
            classes.append(LOGO_SLIDE_CLASS)
        directive = f"<!-- _class: {' '.join(classes)} -->"
        return slide[: match.start()] + directive + slide[match.end() :]
    return f"<!-- _class: {LOGO_SLIDE_CLASS} -->\n\n{slide.lstrip()}"


def _css_url(path: str) -> str:
    return path.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace(
        "\n", ""
    )


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
    css_path = _css_url(markdown_path)
    css = (
        f"{LOGO_BLOCK_START}\n<style>\n"
        "section { position: relative; }\n"
        f"section.{LOGO_SLIDE_CLASS} > img.factory-logo {{ "
        "position: absolute !important; z-index: 30 !important; display: block; "
        "object-fit: contain !important; pointer-events: none; "
        "transform: none !important; margin: 0 !important; padding: 0 !important; "
        "inset: auto !important; }\n"
        f"section.{LOGO_SLIDE_CLASS} > img.factory-logo {{ width: {width}% !important; "
        f"max-width: {width}% !important; max-height: {width}% !important; "
        f"opacity: {opacity:.3f}; {vertical}: {margin_px}px !important; "
        f"{horizontal}: {margin_px}px !important; }}\n"
        f"section.{LOGO_SLIDE_CLASS}[data-marpit-advanced-background=\"content\"] "
        "> img.factory-logo { display: none !important; }\n"
        f"section.{LOGO_SLIDE_CLASS}[data-marpit-advanced-background=\"pseudo\"]"
        f"::before {{ content: \"\" !important; display: block !important; "
        f"position: absolute !important; z-index: 30 !important; "
        f"width: {width}% !important; height: {width}% !important; "
        f"opacity: {opacity:.3f}; inset: auto !important; "
        f"{vertical}: {margin_px}px !important; {horizontal}: {margin_px}px !important; "
        f'background: url("{css_path}") center / contain no-repeat !important; }}\n'
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
            slide = _mark_logo_slide(slide)
        visible_slides.append(slide.strip())
    result = "\n\n".join(part for part in [frontmatter, css] if part)
    if visible_slides:
        result += "\n\n" + "\n\n---\n\n".join(visible_slides)
    return result.rstrip() + "\n"
