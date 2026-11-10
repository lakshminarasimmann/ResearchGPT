from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER

OUTPUT = "ResearchGPT_Changes.pdf"

doc = SimpleDocTemplate(
    OUTPUT,
    pagesize=A4,
    leftMargin=2*cm, rightMargin=2*cm,
    topMargin=2*cm, bottomMargin=2*cm,
    title="ResearchGPT — What We Built & Changed",
)

styles = getSampleStyleSheet()

BLUE   = colors.HexColor("#1a73e8")
GREEN  = colors.HexColor("#188038")
ORANGE = colors.HexColor("#e37400")
RED    = colors.HexColor("#c5221f")
DARK   = colors.HexColor("#202124")
MID    = colors.HexColor("#5f6368")
LIGHT  = colors.HexColor("#f1f3f4")
CODE_BG= colors.HexColor("#f8f9fa")
NEW_BG = colors.HexColor("#e6f4ea")
MOD_BG = colors.HexColor("#e8f0fe")
CUR_BG = colors.HexColor("#fce8e6")

def style(name, **kw):
    base = kw.pop("parent", styles["Normal"])
    return ParagraphStyle(name, parent=base, **kw)

title_s    = style("T", fontSize=24, textColor=BLUE, spaceAfter=4, fontName="Helvetica-Bold", alignment=TA_CENTER)
subtitle_s = style("Sub", fontSize=11, textColor=MID, spaceAfter=18, alignment=TA_CENTER)
h1_s       = style("H1", fontSize=16, textColor=BLUE, spaceBefore=20, spaceAfter=6, fontName="Helvetica-Bold")
h2_s       = style("H2", fontSize=13, textColor=DARK, spaceBefore=14, spaceAfter=4, fontName="Helvetica-Bold")
h3_s       = style("H3", fontSize=11, textColor=MID,  spaceBefore=10, spaceAfter=3, fontName="Helvetica-Bold")
body_s     = style("Body", fontSize=10, textColor=DARK, leading=16, spaceAfter=5)
bullet_s   = style("Bul", fontSize=10, textColor=DARK, leading=15, leftIndent=14, spaceAfter=3)
code_s     = style("Code", fontSize=8.5, textColor=colors.HexColor("#37474f"), backColor=CODE_BG,
                   leftIndent=10, rightIndent=10, leading=13, spaceAfter=6, spaceBefore=3,
                   fontName="Courier", borderPad=4)
label_new  = style("LN", fontSize=8, textColor=GREEN,  fontName="Helvetica-Bold")
label_mod  = style("LM", fontSize=8, textColor=BLUE,   fontName="Helvetica-Bold")
label_cur  = style("LC", fontSize=8, textColor=RED,    fontName="Helvetica-Bold")

def HR(color=colors.HexColor("#dadce0")):
    return HRFlowable(width="100%", thickness=1, color=color, spaceAfter=6, spaceBefore=2)

def B(t): return f"<b>{t}</b>"
def C(t): return f'<font name="Courier" size="9">{t}</font>'

def badge(text, color):
    return f'<font color="{color}"><b>[{text}]</b></font>'

def tbl(headers, rows, widths=None):
    data = [headers] + rows
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,0), BLUE),
        ("TEXTCOLOR",    (0,0), (-1,0), colors.white),
        ("FONTNAME",     (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",     (0,0), (-1,-1), 9),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, LIGHT]),
        ("GRID",         (0,0), (-1,-1), 0.4, colors.HexColor("#dadce0")),
        ("TOPPADDING",   (0,0), (-1,-1), 5),
        ("BOTTOMPADDING",(0,0), (-1,-1), 5),
        ("LEFTPADDING",  (0,0), (-1,-1), 7),
        ("VALIGN",       (0,0), (-1,-1), "TOP"),
    ]))
    return t

def colored_tbl(headers, rows, row_colors, widths=None):
    data = [headers] + rows
    t = Table(data, colWidths=widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND",   (0,0), (-1,0), BLUE),
        ("TEXTCOLOR",    (0,0), (-1,0), colors.white),
        ("FONTNAME",     (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",     (0,0), (-1,-1), 9),
        ("GRID",         (0,0), (-1,-1), 0.4, colors.HexColor("#dadce0")),
        ("TOPPADDING",   (0,0), (-1,-1), 5),
        ("BOTTOMPADDING",(0,0), (-1,-1), 5),
        ("LEFTPADDING",  (0,0), (-1,-1), 7),
        ("VALIGN",       (0,0), (-1,-1), "TOP"),
    ]
    for i, bg in enumerate(row_colors):
        if bg:
            style_cmds.append(("BACKGROUND", (0, i+1), (-1, i+1), bg))
    t.setStyle(TableStyle(style_cmds))
    return t

story = []

# ── COVER ──────────────────────────────────────────────────────────────────
story.append(Spacer(1, 2.5*cm))
story.append(Paragraph("ResearchGPT", title_s))
story.append(Paragraph("What We Built &amp; Changed — Full Changelog", subtitle_s))
story.append(HR(BLUE))
story.append(Spacer(1, 0.4*cm))
story.append(Paragraph(
    "This document covers every addition and modification made to the project across all commits, "
    "from the initial NexusRAG codebase to the current ResearchGPT state — including uncommitted "
    "working-tree changes.",
    style("intro", parent=body_s, fontSize=10.5, textColor=MID, alignment=TA_CENTER)))
story.append(Spacer(1, 0.6*cm))

# Legend
leg_data = [
    [Paragraph(f'<font color="{GREEN}"><b>NEW FILE</b></font>', styles["Normal"]),
     "File created from scratch in this commit"],
    [Paragraph(f'<font color="{BLUE}"><b>MODIFIED</b></font>', styles["Normal"]),
     "Existing file with significant additions or rewrites"],
    [Paragraph(f'<font color="{RED}"><b>UNCOMMITTED</b></font>', styles["Normal"]),
     "Changes in working tree not yet in any commit"],
]
lt = Table(leg_data, colWidths=[4*cm, 11.5*cm])
lt.setStyle(TableStyle([
    ("GRID",        (0,0),(-1,-1), 0.4, colors.HexColor("#dadce0")),
    ("BACKGROUND",  (0,0),(-1,-1), LIGHT),
    ("TOPPADDING",  (0,0),(-1,-1), 5),
    ("BOTTOMPADDING",(0,0),(-1,-1), 5),
    ("LEFTPADDING", (0,0),(-1,-1), 8),
    ("FONTSIZE",    (0,0),(-1,-1), 9),
]))
story.append(lt)
story.append(PageBreak())

# ── COMMIT TIMELINE ────────────────────────────────────────────────────────
story.append(Paragraph("Commit Timeline", h1_s))
story.append(HR())
timeline = [
    ["Hash", "Date", "Description", "Impact"],
    ["38f4775", "Early 2026", "Rename project from NexusRAG to ResearchGPT", "Branding"],
    ["57d7c9c", "Early 2026", "Add files via upload", "Initial files"],
    ["ccb8a74", "Apr 21 2026", "Add ResearchGPT unified UI and root gitignore",
     "Massive — 3,756 additions"],
    ["c4ea420", "Jun 10 2026", "All changed files — second major batch",
     "Large — 2,817 additions"],
    ["c8c88c9", "Jun 10 2026", "All changed files — .gitignore update", "Minor"],
    ["(working)", "Jun 15 2026", "Uncommitted changes in ui.py + llm_client.py", "Active"],
]
story.append(tbl(timeline[0], timeline[1:], [2.5*cm, 3*cm, 7*cm, 3*cm]))
story.append(PageBreak())

# ── COMMIT ccb8a74 ─────────────────────────────────────────────────────────
story.append(Paragraph("Commit ccb8a74 — Apr 21, 2026", h1_s))
story.append(Paragraph('"Add ResearchGPT unified UI and root gitignore"', style("q", parent=body_s, textColor=MID, fontSize=10)))
story.append(HR())
story.append(Paragraph(
    "This was the foundational commit that built the entire ResearchGPT system on top of the "
    "original NexusRAG skeleton. Nearly every component was either created from scratch or "
    "heavily rewritten. 31 files changed with 3,756 additions.", body_s))
story.append(Spacer(1, 0.3*cm))

# New files table
story.append(Paragraph("New Files Created", h2_s))
new_files = [
    ["File", "Lines", "What It Does"],
    [C("rag_new/ui.py"), "749", "Brand-new Streamlit web interface — multi-tab layout, chat sessions, paper/survey view"],
    [C("rag_new/src/analysis/paper_analyzer.py"), "248", "Literature survey engine — fetches arXiv papers, extracts 8 structured fields via LLM"],
    [C("rag_new/src/output_pdf/latex_generator.py"), "244", "Generates IEEE-formatted PDFs via LaTeX/ReportLab"],
    [C("rag_new/src/output_pdf/pdf_generator.py"), "82", "Direct ReportLab PDF output (two-column IEEE format)"],
    [C("rag_new/src/output_pdf/latex_template.py"), "19", "LaTeX template string for IEEE paper structure"],
    [C("rag_new/src/pipeline/ui_pipeline.py"), "379", "Master orchestration pipeline: ingest → index → retrieve → generate → evaluate → output"],
    [C("rag_new/src/analysis/__init__.py"), "0", "Package init"],
    [C("rag_new/src/output_pdf/__init__.py"), "0", "Package init"],
    [C("rag_new/test.py"), "5", "Quick smoke test script"],
]
story.append(colored_tbl(new_files[0], new_files[1:], [NEW_BG]*len(new_files),
             widths=[7*cm, 1.5*cm, 7*cm]))

story.append(Spacer(1, 0.3*cm))
story.append(Paragraph("Major File Rewrites / Additions", h2_s))
mod_files = [
    ["File", "Change", "Key Additions"],
    [C("rag_new/src/generation/generator.py"), "+818 lines",
     "Full IEEE paper generation with 8 sections, citation validation, context refinement, markdown cleanup, section length guidance"],
    [C("rag_new/src/retrieval/retriever.py"), "+452 lines (rewritten)",
     "Hybrid BM25 + Vector search, HyDE strategy, Complex sub-question decomposition, Cross-Encoder reranking with section-aware scoring"],
    [C("rag_new/src/evaluation/evaluator.py"), "+380 lines",
     "G-Eval faithfulness & relevance (1-5), ROUGE-L, Hit Rate, MRR, plagiarism detection with sentence-level similarity and n-gram overlap"],
    [C("rag_new/src/ingestion/ingestor.py"), "+290 lines",
     "Exponential backoff retries, rate limiting, HTML fallback, metadata JSON persistence, duplicate download prevention"],
    [C("rag_new/src/embedding/vector_store.py"), "+189 lines",
     "Topic-specific collections, automatic pruning of stale collections, bulk get-all for BM25 fitting"],
    [C("rag_new/src/processing/processor.py"), "+217 lines",
     "PyMuPDF text extraction with table support, section heading detection, metadata propagation to chunks"],
    [C("rag_new/config/config.py"), "+124 lines (rewritten)",
     "Centralised config with survey settings, BM25 alphas, per-strategy params, plagiarism threshold"],
    [C("rag_new/main.py"), "+404 lines (rewritten)",
     "Full CLI with subcommands: run_all, ingest, index, retrieve, generate, evaluate"],
    [C("rag_new/requirements.txt"), "+56 lines",
     "Added: sentence-transformers, chromadb, rank_bm25, rouge-score, reportlab, PyMuPDF, python-docx, arxiv, certifi"],
]
story.append(colored_tbl(mod_files[0], mod_files[1:], [MOD_BG]*len(mod_files),
             widths=[6*cm, 2.5*cm, 7*cm]))

story.append(Spacer(1, 0.3*cm))
story.append(Paragraph("What This Commit Delivered (Feature Summary)", h2_s))
features_ccb = [
    ("Streamlit UI", "Full web interface with sidebar chat history, paper/survey/quality tabs, settings panel"),
    ("Literature Survey", "Automated survey generation — fetches papers, extracts Problem/Objective/Gap/Methodology/Results/Limitations/Future Scope"),
    ("HyDE Retrieval", "Hypothetical Document Embeddings — LLM generates an answer, then searches using that answer as the query"),
    ("Complex Retrieval", "Sub-question decomposition — breaks comparisons into 2-3 sub-queries and merges results"),
    ("Hybrid Search", "BM25 + Vector search with strategy-specific blending ratios"),
    ("Cross-Encoder Reranking", "ms-marco-MiniLM-L-12-v2 rescores candidates, with bonuses for Results/Methodology sections"),
    ("IEEE Paper Generation", "8-section IEEE papers with roman numeral headings, numbered citations, word-count targets"),
    ("G-Eval Evaluation", "LLM-based Faithfulness and Relevance scoring (1-5) with reasoning explanations"),
    ("Plagiarism Detection", "Sentence-level cosine similarity + 8-gram overlap checking"),
    ("ROUGE-L, Hit Rate, MRR", "Traditional retrieval quality metrics"),
    ("PDF Output", "IEEE two-column PDF via ReportLab and LaTeX template"),
    ("Pipeline Orchestration", "Single ui_pipeline.py coordinates all stages with progress callbacks and 1-hour in-process cache"),
    ("Topic-Isolated Vector DB", "One ChromaDB collection per topic; auto-prunes old collections"),
    ("arXiv Ingestion", "Downloads papers with exponential backoff, rate limiting, HTML fallback"),
    ("CLI Interface", "main.py with subcommands for each pipeline stage"),
]
for feature, desc in features_ccb:
    story.append(Paragraph(f"• {B(feature)}: {desc}", bullet_s))

story.append(PageBreak())

# ── COMMIT c4ea420 ─────────────────────────────────────────────────────────
story.append(Paragraph("Commit c4ea420 — Jun 10, 2026", h1_s))
story.append(Paragraph('"All changed files" — Second major batch', style("q", parent=body_s, textColor=MID, fontSize=10)))
story.append(HR())
story.append(Paragraph(
    "This commit expanded the UI significantly and added three new backend modules: "
    "a dedicated LLM client, session history persistence, and Word/.docx + survey PDF export. "
    "18 files changed with 2,817 additions.", body_s))
story.append(Spacer(1, 0.3*cm))

story.append(Paragraph("New Files Created", h2_s))
new_c4 = [
    ["File", "Lines", "What It Does"],
    [C("rag_new/src/generation/llm_client.py"), "149",
     "Dedicated LLM client extracted from generator.py — dual provider support (Cerebras/OpenAI + Ollama), token estimation, streaming, initial retry skeleton"],
    [C("rag_new/src/history/paper_history.py"), "142",
     "Disk-based session persistence — saves paper text, scores, context, survey rows, timings; base64-encoded PDFs in JSON; load/delete operations"],
    [C("rag_new/src/output_pdf/docx_generator.py"), "213",
     "Microsoft Word (.docx) export for both full paper and survey table via python-docx"],
    [C("rag_new/src/output_pdf/survey_pdf_generator.py"), "196",
     "Combined survey PDF — analysis table + sample IEEE overview paper in one document"],
    [C("rag_new/src/history/__init__.py"), "0", "Package init"],
]
story.append(colored_tbl(new_c4[0], new_c4[1:], [NEW_BG]*len(new_c4),
             widths=[7*cm, 1.5*cm, 7*cm]))

story.append(Spacer(1, 0.3*cm))
story.append(Paragraph("Updated Files", h2_s))
mod_c4 = [
    ["File", "Change", "Key Additions"],
    [C("rag_new/ui.py"), "+1,773 lines",
     "Three-tab layout (Paper / Survey & Analysis / Quality & Sources), quick-edit chips, section attribution, citation fix tool, survey card/table toggle, plagiarism report panel, retrieval analytics, arXiv links, Word+PDF+CSV download buttons"],
    [C("rag_new/src/generation/generator.py"), "+217 lines",
     "Citation rebuilder from source metadata, BibTeX export, improved context refinement"],
    [C("rag_new/src/evaluation/evaluator.py"), "+55 lines",
     "Added score parsing tolerance for varied LLM output formats, structured reasoning extraction"],
    [C("rag_new/src/pipeline/ui_pipeline.py"), "+127 lines",
     "Force-refresh support, collection pruning integration, plagiarism pass, history save wired up, per-stage timing metrics"],
    [C("rag_new/src/retrieval/retriever.py"), "+28 lines",
     "Auto-strategy selector that picks hyde/complex/standard based on query keywords"],
    [C("rag_new/src/embedding/vector_store.py"), "+21 lines",
     "list_topic_collections() and prune_old_collections() for collection lifecycle management"],
    [C("rag_new/src/ingestion/ingestor.py"), "+128 lines",
     "Incremental indexing — tracks already-indexed files, skips on repeat runs unless refresh is forced"],
    [C("rag_new/config/config.py"), "+56 lines",
     "New params: SURVEY_MIN/MAX/DEFAULT_PAPERS, MAX_STALE_COLLECTIONS, per-section word count limits"],
    [C("rag_new/requirements.txt"), "+4 lines",
     "Added: python-docx, openpyxl"],
]
story.append(colored_tbl(mod_c4[0], mod_c4[1:], [MOD_BG]*len(mod_c4),
             widths=[6*cm, 2.5*cm, 7*cm]))

story.append(Spacer(1, 0.3*cm))
story.append(Paragraph("What This Commit Delivered (Feature Summary)", h2_s))
features_c4 = [
    ("Session History", "All generated papers and surveys saved to disk and reloadable from the sidebar"),
    ("Word Export (.docx)", "Download full IEEE paper or survey table as an editable Word document"),
    ("Survey PDF Export", "Combined PDF with structured analysis table + sample overview paper"),
    ("Three-Tab UI", "Paper tab, Survey & Analysis tab, Quality & Sources tab — fully interactive"),
    ("Quick-Edit Chips", "One-click paper refinement: Lengthen, Deeper Methodology, Strengthen Results, Expand Future Work, Formal IEEE Tone, Rewrite Abstract"),
    ("Section Attribution", "Each section of the paper shows which source papers contributed to it"),
    ("Citation Fix Tool", "Rebuilds malformed or missing citations from source paper metadata"),
    ("Survey Card View", "Toggle between table view and card view for literature survey results"),
    ("Retrieval Analytics", "Shows BM25 vs vector blend %, min/avg/max chunk scores, paper contribution chart"),
    ("Auto Strategy Selection", "Automatically picks hyde for open-ended, complex for comparisons, standard otherwise"),
    ("Incremental Indexing", "Only re-processes new papers; skips already-indexed files on re-runs"),
    ("Timing Metrics", "Breakdown of time spent in each pipeline stage shown in the UI"),
    ("Collection Pruning", "Automatically deletes old topic collections beyond the 10-collection limit"),
]
for feature, desc in features_c4:
    story.append(Paragraph(f"• {B(feature)}: {desc}", bullet_s))

story.append(PageBreak())

# ── UNCOMMITTED CHANGES ────────────────────────────────────────────────────
story.append(Paragraph("Uncommitted Changes (Working Tree)", h1_s))
story.append(Paragraph("Current as of Jun 15, 2026 — not yet in any commit", style("q", parent=body_s, textColor=RED, fontSize=10)))
story.append(HR(RED))
story.append(Paragraph(
    "Two tracked files have been modified since the last commit. These changes are "
    "active in the working directory but have not been staged or committed.", body_s))

story.append(Spacer(1, 0.3*cm))
story.append(Paragraph(C("rag_new/src/generation/llm_client.py") + " — Retry Logic Overhaul", h2_s))
story.append(Paragraph(
    "The original LLM client had no retry logic — a single failure would immediately raise an exception. "
    "This change wraps both the regular and streaming generation calls in a retry loop with "
    "exponential backoff.", body_s))

retry_changes = [
    ["What Changed", "Before", "After"],
    ["RateLimitError (429)", "Not handled — crashed immediately",
     "Retries up to 4 times with 2→4→8→16s waits"],
    ["APITimeoutError", "Raised RuntimeError immediately",
     "Retried with same exponential backoff"],
    ["APIConnectionError", "Raised RuntimeError immediately",
     "Retried with same exponential backoff"],
    ["Server errors 5xx", "Not handled",
     "Retried; non-5xx errors still fail fast"],
    ["Streaming calls", "No retry on stream failure",
     "Same retry loop wraps the streaming path too"],
    ["Constants", "Hardcoded values inline",
     "MAX_RETRIES = 4, BASE_BACKOFF = 2.0 at module level"],
    ["import time", "Not imported",
     "Added — needed for time.sleep() between retries"],
    ["Comments", "Two-line docstring on CHARS_PER_TOKEN dict",
     "Removed (follows no-comment convention)"],
]
story.append(colored_tbl(retry_changes[0], retry_changes[1:], [CUR_BG]*len(retry_changes),
             widths=[4*cm, 5.5*cm, 6*cm]))

story.append(Spacer(1, 0.2*cm))
story.append(Paragraph("Retry backoff sequence:", body_s))
story.append(Paragraph(
    "attempt 0 → wait 2s  |  attempt 1 → wait 4s  |  attempt 2 → wait 8s  |  attempt 3 → wait 16s  →  raise",
    code_s))

story.append(Spacer(1, 0.3*cm))
story.append(Paragraph(C("rag_new/ui.py") + " — On-Demand Evaluation Button", h2_s))
story.append(Paragraph(
    "A '▶ Run Evaluation Now' button was added to the Quality & Sources tab. Previously, evaluation "
    "could only be triggered before paper generation via the settings toggle. This change allows "
    "users to run G-Eval scoring at any point after the paper exists — even if evaluation was "
    "skipped initially.", body_s))

eval_changes = [
    ["Aspect", "Detail"],
    ["New imports", C("Evaluator") + " and " + C("LLMClient") + " imported at the top of ui.py"],
    ["Button location", "Quality & Sources tab, below the existing score gauges"],
    ["What it runs", "evaluate_faithfulness() and evaluate_relevance() from Evaluator class"],
    ["Context used", "First 3 retrieved chunks from the current result (same as pipeline uses)"],
    ["Paper text limit", "First 7,000 chars sent to evaluator (matches pipeline default)"],
    ["Result storage", "Scores and reasoning merged back into the active chat result via set_chat()"],
    ["UI feedback", "Shows spinner during evaluation; st.toast('Evaluation complete!') on success"],
    ["Error handling", "Catches exceptions and shows st.error() with the failure message"],
    ["Page refresh", "Calls st.rerun() after success so score gauges update immediately"],
]
story.append(colored_tbl(eval_changes[0], eval_changes[1:], [CUR_BG]*len(eval_changes),
             widths=[4.5*cm, 11*cm]))

story.append(PageBreak())

# ── NEW UNTRACKED FILES ────────────────────────────────────────────────────
story.append(Paragraph("New Untracked Files", h1_s))
story.append(HR())
story.append(Paragraph(
    "These files exist in the working directory but are not tracked by git. "
    "They represent testing infrastructure and a LaTeX paper written about the project.", body_s))

story.append(Spacer(1, 0.2*cm))
untracked = [
    ["File / Directory", "Type", "Purpose"],
    [C("rag_new/tests/ui.spec.ts"), "NEW", "Playwright end-to-end test spec for the Streamlit UI"],
    [C("rag_new/playwright.config.ts"), "NEW", "Playwright configuration (browser, base URL, timeouts)"],
    [C("rag_new/package.json"), "NEW", "Node.js package manifest — Playwright dependency declaration"],
    [C("rag_new/package-lock.json"), "NEW", "Locked dependency tree for npm"],
    [C("rag_new/node_modules/"), "NEW", "Installed Node packages for Playwright (not committed)"],
    [C("rag_new/test-results/"), "NEW", "Playwright test output directory (screenshots, traces)"],
    [C("paper/researchgpt_paper.tex"), "NEW", "LaTeX source for an IEEE paper written about ResearchGPT itself"],
]
story.append(colored_tbl(untracked[0], untracked[1:],
             [NEW_BG, NEW_BG, NEW_BG, NEW_BG, NEW_BG, NEW_BG, NEW_BG],
             widths=[7*cm, 1.5*cm, 7*cm]))

story.append(Spacer(1, 0.3*cm))
story.append(Paragraph("Playwright Testing Setup", h2_s))
story.append(Paragraph(
    "A full end-to-end testing suite has been set up using Playwright for TypeScript. "
    "The test spec in " + C("rag_new/tests/ui.spec.ts") + " drives a real browser against the "
    "running Streamlit app to verify UI behaviour. This is currently untracked and not yet "
    "integrated into any CI pipeline.", body_s))

story.append(Spacer(1, 0.3*cm))
story.append(Paragraph("ResearchGPT Paper", h2_s))
story.append(Paragraph(
    "The file " + C("paper/researchgpt_paper.tex") + " is a LaTeX source document — an IEEE-style "
    "academic paper written about the ResearchGPT system itself. It is likely used as a demonstration "
    "or submission artifact and is untracked.", body_s))

story.append(PageBreak())

# ── FULL CHANGE SUMMARY ────────────────────────────────────────────────────
story.append(Paragraph("Full Change Summary", h1_s))
story.append(HR())

all_changes = [
    ["File", "Status", "Commit / State"],
    [C("rag_new/ui.py"), "NEW → MODIFIED (×2) → UNCOMMITTED",
     "Created in ccb8a74, expanded in c4ea420, button added in working tree"],
    [C("rag_new/src/generation/llm_client.py"), "NEW → UNCOMMITTED",
     "Created in c4ea420, retry logic added in working tree"],
    [C("rag_new/src/generation/generator.py"), "MODIFIED (×2)",
     "Major rewrite in ccb8a74, citation rebuild in c4ea420"],
    [C("rag_new/src/retrieval/retriever.py"), "MODIFIED (×2)",
     "Full rewrite (hybrid+reranking) in ccb8a74, auto-strategy in c4ea420"],
    [C("rag_new/src/evaluation/evaluator.py"), "MODIFIED (×2)",
     "G-Eval+plagiarism in ccb8a74, parsing tolerance in c4ea420"],
    [C("rag_new/src/ingestion/ingestor.py"), "MODIFIED (×2)",
     "Backoff+rate limit in ccb8a74, incremental indexing in c4ea420"],
    [C("rag_new/src/pipeline/ui_pipeline.py"), "NEW",
     "Full orchestration pipeline created in ccb8a74, expanded in c4ea420"],
    [C("rag_new/src/analysis/paper_analyzer.py"), "NEW",
     "Survey analysis engine created in ccb8a74"],
    [C("rag_new/src/history/paper_history.py"), "NEW",
     "Session persistence created in c4ea420"],
    [C("rag_new/src/output_pdf/docx_generator.py"), "NEW",
     "Word export created in c4ea420"],
    [C("rag_new/src/output_pdf/survey_pdf_generator.py"), "NEW",
     "Survey PDF created in c4ea420"],
    [C("rag_new/src/output_pdf/pdf_generator.py"), "NEW",
     "ReportLab PDF created in ccb8a74"],
    [C("rag_new/src/output_pdf/latex_generator.py"), "NEW",
     "LaTeX PDF created in ccb8a74"],
    [C("rag_new/src/embedding/vector_store.py"), "MODIFIED (×2)",
     "Topic collections in ccb8a74, pruning in c4ea420"],
    [C("rag_new/src/processing/processor.py"), "MODIFIED",
     "Section detection, table extraction in ccb8a74"],
    [C("rag_new/config/config.py"), "MODIFIED (×2)",
     "Full rewrite in ccb8a74, survey+collection params in c4ea420"],
    [C("rag_new/main.py"), "MODIFIED",
     "CLI subcommands in ccb8a74"],
    [C("rag_new/requirements.txt"), "MODIFIED (×2)",
     "New ML/PDF libs in ccb8a74, docx+openpyxl in c4ea420"],
    [C("rag_new/tests/ui.spec.ts"), "NEW (untracked)",
     "Playwright UI tests — not yet committed"],
    [C("paper/researchgpt_paper.tex"), "NEW (untracked)",
     "IEEE paper about ResearchGPT — not yet committed"],
]

row_colors = []
for row in all_changes[1:]:
    status = row[1]
    if "untracked" in status:
        row_colors.append(NEW_BG)
    elif "UNCOMMITTED" in status:
        row_colors.append(CUR_BG)
    elif "NEW" in status:
        row_colors.append(NEW_BG)
    else:
        row_colors.append(MOD_BG)

story.append(colored_tbl(all_changes[0], all_changes[1:], row_colors,
             widths=[6.5*cm, 4.5*cm, 4.5*cm]))

doc.build(story)
print(f"PDF written to: {OUTPUT}")
