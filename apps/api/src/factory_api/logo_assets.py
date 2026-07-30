"""Validation and private storage for versioned slide-profile logos."""

from __future__ import annotations

import hashlib
import html
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from factory_agents.tools.thumbnail import chromium_binary
from PIL import Image, ImageChops, ImageDraw, UnidentifiedImageError

from factory_api.config import get_settings

MAX_LOGO_BYTES = 5 * 1024 * 1024
MAX_LOGO_DIMENSION = 8192
MIN_LOGO_DIMENSION = 16
THUMBNAIL_SIZE = (320, 320)
TRANSPARENT_MAX_DIMENSION = 2048
TRANSPARENT_VARIANT_NAME = "transparent.png"
TRANSPARENT_MANIFEST_NAME = "transparent.json"
TRANSPARENT_METHOD = "edge-connected-background-v1"

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


@dataclass(frozen=True)
class TransparentLogoVariant:
    path: str
    media_type: str
    width: int
    height: int
    sha256: str
    source_sha256: str
    method: str


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


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_asset_path(path: Path) -> str:
    return path.resolve().relative_to(get_settings().data_dir.resolve()).as_posix()


def transparent_logo_path(original: Path) -> Path:
    return original.parent / TRANSPARENT_VARIANT_NAME


def _rasterize_svg(path: Path, width: int, height: int) -> Image.Image:
    binary = chromium_binary()
    if binary is None:
        raise LogoValidationError(
            "No se puede crear la variante transparente del SVG porque Chromium "
            "no est\u00e1 disponible"
        )
    scale = min(1.0, TRANSPARENT_MAX_DIMENSION / max(1, width, height))
    viewport_width = max(16, round(width * scale))
    viewport_height = max(16, round(height * scale))
    with tempfile.TemporaryDirectory(prefix="logo-svg-") as tmp:
        temporary = Path(tmp)
        page = temporary / "logo.html"
        screenshot = temporary / "logo.png"
        page.write_text(
            (
                "<!doctype html><html><head><meta charset=\"utf-8\"><style>"
                "*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;"
                "overflow:hidden;background:transparent}"
                "img{display:block;width:100vw;height:100vh;object-fit:contain}"
                "</style></head><body>"
                f'<img src="{html.escape(path.as_uri(), quote=True)}">'
                "</body></html>"
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                binary,
                "--headless",
                "--no-sandbox",
                "--disable-gpu",
                "--hide-scrollbars",
                "--allow-file-access-from-files",
                "--force-device-scale-factor=1",
                "--default-background-color=00000000",
                f"--window-size={viewport_width},{viewport_height}",
                f"--screenshot={screenshot}",
                page.as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0 or not screenshot.is_file():
            raise LogoValidationError(
                "No se pudo rasterizar el SVG para eliminar su fondo"
            )
        with Image.open(screenshot) as rendered:
            rendered.load()
            return rendered.convert("RGBA")


def _load_logo_pixels(original: Path, width: int, height: int) -> Image.Image:
    if original.suffix.lower() == ".svg":
        return _rasterize_svg(original, width, height)
    try:
        with Image.open(original) as source:
            source.load()
            image = source.convert("RGBA")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise LogoValidationError(
            "El original del logo no se puede procesar como imagen"
        ) from exc
    if max(image.size) > TRANSPARENT_MAX_DIMENSION:
        image.thumbnail(
            (TRANSPARENT_MAX_DIMENSION, TRANSPARENT_MAX_DIMENSION),
            Image.Resampling.LANCZOS,
        )
    return image


def _transparent_pixels(image: Image.Image) -> tuple[Image.Image, str]:
    rgba = image.convert("RGBA")
    source_alpha = rgba.getchannel("A")
    total_pixels = rgba.width * rgba.height
    existing_transparent = total_pixels - source_alpha.histogram()[255]
    preserve_existing_alpha = existing_transparent >= max(
        16, round(total_pixels * 0.005)
    )
    if preserve_existing_alpha:
        alpha_bounds = source_alpha.getbbox()
        if alpha_bounds is not None:
            opaque_region = rgba.crop(alpha_bounds)
            corners = [
                opaque_region.getpixel(point)
                for point in (
                    (0, 0),
                    (opaque_region.width - 1, 0),
                    (0, opaque_region.height - 1),
                    (opaque_region.width - 1, opaque_region.height - 1),
                )
            ]
            corner_colors = [pixel[:3] for pixel in corners]
            color_spread = max(
                max(abs(first[channel] - second[channel]) for channel in range(3))
                for first in corner_colors
                for second in corner_colors
            )
            if all(pixel[3] >= 250 for pixel in corners) and color_spread <= 48:
                rgba = opaque_region
                source_alpha = rgba.getchannel("A")
                total_pixels = rgba.width * rgba.height
                preserve_existing_alpha = False

    if preserve_existing_alpha:
        alpha = source_alpha
        method = "existing-alpha-v1"
    else:
        work = rgba.convert("RGB")
        marker = (1, 2, 3)
        if any(work.getpixel(point) == marker for point in {
            (0, 0),
            (work.width - 1, 0),
            (0, work.height - 1),
            (work.width - 1, work.height - 1),
        }):
            marker = (254, 253, 252)
        for point in (
            (0, 0),
            (work.width - 1, 0),
            (0, work.height - 1),
            (work.width - 1, work.height - 1),
        ):
            if work.getpixel(point) != marker:
                ImageDraw.floodfill(work, point, marker, thresh=48)
        difference = ImageChops.difference(
            work, Image.new("RGB", work.size, marker)
        ).convert("L")
        alpha = difference.point(lambda value: 255 if value else 0)
        removed = alpha.histogram()[0]
        if removed < max(16, round(total_pixels * 0.005)):
            raise LogoValidationError(
                "No se detect\u00f3 un fondo conectado al borde que pueda eliminarse"
            )
        alpha = ImageChops.multiply(alpha, source_alpha)
        method = TRANSPARENT_METHOD

    content_bounds = alpha.getbbox()
    if content_bounds is None or sum(alpha.histogram()[1:]) < max(
        16, round(total_pixels * 0.001)
    ):
        raise LogoValidationError(
            "La eliminaci\u00f3n de fondo dejar\u00eda un logo vac\u00edo"
        )
    rgba.putalpha(alpha)
    left, top, right, bottom = content_bounds
    padding = max(2, round(max(rgba.size) * 0.01))
    crop = (
        max(0, left - padding),
        max(0, top - padding),
        min(rgba.width, right + padding),
        min(rgba.height, bottom + padding),
    )
    result = rgba.crop(crop)
    if result.getchannel("A").getextrema()[0] == 255:
        raise LogoValidationError(
            "La variante procesada no contiene transparencia"
        )
    return result, method


def _read_transparent_variant(
    original: Path, source_sha256: str
) -> TransparentLogoVariant | None:
    variant = transparent_logo_path(original)
    manifest = original.parent / TRANSPARENT_MANIFEST_NAME
    if not variant.is_file() or not manifest.is_file():
        return None
    try:
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
        if (
            metadata.get("source_sha256") != source_sha256
            or metadata.get("sha256") != _file_sha256(variant)
        ):
            return None
        with Image.open(variant) as image:
            image.load()
            if image.format != "PNG" or image.mode != "RGBA":
                return None
            if image.getchannel("A").getextrema()[0] == 255:
                return None
            width, height = image.size
        return TransparentLogoVariant(
            path=_relative_asset_path(variant),
            media_type="image/png",
            width=width,
            height=height,
            sha256=str(metadata["sha256"]),
            source_sha256=source_sha256,
            method=str(metadata["method"]),
        )
    except (KeyError, OSError, ValueError, json.JSONDecodeError, UnidentifiedImageError):
        return None


def prepare_transparent_logo(
    original: Path,
    *,
    source_sha256: str,
    width: int,
    height: int,
) -> TransparentLogoVariant:
    """Create or reuse one validated PNG RGBA derivative without changing the original."""
    if _file_sha256(original) != source_sha256:
        raise LogoValidationError(
            "El original del logo ya no coincide con el snapshot del perfil"
        )
    cached = _read_transparent_variant(original, source_sha256)
    if cached is not None:
        return cached

    pixels = _load_logo_pixels(original, width, height)
    processed, method = _transparent_pixels(pixels)
    output = io.BytesIO()
    processed.save(output, format="PNG", optimize=True)
    content = output.getvalue()
    variant_sha256 = hashlib.sha256(content).hexdigest()
    variant = transparent_logo_path(original)
    manifest = original.parent / TRANSPARENT_MANIFEST_NAME
    operation_id = uuid.uuid4().hex
    temporary_variant = variant.with_name(f".{variant.name}.{operation_id}.tmp")
    temporary_manifest = manifest.with_name(f".{manifest.name}.{operation_id}.tmp")
    try:
        temporary_variant.write_bytes(content)
        temporary_manifest.write_text(
            json.dumps(
                {
                    "source_sha256": source_sha256,
                    "sha256": variant_sha256,
                    "method": method,
                    "width": processed.width,
                    "height": processed.height,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        os.replace(temporary_variant, variant)
        os.replace(temporary_manifest, manifest)
    finally:
        temporary_variant.unlink(missing_ok=True)
        temporary_manifest.unlink(missing_ok=True)
    result = _read_transparent_variant(original, source_sha256)
    if result is None:
        variant.unlink(missing_ok=True)
        manifest.unlink(missing_ok=True)
        raise LogoValidationError(
            "La variante transparente no super\u00f3 la validaci\u00f3n final"
        )
    return result


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
