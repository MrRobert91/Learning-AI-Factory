"""Thumbnail generation: HTML template rendered to PNG with headless Chromium."""

import html
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  * {{ margin: 0; box-sizing: border-box; }}
  body {{
    width: 1280px; height: 720px; overflow: hidden;
    display: flex; flex-direction: column; justify-content: center;
    padding: 80px;
    background: linear-gradient(135deg, #1e1b4b 0%, #312e81 55%, #4f46e5 100%);
    font-family: 'DejaVu Sans', Arial, sans-serif; color: #fff;
  }}
  .badge {{
    display: inline-block; align-self: flex-start;
    background: #eab308; color: #1e1b4b;
    font-size: 34px; font-weight: 700; padding: 10px 26px;
    border-radius: 14px; margin-bottom: 42px;
  }}
  h1 {{ font-size: 92px; font-weight: 800; line-height: 1.08; letter-spacing: -2px; }}
  p {{ font-size: 44px; margin-top: 34px; color: #c7d2fe; }}
</style></head>
<body>
  <span class="badge">{badge}</span>
  <h1>{title}</h1>
  {subtitle_html}
</body></html>
"""


def chromium_binary() -> str | None:
    for candidate in (os.environ.get("CHROME_PATH"), "chromium", "chromium-browser"):
        if candidate and shutil.which(candidate):
            return shutil.which(candidate)
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def render_thumbnail(
    title: str, subtitle: str, badge: str, out_path: str | Path
) -> Path | None:
    """Render the thumbnail PNG. Returns None when Chromium is unavailable."""
    binary = chromium_binary()
    if binary is None:
        return None
    subtitle_html = f"<p>{html.escape(subtitle)}</p>" if subtitle else ""
    content = TEMPLATE.format(
        badge=html.escape(badge or "Curso"),
        title=html.escape(title),
        subtitle_html=subtitle_html,
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="thumb-") as tmp:
        page = Path(tmp) / "thumb.html"
        page.write_text(content, encoding="utf-8")
        result = subprocess.run(
            [
                binary,
                "--headless",
                "--no-sandbox",
                "--disable-gpu",
                "--force-device-scale-factor=1",
                "--window-size=1280,720",
                f"--screenshot={out_path}",
                page.as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    if result.returncode != 0 or not out_path.is_file():
        return None
    return out_path
