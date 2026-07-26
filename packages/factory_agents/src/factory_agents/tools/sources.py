"""Deterministic source-corpus tools shared by ideation and Curator."""

import re
from collections.abc import Iterable
from typing import Any

MAX_TOOL_CHARS = 12000
_WORD_RE = re.compile(r"[\wáéíóúüñ]{2,}", re.IGNORECASE)
_LOCATION_RE = re.compile(r"^\[(Página|Diapositiva|Sección)\s+([^\]]+)\]\s*$")


def _tokens(value: str) -> set[str]:
    return {token.casefold() for token in _WORD_RE.findall(value)}


def _segments(document: dict[str, Any]) -> list[dict[str, str]]:
    text = str(document.get("text") or "")
    chunks: list[dict[str, str]] = []
    location = "documento"
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        content = "\n".join(buffer).strip()
        if content:
            chunks.append({"location": location, "text": content})
        buffer.clear()

    for line in text.splitlines():
        marker = _LOCATION_RE.match(line.strip())
        if marker:
            flush()
            location = f"{marker.group(1)} {marker.group(2)}"
            continue
        buffer.append(line)
        if sum(len(item) + 1 for item in buffer) >= 2200:
            flush()
    flush()
    return chunks or [{"location": "documento", "text": text}]


def list_source_documents(documents: Iterable[dict[str, Any]]) -> str:
    rows = []
    for document in documents:
        rows.append(
            "- "
            f"{document.get('id')}: {document.get('name')} "
            f"({document.get('kind')}, {document.get('size_bytes', 0)} bytes)"
        )
    return "\n".join(rows) if rows else "(no hay fuentes válidas)"


def search_source_documents(
    documents: Iterable[dict[str, Any]],
    query: str,
    *,
    max_results: int = 5,
) -> str:
    query_tokens = _tokens(query)
    ranked: list[tuple[int, str, str, str]] = []
    for document in documents:
        for segment in _segments(document):
            text = segment["text"]
            score = len(query_tokens & _tokens(text))
            if query_tokens and score == 0:
                continue
            ranked.append(
                (
                    score,
                    str(document.get("id")),
                    segment["location"],
                    text[:1800],
                )
            )
    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    if not ranked:
        return "(ningún extracto coincide; declara el hueco como no cubierto)"
    rendered = [
        f"[source:{source_id} {location}]\n{text}"
        for _, source_id, location, text in ranked[:max_results]
    ]
    return "\n\n".join(rendered)[:MAX_TOOL_CHARS]


def read_source_document(
    documents: Iterable[dict[str, Any]],
    source_id: str,
    location: str | None = None,
) -> str:
    document = next(
        (item for item in documents if str(item.get("id")) == source_id),
        None,
    )
    if document is None:
        return f"(fuente {source_id} no encontrada)"
    segments = _segments(document)
    if location:
        wanted = location.casefold()
        segments = [
            segment
            for segment in segments
            if wanted in segment["location"].casefold()
        ]
        if not segments:
            return f"(ubicación {location!r} no encontrada en source:{source_id})"
    rendered = [
        f"[source:{source_id} {segment['location']}]\n{segment['text']}"
        for segment in segments
    ]
    return "\n\n".join(rendered)[:MAX_TOOL_CHARS]
