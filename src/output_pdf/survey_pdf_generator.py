import io
import re
from typing import List, Dict

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER, TA_LEFT
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Table, TableStyle,
    Paragraph, Spacer, PageBreak, NextPageTemplate, HRFlowable,
)

PAGE_W, PAGE_H = letter
MARGIN = 0.72 * inch
COL_GAP = 0.2 * inch
BODY_W = PAGE_W - 2 * MARGIN
BODY_H = PAGE_H - 2 * MARGIN
COL_W = (BODY_W - COL_GAP) / 2


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "topic": ParagraphStyle(
            "Topic", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=14,
            leading=18, alignment=TA_CENTER, spaceAfter=4,
        ),
        "table_header": ParagraphStyle(
            "TH", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=6.5,
            leading=8, alignment=TA_CENTER,
        ),
        "table_cell": ParagraphStyle(
            "TC", parent=base["Normal"],
            fontName="Helvetica", fontSize=6,
            leading=7.5, alignment=TA_LEFT,
        ),
        "paper_section_label": ParagraphStyle(
            "PSL", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=11,
            leading=14, alignment=TA_CENTER, spaceAfter=2, spaceBefore=4,
        ),
        "paper_heading": ParagraphStyle(
            "PH", parent=base["Normal"],
            fontName="Times-Bold", fontSize=9,
            leading=11, spaceBefore=8, spaceAfter=3,
            alignment=TA_LEFT,
        ),
        "paper_body": ParagraphStyle(
            "PB", parent=base["Normal"],
            fontName="Times-Roman", fontSize=9,
            leading=11, alignment=TA_JUSTIFY, spaceAfter=4,
            firstLineIndent=12,
        ),
    }


def _build_survey_table(rows: List[Dict], styles: dict) -> Table:
    col_keys = [
        "No.", "Title", "Authors",
        "Journal Details (DOI / Year / Citation)",
        "Problem Statement", "Objective", "Research Gap",
        "Methodology (Algorithm / Techniques)", "Features (Focused)",
        "Results & Discussion (Performance Metric / Value)",
        "Limitations", "Future Scope",
    ]
    headers = [
        "#", "Title", "Authors", "DOI / Year",
        "Problem", "Objective", "Gap",
        "Methodology", "Features",
        "Results", "Limitations", "Future Scope",
    ]
    th = styles["table_header"]
    tc = styles["table_cell"]

    data = [[Paragraph(h, th) for h in headers]]
    for row in rows:
        data.append([Paragraph(str(row.get(k, "")), tc) for k in col_keys])

    # Proportional widths — must sum to BODY_W
    raw = [0.22, 1.1, 0.60, 0.70, 0.72, 0.62, 0.62, 0.72, 0.55, 0.72, 0.55, 0.55]
    scale = BODY_W / sum(raw)
    col_widths = [w * scale for w in raw]

    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#1e3a5f")),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("ALIGN",         (0, 0), (-1, 0),  "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("GRID",          (0, 0), (-1, -1), 0.3, colors.HexColor("#bbbbbb")),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4f8")]),
        ("LEFTPADDING",   (0, 0), (-1, -1), 2),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 2),
        ("TOPPADDING",    (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ALIGN",         (0, 1), (0, -1),  "CENTER"),
        ("FONTNAME",      (0, 1), (0, -1),  "Helvetica-Bold"),
    ]))
    return t


_HEADING_RE = re.compile(
    r"^([IVX]+\.\s+[A-Z]|Abstract|Index Terms|REFERENCES)",
    re.IGNORECASE,
)
_ALL_CAPS_RE = re.compile(r"^[A-Z][A-Z ]{3,}$")


def _paper_to_story(paper_text: str, styles: dict) -> list:
    """Convert plain paper text into reportlab Paragraphs for two-column flow."""
    story = []
    para_lines: list[str] = []

    def flush():
        if para_lines:
            text = " ".join(para_lines).strip()
            if text:
                story.append(Paragraph(text, styles["paper_body"]))
            para_lines.clear()

    for raw_line in paper_text.split("\n"):
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if _HEADING_RE.match(line) or _ALL_CAPS_RE.match(line):
            flush()
            story.append(Spacer(1, 4))
            story.append(Paragraph(line, styles["paper_heading"]))
            story.append(
                HRFlowable(width="100%", thickness=0.4,
                           color=colors.HexColor("#1e3a5f"))
            )
            story.append(Spacer(1, 3))
        else:
            para_lines.append(line)

    flush()
    return story


def generate_survey_combined_pdf(
    rows: List[Dict],
    paper_text: str,
    topic: str,
) -> bytes:
    """
    Returns a PDF as bytes containing:
      - Page(s) 1+  : full survey table (single-column, headers repeat per page)
      - Page(s) N+  : sample IEEE paper in true two-column reportlab layout
    """
    buf = io.BytesIO()
    styles = _styles()

    # ── Page templates ────────────────────────────────────────────────────────
    single_frame = Frame(MARGIN, MARGIN, BODY_W, BODY_H, id="single")
    left_frame   = Frame(MARGIN,                  MARGIN, COL_W, BODY_H, id="left")
    right_frame  = Frame(MARGIN + COL_W + COL_GAP, MARGIN, COL_W, BODY_H, id="right")

    doc = BaseDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN,  bottomMargin=MARGIN,
    )
    doc.addPageTemplates([
        PageTemplate(id="single",  frames=[single_frame]),
        PageTemplate(id="two_col", frames=[left_frame, right_frame]),
    ])

    story = []

    # ── Survey table section ─────────────────────────────────────────────────
    story.append(NextPageTemplate("single"))
    story.append(Paragraph(f"Literature Survey: {topic}", styles["topic"]))
    story.append(HRFlowable(width="100%", thickness=1.5,
                             color=colors.HexColor("#1e3a5f")))
    story.append(Spacer(1, 10))
    story.append(_build_survey_table(rows, styles))

    # ── IEEE paper section ───────────────────────────────────────────────────
    story.append(NextPageTemplate("two_col"))
    story.append(PageBreak())
    story.append(Paragraph("Sample IEEE Write-up", styles["paper_section_label"]))
    story.append(HRFlowable(width="100%", thickness=1,
                             color=colors.HexColor("#1e3a5f")))
    story.append(Spacer(1, 6))
    story.extend(_paper_to_story(paper_text, styles))

    doc.build(story)
    buf.seek(0)
    return buf.read()
