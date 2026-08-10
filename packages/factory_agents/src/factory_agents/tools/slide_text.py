"""Safe, text-only editing helpers for generated Marp slide decks."""

from __future__ import annotations

import re
from dataclasses import dataclass

from factory_agents.tools.images import SIDE_IMAGE_LAYOUT_RE
from factory_agents.tools.logos import LOGO_BLOCK_RE, LOGO_IMAGE_RE
from factory_agents.tools.palette import PALETTE_RE
from factory_agents.tools.slide_layout import (
    LOCAL_CLASS_RE,
    SAFE_AREA_RE,
    SIDE_IMAGE_RE,
)

SLIDE_SEPARATOR_RE = re.compile(r"(?m)^---\s*$")
FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*(?:\n|\Z)", re.DOTALL)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->\s*", re.DOTALL)
STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>.*?</style>\s*", re.IGNORECASE | re.DOTALL)
HTML_IMAGE_RE = re.compile(r"<img\b[^>]*>\s*", re.IGNORECASE | re.DOTALL)
MARKDOWN_IMAGE_RE = re.compile(r"(?m)^\s*!\[[^\]]*\]\([^\n)]+\)\s*$\n?")
FORBIDDEN_EDIT_RE = re.compile(
    r"(?im)^---\s*$|<!--|-->|<\s*/?\s*(?:style|img)\b"
)


@dataclass(frozen=True)
class EditableSlide:
    index: int
    content: str


def _frontmatter_and_body(markdown: str) -> tuple[str, str]:
    normalized = markdown.replace("\r\n", "\n")
    match = FRONTMATTER_RE.match(normalized)
    if match is None:
        return "", normalized
    return match.group(0).rstrip(), normalized[match.end() :]


def _protected_spans(slide: str) -> list[tuple[int, int]]:
    patterns = (
        PALETTE_RE,
        LOGO_BLOCK_RE,
        SAFE_AREA_RE,
        SIDE_IMAGE_LAYOUT_RE,
        SIDE_IMAGE_RE,
        LOGO_IMAGE_RE,
        LOCAL_CLASS_RE,
        STYLE_BLOCK_RE,
        HTML_IMAGE_RE,
        MARKDOWN_IMAGE_RE,
        HTML_COMMENT_RE,
    )
    spans: list[tuple[int, int]] = []
    for pattern in patterns:
        spans.extend(match.span() for match in pattern.finditer(slide))
    if not spans:
        return []
    spans.sort()
    merged = [spans[0]]
    for start, end in spans[1:]:
        previous_start, previous_end = merged[-1]
        if start <= previous_end:
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return merged


def _editable_bounds(slide: str, spans: list[tuple[int, int]]) -> tuple[int, int] | None:
    protected = bytearray(len(slide))
    for start, end in spans:
        protected[start:end] = b"\x01" * (end - start)
    editable = [
        index
        for index, character in enumerate(slide)
        if not protected[index] and not character.isspace()
    ]
    return (editable[0], editable[-1] + 1) if editable else None


def _editable_content(slide: str) -> str:
    spans = _protected_spans(slide)
    if not spans:
        return slide.strip()
    chunks: list[str] = []
    cursor = 0
    for start, end in spans:
        chunks.append(slide[cursor:start])
        cursor = end
    chunks.append(slide[cursor:])
    return re.sub(r"\n{3,}", "\n\n", "".join(chunks)).strip()


def extract_editable_slides(markdown: str) -> list[EditableSlide]:
    """Return only user-facing Markdown text, never Marp configuration or assets."""
    _frontmatter, body = _frontmatter_and_body(markdown)
    return [
        EditableSlide(index=index, content=_editable_content(slide))
        for index, slide in enumerate(SLIDE_SEPARATOR_RE.split(body), start=1)
    ]


def validate_slide_text(content: str) -> str:
    normalized = content.replace("\r\n", "\n").strip()
    if not normalized:
        raise ValueError("El texto de cada diapositiva no puede estar vacío")
    if FORBIDDEN_EDIT_RE.search(normalized):
        raise ValueError(
            "El texto no puede incluir separadores, comentarios, imágenes HTML ni estilos Marp"
        )
    return normalized


def _replace_one_slide(slide: str, content: str) -> str:
    spans = _protected_spans(slide)
    bounds = _editable_bounds(slide, spans)
    if bounds is None:
        protected = slide.strip()
        return f"{protected}\n\n{content}".strip() if protected else content
    first, last = bounds
    prefix = slide[:first].rstrip()
    suffix = slide[last:].lstrip()
    middle_protected = "\n\n".join(
        slide[start:end].strip()
        for start, end in spans
        if start >= first and end <= last and slide[start:end].strip()
    )
    pieces = [prefix, content, middle_protected, suffix]
    return "\n\n".join(piece for piece in pieces if piece).strip()


def replace_editable_slides(markdown: str, contents: list[str]) -> str:
    """Replace slide text while retaining every protected Marp and asset fragment."""
    frontmatter, body = _frontmatter_and_body(markdown)
    slides = SLIDE_SEPARATOR_RE.split(body)
    if len(contents) != len(slides):
        raise ValueError("El número de diapositivas ya no coincide con el artefacto")
    validated = [validate_slide_text(content) for content in contents]
    rebuilt = [
        _replace_one_slide(slide, content)
        for slide, content in zip(slides, validated, strict=True)
    ]
    deck = "\n\n---\n\n".join(rebuilt)
    return "\n\n".join(part for part in (frontmatter, deck) if part).rstrip() + "\n"
