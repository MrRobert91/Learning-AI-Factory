"""OpenRouter image generation and slide-image marker handling."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import mimetypes
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

OPENROUTER_IMAGES_URL = "https://openrouter.ai/api/v1/images"
DEFAULT_IMAGE_MODEL = "bytedance-seed/seedream-4.5"
DEFAULT_IMAGE_STYLE = "editorial_vector"
MAX_IMAGES_PER_DECK = 6
IMAGE_REQUEST_ATTEMPTS = 3  # Initial request plus two retries.

IMAGE_MODEL_OPTIONS: dict[str, dict[str, Any]] = {
    "bytedance-seed/seedream-4.5": {
        "label": "Seedream 4.5",
        "price_hint": "≈ $0.04 por imagen",
        # The current OpenRouter endpoint for Seedream exposes resolution + seed, but
        # rejects aspect_ratio with HTTP 400. Keep slide orientation in the prompt
        # instead of sending an unsupported request parameter.
        "supports_aspect_ratio": False,
        "supports_seed": True,
        "request": {"resolution": "1K"},
    },
    "sourceful/riverflow-v2.5-fast": {
        "label": "Riverflow V2.5 Fast",
        "price_hint": "≈ $0.019 por imagen 1K",
        "supports_aspect_ratio": False,
        "supports_seed": False,
        "request": {"resolution": "1K", "output_format": "jpeg"},
    },
    "black-forest-labs/flux.2-klein-4b": {
        "label": "FLUX.2 Klein 4B",
        "price_hint": "≈ $0.014 por megapíxel",
        "supports_aspect_ratio": False,
        "supports_seed": True,
        "request": {"output_format": "jpeg"},
    },
    "recraft/recraft-v4": {
        "label": "Recraft V4",
        "price_hint": "≈ $0.04 por imagen",
        "supports_aspect_ratio": False,
        "supports_seed": False,
        "request": {},
    },
}

IMAGE_STYLE_PRESETS: dict[str, dict[str, str]] = {
    "editorial_vector": {
        "label": "Ilustración vectorial editorial",
        "prompt": (
            "Editorial vector illustration for a premium educational presentation. "
            "Clean geometric forms, restrained warm palette with indigo accents, crisp edges, "
            "subtle paper texture, generous negative space, sophisticated but approachable."
        ),
    },
    "isometric_3d": {
        "label": "Isométrico 3D",
        "prompt": (
            "Polished isometric 3D educational illustration. Soft studio lighting, rounded forms, "
            "coherent materials, indigo and amber accent palette, uncluttered composition, "
            "clear visual hierarchy, premium product-render quality."
        ),
    },
    "cinematic_photo": {
        "label": "Fotografía cinematográfica",
        "prompt": (
            "Cinematic editorial photography for an educational presentation. Natural realistic "
            "lighting, controlled depth of field, authentic materials, subtle indigo and amber "
            "color grade, purposeful composition, premium documentary feel."
        ),
    },
    "technical_blueprint": {
        "label": "Blueprint técnico / infografía",
        "prompt": (
            "Technical blueprint-style educational infographic. Precise schematic shapes, "
            "dark navy ground, fine luminous cyan and warm amber lines, modular visual hierarchy, "
            "clean engineering aesthetic, abundant negative space."
        ),
    },
    "custom": {
        "label": "Personalizado",
        "prompt": "",
    },
}

CONSISTENCY_PROMPT = (
    "Keep exactly the same visual language, palette, materials, lighting, camera treatment, "
    "and level of detail across the whole deck. Create one clear focal concept. "
    "Do not include words, letters, labels, captions, logos, watermarks, UI text, or borders."
)

MARKER_RE = re.compile(r"<!--\s*factory-image\s+(\{.*?\})\s*-->", re.DOTALL)
FINAL_MARKER_RE = re.compile(
    r"<!--\s*factory-image-id:\s*(?P<id>[a-zA-Z0-9_-]+)\s*-->\s*\n"
    r"(?P<image>!\[[^\]]*\]\([^\n)]+\))"
)

logger = logging.getLogger(__name__)


class ImageGenerationError(RuntimeError):
    """Raised when OpenRouter cannot produce a usable image."""


@dataclass(frozen=True)
class SlideImageSlot:
    image_id: str
    slide_number: int
    prompt: str
    layout: str
    alt: str
    marker: str


@dataclass(frozen=True)
class GeneratedImage:
    content: bytes
    media_type: str
    cost_usd: float | None


def image_options() -> dict[str, Any]:
    """Serializable catalog used by the profile editor."""
    return {
        "default_model": DEFAULT_IMAGE_MODEL,
        "default_style": DEFAULT_IMAGE_STYLE,
        "max_images_per_deck": MAX_IMAGES_PER_DECK,
        "models": [
            {"id": model_id, "label": item["label"], "price_hint": item["price_hint"]}
            for model_id, item in IMAGE_MODEL_OPTIONS.items()
        ],
        "styles": [
            {"id": style_id, "label": item["label"], "prompt": item["prompt"]}
            for style_id, item in IMAGE_STYLE_PRESETS.items()
        ],
    }


def resolve_style_prompt(style: str, custom_prompt: str = "") -> str:
    if style == "custom":
        prompt = custom_prompt.strip()
        if not prompt:
            raise ValueError("El estilo personalizado necesita un prompt")
        return prompt
    return IMAGE_STYLE_PRESETS.get(style, IMAGE_STYLE_PRESETS[DEFAULT_IMAGE_STYLE])["prompt"]


def consistency_seed(deck_identity: str, style_prompt: str) -> int:
    digest = hashlib.sha256(f"{deck_identity}\n{style_prompt}".encode()).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def _body_and_slides(deck: str) -> tuple[str, list[str]]:
    normalized = deck.replace("\r\n", "\n")
    prefix = ""
    body = normalized
    if normalized.startswith("---\n"):
        match = re.search(r"\n---\s*\n", normalized[4:])
        if match:
            end = 4 + match.end()
            prefix, body = normalized[:end], normalized[end:]
    return prefix, re.split(r"(?m)^---\s*$", body)


def parse_image_slots(deck: str, limit: int = MAX_IMAGES_PER_DECK) -> list[SlideImageSlot]:
    """Parse at most one valid marker per slide, capped for cost control."""
    _prefix, slides = _body_and_slides(deck)
    slots: list[SlideImageSlot] = []
    for slide_number, slide in enumerate(slides, start=1):
        matches = list(MARKER_RE.finditer(slide))
        if not matches or len(slots) >= limit:
            continue
        match = matches[0]
        try:
            payload = json.loads(match.group(1))
        except (TypeError, json.JSONDecodeError):
            continue
        prompt = str(payload.get("prompt", "")).strip()
        if not prompt:
            continue
        layout = str(payload.get("layout", "right")).lower()
        if layout not in {"left", "right", "background"}:
            layout = "right"
        slots.append(
            SlideImageSlot(
                image_id=f"slide-{slide_number}",
                slide_number=slide_number,
                prompt=prompt,
                layout=layout,
                alt=str(payload.get("alt", "Ilustración generada")).strip()
                or "Ilustración generada",
                marker=match.group(0),
            )
        )
    return slots


def strip_unprocessed_markers(deck: str) -> str:
    """Never leave internal image instructions in the user-facing Markdown."""
    return MARKER_RE.sub("", deck)


def media_extension(media_type: str, content: bytes) -> str:
    known = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
    }
    if media_type in known:
        return known[media_type]
    if content.startswith(b"\x89PNG"):
        return ".png"
    if content.startswith(b"\xff\xd8"):
        return ".jpg"
    return mimetypes.guess_extension(media_type) or ".img"


def generate_image(
    prompt: str,
    *,
    api_key: str,
    model: str = DEFAULT_IMAGE_MODEL,
    orientation: str = "horizontal",
    seed: int | None = None,
    client: httpx.Client | None = None,
    attempts: int = IMAGE_REQUEST_ATTEMPTS,
) -> GeneratedImage:
    """Generate one image through OpenRouter's dedicated Images API."""
    if not api_key:
        raise ImageGenerationError("OPENROUTER_API_KEY no está configurada")
    option = IMAGE_MODEL_OPTIONS.get(model)
    if option is None:
        raise ImageGenerationError("Modelo de imágenes no permitido")
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        **option["request"],
    }
    if option["supports_aspect_ratio"]:
        payload["aspect_ratio"] = "9:16" if orientation == "vertical" else "16:9"
    if option["supports_seed"] and seed is not None:
        payload["seed"] = seed

    owned_client = client is None
    http = client or httpx.Client(timeout=httpx.Timeout(180.0, connect=20.0))
    last_error: Exception | None = None
    try:
        for attempt in range(1, attempts + 1):
            try:
                response = http.post(
                    OPENROUTER_IMAGES_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://github.com/MrRobert91/Learning-AI-Factory",
                        "X-Title": "AI Learning Factory",
                    },
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()
                item = (result.get("data") or [None])[0]
                if not isinstance(item, dict) or not item.get("b64_json"):
                    raise ImageGenerationError("OpenRouter devolvió una imagen vacía")
                content = base64.b64decode(item["b64_json"], validate=True)
                usage = result.get("usage") or {}
                cost = usage.get("cost")
                return GeneratedImage(
                    content=content,
                    media_type=item.get("media_type") or "application/octet-stream",
                    cost_usd=float(cost) if cost is not None else None,
                )
            except (httpx.HTTPError, ValueError, KeyError, ImageGenerationError) as exc:
                last_error = exc
                logger.warning(
                    "Image generation attempt failed",
                    extra={"model": model, "attempt": attempt, "attempts": attempts},
                )
                if attempt < attempts:
                    time.sleep(0.5 * attempt)
    finally:
        if owned_client:
            http.close()
    raise ImageGenerationError(f"No se pudo generar la imagen: {last_error}")


def _image_markdown(slot: SlideImageSlot, markdown_path: str) -> str:
    marker = f"<!-- factory-image-id: {slot.image_id} -->"
    if slot.layout == "background":
        image = f"![bg brightness:0.42]({markdown_path})"
    else:
        image = f"![bg {slot.layout}:42%]({markdown_path})"
    return f"{marker}\n{image}"


def replace_generated_image(
    deck: str,
    image_id: str,
    markdown_path: str,
    *,
    layout: str,
    alt: str = "Ilustración generada",
) -> str:
    slot = SlideImageSlot(image_id, 0, "", layout, alt, "")
    replacement = _image_markdown(slot, markdown_path)
    pattern = re.compile(
        rf"<!--\s*factory-image-id:\s*{re.escape(image_id)}\s*-->\s*\n"
        r"!\[[^\]]*\]\([^\n)]+\)"
    )
    updated, count = pattern.subn(replacement, deck, count=1)
    if count != 1:
        failed_pattern = re.compile(
            rf"<!--\s*factory-image-failed:\s*{re.escape(image_id)}\s*-->"
        )
        updated, count = failed_pattern.subn(replacement, deck, count=1)
    if count != 1:
        raise ValueError("No se encontró la imagen dentro del Markdown de las slides")
    return updated


def generate_deck_images(
    deck: str,
    *,
    api_key: str,
    model: str,
    style: str,
    custom_style_prompt: str,
    orientation: str,
    deck_identity: str,
    output_dir: Path,
    markdown_asset_dir: str,
    storage_asset_dir: str,
    on_event: Callable[[str, str, dict[str, Any]], None] | None = None,
    client: httpx.Client | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Generate all requested deck images and replace successful markers."""
    style_prompt = resolve_style_prompt(style, custom_style_prompt)
    seed = consistency_seed(deck_identity, style_prompt)
    slots = parse_image_slots(deck)
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    updated = deck
    for slot in slots:
        resolved_prompt = f"{slot.prompt}\n\nSTYLE SYSTEM:\n{style_prompt}\n\n{CONSISTENCY_PROMPT}"
        if on_event:
            on_event(
                "stage",
                f"Generando imagen para la slide {slot.slide_number}…",
                {"slide": slot.slide_number, "image_id": slot.image_id, "model": model},
            )
        try:
            generated = generate_image(
                resolved_prompt,
                api_key=api_key,
                model=model,
                orientation=orientation,
                seed=seed,
                client=client,
            )
            extension = media_extension(generated.media_type, generated.content)
            filename = f"{slot.image_id}{extension}"
            path = output_dir / filename
            path.write_bytes(generated.content)
            markdown_path = f"{markdown_asset_dir}/{filename}".replace("\\", "/")
            updated = updated.replace(slot.marker, _image_markdown(slot, markdown_path), 1)
            records.append(
                {
                    "id": slot.image_id,
                    "slide": slot.slide_number,
                    "prompt": slot.prompt,
                    "layout": slot.layout,
                    "alt": slot.alt,
                    "model": model,
                    "style": style,
                    "style_prompt": style_prompt,
                    "seed": seed if IMAGE_MODEL_OPTIONS[model]["supports_seed"] else None,
                    "path": f"{storage_asset_dir}/{filename}".replace("\\", "/"),
                    "markdown_path": markdown_path,
                    "media_type": generated.media_type,
                    "cost_usd": generated.cost_usd,
                    "status": "generated",
                }
            )
        except (ImageGenerationError, OSError) as exc:
            updated = updated.replace(
                slot.marker, f"<!-- factory-image-failed: {slot.image_id} -->", 1
            )
            records.append(
                {
                    "id": slot.image_id,
                    "slide": slot.slide_number,
                    "prompt": slot.prompt,
                    "layout": slot.layout,
                    "alt": slot.alt,
                    "model": model,
                    "style": style,
                    "style_prompt": style_prompt,
                    "seed": seed if IMAGE_MODEL_OPTIONS[model]["supports_seed"] else None,
                    "status": "failed",
                    "error": str(exc),
                }
            )
            if on_event:
                on_event(
                    "warning",
                    f"No se pudo generar la imagen de la slide {slot.slide_number}; "
                    "el deck continuará sin ella",
                    {"slide": slot.slide_number, "image_id": slot.image_id, "error": str(exc)},
                )
    return strip_unprocessed_markers(updated), records
