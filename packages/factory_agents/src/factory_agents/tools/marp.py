"""Marp CLI rendering: Marp Markdown → HTML / PDF / PPTX.

Best-effort: when marp-cli is not installed the deck's canonical Markdown
is still the artifact; renders are simply skipped and reported.
"""

import shutil
import subprocess
from pathlib import Path

RENDER_FORMATS = ("html", "pdf", "pptx")
RENDER_TIMEOUT = 120


def marp_available() -> bool:
    return shutil.which("marp") is not None


def render_deck(md_path: str | Path) -> dict[str, str]:
    """Render a Marp file to every supported format next to the source.

    Returns {format: path} for the renders that succeeded.
    """
    md_path = Path(md_path)
    if not marp_available():
        return {}
    rendered: dict[str, str] = {}
    for fmt in RENDER_FORMATS:
        out = md_path.with_suffix(f".{fmt}")
        cmd = ["marp", str(md_path), "-o", str(out), "--allow-local-files"]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=RENDER_TIMEOUT
            )
            if result.returncode == 0 and out.is_file():
                rendered[fmt] = str(out)
        except Exception:
            continue
    return rendered


def available_renders(md_path: str | Path) -> dict[str, str]:
    """Return the renders that already exist for a deck."""
    md_path = Path(md_path)
    return {
        fmt: str(md_path.with_suffix(f".{fmt}"))
        for fmt in RENDER_FORMATS
        if md_path.with_suffix(f".{fmt}").is_file()
    }
