import logging
import os
import re
from typing import Dict, List

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _set_cell_bg(cell, hex_color: str):
    """Apply background fill colour to a table cell via raw XML."""
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def _enable_two_columns(section):
    """Add a two-column layout to a Word section via raw XML."""
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    sectPr = section._sectPr
    # Remove any existing cols element first
    for existing in sectPr.findall(qn("w:cols")):
        sectPr.remove(existing)
    cols = OxmlElement("w:cols")
    cols.set(qn("w:num"), "2")
    cols.set(qn("w:space"), "567")   # ~1 cm gap between columns
    cols.set(qn("w:equalWidth"), "1")
    sectPr.append(cols)


# ── IEEE paper → .docx ────────────────────────────────────────────────────────
_HEADING_RE = re.compile(
    r"^([IVX]+\.\s+[A-Z][A-Z\s]+|Abstract|Index Terms|REFERENCES)",
    re.IGNORECASE,
)
_ALL_CAPS_RE = re.compile(r"^[A-Z][A-Z ]{3,}$")
_AUTHOR_LINE_RE = re.compile(
    r"^([\w\s\-,\.]+)\s*[\|·]\s*([\w\s\-,\.]+)\s*[\|·]\s*([\w@\.\-]+)$"
)


def generate_paper_docx(
    paper_text: str,
    title: str,
    output_dir: str,
    filename: str,
) -> str | None:
    try:
        from docx import Document
        from docx.shared import Pt, Cm, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        logger.error("python-docx not installed. Run: pip install python-docx")
        return None

    doc = Document()

    # Page margins — IEEE-like (2.5 cm)
    for sec in doc.sections:
        sec.top_margin    = Cm(2.54)
        sec.bottom_margin = Cm(2.54)
        sec.left_margin   = Cm(2.54)
        sec.right_margin  = Cm(2.54)

    lines = (paper_text or "").split("\n")
    in_header = True   # first few non-empty lines before the first heading
    header_count = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        is_heading = _HEADING_RE.match(stripped) or _ALL_CAPS_RE.match(stripped)

        if is_heading:
            in_header = False
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            run = p.add_run(stripped)
            run.bold = True
            run.font.size = Pt(11)
            run.font.color.rgb = RGBColor(0x1F, 0x4E, 0x79)  # dark blue
        elif in_header:
            # Title / author / affiliation block — centred
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(stripped)
            if header_count == 0:
                run.bold = True
                run.font.size = Pt(16)
            else:
                run.font.size = Pt(11)
            header_count += 1
        else:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p.paragraph_format.first_line_indent = Cm(0.5)
            run = p.add_run(stripped)
            run.font.size = Pt(10)

    # Enable 2-column layout AFTER writing content
    _enable_two_columns(doc.sections[0])

    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{filename}.docx")
    try:
        doc.save(path)
        logger.info("Saved paper .docx: %s", path)
        return path
    except Exception as e:
        logger.error("Failed to save paper .docx: %s", e)
        return None


# ── Survey table → .docx ──────────────────────────────────────────────────────
_SURVEY_COLUMNS = [
    "No.", "Title", "Authors",
    "Journal Details (DOI / Year / Citation)",
    "Problem Statement", "Objective", "Research Gap",
    "Methodology (Algorithm / Techniques)", "Features (Focused)",
    "Results & Discussion (Performance Metric / Value)",
    "Limitations", "Future Scope",
]

# Approximate column widths in cm (must sum ≤ usable page width ~16 cm)
_COL_WIDTHS_CM = [0.7, 2.8, 2.2, 2.0, 1.8, 1.8, 1.8, 1.8, 1.8, 2.0, 1.6, 1.6]


def generate_survey_docx(
    rows: List[Dict],
    topic: str,
    output_dir: str,
    filename: str,
) -> str | None:
    if not rows:
        return None
    try:
        from docx import Document
        from docx.shared import Pt, Cm, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml.ns import qn as _qn
    except ImportError:
        logger.error("python-docx not installed. Run: pip install python-docx")
        return None

    doc = Document()

    # Landscape orientation for wide table
    for sec in doc.sections:
        sec.orientation = 1   # landscape
        sec.page_width, sec.page_height = sec.page_height, sec.page_width
        sec.left_margin  = Cm(1.5)
        sec.right_margin = Cm(1.5)
        sec.top_margin   = Cm(2.0)
        sec.bottom_margin = Cm(2.0)

    # Title
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run(f"Literature Survey: {topic.title()}")
    r.bold = True
    r.font.size = Pt(14)
    doc.add_paragraph()

    num_cols = len(_SURVEY_COLUMNS)
    table = doc.add_table(rows=1 + len(rows), cols=num_cols)
    table.style = "Table Grid"

    # Set column widths
    for col_idx, width in enumerate(_COL_WIDTHS_CM):
        for row in table.rows:
            row.cells[col_idx].width = Cm(width)

    # Header row
    hdr_row = table.rows[0]
    for col_idx, col_name in enumerate(_SURVEY_COLUMNS):
        cell = hdr_row.cells[col_idx]
        cell.text = col_name
        _set_cell_bg(cell, "1F4E79")
        run = cell.paragraphs[0].runs[0]
        run.bold = True
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Data rows
    for r_idx, row_data in enumerate(rows):
        trow = table.rows[r_idx + 1]
        bg = "D6E4F0" if r_idx % 2 == 1 else "FFFFFF"
        for col_idx, col_name in enumerate(_SURVEY_COLUMNS):
            cell = trow.cells[col_idx]
            cell.text = str(row_data.get(col_name, ""))
            _set_cell_bg(cell, bg)
            run = cell.paragraphs[0].runs[0]
            run.font.size = Pt(8)

    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{filename}.docx")
    try:
        doc.save(path)
        logger.info("Saved survey .docx: %s", path)
        return path
    except Exception as e:
        logger.error("Failed to save survey .docx: %s", e)
        return None
