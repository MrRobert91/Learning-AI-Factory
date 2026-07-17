"""Formatted lesson PDF exports built from the canonical Markdown artifacts."""

from __future__ import annotations

import html
import io
import re
from collections.abc import Sequence
from dataclasses import dataclass

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


@dataclass(frozen=True)
class LessonDocument:
    title: str
    markdown: str


def _inline_markup(value: str) -> str:
    """Convert the small inline Markdown subset used by lessons to ReportLab XML."""
    escaped = html.escape(value.strip())
    code_fragments: list[str] = []

    def store_code(match: re.Match[str]) -> str:
        code_fragments.append(f'<font name="Courier" color="#8f2f20">{match.group(1)}</font>')
        return f"@@CODE{len(code_fragments) - 1}@@"

    escaped = re.sub(r"`([^`]+)`", store_code, escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"__([^_]+)__", r"<b>\1</b>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", escaped)
    escaped = re.sub(
        r"\[([^]]+)]\((https?://[^)]+)\)",
        r'<link href="\2" color="#8f2f20"><u>\1</u></link>',
        escaped,
    )
    for index, fragment in enumerate(code_fragments):
        escaped = escaped.replace(f"@@CODE{index}@@", fragment)
    return escaped


def _styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    body = ParagraphStyle(
        "LessonBody",
        parent=sample["BodyText"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=15,
        textColor=colors.HexColor("#2a2119"),
        spaceAfter=7,
        splitLongWords=False,
    )
    return {
        "title": ParagraphStyle(
            "LessonTitle",
            parent=sample["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=29,
            textColor=colors.HexColor("#8f2f20"),
            alignment=TA_CENTER,
            spaceAfter=16,
        ),
        "h1": ParagraphStyle(
            "LessonH1",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=colors.HexColor("#8f2f20"),
            spaceBefore=12,
            spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "LessonH2",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            textColor=colors.HexColor("#3b3028"),
            spaceBefore=10,
            spaceAfter=6,
        ),
        "h3": ParagraphStyle(
            "LessonH3",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=17,
            textColor=colors.HexColor("#3b3028"),
            spaceBefore=8,
            spaceAfter=5,
        ),
        "body": body,
        "quote": ParagraphStyle(
            "LessonQuote",
            parent=body,
            leftIndent=12,
            borderColor=colors.HexColor("#b23a26"),
            borderWidth=2,
            borderPadding=7,
            backColor=colors.HexColor("#f8eee0"),
            textColor=colors.HexColor("#4a3d34"),
        ),
        "code": ParagraphStyle(
            "LessonCode",
            parent=sample["Code"],
            fontName="Courier",
            fontSize=8,
            leading=10,
            leftIndent=7,
            rightIndent=7,
            borderColor=colors.HexColor("#2a2119"),
            borderWidth=1,
            borderPadding=8,
            backColor=colors.HexColor("#2a2119"),
            textColor=colors.HexColor("#f2e9d8"),
            spaceBefore=5,
            spaceAfter=9,
        ),
        "footer": ParagraphStyle(
            "LessonFooter",
            parent=body,
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#76665a"),
        ),
    }


def _table(rows: list[list[str]], styles: dict[str, ParagraphStyle]) -> Table:
    body = [[Paragraph(_inline_markup(cell), styles["body"]) for cell in row] for row in rows]
    columns = max(len(row) for row in rows)
    for row in body:
        row.extend(Paragraph("", styles["body"]) for _ in range(columns - len(row)))
    table = Table(body, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9dcc4")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#2a2119")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#8e7b6d")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _markdown_flowables(markdown: str, styles: dict[str, ParagraphStyle]) -> list:
    lines = markdown.replace("\r\n", "\n").split("\n")
    flowables: list = []
    paragraph: list[str] = []
    index = 0

    def flush_paragraph() -> None:
        if not paragraph:
            return
        value = " ".join(line.strip() for line in paragraph).strip()
        paragraph.clear()
        if value:
            flowables.append(KeepTogether([Paragraph(_inline_markup(value), styles["body"])]))

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith(chr(96) * 3):
            flush_paragraph()
            index += 1
            code_lines: list[str] = []
            while index < len(lines) and not lines[index].strip().startswith(chr(96) * 3):
                code_lines.append(lines[index])
                index += 1
            code = Preformatted("\n".join(code_lines) or " ", styles["code"], maxLineLength=110)
            flowables.append(KeepTogether([code]) if len(code_lines) <= 45 else code)
        elif re.match(r"^#{1,3}\s+", stripped):
            flush_paragraph()
            level = len(stripped) - len(stripped.lstrip("#"))
            value = stripped[level:].strip()
            flowables.append(KeepTogether([Paragraph(_inline_markup(value), styles[f"h{level}"])]))
        elif re.match(r"^[-*+]\s+", stripped):
            flush_paragraph()
            items: list[ListItem] = []
            while index < len(lines) and re.match(r"^\s*[-*+]\s+", lines[index]):
                item = re.sub(r"^\s*[-*+]\s+", "", lines[index]).strip()
                items.append(ListItem(Paragraph(_inline_markup(item), styles["body"])))
                index += 1
            flowables.append(
                KeepTogether(
                    [
                        ListFlowable(
                            items,
                            bulletType="bullet",
                            leftIndent=18,
                            bulletFontName="Helvetica",
                            bulletFontSize=8,
                        )
                    ]
                )
            )
            continue
        elif re.match(r"^\d+[.)]\s+", stripped):
            flush_paragraph()
            items = []
            while index < len(lines) and re.match(r"^\s*\d+[.)]\s+", lines[index]):
                item = re.sub(r"^\s*\d+[.)]\s+", "", lines[index]).strip()
                items.append(ListItem(Paragraph(_inline_markup(item), styles["body"])))
                index += 1
            flowables.append(KeepTogether([ListFlowable(items, bulletType="1", leftIndent=22)]))
            continue
        elif stripped.startswith(">"):
            flush_paragraph()
            quote_lines = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote_lines.append(lines[index].strip().removeprefix(">").strip())
                index += 1
            flowables.append(
                KeepTogether([Paragraph(_inline_markup(" ".join(quote_lines)), styles["quote"])])
            )
            continue
        elif (
            "|" in stripped
            and index + 1 < len(lines)
            and re.match(r"^\s*\|?\s*:?-{3,}", lines[index + 1])
        ):
            flush_paragraph()
            rows = [[cell.strip() for cell in stripped.strip("|").split("|")]]
            index += 2
            while index < len(lines) and "|" in lines[index]:
                rows.append([cell.strip() for cell in lines[index].strip().strip("|").split("|")])
                index += 1
            flowables.append(_table(rows, styles))
            flowables.append(Spacer(1, 7))
            continue
        elif stripped in {"---", "***", "___"}:
            flush_paragraph()
            flowables.append(Spacer(1, 7))
        elif not stripped:
            flush_paragraph()
        else:
            paragraph.append(line)
        index += 1
    flush_paragraph()
    return flowables


def lessons_pdf(documents: Sequence[LessonDocument]) -> bytes:
    """Build a polished PDF, keeping paragraphs and code blocks intact when possible."""
    buffer = io.BytesIO()
    styles = _styles()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=documents[0].title if len(documents) == 1 else "Lecciones del curso",
        author="AI Learning Factory",
    )
    story: list = []
    for index, lesson in enumerate(documents):
        if index:
            story.append(PageBreak())
        story.append(Paragraph(_inline_markup(lesson.title), styles["title"]))
        story.append(Spacer(1, 3))
        story.extend(_markdown_flowables(lesson.markdown, styles))

    def footer(canvas, document) -> None:
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#c9b9a7"))
        canvas.setLineWidth(0.5)
        canvas.line(20 * mm, 12 * mm, A4[0] - 20 * mm, 12 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#76665a"))
        canvas.drawString(20 * mm, 8 * mm, "AI Learning Factory")
        canvas.drawRightString(
            A4[0] - 20 * mm,
            8 * mm,
            f"Pagina {document.page}",
        )
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
