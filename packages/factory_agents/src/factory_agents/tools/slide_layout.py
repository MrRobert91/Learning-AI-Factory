"""Measured safe-area enforcement for Marp slide decks.

The model is allowed to propose content, but layout repair is deterministic:
Marp and Chromium measure the real canvas, progressively smaller canonical
classes are applied, and content is split only at valid Markdown boundaries.
"""

from __future__ import annotations

import base64
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from factory_agents.tools.marp import (
    RENDER_TIMEOUT,
    marp_available,
    prepared_marp_source,
    vertical_theme_path,
)

SAFE_AREA_START = "<!-- factory-safe-area:start -->"
SAFE_AREA_END = "<!-- factory-safe-area:end -->"
SAFE_AREA_RE = re.compile(
    rf"{re.escape(SAFE_AREA_START)}.*?{re.escape(SAFE_AREA_END)}\s*",
    re.DOTALL,
)
LOCAL_CLASS_RE = re.compile(r"<!--\s*_class:\s*(?P<classes>[^>]*?)\s*-->", re.I)
FIT_CLASS_RE = re.compile(r"^factory-fit-[1-4]$")
LOGO_IMAGE_RE = re.compile(r'<img\s+class="factory-logo[^"]*"[^>]*>\s*', re.I)
SIDE_IMAGE_RE = re.compile(
    r"<!--\s*factory-image-id:\s*[^>]+-->\s*"
    r"(?:<!--\s*_class:\s*factory-side-image\s+"
    r"factory-side-image-(?:left|right)(?:\s+factory-has-logo)?\s*-->\s*)?"
    r"!\[[^\]]*\]\([^\n)]+\)\s*",
    re.I,
)
SLIDE_SEPARATOR_RE = re.compile(r"(?m)^---\s*$")
FENCE_RE = re.compile(r"^\s*(```+|~~~+)")
LIST_ITEM_RE = re.compile(r"^(?P<indent>\s*)(?:[-+*]|\d+[.)])\s+")
TABLE_DIVIDER_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)
HEADING_RE = re.compile(r"(?m)^(?P<marks>#{1,6})\s+(?P<title>[^\n]+)$")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÜÑ0-9¿¡])")

SAFE_BOTTOM_PX = {"horizontal": 88, "vertical": 160}
FIT_FONT_PX = {
    "horizontal": {1: 27, 2: 25, 3: 23, 4: 21},
    "vertical": {1: 39, 2: 36, 3: 33, 4: 30},
}
LAYOUT_SCHEMA_VERSION = 1


class SlideLayoutError(RuntimeError):
    """Base error for a deck that cannot be safely published."""


class SlideLayoutUnavailable(SlideLayoutError):
    """Raised when the real Marp/Chromium measurement runtime is missing."""


class SlideOverflowError(SlideLayoutError):
    def __init__(self, slide_number: int, block_kind: str):
        self.slide_number = slide_number
        self.block_kind = block_kind
        super().__init__(
            f"La slide {slide_number} contiene un bloque {block_kind} que no cabe "
            "ni con la tipografía mínima"
        )


@dataclass(frozen=True)
class SlideMeasurement:
    slide_number: int
    available_height: float
    content_height: float
    overflow_px: float

    @property
    def fits(self) -> bool:
        return self.overflow_px <= 1.0


@dataclass(frozen=True)
class MarkdownBlock:
    kind: str
    text: str


@dataclass(frozen=True)
class SlideStructure:
    prefix: str
    classes: tuple[str, ...]
    heading_marks: str
    title: str
    blocks: tuple[MarkdownBlock, ...]
    side_image: str
    logo: str


@dataclass(frozen=True)
class SlideLayoutResult:
    markdown: str
    metadata: dict


def _split_frontmatter(markdown: str) -> tuple[str, str]:
    normalized = markdown.replace("\r\n", "\n").strip()
    if not normalized.startswith("---\n"):
        return "---\nmarp: true\ntheme: default\npaginate: true\n---", normalized
    lines = normalized.splitlines()
    end = next(
        (index for index in range(1, len(lines)) if lines[index].strip() == "---"),
        None,
    )
    if end is None:
        return "---\nmarp: true\ntheme: default\npaginate: true\n---", normalized
    return "\n".join(lines[: end + 1]), "\n".join(lines[end + 1 :]).strip()


def _join_deck(frontmatter: str, slides: list[str]) -> str:
    body = "\n\n---\n\n".join(slide.strip() for slide in slides)
    return f"{frontmatter.strip()}\n\n{body}\n"


def _safe_area_block(orientation: str) -> str:
    if orientation not in SAFE_BOTTOM_PX:
        raise ValueError(f"Unknown slide orientation: {orientation}")
    bottom = SAFE_BOTTOM_PX[orientation]
    fit_rules: list[str] = []
    for level, font_size in FIT_FONT_PX[orientation].items():
        fit_rules.append(
            f"section.factory-fit-{level} {{ font-size: {font_size}px; "
            "line-height: 1.24; }}\n"
            f"section.factory-fit-{level} h1, "
            f"section.factory-fit-{level} h2 {{ margin-bottom: 0.35em; }}\n"
            f"section.factory-fit-{level} p, "
            f"section.factory-fit-{level} ul, "
            f"section.factory-fit-{level} ol, "
            f"section.factory-fit-{level} pre, "
            f"section.factory-fit-{level} table {{ margin-top: 0.25em; "
            "margin-bottom: 0.25em; }}"
        )
    return (
        f"{SAFE_AREA_START}\n<style>\n"
        "section {\n"
        "  box-sizing: border-box;\n"
        f"  --factory-safe-bottom: {bottom}px;\n"
        "  padding-bottom: max(var(--factory-safe-bottom), "
        "var(--factory-logo-safe-bottom, 0px)) !important;\n"
        "}\n"
        + "\n".join(fit_rules)
        + f"\n</style>\n{SAFE_AREA_END}"
    )


def apply_slide_safe_area(markdown: str, orientation: str) -> str:
    """Insert the canonical bottom safe area and fit classes once."""
    clean = SAFE_AREA_RE.sub("", markdown.replace("\r\n", "\n")).strip()
    frontmatter, body = _split_frontmatter(clean)
    block = _safe_area_block(orientation)
    return f"{frontmatter}\n\n{block}\n\n{body}\n"


def _set_fit_level(slide: str, level: int) -> str:
    if level not in range(5):
        raise ValueError("Fit level must be between 0 and 4")
    match = LOCAL_CLASS_RE.search(slide)
    classes = [] if match is None else match.group("classes").split()
    classes = [item for item in classes if not FIT_CLASS_RE.fullmatch(item)]
    if level:
        classes.append(f"factory-fit-{level}")
    directive = f"<!-- _class: {' '.join(classes)} -->" if classes else ""
    if match is not None:
        updated = slide[: match.start()] + directive + slide[match.end() :]
    elif directive:
        updated = f"{directive}\n\n{slide.lstrip()}"
    else:
        updated = slide
    return re.sub(r"\n{3,}", "\n\n", updated).strip()


def _chromium_path() -> str | None:
    configured = os.environ.get("CHROME_PATH", "").strip()
    candidates = [
        configured,
        *(shutil.which(name) or "" for name in (
            "chromium",
            "chromium-browser",
            "google-chrome",
            "google-chrome-stable",
            "chrome",
            "msedge",
        )),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    return next((item for item in candidates if item and Path(item).is_file()), None)


def slide_layout_available() -> bool:
    return marp_available() and _chromium_path() is not None


MEASUREMENT_SCRIPT = r"""
<script id="factory-layout-measurement">
(() => {
  const sections = [...document.querySelectorAll('section')].filter((section) => {
    const layer = section.dataset.marpitAdvancedBackground;
    return !layer || layer === 'content';
  });
  const results = sections.map((section, index) => {
    const sectionRect = section.getBoundingClientRect();
    const style = getComputedStyle(section);
    const paddingTop = Number.parseFloat(style.paddingTop) || 0;
    const paddingBottom = Number.parseFloat(style.paddingBottom) || 0;
    const nodes = [...section.querySelectorAll('*')].filter((node) => {
      if (node.matches('style, script, img.factory-logo, img[alt^="bg "]')) return false;
      const nodeStyle = getComputedStyle(node);
      return nodeStyle.display !== 'none' && nodeStyle.visibility !== 'hidden' &&
        nodeStyle.position !== 'absolute' && nodeStyle.position !== 'fixed';
    });
    const rects = nodes.map((node) => node.getBoundingClientRect())
      .filter((rect) => rect.width > 0 && rect.height > 0);
    const top = rects.length ? Math.min(...rects.map((rect) => rect.top)) :
      sectionRect.top + paddingTop;
    const bottom = rects.length ? Math.max(...rects.map((rect) => rect.bottom)) : top;
    const availableTop = sectionRect.top + paddingTop;
    const availableBottom = sectionRect.bottom - paddingBottom;
    const edgeOverflow = Math.max(0, availableTop - top, bottom - availableBottom);
    const scrollOverflow = Math.max(0, section.scrollHeight - section.clientHeight);
    return {
      slide_number: index + 1,
      available_height: Math.max(0, availableBottom - availableTop),
      content_height: Math.max(0, bottom - top),
      overflow_px: Math.max(edgeOverflow, scrollOverflow),
    };
  });
  const json = JSON.stringify(results);
  document.body.dataset.factoryOverflow = btoa(unescape(encodeURIComponent(json)));
})();
</script>
"""


def _measure_deck(md_path: Path) -> list[SlideMeasurement]:
    browser = _chromium_path()
    if not marp_available() or browser is None:
        raise SlideLayoutUnavailable(
            "Marp CLI y Chromium son obligatorios para validar el overflow de slides"
        )
    with tempfile.TemporaryDirectory(prefix="factory-slide-layout-") as temp_name:
        temp_dir = Path(temp_name)
        rendered_html = temp_dir / "deck.html"
        with prepared_marp_source(md_path, inline_images=True) as source:
            result = subprocess.run(
                [
                    shutil.which("marp") or "marp",
                    str(source),
                    "-o",
                    str(rendered_html),
                    "--theme-set",
                    str(vertical_theme_path()),
                    "--allow-local-files",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=RENDER_TIMEOUT,
            )
        if result.returncode != 0 or not rendered_html.is_file():
            raise SlideLayoutError(
                "Marp no pudo preparar la validación de overflow: "
                + result.stderr[-500:].strip()
            )
        source_html = rendered_html.read_text(encoding="utf-8")
        if "</body>" not in source_html:
            raise SlideLayoutError("Marp produjo HTML sin un body medible")
        rendered_html.write_text(
            source_html.replace("</body>", f"{MEASUREMENT_SCRIPT}</body>", 1),
            encoding="utf-8",
        )
        command = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
            "--allow-file-access-from-files",
            "--virtual-time-budget=1500",
            "--dump-dom",
            rendered_html.resolve().as_uri(),
        ]
        if os.name != "nt":
            command.insert(1, "--no-sandbox")
        browser_result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=RENDER_TIMEOUT,
        )
        match = re.search(
            r'data-factory-overflow="(?P<payload>[^"]+)"', browser_result.stdout
        )
        if browser_result.returncode != 0 or match is None:
            raise SlideLayoutError(
                "Chromium no pudo medir el overflow real: "
                + browser_result.stderr[-500:].strip()
            )
        encoded = html.unescape(match.group("payload"))
        payload = json.loads(base64.b64decode(encoded).decode("utf-8"))
        return [SlideMeasurement(**item) for item in payload]


def _paragraph_blocks(text: str) -> list[MarkdownBlock]:
    sentences = [item.strip() for item in SENTENCE_RE.split(text) if item.strip()]
    if len(sentences) <= 1:
        return [MarkdownBlock("párrafo", text.strip())]
    return [MarkdownBlock("párrafo", sentence) for sentence in sentences]


def _markdown_blocks(markdown: str) -> list[MarkdownBlock]:
    lines = markdown.strip().splitlines()
    blocks: list[MarkdownBlock] = []
    index = 0
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        fence = FENCE_RE.match(lines[index])
        if fence:
            marker = fence.group(1)[0]
            start = index
            index += 1
            while index < len(lines) and not lines[index].lstrip().startswith(marker * 3):
                index += 1
            if index < len(lines):
                index += 1
            blocks.append(MarkdownBlock("código", "\n".join(lines[start:index])))
            continue
        if index + 1 < len(lines) and "|" in lines[index] and TABLE_DIVIDER_RE.match(
            lines[index + 1]
        ):
            start = index
            index += 2
            while index < len(lines) and lines[index].strip() and "|" in lines[index]:
                index += 1
            blocks.append(MarkdownBlock("tabla", "\n".join(lines[start:index])))
            continue
        list_match = LIST_ITEM_RE.match(lines[index])
        if list_match:
            start = index
            base_indent = len(list_match.group("indent"))
            index += 1
            while index < len(lines):
                candidate = LIST_ITEM_RE.match(lines[index])
                if candidate and len(candidate.group("indent")) <= base_indent:
                    break
                if not lines[index].strip():
                    next_nonempty = next(
                        (
                            item
                            for item in range(index + 1, len(lines))
                            if lines[item].strip()
                        ),
                        len(lines),
                    )
                    if next_nonempty == len(lines) or LIST_ITEM_RE.match(lines[next_nonempty]):
                        break
                index += 1
            blocks.append(MarkdownBlock("elemento de lista", "\n".join(lines[start:index])))
            continue
        start = index
        index += 1
        while index < len(lines) and lines[index].strip():
            if FENCE_RE.match(lines[index]) or LIST_ITEM_RE.match(lines[index]):
                break
            if index + 1 < len(lines) and TABLE_DIVIDER_RE.match(lines[index + 1]):
                break
            index += 1
        text = "\n".join(lines[start:index]).strip()
        kind = "subtítulo" if text.startswith("#") else "párrafo"
        blocks.extend(
            [MarkdownBlock(kind, text)] if kind != "párrafo" else _paragraph_blocks(text)
        )
    return blocks


def _slide_structure(slide: str) -> SlideStructure:
    logo_match = LOGO_IMAGE_RE.search(slide)
    logo = logo_match.group(0).strip() if logo_match else ""
    clean = LOGO_IMAGE_RE.sub("", slide)
    image_match = SIDE_IMAGE_RE.search(clean)
    side_image = image_match.group(0).strip() if image_match else ""
    clean = SIDE_IMAGE_RE.sub("", clean)
    class_match = LOCAL_CLASS_RE.search(clean)
    classes = tuple(class_match.group("classes").split()) if class_match else ()
    clean = LOCAL_CLASS_RE.sub("", clean, count=1)
    heading = HEADING_RE.search(clean)
    if heading is None:
        prefix = ""
        title = "Contenido"
        marks = "##"
        content = clean
    else:
        prefix = clean[: heading.start()].strip()
        title = heading.group("title").strip()
        marks = heading.group("marks")
        content = clean[heading.end() :]
    return SlideStructure(
        prefix=prefix,
        classes=classes,
        heading_marks=marks,
        title=title,
        blocks=tuple(_markdown_blocks(content)),
        side_image=side_image,
        logo=logo,
    )


def _compose_part(
    structure: SlideStructure,
    blocks: list[MarkdownBlock],
    *,
    part_number: int,
    keep_visuals: bool,
) -> str:
    classes = [item for item in structure.classes if not FIT_CLASS_RE.fullmatch(item)]
    if not keep_visuals:
        classes = [
            item
            for item in classes
            if item
            not in {
                "factory-side-image",
                "factory-side-image-left",
                "factory-side-image-right",
                "factory-has-logo",
                "factory-logo-bottom",
            }
        ]
    classes.append("factory-fit-4")
    pieces: list[str] = []
    if part_number == 1 and structure.prefix:
        pieces.append(structure.prefix)
    pieces.append(f"<!-- _class: {' '.join(dict.fromkeys(classes))} -->")
    if keep_visuals and structure.side_image:
        pieces.append(structure.side_image)
    suffix = "" if part_number == 1 else f" (continuación {part_number})"
    pieces.append(f"{structure.heading_marks} {structure.title}{suffix}")
    pieces.extend(block.text for block in blocks)
    if keep_visuals and structure.logo:
        pieces.append(structure.logo)
    return "\n\n".join(piece for piece in pieces if piece).strip()


def _fit_levels(
    md_path: Path,
    frontmatter: str,
    slides: list[str],
    measure: Callable[[Path], list[SlideMeasurement]],
    adjustments: list[dict],
) -> tuple[list[str], list[SlideMeasurement]]:
    levels = [0] * len(slides)
    measurements: list[SlideMeasurement] = []
    for level in range(5):
        md_path.write_text(_join_deck(frontmatter, slides), encoding="utf-8")
        measurements = measure(md_path)
        if len(measurements) != len(slides):
            raise SlideLayoutError("Marp devolvió un número inesperado de slides")
        overflowing = [index for index, item in enumerate(measurements) if not item.fits]
        if not overflowing or level == 4:
            break
        for index in overflowing:
            next_level = level + 1
            slides[index] = _set_fit_level(slides[index], next_level)
            levels[index] = next_level
    for index, level in enumerate(levels):
        if level:
            orientation = (
                "vertical" if "factory-vertical" in frontmatter else "horizontal"
            )
            adjustments.append(
                {
                    "slide": index + 1,
                    "action": "font_fit",
                    "fit_level": level,
                    "font_size_px": FIT_FONT_PX[orientation][level],
                }
            )
    return slides, measurements


def fit_and_validate_slide_deck(
    md_path: str | Path,
    *,
    orientation: str,
    on_event: Callable[[str, dict], None] | None = None,
    measure: Callable[[Path], list[SlideMeasurement]] | None = None,
) -> SlideLayoutResult:
    """Repair a deck in place and return auditable layout metadata."""
    path = Path(md_path)
    original = path.read_text(encoding="utf-8")
    prepared = apply_slide_safe_area(original, orientation)
    frontmatter, body = _split_frontmatter(prepared)
    slides = [item.strip() for item in SLIDE_SEPARATOR_RE.split(body)]
    slides = [item for item in slides if item]
    if not slides:
        raise SlideLayoutError("El deck no contiene ninguna slide")
    measure_deck = measure or _measure_deck
    adjustments: list[dict] = []
    slides, measurements = _fit_levels(
        path, frontmatter, slides, measure_deck, adjustments
    )
    index = 0
    slides_before = len(slides)
    while index < len(slides):
        if measurements[index].fits:
            index += 1
            continue
        structure = _slide_structure(slides[index])
        if not structure.blocks:
            raise SlideOverflowError(index + 1, "sin puntos de división")
        accepted: list[str] = []
        block_start = 0
        visuals_removed = False
        while block_start < len(structure.blocks):
            candidates: list[tuple[int, str]] = []
            for end in range(block_start + 1, len(structure.blocks) + 1):
                keep_visuals = block_start == 0 and not visuals_removed
                candidate = _compose_part(
                    structure,
                    list(structure.blocks[block_start:end]),
                    part_number=len(accepted) + 1,
                    keep_visuals=keep_visuals,
                )
                candidates.append((end, candidate))
            trial = (
                slides[:index]
                + accepted
                + [candidate for _end, candidate in candidates]
                + slides[index + 1 :]
            )
            path.write_text(_join_deck(frontmatter, trial), encoding="utf-8")
            trial_measurements = measure_deck(path)
            candidate_start = index + len(accepted)
            fitting = [
                candidate
                for candidate, measurement in zip(
                    candidates,
                    trial_measurements[
                        candidate_start : candidate_start + len(candidates)
                    ],
                    strict=True,
                )
                if measurement.fits
            ]
            best_end, best_slide = fitting[-1] if fitting else (None, "")
            if best_end is None and block_start == 0 and (structure.side_image or structure.logo):
                visuals_removed = True
                continue
            if best_end is None:
                raise SlideOverflowError(
                    index + len(accepted) + 1,
                    structure.blocks[block_start].kind,
                )
            accepted.append(best_slide)
            block_start = best_end
        slides[index : index + 1] = accepted
        adjustments.append(
            {
                "slide": index + 1,
                "action": "split",
                "created_slides": len(accepted),
                "visuals_removed": visuals_removed,
            }
        )
        path.write_text(_join_deck(frontmatter, slides), encoding="utf-8")
        measurements = measure_deck(path)
        index += len(accepted)

    path.write_text(_join_deck(frontmatter, slides), encoding="utf-8")
    final_measurements = measure_deck(path)
    overflowing = [item for item in final_measurements if not item.fits]
    if overflowing:
        raise SlideOverflowError(overflowing[0].slide_number, "contenido")
    metadata = {
        "schema_version": LAYOUT_SCHEMA_VERSION,
        "status": "passed",
        "orientation": orientation,
        "safe_bottom_px": SAFE_BOTTOM_PX[orientation],
        "slides_before": slides_before,
        "slides_after": len(slides),
        "adjustments": adjustments,
        "measurements": [
            {
                "slide": item.slide_number,
                "available_height": round(item.available_height, 2),
                "content_height": round(item.content_height, 2),
                "overflow_px": round(item.overflow_px, 2),
            }
            for item in final_measurements
        ],
    }
    if on_event:
        for measurement in final_measurements:
            on_event(
                "Área segura de slide validada",
                {
                    "slide": measurement.slide_number,
                    "available_height": round(measurement.available_height, 2),
                    "content_height": round(measurement.content_height, 2),
                    "overflow_px": round(measurement.overflow_px, 2),
                },
            )
    for adjustment in adjustments:
        if on_event:
            on_event("Slide ajustada para respetar el área segura", adjustment)
    return SlideLayoutResult(markdown=path.read_text(encoding="utf-8"), metadata=metadata)


def prepare_slide_layout(
    md_path: str | Path,
    *,
    orientation: str,
    on_event: Callable[[str, dict], None] | None = None,
) -> SlideLayoutResult:
    """Apply safe areas and measure them when the rendering runtime is available."""
    path = Path(md_path)
    if slide_layout_available():
        return fit_and_validate_slide_deck(
            path,
            orientation=orientation,
            on_event=on_event,
        )
    markdown = apply_slide_safe_area(path.read_text(encoding="utf-8"), orientation)
    path.write_text(markdown, encoding="utf-8")
    return SlideLayoutResult(
        markdown=markdown,
        metadata={
            "schema_version": LAYOUT_SCHEMA_VERSION,
            "status": "unavailable",
            "orientation": orientation,
            "safe_bottom_px": SAFE_BOTTOM_PX[orientation],
            "slides_before": None,
            "slides_after": None,
            "adjustments": [],
            "measurements": [],
        },
    )
