import base64
import html
import os
import re
import time
import streamlit as st
import io
import pandas as pd


from config.config import Config
from src.pipeline.ui_pipeline import run_rag_for_ui_pipeline, refine_paper_with_instruction
from src.analysis.paper_analyzer import analyze_topic, generate_sample_paper
from src.output_pdf.survey_pdf_generator import generate_survey_combined_pdf
from src.output_pdf.docx_generator import generate_paper_docx, generate_survey_docx
from src.generation.generator import RAGGenerator as _RAGGenerator
from src.evaluation.evaluator import Evaluator as _Evaluator
from src.generation.llm_client import LLMClient as _LLMClient
from src.history.paper_history import save_result as _history_save, save_session as _history_save_session, list_history, load_result as _history_load, delete_result as _history_delete

st.set_page_config(page_title="ResearchGPT", page_icon="📄", layout="wide", initial_sidebar_state="expanded")


# ── Helpers ───────────────────────────────────────────────────────────────────
def clamp_score(score, min_val=0.0, max_val=5.0):
    if score is None:
        return None
    try:
        return max(min_val, min(max_val, float(score)))
    except (TypeError, ValueError):
        return None


def score_badge(score: float | None, label: str) -> str:
    if score is None:
        return (
            f'<div style="text-align:center;padding:10px 0">'
            f'<div style="font-size:11px;color:#8b949e;margin-bottom:4px">{label}</div>'
            f'<span style="background:rgba(139,148,158,0.15);color:#8b949e;'
            f'border-radius:20px;padding:4px 14px;font-size:13px">—</span></div>'
        )
    if score >= 4.0:
        bg, fg, tag = "rgba(46,160,67,0.15)", "#3fb950", "Good"
    elif score >= 3.0:
        bg, fg, tag = "rgba(210,153,34,0.15)", "#d29922", "Fair"
    else:
        bg, fg, tag = "rgba(248,81,73,0.15)", "#f85149", "Poor"
    return (
        f'<div style="text-align:center;padding:10px 0">'
        f'<div style="font-size:11px;color:#8b949e;margin-bottom:4px">{label}</div>'
        f'<span style="background:{bg};color:{fg};border-radius:20px;'
        f'padding:4px 14px;font-size:14px;font-weight:600">'
        f'⬤ {score:.1f}/5</span>'
        f'<div style="font-size:11px;color:{fg};margin-top:3px">{tag}</div></div>'
    )


def extract_topic(text: str) -> str | None:
    """Return topic string if message is a generation request, else None."""
    t = text.strip()
    triggers = [
        r"^(?:write|generate|create|make|produce|draft|build)\s+(?:a\s+)?(?:(?:research\s+)?paper|ieee\s+paper|paper)\s+(?:on|about|regarding|for)\s+(.+)$",
        r"^(?:write|generate|create)\s+(?:on|about)\s+(.+)$",
        r"^(?:paper|research paper)\s+(?:on|about)\s+(.+)$",
        r"^(?:on|about)\s+(.+)$",
    ]
    for pattern in triggers:
        m = re.match(pattern, t, re.IGNORECASE)
        if m:
            return m.group(1).strip().rstrip(".")
    refinement_keywords = [
        "longer", "shorter", "expand", "add", "remove", "change", "fix",
        "rewrite", "update", "modify", "improve", "make", "section", "more",
        "less", "tone", "style", "introduction", "conclusion", "abstract",
    ]
    words = t.split()
    if len(words) <= 8 and not any(kw in t.lower() for kw in refinement_keywords):
        return t
    return None


def is_meaningful(text: str, min_words: int = 2, min_real_chars: int = 4) -> bool:
    t = text.strip()
    if len(t) < min_real_chars:
        return False
    words = t.split()
    if len(words) < min_words:
        if len(words) == 1 and len(words[0]) >= 4 and re.match(r"^[a-zA-Z]+$", words[0]):
            return True
        return False
    alpha = sum(c.isalpha() for c in t)
    return (alpha / max(len(t), 1)) >= 0.5


def auto_select_strategy(query: str) -> str:
    q = query.lower()
    if any(k in q for k in ["compare", "versus", "vs", "tradeoff", "benchmark"]) or len(query.split()) > 16:
        return "complex"
    return "hyde"


@st.cache_data(show_spinner=False)
def get_base64_image(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


# ── CSS ───────────────────────────────────────────────────────────────────────
img_b64 = get_base64_image(Config.UI_BACKGROUND_IMAGE_PATH)
bg_css = (
    f'background-image: url("data:image/png;base64,{img_b64}"); '
    f'background-attachment: fixed; background-size: cover;'
    if img_b64
    else "background: #0d1117;"
)

st.markdown(
    f"""
    <style>
    /* ── Base ── */
    .stApp {{
        {bg_css}
        color: #e5e5e5;
    }}
    [data-testid="stChatMessage"] {{
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.07);
        border-radius: 14px;
        margin-bottom: 12px;
        padding: 6px 10px;
    }}
    .paper-box {{
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.09);
        border-radius: 10px;
        padding: 22px 26px;
        line-height: 1.85;
        white-space: pre-wrap;
        font-family: Georgia, 'Times New Roman', serif;
        font-size: 14.5px;
    }}
    /* ── Sidebar ── */
    section[data-testid="stSidebar"] {{
        background: #141414 !important;
        border-right: 1px solid rgba(255,255,255,0.06);
    }}
    /* ── Buttons ── */
    .stButton>button, .stDownloadButton>button {{
        background: #2563eb;
        color: #fff;
        border-radius: 20px;
        border: none;
        font-weight: 500;
        font-size: 12px !important;
    }}
    .stButton>button:hover {{ background: #1d4ed8; }}
    .stDownloadButton>button:hover {{ background: #1d4ed8; }}
    div[data-testid="stSidebar"] .stButton>button {{
        background: transparent !important;
        color: #a3a3a3 !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
        font-weight: 400 !important;
        text-align: left !important;
        justify-content: flex-start !important;
        font-size: 13px !important;
        padding: 6px 10px !important;
    }}
    div[data-testid="stSidebar"] .stButton>button:hover {{
        background: rgba(255,255,255,0.07) !important;
        color: #e5e5e5 !important;
    }}
    div[data-testid="stSidebar"] .stButton>button[kind="primary"] {{
        background: rgba(37,99,235,0.15) !important;
        border-color: rgba(37,99,235,0.4) !important;
        color: #3b82f6 !important;
        font-weight: 600 !important;
    }}
    div[data-testid="stSidebar"] button[title="Delete this chat"],
    div[data-testid="stSidebar"] button[title="Delete this entry"],
    div[data-testid="stSidebar"] button[title="Delete"] {{
        background: transparent !important;
        border: none !important;
        color: #484f58 !important;
        font-size: 11px !important;
        padding: 2px 4px !important;
        min-width: 0 !important;
    }}
    div[data-testid="stSidebar"] button[title="Delete this chat"]:hover,
    div[data-testid="stSidebar"] button[title="Delete this entry"]:hover,
    div[data-testid="stSidebar"] button[title="Delete"]:hover {{
        color: #dc2626 !important;
        background: rgba(220,38,38,0.1) !important;
    }}
    div[data-testid="stSidebar"] div:first-child .stButton>button {{
        background: #2563eb !important;
        color: #fff !important;
        border: none !important;
        font-weight: 600 !important;
        font-size: 14px !important;
    }}
    /* ── Typography ── */
    h1,h2,h3,label,span,p,li {{ color: #e5e5e5 !important; }}
    .stCaption {{ color: #a3a3a3 !important; }}
    /* ── Tabs ── */
    .stTabs [data-baseweb="tab"] {{ color: #a3a3a3; font-size: 13px; }}
    .stTabs [aria-selected="true"] {{ color: #3b82f6 !important; border-bottom-color: #3b82f6 !important; }}
    /* ── Inputs ── */
    .stTextInput input, .stSelectbox > div > div {{
        background: rgba(255,255,255,0.05) !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        color: #e5e5e5 !important;
        border-radius: 8px !important;
    }}
    [data-testid="stChatInput"] textarea {{
        background: rgba(17,17,17,0.97) !important;
        color: #e5e5e5 !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 12px !important;
        font-size: 15px !important;
    }}
    hr {{ border-color: rgba(255,255,255,0.07) !important; }}
    /* ── Survey table ── */
    .survey-table-wrapper {{
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        border-radius: 10px;
        border: 1px solid rgba(255,255,255,0.09);
        margin-bottom: 24px;
        width: 100%;
        max-height: 600px;
        overflow-y: auto;
    }}
    .survey-table {{
        min-width: 1400px;
        border-collapse: collapse;
        font-size: 12px;
        font-family: 'Segoe UI', sans-serif;
    }}
    .survey-table thead th {{
        background: #111111;
        color: #3b82f6;
        padding: 10px 14px;
        text-align: left;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        border-bottom: 1px solid rgba(255,255,255,0.1);
        white-space: nowrap;
        position: sticky;
        top: 0;
        z-index: 2;
    }}
    .survey-table thead th:nth-child(1) {{
        position: sticky; left: 0; top: 0; z-index: 3;
        width: 40px; min-width: 40px;
    }}
    .survey-table thead th:nth-child(2) {{
        position: sticky; left: 40px; top: 0; z-index: 3;
        min-width: 180px; max-width: 180px;
    }}
    .survey-table thead th:nth-child(3) {{
        min-width: 80px; max-width: 80px;
    }}
    .survey-table td {{
        padding: 10px 14px;
        color: #e5e5e5;
        border-bottom: 1px solid rgba(255,255,255,0.05);
        vertical-align: top;
        line-height: 1.5;
        max-height: 120px;
        overflow-y: auto;
    }}
    .survey-table td:nth-child(1) {{
        position: sticky; left: 0; z-index: 1;
        background: #0f0f0f; width: 40px; min-width: 40px;
    }}
    .survey-table td:nth-child(2) {{
        position: sticky; left: 40px; z-index: 1;
        background: #0f0f0f; min-width: 180px; max-width: 180px;
    }}
    .survey-table tr:nth-child(even) td {{
        background: rgba(255,255,255,0.02);
    }}
    .survey-table tr:nth-child(even) td:nth-child(1),
    .survey-table tr:nth-child(even) td:nth-child(2) {{
        background: #111111;
    }}
    .survey-table tr:hover td {{
        background: rgba(37,99,235,0.06);
    }}
    .survey-table td.col-no {{ min-width: 40px; width: 40px; text-align:center; }}
    .survey-table td.col-title {{ min-width: 180px; max-width: 180px; font-weight:600; }}
    .survey-table td.col-authors {{ min-width: 150px; max-width: 150px; }}
    .survey-table td.col-link {{ min-width: 80px; max-width: 80px; text-align:center; }}
    .survey-table td.col-doi {{ min-width: 160px; max-width: 200px; }}
    .survey-table td.col-wide {{ min-width: 200px; max-width: 260px; }}
    .paper-no {{
        background: rgba(37,99,235,0.2);
        color: #3b82f6;
        font-weight: 700;
        text-align: center;
        min-width: 40px !important;
    }}
    .paper-title {{
        font-weight: 600;
        color: #e5e5e5;
        min-width: 180px !important;
        max-width: 180px !important;
    }}
    /* ── Survey card view ── */
    .survey-card {{
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 10px;
        padding: 16px 20px;
        margin-bottom: 10px;
    }}
    .survey-card-grid {{
        display: grid;
        grid-template-columns: 1fr 1fr 1fr;
        gap: 16px;
        margin-top: 12px;
    }}
    .survey-card-field {{ font-size: 12px; line-height: 1.6; }}
    .survey-card-label {{ font-size: 10px; color: #a3a3a3; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; }}
    .arXiv-link {{
        display: inline-block;
        background: rgba(37,99,235,0.15);
        color: #3b82f6 !important;
        border: 1px solid rgba(37,99,235,0.3);
        border-radius: 6px;
        padding: 2px 10px;
        font-size: 11px;
        text-decoration: none !important;
        font-weight: 500;
    }}
    .arXiv-link:hover {{ background: rgba(37,99,235,0.3); }}
    /* ── Faithfulness alert banner ── */
    .faith-alert {{
        background: rgba(220,38,38,0.12);
        border: 1px solid rgba(220,38,38,0.4);
        border-radius: 10px;
        padding: 14px 18px;
        margin-bottom: 14px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
    }}
    .faith-alert-text {{ flex: 1; }}
    .faith-alert-title {{ font-size: 14px; font-weight: 700; color: #f87171 !important; margin: 0 0 2px 0; }}
    .faith-alert-sub {{ font-size: 12px; color: #fca5a5 !important; margin: 0; }}
    /* ── Faithfulness badge (topbar) ── */
    .faith-badge-good {{ display:inline-block; background:rgba(22,163,74,0.15); color:#4ade80 !important;
        border:1px solid rgba(22,163,74,0.35); border-radius:20px; padding:2px 12px; font-size:11px; font-weight:600; }}
    .faith-badge-fair {{ display:inline-block; background:rgba(234,179,8,0.15); color:#facc15 !important;
        border:1px solid rgba(234,179,8,0.35); border-radius:20px; padding:2px 12px; font-size:11px; font-weight:600; }}
    .faith-badge-poor {{ display:inline-block; background:rgba(220,38,38,0.15); color:#f87171 !important;
        border:1px solid rgba(220,38,38,0.35); border-radius:20px; padding:2px 12px; font-size:11px; font-weight:600; }}
    /* ── Step badge ── */
    .step-badge {{
        display: inline-block;
        background: rgba(37,99,235,0.15);
        color: #3b82f6;
        border: 1px solid rgba(37,99,235,0.3);
        border-radius: 20px;
        padding: 3px 14px;
        font-size: 12px;
        font-weight: 600;
        letter-spacing: 0.04em;
        margin-bottom: 8px;
    }}
    /* ── IEEE preview ── */
    .ieee-preview {{
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.09);
        border-radius: 10px;
        padding: 18px 20px;
        max-height: 680px;
        overflow-y: auto;
        color: #e5e5e5;
    }}
    .ieee-body {{
        column-count: 2;
        column-gap: 18px;
        column-rule: 1px solid rgba(255,255,255,0.1);
        font-family: 'Times New Roman', Times, serif;
        font-size: 11.5px;
        line-height: 1.65;
        text-align: justify;
    }}
    .ieee-sh {{
        font-family: 'Times New Roman', Times, serif;
        font-size: 10px;
        font-weight: bold;
        color: #3b82f6;
        margin-top: 10px;
        margin-bottom: 3px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }}
    .ieee-para {{ margin: 0 0 5px 0; text-indent: 12px; }}
    /* ── Section nav ── */
    [data-testid='stDeployButton'] {{display: none;}}
    header[data-testid="stHeader"] button[title="Deploy this app"] {{display: none;}}
    .section-nav {{
        display: flex; flex-wrap: wrap; gap: 6px 16px;
        padding: 10px 16px;
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.07);
        border-radius: 8px; margin-bottom: 12px;
    }}
    .section-nav a {{
        color: #3b82f6 !important; text-decoration: none;
        font-size: 12px; white-space: nowrap;
    }}
    .section-nav a:hover {{ text-decoration: underline; }}
    .topic-heading {{
        font-size: 21px; font-weight: 700; color: #e5e5e5 !important;
        margin: 0 0 6px 0; letter-spacing: -0.3px;
    }}
    /* ── Home screen ── */
    .home-hero {{
        max-width: 680px;
        margin: 60px auto 0 auto;
        text-align: center;
        padding: 0 20px;
    }}
    .home-hero h1 {{
        font-size: 32px; font-weight: 700; color: #e5e5e5 !important;
        margin-bottom: 12px; letter-spacing: -0.5px;
    }}
    .home-hero p {{
        font-size: 15px; color: #a3a3a3 !important; margin-bottom: 28px; line-height: 1.6;
    }}
    .example-box {{
        border: 1px solid rgba(99,102,241,0.3);
        border-radius: 12px;
        padding: 16px 20px 20px 20px;
        background: rgba(99,102,241,0.06);
        margin: 0 auto;
        max-width: 680px;
    }}
    .example-box-label {{
        font-size: 11px;
        font-weight: 600;
        color: #6366f1;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        margin-bottom: 12px;
    }}
    .topic-pill {{
        display: inline-block;
        background: rgba(37,99,235,0.12);
        border: 1px solid rgba(37,99,235,0.3);
        color: #3b82f6 !important;
        border-radius: 20px;
        padding: 5px 16px;
        font-size: 13px;
        margin: 4px;
        cursor: pointer;
    }}
    .topic-pill:hover {{ background: rgba(37,99,235,0.25); }}
    /* ── Settings page ── */
    .settings-page {{
        max-width: 600px;
        margin: 40px auto;
        padding: 0 20px;
    }}
    .settings-page h2 {{
        font-size: 22px; font-weight: 700; color: #e5e5e5 !important;
        margin-bottom: 24px;
    }}
    /* ── Sidebar recent item ── */
    .recent-item-meta {{
        font-size: 11px; color: #6b7280; margin-top: 1px;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ── Multi-chat session state ──────────────────────────────────────────────────
def _make_chat(chat_id: int) -> dict:
    return {
        "id": chat_id,
        "title": "New Chat",
        "messages": [],
        "topic": "",
        "paper_text": "",
        "context": [],
        "result": None,
        "has_paper": False,
        "has_survey": False,
        "survey_rows": [],
        "survey_paper_text": "",
        "survey_pdf_bytes": None,
        "processing": None,
        "pending_input": "",
        "search_keywords": "",
    }


def _init():
    if "chats" not in st.session_state:
        st.session_state.chats = [_make_chat(0)]
    if "active_chat" not in st.session_state:
        st.session_state.active_chat = 0
    if "_next_chat_id" not in st.session_state:
        st.session_state._next_chat_id = 1
    if "show_settings" not in st.session_state:
        st.session_state.show_settings = False
    # Settings defaults (persisted in session state, not sidebar widgets)
    if "_s_strategy" not in st.session_state:
        st.session_state._s_strategy = "auto"
    if "_s_num_survey" not in st.session_state:
        st.session_state._s_num_survey = Config.SURVEY_DEFAULT_PAPERS
    if "_s_topk" not in st.session_state:
        st.session_state._s_topk = 6
    if "_s_refresh" not in st.session_state:
        st.session_state._s_refresh = True
    if "_s_eval" not in st.session_state:
        st.session_state._s_eval = True


_init()


def chat() -> dict:
    idx = st.session_state.active_chat
    if idx >= len(st.session_state.chats):
        st.session_state.active_chat = len(st.session_state.chats) - 1
        idx = st.session_state.active_chat
    return st.session_state.chats[idx]


def set_chat(key: str, value):
    chat()[key] = value


def new_chat():
    cid = st.session_state._next_chat_id
    st.session_state._next_chat_id += 1
    st.session_state.chats.append(_make_chat(cid))
    st.session_state.active_chat = len(st.session_state.chats) - 1


# ── API key guard ─────────────────────────────────────────────────────────────
_needs_api_key = Config.LLM_PROVIDER != "ollama"
_has_api_key = bool(
    os.environ.get("CEREBRAS_API_KEY")
    or os.environ.get("GROQ_API_KEY")
    or os.environ.get("OPENAI_API_KEY")
)
if _needs_api_key and not _has_api_key:
    st.error(
        "**API key not found.**\n\n"
        "Open `rag_new/.env` and set `CEREBRAS_API_KEY=your_key_here`, "
        "then restart the app. Get a free key at https://cloud.cerebras.ai\n\n"
        f"*(Current provider: `{Config.LLM_PROVIDER}` — set `RAG_LLM_PROVIDER=ollama` "
        "in `.env` to run without an API key.)*"
    )
    st.stop()


# ── IEEE preview helper ───────────────────────────────────────────────────────
def _paper_to_ieee_html(paper_text: str) -> str:
    """Convert plain paper text to HTML for the two-column IEEE preview panel."""
    heading_re = re.compile(
        r"^([IVX]+\.\s+[A-Z]|Abstract|Index Terms|REFERENCES)",
        re.IGNORECASE,
    )
    all_caps_re = re.compile(r"^[A-Z][A-Z ]{3,}$")
    parts: list[str] = []
    para_lines: list[str] = []

    def flush():
        if para_lines:
            text = " ".join(para_lines).strip()
            if text:
                parts.append(f'<p class="ieee-para">{html.escape(text)}</p>')
            para_lines.clear()

    for raw in paper_text.split("\n"):
        line = raw.strip()
        if not line:
            flush()
            continue
        if heading_re.match(line) or all_caps_re.match(line):
            flush()
            parts.append(f'<div class="ieee-sh">{html.escape(line)}</div>')
        else:
            para_lines.append(line)
    flush()
    return "\n".join(parts)


# ── Section nav helpers ───────────────────────────────────────────────────────
def _extract_sections(paper_text: str) -> list:
    """Returns [(anchor_id, display_label), ...] for each section heading."""
    heading_re = re.compile(
        r'^([IVX]+\.\s+[A-Z][A-Z\s]+|Abstract|Index Terms|REFERENCES)',
        re.IGNORECASE
    )
    all_caps_re = re.compile(r'^[A-Z][A-Z ]{3,}$')
    # Map well-known heading patterns to clean display names
    _clean_map = [
        (re.compile(r'^abstract$', re.I),       "Abstract"),
        (re.compile(r'^index\s+terms?$', re.I), "Index Terms"),
        (re.compile(r'^references?$', re.I),    "References"),
        (re.compile(r'^([IVX]+)\.\s+(.+)$', re.I), None),  # handled inline
    ]
    sections = []
    for i, line in enumerate(paper_text.split('\n')):
        stripped = line.strip()
        if not stripped:
            continue
        if heading_re.match(stripped) or all_caps_re.match(stripped):
            label = stripped
            # Try to clean: for "I. INTRODUCTION" → "I. Introduction"
            m_roman = re.match(r'^([IVX]+)\.\s+(.+)$', stripped, re.I)
            if m_roman:
                label = f"{m_roman.group(1).upper()}. {m_roman.group(2).strip().title()}"
            elif stripped.upper() == "ABSTRACT":
                label = "Abstract"
            elif stripped.upper().startswith("INDEX TERM"):
                label = "Index Terms"
            elif stripped.upper().startswith("REFERENCE"):
                label = "References"
            else:
                # Title-case the heading
                label = stripped.title()
            sections.append((f"psec{i}", label))
    return sections


def _paper_to_html_with_anchors(paper_text: str) -> str:
    """Render paper as HTML preserving whitespace, with anchor IDs at headings."""
    heading_re = re.compile(
        r'^([IVX]+\.\s+[A-Z][A-Z\s]+|Abstract|Index Terms|REFERENCES)',
        re.IGNORECASE
    )
    all_caps_re = re.compile(r'^[A-Z][A-Z ]{3,}$')
    out = []
    for i, line in enumerate(paper_text.split('\n')):
        stripped = line.strip()
        if stripped and (heading_re.match(stripped) or all_caps_re.match(stripped)):
            out.append(
                f'<span id="psec{i}" style="font-weight:700;display:block;'
                f'margin-top:10px">{html.escape(line)}</span>'
            )
        else:
            out.append(html.escape(line))
    return '\n'.join(out)


def _paper_stats(paper_text: str) -> str:
    words = len(re.findall(r'\b\w+\b', paper_text or ""))
    reading_min = max(1, round(words / 250))
    pages = round(words / 500, 1)
    return f"~{words:,} words · ~{reading_min} min read · ~{pages} pages"


_STOP_WORDS = {
    "the","a","an","and","or","in","on","of","for","to","with","is","are","was","were",
    "that","this","it","by","from","at","as","be","been","have","has","not","which","they",
    "their","its","but","than","then","also","each","all","such","these","those","more",
}


def _expand_keywords(topic: str) -> str:
    """Break a topic sentence into meaningful comma-separated search keywords."""
    words = re.findall(r'\b[a-zA-Z]{3,}\b', topic)
    seen: dict = {}
    for w in words:
        lw = w.lower()
        if lw not in _STOP_WORDS and lw not in seen:
            seen[lw] = w
    return ", ".join(seen.values())


def _map_section_sources(paper_text: str, chunks: list) -> list:
    """Returns [(section_label, [paper_title, ...]), ...] — keyword-overlap attribution."""
    sections = _extract_sections(paper_text)
    if not sections or not chunks:
        return []
    lines = paper_text.split('\n')
    results = []
    for s_idx, (anchor, label) in enumerate(sections):
        line_num = int(anchor[4:])
        next_line = int(sections[s_idx + 1][0][4:]) if s_idx + 1 < len(sections) else len(lines)
        body = ' '.join(lines[line_num + 1:next_line]).lower()
        body_words = set(re.findall(r'\b[a-z]{5,}\b', body)) - _STOP_WORDS
        if not body_words:
            results.append((label, []))
            continue
        scored = []
        for chunk in chunks:
            ctext = (chunk.get('text') or '').lower()
            cwords = set(re.findall(r'\b[a-z]{5,}\b', ctext)) - _STOP_WORDS
            scored.append((len(body_words & cwords), (chunk.get('title') or 'Unknown')[:55]))
        scored.sort(reverse=True)
        seen: list = []
        for score, title in scored:
            if score < 3:
                break
            if title not in seen:
                seen.append(title)
            if len(seen) >= 3:
                break
        results.append((label, seen))
    return results


_ROMAN_MAP = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5,
    "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10,
}

# Chip label → full LLM instruction
_REFINEMENT_CHIPS = {
    "📏 Lengthen paper":    (
        "Expand every section that is under-developed (fewer than 2 full paragraphs). "
        "Add more technical depth, analysis, and inline citations [N]. "
        "Target at least 3 full pages of dense IEEE-style prose."
    ),
    "🔬 Deeper methodology": (
        "Rewrite Section V (Methodology) with greater technical depth: "
        "describe each algorithm step-by-step, explain design decisions, "
        "and connect techniques explicitly to the identified research gap."
    ),
    "📊 Strengthen results": (
        "Expand the Results/Evaluation section: add specific quantitative comparisons, "
        "organise key metrics into a structured table, and cite the source paper "
        "for every number or percentage reported."
    ),
    "🔮 Expand future work": (
        "Rewrite the Conclusion and Future Scope section with 4-5 concrete, specific "
        "research directions grounded in the limitations identified by the source papers. "
        "Be precise about open problems — avoid vague generalities."
    ),
    "✍️ Formal IEEE tone":  (
        "Rewrite the entire paper in strict IEEE academic style: "
        "consistent third-person, no informal phrases, passive voice where appropriate, "
        "every claim backed by an inline citation, and section headings in IEEE roman-numeral format."
    ),
    "✏️ Rewrite abstract":  (
        "Rewrite the Abstract to be 150–200 words, covering exactly: "
        "(1) motivation and problem, (2) key methodology used, "
        "(3) main quantitative results, (4) significance / contribution of the work."
    ),
}


def _resolve_section_instruction(instruction: str, paper_text: str) -> str:
    """Detect section references in the instruction and inject that section's current text."""
    if not paper_text:
        return instruction
    sections = _extract_sections(paper_text)
    if not sections:
        return instruction

    lines = paper_text.split('\n')
    target_idx = None

    # "section III" / "section iv"
    m_roman = re.search(r'\bsection\s+([ivxIVX]{1,6})\b', instruction, re.IGNORECASE)
    if m_roman:
        roman_key = m_roman.group(1).lower()
        for idx, (anchor, label) in enumerate(sections):
            if re.match(rf'^{re.escape(m_roman.group(1))}[.\s]', label, re.IGNORECASE):
                target_idx = idx
                break

    # "section 3"
    if target_idx is None:
        m_num = re.search(r'\bsection\s+(\d+)\b', instruction, re.IGNORECASE)
        if m_num:
            sec_num = int(m_num.group(1))
            numbered = [i for i, (_, lbl) in enumerate(sections)
                        if re.match(r'^[IVXivx]+[.\s]', lbl)]
            if 1 <= sec_num <= len(numbered):
                target_idx = numbered[sec_num - 1]

    # Named section ("the introduction", "methodology", etc.)
    if target_idx is None:
        _name_aliases = [
            ("abstract",      ["abstract"]),
            ("introduction",  ["introduction"]),
            ("methodology",   ["methodology", "method"]),
            ("results",       ["results", "evaluation", "experiment"]),
            ("discussion",    ["discussion"]),
            ("conclusion",    ["conclusion"]),
            ("literature",    ["literature", "related work", "background"]),
            ("future",        ["future work", "future scope"]),
            ("references",    ["references"]),
        ]
        instr_lower = instruction.lower()
        for key, aliases in _name_aliases:
            if any(a in instr_lower for a in aliases):
                for idx, (_, label) in enumerate(sections):
                    if key in label.lower():
                        target_idx = idx
                        break
                if target_idx is not None:
                    break

    if target_idx is None:
        return instruction

    anchor, sec_label = sections[target_idx]
    line_num = int(anchor[4:])
    next_line = int(sections[target_idx + 1][0][4:]) if target_idx + 1 < len(sections) else len(lines)
    sec_body = '\n'.join(lines[line_num:next_line]).strip()
    sec_body = sec_body[:1400] + ('…' if len(sec_body) > 1400 else '')

    return (
        f"{instruction}\n\n"
        f"The current content of **{sec_label}** is:\n"
        f"---\n{sec_body}\n---\n"
        f"Focus your revision specifically on this section, preserving the rest of the paper."
    )


def _generate_bibtex(chunks: list) -> str:
    seen: set = set()
    used_citekeys: dict = {}
    entries: list = []
    for chunk in chunks:
        title   = (chunk.get("title") or "Unknown").strip()
        if title in seen:
            continue
        seen.add(title)
        authors = chunk.get("authors", [])
        author_str = " and ".join(authors) if isinstance(authors, list) else str(authors or "")
        year       = str(chunk.get("published", ""))[:4] or "2024"
        arxiv_id   = (chunk.get("arxiv_id") or "").strip()
        first_auth = (authors[0].split()[-1] if authors else "unknown").lower()
        first_word = re.sub(r"[^a-z]", "", (title.split()[0] if title else "paper").lower())
        base_key   = f"{first_auth}{year}{first_word}"
        if base_key in used_citekeys:
            used_citekeys[base_key] += 1
            citekey = f"{base_key}{chr(96 + used_citekeys[base_key])}"  # a, b, c...
        else:
            used_citekeys[base_key] = 1
            citekey = base_key
        entry = (
            f"@article{{{citekey},\n"
            f"  author       = {{{author_str}}},\n"
            f"  title        = {{{{{title}}}}},\n"
            f"  year         = {{{year}}},\n"
        )
        if arxiv_id:
            entry += (
                f"  eprint       = {{{arxiv_id}}},\n"
                f"  archivePrefix = {{arXiv}},\n"
                f"  url          = {{https://arxiv.org/abs/{arxiv_id}}},\n"
            )
        entry += "}"
        entries.append(entry)
    return "\n\n".join(entries)


def _extract_arxiv_link(row: dict) -> str:
    """Try to extract an arXiv URL from the Journal Details column."""
    jd = str(row.get("Journal Details (DOI / Year / Citation)", "") or "")
    m = re.search(r"arXiv:(\S+)", jd, re.I)
    if m:
        aid = m.group(1).rstrip(".")
        return f"https://arxiv.org/abs/{aid}"
    return ""


# ── Survey table renderer ─────────────────────────────────────────────────────
def render_survey_section(rows: list, done_topic: str, survey_paper_text: str,
                           survey_pdf_bytes: bytes | None):
    st.success(f"Literature survey — analysed **{len(rows)}** papers on: *{done_topic}*")

    # View toggle
    _view_key = f"survey_view_{done_topic[:20]}"
    _view = st.radio("View", ["Table view", "Card view"], key=_view_key,
                     horizontal=True, label_visibility="collapsed")

    if _view == "Table view":
        # ── Enhanced table with sticky cols, link col, cell scroll ───────────
        _col_headers = [
            ("No.",        "col-no"),
            ("Title",      "col-title"),
            ("Authors",    "col-authors"),
            ("Link",       "col-link"),
            ("Journal Details\n(DOI / Year / Citation)", "col-doi"),
            ("Problem Statement",                        "col-wide"),
            ("Objective",                                "col-wide"),
            ("Research Gap",                             "col-wide"),
            ("Methodology\n(Algorithm / Techniques)",    "col-wide"),
            ("Features\n(Focused)",                      "col-wide"),
            ("Results & Discussion\n(Performance Metric / Value)", "col-wide"),
            ("Limitations",  "col-wide"),
            ("Future Scope", "col-wide"),
        ]
        _col_keys = [
            "No.", "Title", "Authors", "__link__",
            "Journal Details (DOI / Year / Citation)",
            "Problem Statement", "Objective", "Research Gap",
            "Methodology (Algorithm / Techniques)", "Features (Focused)",
            "Results & Discussion (Performance Metric / Value)",
            "Limitations", "Future Scope",
        ]
        header_html = "".join(
            f"<th>{html.escape(lbl).replace(chr(10), '<br/>')}</th>"
            for lbl, _ in _col_headers
        )
        rows_html = ""
        for i, row in enumerate(rows):
            cells = ""
            arxiv_url = _extract_arxiv_link(row)
            for key, css in zip(_col_keys, [c[1] for c in _col_headers]):
                if key == "__link__":
                    if arxiv_url:
                        cell = f'<a class="arXiv-link" href="{arxiv_url}" target="_blank">📄 arXiv</a>'
                    else:
                        cell = '<span style="color:#555;font-size:11px">—</span>'
                    cells += f"<td class='{css}'>{cell}</td>"
                else:
                    val = html.escape(str(row.get(key, "")))
                    cells += f"<td class='{css}'>{val}</td>"
            rows_html += f"<tr>{cells}</tr>"
        table_html = (
            f'<div class="survey-table-wrapper"><table class="survey-table">'
            f'<thead><tr>{header_html}</tr></thead>'
            f'<tbody>{rows_html}</tbody></table></div>'
        )
        st.markdown(table_html, unsafe_allow_html=True)

    else:
        # ── Card view ────────────────────────────────────────────────────────
        for i, row in enumerate(rows):
            title   = row.get("Title", f"Paper {i+1}")
            authors = row.get("Authors", "")
            jd      = row.get("Journal Details (DOI / Year / Citation)", "")
            year_m  = re.search(r'\b(19|20)\d{2}\b', jd)
            year    = year_m.group(0) if year_m else ""
            arxiv_url = _extract_arxiv_link(row)
            lbl_short = f"**{i+1}.** {title[:70]}{'…' if len(title)>70 else ''}"
            if year:
                lbl_short += f"  ·  {year}"
            if authors:
                lbl_short += f"  ·  {authors[:40]}{'…' if len(authors)>40 else ''}"
            with st.expander(lbl_short, expanded=False):
                if arxiv_url:
                    st.markdown(
                        f'<a class="arXiv-link" href="{arxiv_url}" target="_blank">🔗 View on arXiv</a>',
                        unsafe_allow_html=True,
                    )
                    st.write("")
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.markdown(f"**Problem Statement**\n\n{row.get('Problem Statement','—')}")
                with c2:
                    st.markdown(f"**Objective**\n\n{row.get('Objective','—')}")
                with c3:
                    st.markdown(f"**Research Gap**\n\n{row.get('Research Gap','—')}")
                st.write("")
                st.markdown(f"**Methodology:** {row.get('Methodology (Algorithm / Techniques)','—')}")
                st.markdown(f"**Results:** {row.get('Results & Discussion (Performance Metric / Value)','—')}")
                st.markdown(f"**Limitations:** {row.get('Limitations','—')}")
                st.markdown(f"**Future Scope:** {row.get('Future Scope','—')}")
                st.code(jd or "—", language=None)

    # Research gap summary panel
    _gaps = [
        (r.get("Title", f"Paper {i+1}")[:55], r.get("Research Gap", ""))
        for i, r in enumerate(rows)
        if r.get("Research Gap") and r["Research Gap"].strip().lower() not in ("", "not mentioned")
    ]
    if _gaps:
        with st.expander(f"🔍 Research Gap Summary ({len(_gaps)} papers)", expanded=False):
            for i, (title, gap) in enumerate(_gaps, 1):
                st.markdown(
                    f'<div style="margin-bottom:10px">'
                    f'<span style="color:#3b82f6;font-size:12px;font-weight:600">[{i}] {html.escape(title)}</span>'
                    f'<div style="font-size:13px;color:#c9d1d9;margin-top:2px">{html.escape(gap)}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    # ── Downloads ─────────────────────────────────────────────────────────────
    st.write("")
    df = pd.DataFrame(rows)
    _safe_topic = done_topic[:30].replace(' ', '_')
    dl1, dl2, dl3, dl4 = st.columns(4)
    with dl1:
        st.download_button(
            "⬇ CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name=f"survey_{_safe_topic}.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with dl2:
        try:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as w:
                df.to_excel(w, index=False, sheet_name="Literature Survey")
            st.download_button(
                "⬇ Excel",
                data=buf.getvalue(),
                file_name=f"survey_{_safe_topic}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        except ImportError:
            st.caption("Install `openpyxl` for Excel export.")
    with dl3:
        if st.button("⬇ Word (.docx)", key=f"survey_docx_{done_topic[:20]}", use_container_width=True):
            _sdocx = generate_survey_docx(
                rows,
                topic=done_topic,
                output_dir=Config.OUTPUT_DIR,
                filename=f"survey_{_safe_topic}",
            )
            if _sdocx and os.path.exists(_sdocx):
                with open(_sdocx, "rb") as _sf:
                    st.download_button(
                        "Click to save",
                        data=_sf.read(),
                        file_name=os.path.basename(_sdocx),
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key=f"survey_docx_save_{done_topic[:20]}",
                    )
            else:
                st.error("Word export failed.")
    with dl4:
        if survey_pdf_bytes:
            st.download_button(
                "⬇ PDF (IEEE)",
                data=survey_pdf_bytes,
                file_name=f"survey_{done_topic[:30].replace(' ', '_')}_ieee.pdf",
                mime="application/pdf",
                use_container_width=True,
                type="primary",
            )


# ── RAG paper tabs renderer ───────────────────────────────────────────────────
def render_paper_tabs(result: dict, uid: str, topic: str = ""):
    paper_text = result.get("paper_text", "")
    n = result.get("num_papers", 0)
    strat = result.get("strategy", "N/A")
    pages = result.get("page_estimate", 0)
    faith = clamp_score(result.get("faithfulness"))

    # Topic header
    if topic:
        st.markdown(f'<p class="topic-heading">{html.escape(topic.title())}</p>', unsafe_allow_html=True)

    # Topbar: metadata + faithfulness badge
    _stats_str = _paper_stats(paper_text) if paper_text else f"~{pages:.1f} pages"
    if faith is not None:
        if faith >= 4:
            _badge = f'<span class="faith-badge-good">Faithfulness {faith:.0f}/5</span>'
        elif faith >= 2:
            _badge = f'<span class="faith-badge-fair">Faithfulness {faith:.0f}/5</span>'
        else:
            _badge = f'<span class="faith-badge-poor">⚠ Faithfulness {faith:.0f}/5</span>'
        st.markdown(
            f'<div style="font-size:13px;color:#a3a3a3;margin-bottom:6px">'
            f'Based on <b style="color:#e5e5e5">{n}</b> arXiv paper(s) &nbsp;·&nbsp; '
            f'strategy: <code>{strat}</code> &nbsp;·&nbsp; {_stats_str}'
            f' &nbsp;&nbsp;{_badge}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.caption(
            f"Based on **{n}** arXiv paper(s) · strategy: `{strat}` · {_stats_str}"
        )

    if 0 < n < 4:
        st.caption(f"⚠️ Only {n} source paper(s) — results may be shallow. Tick **Refresh papers from arXiv** in Settings and regenerate.")

    # Tab label: add ⚠ badge on Quality tab if faithfulness is poor
    _quality_label = "⚠ Quality & Sources" if (faith is not None and faith < 3) else "Quality & Sources"
    t_paper, t_survey, t_quality = st.tabs(["Paper", "Survey & Analysis", _quality_label])

    with t_paper:
        if paper_text:
            # Faithfulness alert banner (dismissible via session state)
            _banner_key = f"faith_banner_dismissed_{uid}"
            if faith is not None and faith < 3 and not st.session_state.get(_banner_key):
                bc1, bc2 = st.columns([8, 1])
                with bc1:
                    st.markdown(
                        f'<div class="faith-alert">'
                        f'<div class="faith-alert-text">'
                        f'<p class="faith-alert-title">⚠ Low faithfulness detected</p>'
                        f'<p class="faith-alert-sub">This paper contains claims not fully grounded in '
                        f'retrieved sources. Consider regenerating or fixing citations.</p>'
                        f'</div></div>',
                        unsafe_allow_html=True,
                    )
                with bc2:
                    if st.button("✕", key=f"dismiss_banner_{uid}", help="Dismiss"):
                        st.session_state[_banner_key] = True
                        st.rerun()
                # Fix citations shortcut in banner row
                if paper_text and result.get("retrieved_context"):
                    if st.button("🔧 Fix Citations", key=f"banner_fix_cit_{uid}", type="primary"):
                        _raw_ctx = [
                            {"metadata": {
                                "title":     c.get("title", ""),
                                "authors":   c.get("authors", []),
                                "published": c.get("published", ""),
                                "arxiv_id":  c.get("arxiv_id", ""),
                            }}
                            for c in result["retrieved_context"]
                        ]
                        _fixed = _RAGGenerator.fix_citations_from_metadata(paper_text, _raw_ctx)
                        set_chat("paper_text", _fixed)
                        prev = active["result"] or {}
                        set_chat("result", {**prev, "paper_text": _fixed})
                        st.toast("Citations rebuilt!", icon="✅")
                        st.rerun()

            # Section jump nav (clean labels)
            sections = _extract_sections(paper_text)
            if sections:
                links = " &nbsp;·&nbsp; ".join(
                    f'<a href="#{aid}">{html.escape(lbl)}</a>'
                    for aid, lbl in sections
                )
                st.markdown(f'<div class="section-nav">{links}</div>', unsafe_allow_html=True)

            # Paper rendered with anchor IDs at headings
            paper_html = _paper_to_html_with_anchors(paper_text)
            st.markdown(
                f'<div class="paper-box">{paper_html}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.warning("No paper text was generated.")

        st.write("")
        col_pdf, col_docx, col_cp = st.columns([1, 1, 1])
        pdf_path = result.get("pdf_path")
        with col_pdf:
            if pdf_path and os.path.exists(pdf_path):
                with open(pdf_path, "rb") as f:
                    st.download_button(
                        "⬇ Download PDF",
                        data=f.read(),
                        file_name=os.path.basename(pdf_path),
                        mime="application/pdf",
                        key=f"dl_pdf_{uid}",
                        use_container_width=True,
                    )
            else:
                st.caption("PDF not available.")
        with col_docx:
            if paper_text:
                _docx_cache_key = f"_docx_bytes_{uid}"
                if _docx_cache_key not in st.session_state:
                    _docx_path = generate_paper_docx(
                        paper_text,
                        title=topic or "ieee_paper",
                        output_dir=Config.OUTPUT_DIR,
                        filename=f"{re.sub(r'[^a-zA-Z0-9]', '_', topic or 'paper')[:40]}_IEEE",
                    )
                    if _docx_path and os.path.exists(_docx_path):
                        with open(_docx_path, "rb") as _f:
                            st.session_state[_docx_cache_key] = _f.read()
                    else:
                        st.session_state[_docx_cache_key] = None
                _docx_bytes = st.session_state.get(_docx_cache_key)
                if _docx_bytes:
                    st.download_button(
                        "⬇ Download Word (.docx)",
                        data=_docx_bytes,
                        file_name=f"{re.sub(r'[^a-zA-Z0-9]', '_', topic or 'paper')[:40]}_IEEE.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key=f"dl_docx_{uid}",
                        use_container_width=True,
                    )
                else:
                    st.caption("Word export failed.")
        # #4 — copy text
        with col_cp:
            with st.expander("Copy paper text"):
                st.text_area(
                    "Select all (Ctrl+A) then copy (Ctrl+C)",
                    value=paper_text,
                    height=180,
                    key=f"copy_ta_{uid}",
                )

        # 5.3 — Section source attribution
        _ctx_chunks = result.get("retrieved_context", [])
        if paper_text and _ctx_chunks:
            _sec_map = _map_section_sources(paper_text, _ctx_chunks)
            _sec_map_nonempty = [(lbl, titles) for lbl, titles in _sec_map if titles]
            if _sec_map_nonempty:
                with st.expander(f"📑 Section Sources ({len(_sec_map_nonempty)} sections attributed)", expanded=False):
                    for lbl, titles in _sec_map_nonempty:
                        st.markdown(
                            f'<div style="margin-bottom:8px">'
                            f'<span style="color:#58a6ff;font-size:12px;font-weight:600">{html.escape(lbl)}</span>',
                            unsafe_allow_html=True,
                        )
                        for t in titles:
                            st.markdown(
                                f'<div style="font-size:12px;color:#8b949e;margin-left:12px">· {html.escape(t)}</div>',
                                unsafe_allow_html=True,
                            )
                        st.markdown('</div>', unsafe_allow_html=True)

        # Fix Citations button (dedicated, metadata-based)
        st.write("")
        if paper_text and result.get("retrieved_context"):
            if st.button("🔧 Fix Citations (rebuild from source metadata)", key=f"fix_cit_{uid}"):
                _raw_ctx = [
                    {"metadata": {
                        "title":     c.get("title", ""),
                        "authors":   c.get("authors", []),
                        "published": c.get("published", ""),
                        "arxiv_id":  c.get("arxiv_id", ""),
                    }}
                    for c in result["retrieved_context"]
                ]
                _fixed = _RAGGenerator.fix_citations_from_metadata(paper_text, _raw_ctx)
                set_chat("paper_text", _fixed)
                prev = active["result"] or {}
                set_chat("result", {**prev, "paper_text": _fixed})
                st.toast("Citations rebuilt from source metadata!", icon="✅")
                st.rerun()

    with t_survey:
        _atbl = result.get("analysis_table", [])
        if not _atbl:
            st.info("Analysis table not available for this paper. Re-generate to get it.")
        else:
            st.markdown(f"Comparative analysis of **{len(_atbl)}** paper(s) used to generate this review.")
            _acols = [
                ("No.",                                                   "paper-no"),
                ("Title",                                                 "paper-title"),
                ("Authors",                                               ""),
                ("Journal Details\n(DOI / Year / Citation)",              ""),
                ("Problem Statement",                                     ""),
                ("Objective",                                             ""),
                ("Research Gap",                                          ""),
                ("Methodology\n(Algorithm / Techniques)",                 ""),
                ("Features\n(Focused)",                                   ""),
                ("Results & Discussion\n(Performance Metric / Value)",    ""),
                ("Limitations",                                           ""),
                ("Future Scope",                                          ""),
            ]
            _acol_keys = [
                "No.", "Title", "Authors",
                "Journal Details (DOI / Year / Citation)",
                "Problem Statement", "Objective", "Research Gap",
                "Methodology (Algorithm / Techniques)", "Features (Focused)",
                "Results & Discussion (Performance Metric / Value)",
                "Limitations", "Future Scope",
            ]
            _ahdr = "".join(
                f"<th>{html.escape(lbl).replace(chr(10), '<br/>')}</th>"
                for lbl, _ in _acols
            )
            _arows_html = ""
            for row in _atbl:
                _cells = ""
                for key, css in zip(_acol_keys, [c[1] for c in _acols]):
                    val = html.escape(str(row.get(key, "")))
                    _cells += f"<td class='{css}'>{val}</td>"
                _arows_html += f"<tr>{_cells}</tr>"
            _atable_html = (
                f'<div class="survey-table-wrapper"><table class="survey-table">'
                f'<thead><tr>{_ahdr}</tr></thead>'
                f'<tbody>{_arows_html}</tbody></table></div>'
            )
            st.markdown(_atable_html, unsafe_allow_html=True)

            _adf = pd.DataFrame(_atbl)
            _dl1, _dl2 = st.columns(2)
            with _dl1:
                st.download_button(
                    "Download CSV",
                    data=_adf.to_csv(index=False).encode("utf-8"),
                    file_name=f"analysis_{(result.get('strategy','') or 'paper')}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            with _dl2:
                try:
                    _buf = io.BytesIO()
                    with pd.ExcelWriter(_buf, engine="openpyxl") as _w:
                        _adf.to_excel(_w, index=False, sheet_name="Analysis Table")
                    st.download_button(
                        "Download Excel",
                        data=_buf.getvalue(),
                        file_name=f"analysis_{(result.get('strategy','') or 'paper')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )
                except ImportError:
                    st.caption("Install `openpyxl` for Excel export.")

    with t_quality:
        if result.get("evaluation_error"):
            st.warning(f"Quality evaluation failed: {result['evaluation_error']}")

        faith = clamp_score(result.get("faithfulness"))
        rel   = clamp_score(result.get("relevance"))
        _eval_ran = faith is not None or rel is not None

        # ── Score gauges ──────────────────────────────────────────────────────
        def _gauge_html(score: float | None, label: str, description: str) -> str:
            if score is None:
                return (
                    f'<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);'
                    f'border-radius:10px;padding:14px 16px;margin-bottom:8px">'
                    f'<div style="font-size:11px;color:#8b949e;margin-bottom:6px;text-transform:uppercase;'
                    f'letter-spacing:0.05em">{label}</div>'
                    f'<div style="font-size:22px;font-weight:700;color:#444">—</div>'
                    f'<div style="font-size:11px;color:#555;margin-top:4px">{description}</div>'
                    f'</div>'
                )
            pct = int(score / 5.0 * 100)
            if score >= 4.0:
                color, tag = "#3fb950", "Good"
            elif score >= 3.0:
                color, tag = "#d29922", "Fair"
            else:
                color, tag = "#f85149", "Poor"
            return (
                f'<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);'
                f'border-radius:10px;padding:14px 16px;margin-bottom:8px">'
                f'<div style="font-size:11px;color:#8b949e;margin-bottom:6px;text-transform:uppercase;'
                f'letter-spacing:0.05em">{label}</div>'
                f'<div style="font-size:26px;font-weight:700;color:{color}">{score:.1f}'
                f'<span style="font-size:14px;color:#8b949e;font-weight:400"> / 5</span></div>'
                f'<div style="background:rgba(255,255,255,0.07);border-radius:6px;height:6px;'
                f'overflow:hidden;margin:8px 0 4px">'
                f'<div style="width:{pct}%;height:6px;background:{color};border-radius:6px"></div></div>'
                f'<div style="font-size:12px;color:{color}">{tag}</div>'
                f'</div>'
            )

        # ── Layout: scores left, pipeline info right ───────────────────────
        _ql, _qr = st.columns([1.2, 1], gap="large")
        with _ql:
            st.markdown("**Quality Scores**")
            if not _eval_ran:
                st.markdown(
                    '<div style="background:rgba(88,166,255,0.07);border:1px solid rgba(88,166,255,0.2);'
                    'border-radius:10px;padding:16px;color:#8b949e;font-size:13px">'
                    '📊 Quality evaluation not run.<br/>'
                    '<span style="color:#58a6ff">Enable <b>Run quality evaluation</b> in Generation settings '
                    'and regenerate to see faithfulness and relevance scores.</span>'
                    '</div>',
                    unsafe_allow_html=True,
                )
                st.write("")
                if paper_text and st.button("▶ Run Evaluation Now", key=f"run_eval_now_{uid}", type="primary"):
                    with st.spinner("Running G-Eval scoring…"):
                        try:
                            _llm = _LLMClient()
                            _eval_ctx = result.get("retrieved_context", [])[:3]
                            _faith = _Evaluator.evaluate_faithfulness(active["topic"], paper_text[:7000], _eval_ctx, _llm)
                            _rel   = _Evaluator.evaluate_relevance(active["topic"], paper_text[:7000], _llm)
                            _prev  = active["result"] or {}
                            set_chat("result", {
                                **_prev,
                                "faithfulness":           _faith.get("score"),
                                "relevance":              _rel.get("score"),
                                "faithfulness_reasoning": _faith.get("reasoning", ""),
                                "relevance_reasoning":    _rel.get("reasoning", ""),
                            })
                            st.toast("Evaluation complete!", icon="✅")
                            st.rerun()
                        except Exception as _eval_err:
                            st.error(f"Evaluation failed: {_eval_err}")
            else:
                _sc1, _sc2 = st.columns(2)
                with _sc1:
                    st.markdown(
                        _gauge_html(faith, "Faithfulness", "Does the paper stay true to source material?"),
                        unsafe_allow_html=True,
                    )
                with _sc2:
                    st.markdown(
                        _gauge_html(rel, "Relevance", "How well does the paper address the topic?"),
                        unsafe_allow_html=True,
                    )

        with _qr:
            st.markdown("**Pipeline Info**")
            timings = result.get("timings", {})
            _info_rows = [
                ("Sources", f"{n} paper(s)"),
                ("Strategy", strat),
                ("Index", f"{timings.get('index_seconds', '—')}s"),
                ("Retrieval", f"{timings.get('retrieval_seconds', '—')}s"),
                ("Generation", f"{timings.get('generation_seconds', '—')}s"),
                ("Total", f"{timings.get('total_seconds', '—')}s"),
            ]
            rows_html = "".join(
                f'<div style="display:flex;justify-content:space-between;padding:7px 0;'
                f'border-bottom:1px solid rgba(255,255,255,0.05);font-size:13px">'
                f'<span style="color:#8b949e">{k}</span>'
                f'<span style="color:#e6edf3;font-weight:600">{v}</span></div>'
                for k, v in _info_rows
            )
            st.markdown(
                f'<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);'
                f'border-radius:10px;padding:12px 16px">{rows_html}</div>',
                unsafe_allow_html=True,
            )

        # ── Retrieval scores ──────────────────────────────────────────────────
        _chunks = result.get("retrieved_context", [])
        if _chunks:
            st.divider()
            st.markdown("**Retrieval scores**")
            _scores = [c.get("rerank_score") or c.get("score") for c in _chunks]
            _scores = [s for s in _scores if s is not None]
            _unique_titles = len({(c.get("title") or "?") for c in _chunks})

            _BM25_ALPHA = {"hyde": 0.7, "complex": 0.45, "standard": 0.5}
            _vec_ratio = _BM25_ALPHA.get(strat, 0.5)
            _bm25_ratio = 1.0 - _vec_ratio

            _avg_s = f"{sum(_scores)/len(_scores):.3f}" if _scores else "—"
            _max_s = f"{max(_scores):.3f}" if _scores else "—"
            _min_s = f"{min(_scores):.3f}" if _scores else "—"

            rs1, rs2, rs3, rs4, rs5 = st.columns(5)
            rs1.metric("Chunks", f"{len(_chunks)} / {num_retrieval_papers}")
            rs2.metric("Papers used", f"{_unique_titles} / {n}")
            rs3.metric("Avg score", f"{_avg_s} / 1.000")
            rs4.metric("Max score", f"{_max_s} / 1.000")
            rs5.metric("Min score", f"{_min_s} / 1.000")

            st.markdown(
                f'<div style="margin-top:8px;font-size:12px;color:#8b949e">'
                f'Hybrid blend — '
                f'<span style="color:#58a6ff">Vector {_vec_ratio:.0%}</span> / '
                f'<span style="color:#d29922">BM25 {_bm25_ratio:.0%}</span>'
                f' &nbsp;·&nbsp; strategy: <code>{strat}</code>'
                f'</div>',
                unsafe_allow_html=True,
            )

        # ── Evaluation reasoning (only shown when content exists) ─────────────
        _has_reasoning = result.get("faithfulness_reasoning") or result.get("relevance_reasoning")
        if _has_reasoning:
            st.divider()
            with st.expander("📋 Evaluation reasoning", expanded=False):
                if result.get("faithfulness_reasoning"):
                    st.markdown("**Faithfulness**")
                    st.info(result["faithfulness_reasoning"])
                if result.get("relevance_reasoning"):
                    st.markdown("**Relevance**")
                    st.info(result["relevance_reasoning"])

        # ── Sources section (merged into Quality & Sources tab) ───────────────
        st.divider()
        st.markdown("**Sources**")
        chunks = result.get("retrieved_context", [])
        if not chunks:
            st.info("No retrieved chunks available.")
        else:
            from collections import Counter
            title_counts = Counter(
                (c.get("title") or "Unknown")[:50] for c in chunks
            )
            if len(title_counts) > 1:
                st.markdown("**Paper contribution** *(chunks used)*")
                contrib_df = pd.DataFrame(
                    {"Chunks": list(title_counts.values())},
                    index=list(title_counts.keys()),
                )
                st.bar_chart(contrib_df, height=140)

            with st.expander(f"View {len(chunks[:8])} retrieved chunks", expanded=False):
                for i, chunk in enumerate(chunks[:8], 1):
                    title = chunk.get("title") or "Unknown"
                    score = chunk.get("rerank_score") or chunk.get("score")
                    text = re.sub(r"\s+", " ", chunk.get("text", "")).strip()
                    st.markdown(f"**[{i}] {title}**")
                    st.caption(f"score: {score}")
                    st.write(text[:600] + ("…" if len(text) > 600 else ""))
                    if i < len(chunks[:8]):
                        st.divider()

        pr = result.get("plagiarism_report")
        if pr:
            with st.expander("Plagiarism report"):
                pc1, pc2, pc3 = st.columns(3)
                pc1.metric("Avg Similarity", f"{pr.get('overall_similarity_pct',0)}%")
                pc2.metric("Max Sentence Sim", f"{pr.get('max_sentence_similarity_pct',0)}%")
                pc3.metric("8-gram Overlap", f"{pr.get('ngram_overlap_pct',0)}%")


# ── Sidebar ───────────────────────────────────────────────────────────────────
# Read settings from session state (set via settings page)
strategy_ui         = st.session_state.get("_s_strategy", "auto")
num_survey_papers   = st.session_state.get("_s_num_survey", Config.SURVEY_DEFAULT_PAPERS)
num_retrieval_papers = st.session_state.get("_s_topk", 6)
refresh_sources     = st.session_state.get("_s_refresh", True)
run_eval            = st.session_state.get("_s_eval", True)
# Hardcoded defaults
fast_mode        = True
generate_pdf     = True
use_latex_pdf    = True
fast_5page_mode  = True
min_pages        = Config.MIN_PAGES_DEFAULT

with st.sidebar:
    st.title("ResearchGPT")
    st.caption("Literature survey + IEEE paper generator")

    if st.button("+ New Research", use_container_width=True):
        new_chat()
        st.rerun()

    st.write("")

    # ── Unified "Recent" list (chats + saved history merged) ─────────────────
    if "hist_confirm_delete" not in st.session_state:
        st.session_state.hist_confirm_delete = None

    if st.session_state.get("_hist_dirty", True) or "_hist_cache" not in st.session_state:
        st.session_state._hist_cache = list_history(max_entries=10)
        st.session_state._hist_dirty = False
    _hist = st.session_state._hist_cache

    # Build unified list: active chats first (newest first), then history entries
    _recent_items = []
    for i in range(len(st.session_state.chats) - 1, -1, -1):
        c = st.session_state.chats[i]
        _recent_items.append({
            "type": "chat",
            "idx": i,
            "id": c["id"],
            "title": c["title"],
            "ts": None,
            "is_active": (i == st.session_state.active_chat),
        })

    _hist_fnames_used = set()
    for _h in _hist:
        # Avoid duplicating if a chat was loaded from history (same topic)
        _recent_items.append({
            "type": "history",
            "fname": _h["fname"],
            "title": _h["topic"],
            "ts": _h["saved_at"],
            "is_active": False,
        })
        _hist_fnames_used.add(_h["fname"])

    if _recent_items:
        st.caption("RECENT")

        # History delete confirmation banner
        if st.session_state.hist_confirm_delete:
            _del_fname = st.session_state.hist_confirm_delete
            _del_topic = next((_h["topic"] for _h in _hist if _h["fname"] == _del_fname), _del_fname)
            st.warning(f"Delete **{_del_topic[:35]}**?")
            _dc1, _dc2 = st.columns(2)
            with _dc1:
                if st.button("Delete", type="primary", use_container_width=True, key="hist_del_confirm"):
                    _history_delete(_del_fname)
                    st.session_state.hist_confirm_delete = None
                    st.session_state._hist_dirty = True
                    st.rerun()
            with _dc2:
                if st.button("Cancel", use_container_width=True, key="hist_del_cancel"):
                    st.session_state.hist_confirm_delete = None
                    st.rerun()

        for item in _recent_items:
            _raw_title = item["title"]
            _label = ("▶  " if item["is_active"] else "📄  ") + \
                     (_raw_title[:22] + "…" if len(_raw_title) > 22 else _raw_title)
            _btn_type = "primary" if item["is_active"] else "secondary"
            _ts_str = time.strftime("%m/%d %H:%M", time.localtime(item["ts"])) if item.get("ts") else ""

            _rc1, _rc2 = st.columns([5, 1])
            with _rc1:
                _btn_label = _label
                if _ts_str:
                    _btn_label = _label  # keep label clean; show ts below via caption (can't in button)
                if st.button(_btn_label, key=f"recent_{item['type']}_{item.get('id', item.get('fname',''))}",
                             use_container_width=True, type=_btn_type, help=_raw_title):
                    if item["type"] == "chat":
                        i = item["idx"]
                        if not item["is_active"]:
                            st.session_state.active_chat = i
                            st.rerun()
                    else:
                        # Load from history
                        _hdata = _history_load(item["fname"])
                        if _hdata and _hdata.get("paper_text"):
                            _hresult = {k: _hdata.get(k) for k in (
                                "paper_text", "num_papers", "strategy", "page_estimate",
                                "faithfulness", "relevance", "faithfulness_reasoning",
                                "relevance_reasoning", "retrieved_context", "plagiarism_report",
                                "timings", "status", "analysis_table",
                                "latex_compile_log", "tex_path", "pdf_path",
                                "rouge_l", "ai_rewrite_passes", "humanize_applied", "min_pages_target",
                            )}
                            for _dk in ("evaluation_error","rouge_l","ai_rewrite_passes","humanize_applied",
                                        "latex_compile_log","tex_path","pdf_path","error","min_pages_target","analysis_table"):
                                _hresult.setdefault(_dk, [] if _dk == "analysis_table" else None)
                            _hresult.setdefault("ai_rewrite_passes", 0)
                            _hresult.setdefault("humanize_applied", False)

                            import base64 as _b64
                            _survey_pdf = None
                            if _hdata.get("survey_pdf_b64"):
                                try:
                                    _survey_pdf = _b64.b64decode(_hdata["survey_pdf_b64"])
                                except Exception:
                                    pass

                            set_chat("topic", _hdata["topic"])
                            set_chat("title", _hdata["topic"].title()[:40])
                            set_chat("paper_text", _hdata["paper_text"])
                            set_chat("context", _hdata.get("retrieved_context", []))
                            set_chat("result", _hresult)
                            set_chat("survey_rows", _hdata.get("survey_rows", []))
                            set_chat("survey_paper_text", _hdata.get("survey_paper_text", ""))
                            set_chat("survey_pdf_bytes", _survey_pdf)
                            set_chat("has_survey", True)
                            set_chat("has_paper", True)
                            set_chat("processing", None)
                            st.rerun()
            with _rc2:
                if item["type"] == "chat":
                    if st.button("✕", key=f"del_chat_{item['id']}", help="Delete this chat"):
                        i = item["idx"]
                        if item["is_active"]:
                            remaining = [j for j in range(len(st.session_state.chats)) if j != i]
                            st.session_state.active_chat = remaining[-1] if remaining else 0
                        st.session_state.chats.pop(i)
                        if not st.session_state.chats:
                            st.session_state.chats = [_make_chat(st.session_state._next_chat_id)]
                            st.session_state._next_chat_id += 1
                            st.session_state.active_chat = 0
                        elif st.session_state.active_chat >= len(st.session_state.chats):
                            st.session_state.active_chat = len(st.session_state.chats) - 1
                        st.rerun()
                else:
                    if st.button("✕", key=f"hdel_{item['fname']}", help="Delete"):
                        st.session_state.hist_confirm_delete = item["fname"]
                        st.rerun()

    # ── Settings link at very bottom ─────────────────────────────────────────
    st.write("")
    st.divider()
    if st.button("⚙ Generation settings", use_container_width=True):
        st.session_state.show_settings = not st.session_state.get("show_settings", False)
        st.rerun()
    st.caption("Powered by Cerebras LLM + arXiv RAG")


# ── Main page ─────────────────────────────────────────────────────────────────
active = chat()
messages = active["messages"]
has_paper = active["has_paper"]
has_survey = active["has_survey"]
processing = active["processing"]

# ── Settings page (full-screen overlay) ──────────────────────────────────────
if st.session_state.get("show_settings"):
    st.markdown('<div class="settings-page">', unsafe_allow_html=True)
    st.markdown("## ⚙ Generation Settings")
    st.caption("Author details")
    st.text_input("Full name", placeholder="e.g. Jane Smith", key="author_name")
    st.text_input("Affiliation", placeholder="e.g. MIT CSAIL", key="author_affil")
    st.text_input("Email", placeholder="e.g. jsmith@mit.edu", key="author_email")
    st.divider()
    st.caption("Retrieval & generation")
    _strategy_help = (
        "**auto** — picks best strategy for your query\n\n"
        "**hyde** — generates a hypothetical answer first; best for open-ended topics\n\n"
        "**complex** — breaks query into sub-questions; best for comparisons\n\n"
        "**standard** — plain BM25 + vector search; fastest"
    )
    _strat_opts = ["auto", "hyde", "complex", "standard"]
    _strat_idx  = _strat_opts.index(st.session_state.get("_s_strategy", "auto"))
    _new_strat = st.selectbox("Retrieval Strategy", _strat_opts, index=_strat_idx, help=_strategy_help)
    _strategy_desc = {
        "auto":     "Automatically picks the best strategy for your query.",
        "hyde":     "Generates a hypothetical answer first — best for open-ended topics.",
        "complex":  "Breaks your query into sub-questions — best for comparisons & benchmarks.",
        "standard": "Plain hybrid BM25 + vector search — fastest.",
    }
    st.caption(_strategy_desc.get(_new_strat, ""))
    _new_survey = st.number_input(
        "Survey papers", min_value=Config.SURVEY_MIN_PAPERS, max_value=Config.SURVEY_MAX_PAPERS,
        value=int(st.session_state.get("_s_num_survey", Config.SURVEY_DEFAULT_PAPERS)),
        help="How many arXiv papers to fetch for the survey.",
    )
    _new_topk = st.slider(
        "Retrieval chunks (top-k)", min_value=3, max_value=12,
        value=int(st.session_state.get("_s_topk", 6)),
        help="Chunks retrieved for paper generation. Higher = richer context, slower.",
    )
    _new_refresh = st.checkbox(
        "Refresh papers from arXiv",
        value=bool(st.session_state.get("_s_refresh", True)),
        help="Force re-download papers. Enable if results used too few sources.",
    )
    _new_eval = st.checkbox(
        "Run quality evaluation",
        value=bool(st.session_state.get("_s_eval", True)),
        help="Score faithfulness and relevance. Adds ~30s.",
    )
    st.write("")
    if st.button("✓ Save & return", type="primary"):
        st.session_state._s_strategy  = _new_strat
        st.session_state._s_num_survey = _new_survey
        st.session_state._s_topk      = _new_topk
        st.session_state._s_refresh   = _new_refresh
        st.session_state._s_eval      = _new_eval
        st.session_state.show_settings = False
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

# Re-read settings after potential save
strategy_ui          = st.session_state.get("_s_strategy", "auto")
num_survey_papers    = st.session_state.get("_s_num_survey", Config.SURVEY_DEFAULT_PAPERS)
num_retrieval_papers = st.session_state.get("_s_topk", 6)
refresh_sources      = st.session_state.get("_s_refresh", True)
run_eval             = st.session_state.get("_s_eval", True)

# ── New Research home screen ──────────────────────────────────────────────────
_EXAMPLE_TOPICS = [
    "finetuning methods for LLMs",
    "quantum computing",
    "transformer architectures in NLP",
]

if not messages and not has_survey and processing is None:
    with st.chat_message("assistant"):
        st.markdown(
            "**Hey! I'm ResearchGPT.**\n\n"
            "Tell me your research topic and I'll:\n\n"
            "1. **Run a literature survey** — compare up to 15 real arXiv papers in a structured table\n"
            "2. **Write a full IEEE paper** — using the best retrieved context and your chosen strategy\n\n"
            "Just type your topic below. For example:"
        )
        for _ptopic in _EXAMPLE_TOPICS:
            st.markdown(f"- *{_ptopic}*")
        st.markdown("Once the paper is ready, keep chatting to refine it.")

# ── Show previous messages (refinements) ─────────────────────────────────────
for i, msg in enumerate(messages):
    with st.chat_message(msg["role"]):
        if msg["content_type"] == "text":
            st.markdown(msg["content"])
        elif msg["content_type"] == "error":
            st.error(msg["content"])
            if active.get("has_survey") and not active.get("has_paper"):
                if st.button("Try Again", key=f"retry_{i}", type="primary"):
                    set_chat("processing", "generating")
                    st.rerun()

# ── Show persisted survey results ────────────────────────────────────────────
if has_survey and active["survey_rows"]:
    st.divider()
    render_survey_section(
        active["survey_rows"],
        active["topic"],
        active["survey_paper_text"],
        active.get("survey_pdf_bytes"),
    )

# ── Show persisted RAG paper ──────────────────────────────────────────────────
if has_paper and active["result"]:
    st.divider()
    render_paper_tabs(active["result"], uid=str(active["id"]), topic=active.get("topic", ""))

    # 6.1 — Compact refinement chip row
    if processing is None:
        st.markdown('<span style="font-size:11px;color:#8b949e;letter-spacing:0.04em">QUICK EDITS</span>', unsafe_allow_html=True)
        _chip_items = list(_REFINEMENT_CHIPS.items())
        _chip_cols = st.columns(len(_chip_items))
        for _col, (_label, _instruction) in zip(_chip_cols, _chip_items):
            with _col:
                if st.button(_label, key=f"chip_{_label}_{active['id']}", use_container_width=True):
                    active["messages"].append({"role": "user", "content_type": "text", "content": _label})
                    set_chat("pending_input", _instruction)
                    set_chat("processing", "refining")
                    st.rerun()

# ── Processing: Keyword review — auto-apply silently ─────────────────────────
if processing == "keyword_review":
    set_chat("search_keywords", _expand_keywords(active["topic"]) or active["topic"])
    set_chat("processing", "surveying")
    st.rerun()


# ── Processing: Step 1 — Literature Survey ────────────────────────────────────
if processing == "surveying":
    st.divider()
    prog = st.progress(0)
    stat = st.empty()

    def _cb(cur, tot, msg):
        prog.progress(cur / max(tot, 1))
        stat.text(msg)

    _search_q = (active.get("search_keywords") or active["topic"]).strip()
    rows = analyze_topic(
        _search_q,
        max_papers=int(num_survey_papers),
        progress_callback=_cb,
    )
    prog.empty()
    stat.empty()

    set_chat("has_survey", True)  # mark survey as attempted regardless of outcome
    if rows:
        with st.spinner("Generating survey-based sample paper…"):
            survey_paper = generate_sample_paper(active["topic"], rows)
        set_chat("survey_rows", rows)
        set_chat("survey_paper_text", survey_paper)

        if survey_paper:
            with st.spinner("Building combined IEEE PDF…"):
                try:
                    pdf_bytes = generate_survey_combined_pdf(rows, survey_paper, active["topic"])
                    set_chat("survey_pdf_bytes", pdf_bytes)
                except Exception:
                    set_chat("survey_pdf_bytes", None)
    else:
        st.warning("No papers found for the survey — continuing to paper generation.")

    set_chat("processing", "generating")
    st.rerun()

# ── Processing: Step 2 — RAG Paper Generation ─────────────────────────────────
if processing == "generating":
    st.divider()
    chosen_strategy = (
        auto_select_strategy(active["topic"])
        if strategy_ui == "auto"
        else strategy_ui
    )
    _aname  = st.session_state.get("author_name", "").strip()
    _aaffil = st.session_state.get("author_affil", "").strip()
    _aemail = st.session_state.get("author_email", "").strip()
    _user_prefs = "\n".join(filter(None, [
        f"Author name: {_aname}"   if _aname  else "",
        f"Affiliation: {_aaffil}"  if _aaffil else "",
        f"Email: {_aemail}"        if _aemail else "",
    ]))

    # 2.1 — Live step tracker using st.status
    with st.status("Starting pipeline…", expanded=True) as _gen_status:
        _log_placeholder = st.empty()
        _log_lines: list = []

        _DONE_STEPS = {"fetch_done", "index_done", "retrieve_done",
                       "generate_done", "analysis_start", "postprocess_start",
                       "pdf_start", "done"}

        def _progress_cb(step: str, detail: str) -> None:
            icon = "✅" if step in _DONE_STEPS or step.endswith("_done") else "⏳"
            if step == "done":
                icon = "🎉"
            _log_lines.append(f"{icon} {detail}")
            _log_placeholder.markdown("\n\n".join(_log_lines[-8:]))
            _gen_status.update(label=detail)

        try:
            result = run_rag_for_ui_pipeline(
                topic=active["topic"],
                retrieval_strategy=chosen_strategy,
                include_evaluation=run_eval,
                fast_mode=fast_mode,
                generate_pdf=generate_pdf,
                force_refresh_sources=refresh_sources,
                use_latex_pdf=use_latex_pdf,
                run_plagiarism_check=True,
                apply_ai_rewrite=True,
                target_similarity_pct=25.0,
                max_rewrite_passes=1 if fast_mode else 2,
                fast_5page_mode=fast_5page_mode,
                min_pages=min_pages,
                user_preferences=_user_prefs,
                progress_callback=_progress_cb,
                retrieval_top_k=num_retrieval_papers,
            )
        except Exception as exc:
            result = {
                "paper_text": "", "pdf_path": None, "num_papers": 0,
                "strategy": chosen_strategy, "faithfulness": None, "relevance": None,
                "faithfulness_reasoning": None, "relevance_reasoning": None,
                "retrieved_context": [], "plagiarism_report": None, "rouge_l": None,
                "ai_rewrite_passes": 0, "humanize_applied": False, "timings": {},
                "status": "failed", "error": str(exc),
                "latex_compile_log": None, "tex_path": None,
                "page_estimate": 0.0, "min_pages_target": None,
                "analysis_table": [],
            }

        if result.get("paper_text"):
            _gen_status.update(label="✅ Paper ready!", state="complete", expanded=False)
        else:
            _gen_status.update(label="❌ Generation failed", state="error", expanded=True)

    set_chat("processing", None)
    if result.get("paper_text"):
        set_chat("result", result)
        set_chat("paper_text", result["paper_text"])
        set_chat("context", result.get("retrieved_context", []))
        set_chat("has_paper", True)
        try:
            _history_save_session(
                active["topic"],
                result,
                survey_rows=active.get("survey_rows", []),
                survey_paper_text=active.get("survey_paper_text", ""),
                survey_pdf_bytes=active.get("survey_pdf_bytes"),
            )
            st.session_state._hist_dirty = True
        except Exception:
            pass
    else:
        active["messages"].append({
            "role": "assistant", "content_type": "error",
            "content": result.get("error", "Paper generation failed — please try again."),
        })
    st.rerun()

# ── Processing: Refinement ────────────────────────────────────────────────────
if processing == "refining":
    with st.chat_message("assistant"):
        with st.spinner("Applying your changes…"):
            try:
                raw_context = [
                    {
                        "text": c.get("text", ""),
                        "metadata": {
                            "title": c.get("title", ""),
                            "authors": c.get("authors", ""),
                            "published": c.get("published", ""),
                            "filepath": c.get("filepath", ""),
                        },
                    }
                    for c in active["context"]
                ]
                _enriched_instruction = _resolve_section_instruction(
                    active["pending_input"], active["paper_text"]
                )
                refine_result = refine_paper_with_instruction(
                    topic=active["topic"],
                    paper_text=active["paper_text"],
                    context=raw_context,
                    instruction=_enriched_instruction,
                    generate_pdf=generate_pdf,
                    use_latex_pdf=use_latex_pdf,
                )
            except Exception as _ref_exc:
                refine_result = {"status": "error", "error": str(_ref_exc), "paper_text": ""}

    set_chat("processing", None)
    if refine_result["status"] == "ok":
        new_text = refine_result["paper_text"]
        set_chat("paper_text", new_text)
        prev = active["result"] or {}
        new_pdf = refine_result.get("pdf_path")
        updated_result = {
            **prev,
            "paper_text": new_text,
            "pdf_path": new_pdf if (new_pdf and os.path.exists(new_pdf)) else prev.get("pdf_path"),
            "latex_compile_log": refine_result.get("latex_compile_log") or prev.get("latex_compile_log"),
            "tex_path": refine_result.get("tex_path") or prev.get("tex_path"),
            # Scores are for the old text — clear them so the UI shows — instead of misleading values
            "faithfulness": None,
            "relevance": None,
            "faithfulness_reasoning": None,
            "relevance_reasoning": None,
            "evaluation_error": None,
        }
        if generate_pdf and not (new_pdf and os.path.exists(new_pdf)):
            st.warning("PDF could not be regenerated — check the Compile tab. Text is updated.")
        set_chat("result", updated_result)
        # Clear cached DOCX so it regenerates with the updated paper text
        st.session_state.pop(f"_docx_bytes_{active['id']}", None)
        st.toast("Paper updated!", icon="✅")
    else:
        active["messages"].append({
            "role": "assistant", "content_type": "text",
            "content": f"Refinement failed: {refine_result['error']}",
        })
    set_chat("pending_input", "")
    st.rerun()


# ── Chat input ────────────────────────────────────────────────────────────────
if not has_survey:
    _placeholder = "Enter your research topic…"
elif not has_paper:
    _placeholder = "Paper generation pending — or type a new topic to start fresh…"
else:
    _placeholder = "Ask for changes (e.g. 'make the intro longer', 'add a section on RLHF')…"

_is_processing = processing is not None
if _is_processing:
    _labels = {
        "surveying":  "Running literature survey…",
        "generating": "Generating paper…",
        "refining":   "Applying changes…",
    }
    st.info(_labels.get(processing, "Processing…"), icon="⏳")

user_msg = st.chat_input(_placeholder, disabled=_is_processing)

if user_msg and user_msg.strip() and processing is None:
    user_msg = user_msg.strip()

    if not is_meaningful(user_msg):
        pass
    else:
        # Once a paper or survey exists, never treat the message as a new topic —
        # the user must click "+ New Chat" to start fresh.
        detected_topic = extract_topic(user_msg) if (not has_survey and not has_paper) else None

        if detected_topic:
            # Starting fresh — wipe messages so old topic's chat doesn't bleed through
            set_chat("messages", [])

        active["messages"].append(
            {"role": "user", "content_type": "text", "content": user_msg}
        )

        if detected_topic:
            set_chat("topic", detected_topic)
            set_chat("title", detected_topic.title()[:40])
            set_chat("has_survey", False)
            set_chat("has_paper", False)
            set_chat("survey_rows", [])
            set_chat("survey_paper_text", "")
            set_chat("survey_pdf_bytes", None)
            set_chat("result", None)
            set_chat("search_keywords", "")
            set_chat("processing", "keyword_review")
        elif has_paper:
            # 6.2 — enrich with section context if the message references a section
            _enriched = _resolve_section_instruction(user_msg, active.get("paper_text", ""))
            set_chat("pending_input", _enriched)
            set_chat("processing", "refining")
        else:
            active["messages"].append({
                "role": "assistant", "content_type": "text",
                "content": (
                    "I'm not sure what topic to research. Try something like:\n\n"
                    "*finetuning methods for LLMs*\n\n"
                    "or *transformer architectures in NLP*."
                ),
            })

        st.rerun()
