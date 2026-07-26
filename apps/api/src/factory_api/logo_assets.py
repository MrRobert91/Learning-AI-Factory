"""Validation and private storage for versioned slide-profile logos."""

from __future__ import annotations

import hashlib
import io
import re
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from factory_api.config import get_settings

MAX_LOGO_BYTES = 5 * 1024 * 1024
MAX_LOGO_DIMENSION = 8192
MIN_LOGO_DIMENSION = 16
THUMBNAIL_SIZE = (320, 320)

_RASTER_FORMATS = {
    "PNG": ("image/png", ".png", {".png"}),
    "WEBP": ("image/webp", ".webp", {".webp"}),
    "JPEG": ("image/jpeg", ".jpg", {".jpg", ".jpeg"}),
}
_ALLOWED_EXTENSIONS = {".png", ".webp", ".svg", ".jpg", ".jpeg"}
_SVG_NS = "http://www.w3.org/2000/svg"
_FORBIDDEN_SVG_TAGS = {"script", "foreignObject", "iframe", "object", "embed"}
_EXTERNAL_REFERENCE = re.compile(r"^(?:https?:|file:|javascript:|data:)", re.I)


class LogoValidationError(ValueError):
    """Raised when an uploaded/generated logo is unsafe or unsupported."""


@dataclass(frozen=True)
class ValidatedLogo:
    content: bytes
    thumbnail: bytes
    media_type: str
    extension: str
    thumbnail_extension: str
    width: int
    height: int
    sha256: str


def _dimension(value: str | None) -> int | None:
    if not value:
        return None
    match = re.match(r"^\s*(\d+(?:\.\d+)?)", value)
    return max(1, round(float(match.group(1)))) if match else None


def _check_dimensions(width: int, height: int) -> None:
    if width < MIN_LOGO_DIMENSION or height < MIN_LOGO_DIMENSION:
        raise LogoValidationError("El logo debe medir al menos 16 x 16 px")
    if width > MAX_LOGO_DIMENSION or height > MAX_LOGO_DIMENSION:
        raise LogoValidationError("El logo supera las dimensiones m\u00e1ximas de 8192 px")


def _sanitize_svg(content: bytes) -> tuple[bytes, bytes, int, int]:
    lowered = content[:4096].lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise LogoValidationError("El SVG contiene declaraciones XML no permitidas")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise LogoValidationError("El SVG no es v\u00e1lido") from exc
    if root.tag.rsplit("}", 1)[-1] != "svg":
        raise LogoValidationError("El archivo no contiene un SVG")

    for parent in list(root.iter()):
        for child in list(parent):
            if child.tag.rsplit("}", 1)[-1] in _FORBIDDEN_SVG_TAGS:
                parent.remove(child)
        for attr in list(parent.attrib):
            local = attr.rsplit("}", 1)[-1].lower()
            value = parent.attrib[attr].strip()
            if local.startswith("on") or (
                local in {"href", "src"} and _EXTERNAL_REFERENCE.match(value)
            ) or ("url(" in value.lower() and "url(#" not in value.lower()):
                del parent.attrib[attr]
        if parent.tag.rsplit("}", 1)[-1] == "style" and parent.text:
            lowered_style = parent.text.lower()
            if "@import" in lowered_style or re.search(r"url\((?!\s*#)", lowered_style):
                parent.text = ""

    width = _dimension(root.get("width"))
    height = _dimension(root.get("height"))
    view_box = root.get("viewBox", "").replace(",", " ").split()
    if (width is None or height is None) and len(view_box) == 4:
        try:
            width = width or max(1, round(float(view_box[2])))
            height = height or max(1, round(float(view_box[3])))
        except ValueError as exc:
            raise LogoValidationError("El viewBox del SVG no es v\u00e1lido") from exc
    if width is None or height is None:
        raise LogoValidationError("El SVG debe declarar width/height o viewBox")
    _check_dimensions(width, height)

    ET.register_namespace("", _SVG_NS)
    sanitized = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    thumb_root = ET.fromstring(sanitized)
    thumb_root.set("width", str(THUMBNAIL_SIZE[0]))
    thumb_root.set("height", str(THUMBNAIL_SIZE[1]))
    thumb_root.set("preserveAspectRatio", "xMidYMid meet")
    thumbnail = ET.tostring(thumb_root, encoding="utf-8", xml_declaration=True)
    return sanitized, thumbnail, width, height


def _validate_raster(content: bytes) -> tuple[bytes, bytes, str, str, int, int]:
    try:
        with Image.open(io.BytesIO(content)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(content)) as image:
            detected = image.format or ""
            if detected not in _RASTER_FORMATS:
                raise LogoValidationError("Formato de imagen no permitido")
            media_type, extension, _extensions = _RASTER_FORMATS[detected]
            width, height = image.size
            _check_dimensions(width, height)
            image.thumbnail(THUMBNAIL_SIZE)
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA")
            thumbnail_buffer = io.BytesIO()
            image.save(thumbnail_buffer, format="PNG", optimize=True)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise LogoValidationError("La imagen est\u00e1 corrupta o no es compatible") from exc
    return content, thumbnail_buffer.getvalue(), media_type, extension, width, height


def validate_logo(content: bytes, filename: str, declared_media_type: str = "") -> ValidatedLogo:
    if not content:
        raise LogoValidationError("El archivo est\u00e1 vac\u00edo")
    if len(content) > MAX_LOGO_BYTES:
        raise LogoValidationError("El logo supera el l\u00edmite de 5 MB")
    extension = Path(filename).suffix.lower()
    if extension not in _ALLOWED_EXTENSIONS:
        raise LogoValidationError("Solo se admiten PNG, WebP, SVG, JPG y JPEG")

    if extension == ".svg" or content.lstrip().startswith(b"<"):
        sanitized, thumbnail, width, height = _sanitize_svg(content)
        detected_media_type = "image/svg+xml"
        detected_extension = ".svg"
        thumbnail_extension = ".svg"
        normalized = sanitized
    else:
        normalized, thumbnail, detected_media_type, detected_extension, width, height = (
            _validate_raster(content)
        )
        thumbnail_extension = ".png"

    compatible_extensions = (
        {".jpg", ".jpeg"} if detected_extension == ".jpg" else {detected_extension}
    )
    if extension not in compatible_extensions:
        raise LogoValidationError("La extensi\u00f3n no coincide con el contenido real")
    if declared_media_type and declared_media_type not in {
        detected_media_type,
        "application/octet-stream",
    }:
        raise LogoValidationError("El tipo MIME no coincide con el contenido real")

    return ValidatedLogo(
        content=normalized,
        thumbnail=thumbnail,
        media_type=detected_media_type,
        extension=detected_extension,
        thumbnail_extension=thumbnail_extension,
        width=width,
        height=height,
        sha256=hashlib.sha256(normalized).hexdigest(),
    )


def store_logo(profile_id: str, logo_id: str, logo: ValidatedLogo) -> tuple[str, str]:
    relative_dir = Path("profile-assets") / profile_id / "logos" / logo_id
    directory = get_settings().data_dir / relative_dir
    directory.mkdir(parents=True, exist_ok=False)
    original = directory / f"original{logo.extension}"
    thumbnail = directory / f"thumbnail{logo.thumbnail_extension}"
    original.write_bytes(logo.content)
    thumbnail.write_bytes(logo.thumbnail)
    return original.relative_to(get_settings().data_dir).as_posix(), thumbnail.relative_to(
        get_settings().data_dir
    ).as_posix()


def stored_logo_path(relative_path: str) -> Path | None:
    root = get_settings().data_dir.resolve()
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root / "profile-assets") or not candidate.is_file():
        return None
    return candidate


def remove_logo_files(profile_id: str, logo_id: str) -> None:
    root = (get_settings().data_dir / "profile-assets" / profile_id / "logos").resolve()
    target = (root / logo_id).resolve()
    if target.parent == root:
        shutil.rmtree(target, ignore_errors=True)


def remove_profile_logo_files(profile_id: str) -> None:
    root = (get_settings().data_dir / "profile-assets").resolve()
    target = (root / profile_id).resolve()
    if target.parent == root:
        shutil.rmtree(target, ignore_errors=True)
