"""Marp CLI rendering: Marp Markdown → HTML / PDF / PPTX.

Best-effort: when marp-cli is not installed the deck's canonical Markdown
is still the artifact; renders are simply skipped and reported.
"""

import base64
import logging
import mimetypes
import re
import shutil
import subprocess
import uuid
from pathlib import Path

RENDER_FORMATS = ("html", "pdf", "pptx")
RENDER_TIMEOUT = 120
logger = logging.getLogger(__name__)
MARKDOWN_IMAGE_RE = re.compile(r"(!\[[^\]]*\]\()(?P<target>[^)]+)(\))")


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
        source = md_path
        temporary_source: Path | None = None
        if fmt == "html":
            markdown = md_path.read_text(encoding="utf-8")
            inlined = inline_local_images(markdown, md_path.parent)
            if inlined != markdown:
                temporary_source = md_path.with_name(
                    f".{md_path.stem}-{uuid.uuid4().hex[:8]}-html.md"
                )
                temporary_source.write_text(inlined, encoding="utf-8")
                source = temporary_source
        cmd = ["marp", str(source), "-o", str(out), "--allow-local-files"]
        logger.info(
            "Marp render started",
            extra={
                "source_path": str(md_path),
                "render_format": fmt,
                "output_path": str(out),
            },
        )
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=RENDER_TIMEOUT)
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
        finally:
            if temporary_source is not None:
                temporary_source.unlink(missing_ok=True)
    return rendered


def available_renders(md_path: str | Path) -> dict[str, str]:
    """Return the renders that already exist for a deck."""
    md_path = Path(md_path)
    return {
        fmt: str(md_path.with_suffix(f".{fmt}"))
        for fmt in RENDER_FORMATS
        if md_path.with_suffix(f".{fmt}").is_file()
    }
