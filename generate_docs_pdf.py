from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER

OUTPUT = "ResearchGPT_Documentation.pdf"

doc = SimpleDocTemplate(
    OUTPUT,
    pagesize=A4,
    leftMargin=2*cm, rightMargin=2*cm,
    topMargin=2*cm, bottomMargin=2*cm,
    title="ResearchGPT Documentation",
    author="ResearchGPT"
)

styles = getSampleStyleSheet()

# Custom styles
ACCENT = colors.HexColor("#1a73e8")
LIGHT_BG = colors.HexColor("#f1f3f4")
DARK = colors.HexColor("#202124")
MID = colors.HexColor("#5f6368")
CODE_BG = colors.HexColor("#f8f9fa")

title_style = ParagraphStyle("DocTitle", parent=styles["Title"],
    fontSize=26, textColor=ACCENT, spaceAfter=6, spaceBefore=0,
    fontName="Helvetica-Bold", alignment=TA_CENTER)

subtitle_style = ParagraphStyle("DocSubtitle", parent=styles["Normal"],
    fontSize=12, textColor=MID, spaceAfter=20, alignment=TA_CENTER)

h1_style = ParagraphStyle("H1", parent=styles["Heading1"],
    fontSize=16, textColor=ACCENT, spaceBefore=20, spaceAfter=6,
    fontName="Helvetica-Bold", borderPad=0)

h2_style = ParagraphStyle("H2", parent=styles["Heading2"],
    fontSize=13, textColor=DARK, spaceBefore=14, spaceAfter=4,
    fontName="Helvetica-Bold")

h3_style = ParagraphStyle("H3", parent=styles["Heading3"],
    fontSize=11, textColor=MID, spaceBefore=10, spaceAfter=3,
    fontName="Helvetica-Bold")

body_style = ParagraphStyle("Body", parent=styles["Normal"],
    fontSize=10, textColor=DARK, leading=16, spaceAfter=6)

bullet_style = ParagraphStyle("Bullet", parent=styles["Normal"],
    fontSize=10, textColor=DARK, leading=15, leftIndent=16,
    bulletIndent=4, spaceAfter=3)

code_style = ParagraphStyle("Code", parent=styles["Code"],
    fontSize=8.5, textColor=colors.HexColor("#37474f"),
    backColor=CODE_BG, leftIndent=12, rightIndent=12,
    leading=13, spaceAfter=8, spaceBefore=4,
    fontName="Courier", borderPad=6)

toc_style = ParagraphStyle("TOC", parent=styles["Normal"],
    fontSize=10, textColor=DARK, leading=18, leftIndent=12)

toc_h_style = ParagraphStyle("TOCH", parent=styles["Normal"],
    fontSize=11, textColor=ACCENT, leading=20, fontName="Helvetica-Bold")

def HR():
    return HRFlowable(width="100%", thickness=1, color=colors.HexColor("#dadce0"),
                      spaceAfter=8, spaceBefore=4)

def B(text): return f"<b>{text}</b>"
def I(text): return f"<i>{text}</i>"
def C(text): return f'<font name="Courier" size="9">{text}</font>'

def table(headers, rows, col_widths=None):
    data = [headers] + rows
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("TOPPADDING", (0, 1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dadce0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t

story = []

# ── COVER ──────────────────────────────────────────────────────────────────
story.append(Spacer(1, 3*cm))
story.append(Paragraph("ResearchGPT", title_style))
story.append(Paragraph("Project Documentation", subtitle_style))
story.append(HR())
story.append(Spacer(1, 0.5*cm))

story.append(Paragraph(
    "An agentic Retrieval-Augmented Generation system that transforms a research topic "
    "into a fully formatted IEEE research paper or literature survey — powered by hybrid "
    "search, cross-encoder reranking, and LLM-based generation and evaluation.",
    ParagraphStyle("Intro", parent=body_style, fontSize=11, leading=18,
                   textColor=MID, alignment=TA_CENTER)
))
story.append(Spacer(1, 1*cm))

# ── TABLE OF CONTENTS ──────────────────────────────────────────────────────
story.append(Paragraph("Table of Contents", h1_style))
story.append(HR())
toc = [
    ("1.", "Overview"),
    ("2.", "Architecture"),
    ("3.", "UI Features"),
    ("4.", "Backend Pipeline"),
    ("  4.1", "Ingestion"),
    ("  4.2", "Processing & Chunking"),
    ("  4.3", "Embedding & Vector Store"),
    ("  4.4", "Retrieval"),
    ("  4.5", "Generation"),
    ("  4.6", "Evaluation"),
    ("  4.7", "Analysis"),
    ("  4.8", "Output Generation"),
    ("  4.9", "History & Caching"),
    ("5.", "Configuration Reference"),
    ("6.", "How to Run"),
]
for num, title in toc:
    style = toc_h_style if not num.startswith("  ") else toc_style
    story.append(Paragraph(f"{num}&nbsp;&nbsp;&nbsp;{title}", style))

story.append(PageBreak())

# ── 1. OVERVIEW ────────────────────────────────────────────────────────────
story.append(Paragraph("1. Overview", h1_style))
story.append(HR())
story.append(Paragraph(
    "ResearchGPT is an agentic RAG system that fetches real academic papers from arXiv, "
    "retrieves relevant content using hybrid search, generates grounded IEEE papers via an LLM, "
    "and evaluates output quality — all through an interactive Streamlit web interface.",
    body_style))
story.append(Spacer(1, 0.2*cm))

overview_items = [
    "Fetches academic papers directly from arXiv based on the user's research topic",
    "Generates full IEEE-formatted research papers with proper citations",
    "Produces structured literature surveys with comparative analysis across papers",
    "Evaluates output quality using G-Eval (Faithfulness & Relevance, scored 1–5)",
    "Detects plagiarism at sentence level with n-gram overlap analysis",
    "Supports export to PDF, Word (.docx), CSV, and Excel",
    "Allows iterative paper refinement through natural language instructions",
]
for item in overview_items:
    story.append(Paragraph(f"• {item}", bullet_style))

# ── 2. ARCHITECTURE ────────────────────────────────────────────────────────
story.append(Spacer(1, 0.4*cm))
story.append(Paragraph("2. Architecture", h1_style))
story.append(HR())
story.append(Paragraph("The system follows a modular pipeline where each stage is independently configurable:", body_style))
story.append(Spacer(1, 0.2*cm))

arch = [
    ["Stage", "Component", "Description"],
    ["1", "Ingestion", "Fetch & download PDFs from arXiv"],
    ["2", "Processing", "Extract text, clean, detect sections, chunk"],
    ["3", "Embedding", "Encode chunks with BAAI/bge-base-en-v1.5 → ChromaDB"],
    ["4", "Retrieval", "Hybrid BM25 + Vector Search → Cross-Encoder Rerank"],
    ["5", "Generation", "LLM synthesizes IEEE paper from retrieved context"],
    ["6", "Evaluation", "G-Eval scoring, ROUGE-L, plagiarism detection"],
    ["7", "Output", "Export to IEEE PDF, Word (.docx), CSV/Excel"],
]
story.append(table(arch[0], arch[1:], col_widths=[1.5*cm, 4*cm, 10*cm]))

# ── 3. UI FEATURES ─────────────────────────────────────────────────────────
story.append(Spacer(1, 0.5*cm))
story.append(Paragraph("3. UI Features", h1_style))
story.append(HR())

story.append(Paragraph("3.1 Session Management", h2_style))
for item in [
    "Recent Research sidebar — lists all past topics with one-click reload",
    "New Research button — creates an isolated chat session per topic",
    "Persistent history — papers and surveys reload from disk between sessions",
]:
    story.append(Paragraph(f"• {item}", bullet_style))

story.append(Paragraph("3.2 Settings Panel", h2_style))
settings_rows = [
    ["Author Name / Affiliation / Email", "Free text", "—"],
    ["Retrieval Strategy", "auto, hyde, complex, standard", "auto"],
    ["Survey Paper Count", "3–15", "10"],
    ["Top-K Retrieval Chunks", "3–12", "5"],
    ["Refresh from arXiv", "Toggle", "Off"],
    ["Run Quality Evaluation", "Toggle", "On"],
]
story.append(table(["Setting", "Options", "Default"], settings_rows,
                   col_widths=[6*cm, 6*cm, 3.5*cm]))

story.append(Paragraph("3.3 Tab 1 — Paper", h2_style))
for item in [
    "Full IEEE-formatted paper with section navigation anchors",
    "Faithfulness quality badge (Good / Fair / Poor) in the header",
    "Quick-edit chips: Lengthen, Deeper Methodology, Strengthen Results, Expand Future Work, Formal IEEE Tone, Rewrite Abstract",
    "PDF and Word (.docx) download buttons",
    "Section-to-source attribution — which papers contributed to each section",
    "Citation rebuild tool — reconstructs citations from source metadata",
]:
    story.append(Paragraph(f"• {item}", bullet_style))

story.append(Paragraph("3.4 Tab 2 — Survey & Analysis", h2_style))
for item in [
    "Structured comparison table across 8 fields per paper: Problem Statement, Objective, Research Gap, Methodology, Features, Results & Discussion, Limitations, Future Scope",
    "Toggle between Table view and Card view",
    "Direct arXiv links per paper",
    "Research Gap summary panel",
    "Export as CSV or Excel",
]:
    story.append(Paragraph(f"• {item}", bullet_style))

story.append(Paragraph("3.5 Tab 3 — Quality & Sources", h2_style))
for item in [
    "Gauge charts for Faithfulness and Relevance (1–5 scale)",
    "LLM-generated reasoning behind each quality score",
    "Pipeline stats: paper count, strategy used, timing breakdown (index / retrieval / generation / total)",
    "Retrieval analytics: chunks retrieved, BM25 vs vector blend ratio, min/avg/max scores",
    "Paper contribution chart — chunks per source paper",
    "Retrieved chunks viewer with individual scores",
    "Plagiarism report: sentence-level similarity % and n-gram overlap %",
]:
    story.append(Paragraph(f"• {item}", bullet_style))

story.append(PageBreak())

# ── 4. BACKEND PIPELINE ────────────────────────────────────────────────────
story.append(Paragraph("4. Backend Pipeline", h1_style))
story.append(HR())

# 4.1 Ingestion
story.append(Paragraph("4.1 Ingestion", h2_style))
story.append(Paragraph(B("File:") + " " + C("rag_new/src/ingestion/ingestor.py"), body_style))
for item in [
    "Fetches papers from arXiv via the arxiv Python library with a direct Atom API fallback",
    "Exponential backoff retries on failures: 2 → 4 → 8 → 16 seconds",
    "Rate limiting between downloads (1s default) to respect arXiv limits",
    "Validates downloaded files (>1000 bytes minimum to detect failed downloads)",
    "Falls back to arXiv HTML version if PDF is unavailable",
    "Persists metadata to _papers_metadata.json to skip re-downloads on repeat runs",
]:
    story.append(Paragraph(f"• {item}", bullet_style))

story.append(Spacer(1, 0.2*cm))
ing_rows = [
    ["MAX_PAPERS", "5 (fast) / 8 (full)", "Papers fetched per topic"],
    ["MAX_RETRIES", "3", "Download retry attempts"],
    ["RETRY_DELAY", "2.0s", "Initial backoff (doubles each retry)"],
    ["DOWNLOAD_RATE_LIMIT", "1.0s", "Delay between downloads"],
]
story.append(table(["Parameter", "Default", "Purpose"], ing_rows,
                   col_widths=[5*cm, 4*cm, 6.5*cm]))

# 4.2 Processing
story.append(Paragraph("4.2 Processing & Chunking", h2_style))
story.append(Paragraph(B("File:") + " " + C("rag_new/src/processing/processor.py"), body_style))
for item in [
    "PDF extraction via PyMuPDF (fitz) — handles text, tables, and multi-page documents",
    "Cleans junk lines: page numbers, running headers, arXiv/proceedings boilerplate",
    "Chunking via LangChain RecursiveCharacterTextSplitter with hierarchical separators",
    "Detects dominant section per chunk (Abstract, Introduction, Methodology, etc.)",
    "Propagates full paper metadata to every chunk for traceability",
]:
    story.append(Paragraph(f"• {item}", bullet_style))

story.append(Spacer(1, 0.2*cm))
chunk_rows = [
    ["CHUNK_SIZE", "1000 chars"],
    ["CHUNK_OVERLAP", "350 chars (35% overlap for context continuity)"],
    ["Separators", "\\n\\n  →  \\n  →  .   →  (space)  →  (empty)"],
]
story.append(table(["Parameter", "Value"], chunk_rows, col_widths=[4*cm, 11.5*cm]))

# 4.3 Embedding
story.append(Paragraph("4.3 Embedding & Vector Store", h2_style))
story.append(Paragraph(B("File:") + " " + C("rag_new/src/embedding/vector_store.py"), body_style))
for item in [
    "Embedding model: BAAI/bge-base-en-v1.5 (sentence-transformers)",
    "Vector database: ChromaDB, persistent and disk-backed",
    "One collection per research topic — prevents cross-topic noise",
    "Operations: upsert, semantic query, reset, bulk retrieval for BM25 fitting",
    "Automatic pruning of stale collections (keeps 10 most recent)",
]:
    story.append(Paragraph(f"• {item}", bullet_style))

# 4.4 Retrieval
story.append(Paragraph("4.4 Retrieval", h2_style))
story.append(Paragraph(B("File:") + " " + C("rag_new/src/retrieval/retriever.py"), body_style))
story.append(Paragraph(
    "All strategies use Hybrid BM25 + Vector Search with strategy-specific blending ratios, "
    "followed by Cross-Encoder reranking.", body_style))
story.append(Spacer(1, 0.2*cm))

ret_rows = [
    ["HyDE", "LLM generates a hypothetical answer; that answer is embedded and searched", "30%"],
    ["Complex", "Query decomposed into 2–3 sub-questions; retrieved independently and merged", "55%"],
    ["Standard", "Direct embedding of the raw query + BM25", "50%"],
    ["Auto", "Automatically selects strategy based on query characteristics", "Varies"],
]
story.append(table(["Strategy", "How It Works", "BM25 Weight"],
                   ret_rows, col_widths=[2.5*cm, 10*cm, 3*cm]))
story.append(Spacer(1, 0.3*cm))

story.append(Paragraph("Cross-Encoder Re-ranking", h3_style))
for item in [
    "Model: ms-marco-MiniLM-L-12-v2",
    "Rescores top-20 candidate chunks with (query, document) pairs",
    "Section-aware bonus (+0.1) for Results, Methodology, Conclusion, Discussion, Experiment, Evaluation, Analysis, Findings",
    "Returns final top-K after reranking (default: 5)",
]:
    story.append(Paragraph(f"• {item}", bullet_style))

# 4.5 Generation
story.append(Paragraph("4.5 Generation", h2_style))
story.append(Paragraph(
    B("Files:") + " " + C("rag_new/src/generation/llm_client.py") + ", " +
    C("rag_new/src/generation/generator.py"), body_style))

story.append(Paragraph("LLM Provider Support", h3_style))
prov_rows = [
    ["Cerebras / OpenAI", "Cloud", "https://api.cerebras.ai/v1"],
    ["Ollama", "Local", "http://localhost:11434/api/generate"],
]
story.append(table(["Provider", "Mode", "Endpoint"], prov_rows,
                   col_widths=[5*cm, 3*cm, 7.5*cm]))

story.append(Paragraph("Generation Features", h3_style))
for item in [
    "Context refinement: extracts only query-relevant sentences from each chunk before prompting",
    "Citation validation: removes hallucinated [N] citations not present in actual sources",
    "Generates full IEEE papers — 8 sections, roman numeral headings, numbered citations",
    "Exponential backoff on rate limits and timeouts (up to 4 retries)",
    "Streaming support for long-form generation",
]:
    story.append(Paragraph(f"• {item}", bullet_style))

story.append(Spacer(1, 0.2*cm))
gen_rows = [
    ["LLM_TEMPERATURE", "0.2", "Low temperature for consistent, factual output"],
    ["LLM_MAX_TOKENS", "8192", "Maximum generation length"],
    ["MAX_CONTEXT_TOKENS", "3000 chars", "Context window per chunk"],
    ["SECTION_MIN_WORDS", "150", "Minimum words per paper section"],
    ["SECTION_MAX_WORDS", "600", "Target maximum words per section"],
]
story.append(table(["Parameter", "Default", "Purpose"], gen_rows,
                   col_widths=[5*cm, 3.5*cm, 7*cm]))

# 4.6 Evaluation
story.append(Paragraph("4.6 Evaluation", h2_style))
story.append(Paragraph(B("File:") + " " + C("rag_new/src/evaluation/evaluator.py"), body_style))

story.append(Paragraph("LLM-Based Metrics (G-Eval)", h3_style))
eval_rows = [
    ["Faithfulness", "1–5", "Are all claims supported by retrieved context?"],
    ["Relevance", "1–5", "Does the paper address the specific research query?"],
]
story.append(table(["Metric", "Scale", "Question Asked"], eval_rows,
                   col_widths=[4*cm, 2.5*cm, 9*cm]))

story.append(Paragraph("Traditional Metrics", h3_style))
trad_rows = [
    ["ROUGE-L", "F1 score between generated text and source chunks (LCS-based)"],
    ["Hit Rate", "Whether retrieved chunks include the expected relevant papers"],
    ["MRR", "Mean Reciprocal Rank — position of first relevant result (higher is better)"],
]
story.append(table(["Metric", "Description"], trad_rows, col_widths=[3*cm, 12.5*cm]))

story.append(Paragraph("Plagiarism Detection", h3_style))
for item in [
    "Sentence-level cosine similarity scoring (threshold: 0.65)",
    "8-gram overlap detection across all source chunks",
    "Reports: overall similarity %, max sentence similarity %, n-gram overlap %",
    "Flags suspicious sentences with matched source and similarity score",
]:
    story.append(Paragraph(f"• {item}", bullet_style))

story.append(PageBreak())

# 4.7 Analysis
story.append(Paragraph("4.7 Analysis", h2_style))
story.append(Paragraph(B("File:") + " " + C("rag_new/src/analysis/paper_analyzer.py"), body_style))
for item in [
    "Fetches paper metadata and abstracts directly from arXiv Atom API",
    "Downloads and extracts PDF text (up to 10 pages per paper for speed)",
    "Falls back to abstract only if PDF extraction fails",
    "LLM extracts 8 structured fields per paper via a single structured prompt",
    "1-second delay between LLM calls to respect rate limits",
    "Generates a sample IEEE overview paper from the combined survey data",
]:
    story.append(Paragraph(f"• {item}", bullet_style))

story.append(Spacer(1, 0.2*cm))
story.append(Paragraph("Fields extracted per paper:", body_style))
fields = [
    "Problem Statement", "Objective", "Research Gap",
    "Methodology (Algorithms/Techniques)", "Features (Focused)",
    "Results & Discussion (with metrics)", "Limitations", "Future Scope"
]
for i, f in enumerate(fields, 1):
    story.append(Paragraph(f"{i}. {f}", bullet_style))

# 4.8 Output
story.append(Paragraph("4.8 Output Generation", h2_style))
story.append(Paragraph(B("Directory:") + " " + C("rag_new/src/output_pdf/"), body_style))
out_rows = [
    ["IEEE PDF", "ReportLab", "Two-column layout, proper typography and fonts"],
    ["LaTeX → PDF", "ReportLab + pdflatex", "Full LaTeX template with equations and tables"],
    ["Word (.docx)", "python-docx", "Editable, preserves IEEE section structure"],
    ["CSV / Excel", "pandas", "Survey analysis table for data analysis"],
    ["Survey PDF", "ReportLab", "Combined analysis table + sample overview paper"],
]
story.append(table(["Format", "Library", "Notes"], out_rows,
                   col_widths=[3.5*cm, 4.5*cm, 7.5*cm]))

# 4.9 History
story.append(Paragraph("4.9 History & Caching", h2_style))
story.append(Paragraph(B("File:") + " " + C("rag_new/src/history/paper_history.py"), body_style))
for item in [
    "Results persisted to disk, keyed by topic + strategy + fast_mode hash",
    "Saved data: paper text, evaluation scores, retrieved context, survey rows, timing metrics",
    "In-process cache with 1-hour TTL — skips full pipeline on repeated identical queries",
    "Base64-encoded PDFs embedded in history JSON for portability",
    "Load and delete operations for session management",
]:
    story.append(Paragraph(f"• {item}", bullet_style))

story.append(PageBreak())

# ── 5. CONFIGURATION ───────────────────────────────────────────────────────
story.append(Paragraph("5. Configuration Reference", h1_style))
story.append(HR())
story.append(Paragraph(
    "All settings are centralized in " + C("rag_new/config/config.py") +
    " and can be overridden via a " + C(".env") + " file at the project root.",
    body_style))
story.append(Spacer(1, 0.3*cm))

config_rows = [
    ["Ingestion", "MAX_PAPERS", "5", "Papers fetched from arXiv per topic"],
    ["Ingestion", "MAX_RETRIES", "3", "Download retry attempts"],
    ["Ingestion", "RETRY_DELAY", "2.0s", "Initial backoff (doubles each retry)"],
    ["Ingestion", "DOWNLOAD_RATE_LIMIT", "1.0s", "Delay between downloads"],
    ["Chunking", "CHUNK_SIZE", "1000", "Characters per chunk"],
    ["Chunking", "CHUNK_OVERLAP", "350", "Overlap chars for context continuity"],
    ["Embedding", "EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5", "Semantic encoder model"],
    ["Retrieval", "CROSS_ENCODER_MODEL", "ms-marco-MiniLM-L-12-v2", "Reranker model"],
    ["Retrieval", "TOP_K", "5", "Final results returned after reranking"],
    ["Retrieval", "RETRIEVAL_WINDOW_SIZE", "20", "Candidates before reranking"],
    ["Retrieval", "BM25_ALPHA_HYDE", "0.7", "Vector blend weight for HyDE strategy"],
    ["Retrieval", "BM25_ALPHA_COMPLEX", "0.45", "Vector blend weight for Complex strategy"],
    ["Retrieval", "BM25_ALPHA_STANDARD", "0.5", "Vector blend weight for Standard strategy"],
    ["Generation", "LLM_PROVIDER", "openai", "LLM provider: openai or ollama"],
    ["Generation", "OPENAI_MODEL", "gpt-oss-120b", "Model ID for cloud generation"],
    ["Generation", "LLM_TEMPERATURE", "0.2", "Low = consistent and factual output"],
    ["Generation", "LLM_MAX_TOKENS", "8192", "Maximum tokens in LLM output"],
    ["Survey", "SURVEY_DEFAULT_PAPERS", "10", "Default papers for literature survey"],
    ["Survey", "SURVEY_MIN_PAPERS", "3", "Minimum papers allowed in survey"],
    ["Survey", "SURVEY_MAX_PAPERS", "15", "Maximum papers allowed in survey"],
    ["Evaluation", "PLAGIARISM_THRESHOLD", "0.65", "Sentence similarity alarm threshold"],
    ["Vector DB", "MAX_STALE_COLLECTIONS", "10", "Max topic collections to retain on disk"],
]
story.append(table(
    ["Category", "Parameter", "Default", "Description"],
    config_rows,
    col_widths=[3*cm, 5*cm, 3.5*cm, 4*cm]
))

# ── 6. HOW TO RUN ──────────────────────────────────────────────────────────
story.append(Spacer(1, 0.5*cm))
story.append(Paragraph("6. How to Run", h1_style))
story.append(HR())

story.append(Paragraph("Start the Web App", h2_style))
story.append(Paragraph(
    C("cd rag_new") + "&nbsp;&nbsp;&nbsp;" + C("streamlit run ui.py"),
    code_style))

story.append(Paragraph("CLI Commands", h2_style))
cli_rows = [
    ["run_all --query \"topic\"", "Run the full end-to-end pipeline"],
    ["ingest --query \"topic\"", "Download papers from arXiv only"],
    ["index", "Build the vector index only"],
    ["retrieve --query \"topic\"", "Run retrieval only and print chunks"],
    ["generate --topic \"topic\"", "Generate paper only (requires existing index)"],
    ["evaluate --query \"topic\"", "Run evaluation metrics only"],
]
story.append(table(["Command", "Description"], cli_rows,
                   col_widths=[7*cm, 8.5*cm]))

story.append(Paragraph("Programmatic Usage", h2_style))
code_text = (
    "from src.pipeline.ui_pipeline import run_rag_for_ui_pipeline\n\n"
    "result = run_rag_for_ui_pipeline(\n"
    "    topic=\"Finetuning methods for large language models\",\n"
    "    retrieval_strategy=\"hyde\",\n"
    "    include_evaluation=True,\n"
    "    fast_mode=True,\n"
    ")\n\n"
    "print(result[\"paper_text\"])    # Full IEEE paper\n"
    "print(result[\"faithfulness\"])  # 1-5 score\n"
    "print(result[\"relevance\"])     # 1-5 score"
)
story.append(Paragraph(code_text.replace("\n", "<br/>").replace(" ", "&nbsp;"), code_style))

story.append(Paragraph("LLM Provider Configuration (.env)", h2_style))
env_text = (
    "# Use Cerebras / OpenAI (cloud)\n"
    "LLM_PROVIDER=openai\n"
    "OPENAI_API_KEY=your_key_here\n\n"
    "# OR use Ollama (local)\n"
    "LLM_PROVIDER=ollama"
)
story.append(Paragraph(env_text.replace("\n", "<br/>").replace(" ", "&nbsp;"), code_style))

# ── BUILD ──────────────────────────────────────────────────────────────────
doc.build(story)
print(f"PDF written to: {OUTPUT}")
