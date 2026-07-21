"""Marp CLI rendering: Marp Markdown → HTML / PDF / PPTX.

Best-effort: when marp-cli is not installed the deck's canonical Markdown
is still the artifact; renders are simply skipped and reported.
"""

import base64
import hashlib
import json
import logging
import mimetypes
import re
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

RENDER_FORMATS = ("html", "pdf", "pptx")
RENDER_TIMEOUT = 120
RENDER_SCHEMA_VERSION = 2
logger = logging.getLogger(__name__)
MARKDOWN_IMAGE_RE = re.compile(r"(!\[[^\]]*\]\()(?P<target>[^)]+)(\))")
VERTICAL_CANVAS_START = "<!-- factory-vertical-canvas:start -->"
VERTICAL_CANVAS_END = "<!-- factory-vertical-canvas:end -->"
VERTICAL_CANVAS_RE = re.compile(
    rf"{re.escape(VERTICAL_CANVAS_START)}.*?{re.escape(VERTICAL_CANVAS_END)}\s*",
    re.DOTALL,
)
VERTICAL_CANVAS_BLOCK = f"{VERTICAL_CANVAS_START}\n{VERTICAL_CANVAS_END}"
VERTICAL_THEME_NAME = "factory-vertical"


def _frontmatter_end(lines: list[str]) -> int | None:
    if not lines or lines[0].strip() != "---":
        return None
    return next(
        (index for index in range(1, len(lines)) if lines[index].strip() == "---"),
        None,
    )


def _has_legacy_vertical_size(markdown: str) -> bool:
    lines = markdown.replace("\r\n", "\n").splitlines()
    end = _frontmatter_end(lines)
    if end is None:
        return False
    return any(
        line.strip().lower() == "size: 1080px 1920px"
        for line in lines[1:end]
        if line == line.lstrip()
    )


def apply_marp_orientation(markdown: str, orientation: str) -> str:
    """Apply the canonical 16:9 or registered 9:16 canvas to a Marp deck."""
    if orientation not in {"horizontal", "vertical"}:
        raise ValueError(f"Unknown slide orientation: {orientation}")

    clean = VERTICAL_CANVAS_RE.sub("", markdown.replace("\r\n", "\n")).strip()
    lines = clean.splitlines()
    end = _frontmatter_end(lines)
    if end is None:
        frontmatter = ["marp: true", "paginate: true"]
        body = clean
    else:
        frontmatter = [
            line
            for line in lines[1:end]
            if not (
                line == line.lstrip()
                and line.strip().startswith(("size:", "theme:"))
            )
        ]
        body = "\n".join(lines[end + 1 :]).strip()

    if orientation == "vertical":
        frontmatter.extend([f"theme: {VERTICAL_THEME_NAME}", "size: 9:16"])
    else:
        frontmatter.extend(["theme: default", "size: 16:9"])
    result = "\n".join(["---", *frontmatter, "---"])
    if orientation == "vertical":
        result += f"\n\n{VERTICAL_CANVAS_BLOCK}"
    if body:
        result += f"\n\n{body}"
    return result.rstrip() + "\n"


def normalize_marp_canvas(markdown: str) -> str:
    """Upgrade legacy vertical decks without mutating their stored artifact."""
    if VERTICAL_CANVAS_START in markdown or _has_legacy_vertical_size(markdown):
        return apply_marp_orientation(markdown, "vertical")
    return markdown


def vertical_theme_path() -> Path:
    """Return the packaged Marp theme that defines the native 9:16 preset."""
    return Path(__file__).with_name("factory_vertical.css")


def render_manifest_path(md_path: str | Path) -> Path:
    return Path(md_path).with_suffix(".render.json")


def _source_digest(md_path: Path) -> str:
    return hashlib.sha256(md_path.read_bytes()).hexdigest()


def legacy_vertical_render_is_current(md_path: str | Path) -> bool:
    """Return whether a legacy 9:16 source has renders made by this canvas version."""
    path = Path(md_path)
    try:
        manifest = json.loads(render_manifest_path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        manifest.get("schema_version") == RENDER_SCHEMA_VERSION
        and manifest.get("source_sha256") == _source_digest(path)
    )


@contextmanager
def prepared_marp_source(
    md_path: str | Path, *, inline_images: bool = False
) -> Iterator[Path]:
    """Yield a normalized render source beside the canonical Markdown."""
    path = Path(md_path)
    markdown = path.read_text(encoding="utf-8")
    prepared = normalize_marp_canvas(markdown)
    if inline_images:
        prepared = inline_local_images(prepared, path.parent)
    if prepared == markdown:
        yield path
        return

    temporary = path.with_name(f".{path.stem}-{uuid.uuid4().hex[:8]}-render.md")
    temporary.write_text(prepared, encoding="utf-8")
    try:
        yield temporary
    finally:
        temporary.unlink(missing_ok=True)


def inline_local_images(markdown: str, base_dir: str | Path) -> str:
    """Embed local Markdown images as data URIs for portable combined/HTML renders."""
    root = Path(base_dir).resolve()

    def replace(match: re.Match) -> str:
        raw_target = match.group("target").strip()
        target = raw_target.strip("<>")
        if target.startswith(("http://", "https://", "data:", "#")):
            return match.group(0)
        path = (root / target).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return match.group(0)
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"{match.group(1)}data:{media_type};base64,{encoded}{match.group(3)}"

    return MARKDOWN_IMAGE_RE.sub(replace, markdown)


def marp_available() -> bool:
    return shutil.which("marp") is not None


def render_deck(md_path: str | Path) -> dict[str, str]:
    """Render a Marp file to every supported format next to the source."""
    md_path = Path(md_path)
    if not marp_available():
        logger.warning(
            "Marp CLI is not available",
            extra={"source_path": str(md_path)},
        )
        return {}
    rendered: dict[str, str] = {}
    for fmt in RENDER_FORMATS:
        out = md_path.with_suffix(f".{fmt}")
        out.unlink(missing_ok=True)
        with prepared_marp_source(md_path, inline_images=fmt == "html") as source:
            cmd = [
                "marp",
                str(source),
                "-o",
                str(out),
                "--theme-set",
                str(vertical_theme_path()),
                "--allow-local-files",
            ]
            logger.info(
                "Marp render started",
                extra={
                    "source_path": str(md_path),
                    "render_format": fmt,
                    "output_path": str(out),
                },
            )
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=RENDER_TIMEOUT
                )
                if result.returncode == 0 and out.is_file():
                    rendered[fmt] = str(out)
                    logger.info(
                        "Marp render completed",
                        extra={"render_format": fmt, "output_path": str(out)},
                    )
                else:
                    logger.error(
                        "Marp render failed",
                        extra={
                            "render_format": fmt,
                            "return_code": result.returncode,
                            "stderr": result.stderr[-1000:],
                        },
                    )
            except Exception:
                logger.exception(
                    "Marp render crashed",
                    extra={"render_format": fmt, "source_path": str(md_path)},
                )
    if rendered:
        render_manifest_path(md_path).write_text(
            json.dumps(
                {
                    "schema_version": RENDER_SCHEMA_VERSION,
                    "source_sha256": _source_digest(md_path),
                    "formats": sorted(rendered),
                }
            ),
            encoding="utf-8",
        )
    return rendered


def available_renders(md_path: str | Path) -> dict[str, str]:
    """Return the renders that already exist for a deck."""
    md_path = Path(md_path)
    return {
        fmt: str(md_path.with_suffix(f".{fmt}"))
        for fmt in RENDER_FORMATS
        if md_path.with_suffix(f".{fmt}").is_file()
    }
