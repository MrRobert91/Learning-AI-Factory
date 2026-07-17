"""Marp CLI rendering: Marp Markdown → HTML / PDF / PPTX.

Best-effort: when marp-cli is not installed the deck's canonical Markdown
is still the artifact; renders are simply skipped and reported.
"""

import logging
import shutil
import subprocess
from pathlib import Path

RENDER_FORMATS = ("html", "pdf", "pptx")
RENDER_TIMEOUT = 120
logger = logging.getLogger(__name__)


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
        cmd = ["marp", str(md_path), "-o", str(out), "--allow-local-files"]
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
    return rendered


def available_renders(md_path: str | Path) -> dict[str, str]:
    """Return the renders that already exist for a deck."""
    md_path = Path(md_path)
    return {
        fmt: str(md_path.with_suffix(f".{fmt}"))
        for fmt in RENDER_FORMATS
        if md_path.with_suffix(f".{fmt}").is_file()
    }
