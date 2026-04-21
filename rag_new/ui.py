import base64
import html
import os
import re
import streamlit as st
import io
import pandas as pd


from config.config import Config
from src.pipeline.ui_pipeline import run_rag_for_ui_pipeline, refine_paper_with_instruction
from src.analysis.paper_analyzer import analyze_topic, generate_sample_paper

st.set_page_config(page_title="ResearchGPT", page_icon="📄", layout="wide")


# ── Helpers ───────────────────────────────────────────────────────────────────
def clamp_score(score, min_val=0.0, max_val=5.0):
    if score is None:
        return None
    try:
        return max(min_val, min(max_val, float(score)))
    except (TypeError, ValueError):
        return None


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
    .stApp {{
        {bg_css}
        color: #e6edf3;
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
    section[data-testid="stSidebar"] {{
        background: rgba(8,11,22,0.97) !important;
        border-right: 1px solid rgba(255,255,255,0.06);
    }}
    .stButton>button, .stDownloadButton>button {{
        background: #238636;
        color: #fff;
        border-radius: 8px;
        border: none;
        font-weight: 600;
    }}
    .stButton>button:hover {{ background: #2ea043; }}
    div[data-testid="stSidebar"] .stButton>button {{
        background: transparent !important;
        color: #8b949e !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
        font-weight: 400 !important;
        text-align: left !important;
        justify-content: flex-start !important;
        font-size: 13px !important;
        padding: 6px 10px !important;
    }}
    div[data-testid="stSidebar"] .stButton>button:hover {{
        background: rgba(255,255,255,0.07) !important;
        color: #e6edf3 !important;
    }}
    div[data-testid="stSidebar"] .stButton>button[kind="primary"] {{
        background: rgba(88,166,255,0.15) !important;
        border-color: rgba(88,166,255,0.4) !important;
        color: #58a6ff !important;
        font-weight: 600 !important;
    }}
    div[data-testid="stSidebar"] div:first-child .stButton>button {{
        background: #238636 !important;
        color: #fff !important;
        border: none !important;
        font-weight: 600 !important;
        font-size: 14px !important;
    }}
    h1,h2,h3,label,span,p,li {{ color: #e6edf3 !important; }}
    .stCaption {{ color: #8b949e !important; }}
    .stTabs [data-baseweb="tab"] {{ color: #8b949e; font-size: 13px; }}
    .stTabs [aria-selected="true"] {{ color: #58a6ff !important; border-bottom-color: #58a6ff !important; }}
    .stTextInput input, .stSelectbox > div > div {{
        background: rgba(255,255,255,0.05) !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        color: #e6edf3 !important;
        border-radius: 8px !important;
    }}
    [data-testid="stChatInput"] textarea {{
        background: rgba(22,27,34,0.95) !important;
        color: #e6edf3 !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 12px !important;
        font-size: 15px !important;
    }}
    hr {{ border-color: rgba(255,255,255,0.07) !important; }}
    .survey-table-wrapper {{
        overflow-x: auto;
        border-radius: 10px;
        border: 1px solid rgba(255,255,255,0.09);
        margin-bottom: 24px;
    }}
    .survey-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
        font-family: 'Segoe UI', sans-serif;
    }}
    .survey-table th {{
        background: rgba(88,166,255,0.15);
        color: #58a6ff;
        padding: 10px 14px;
        text-align: left;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        border-bottom: 1px solid rgba(255,255,255,0.1);
        white-space: nowrap;
    }}
    .survey-table td {{
        padding: 10px 14px;
        color: #e6edf3;
        border-bottom: 1px solid rgba(255,255,255,0.05);
        vertical-align: top;
        min-width: 180px;
        max-width: 280px;
        line-height: 1.5;
    }}
    .survey-table tr:nth-child(even) td {{
        background: rgba(255,255,255,0.02);
    }}
    .survey-table tr:hover td {{
        background: rgba(88,166,255,0.06);
    }}
    .paper-no {{
        background: rgba(88,166,255,0.2);
        color: #58a6ff;
        font-weight: 700;
        text-align: center;
        min-width: 40px !important;
    }}
    .paper-title {{
        font-weight: 600;
        color: #e6edf3;
        min-width: 200px !important;
        max-width: 260px !important;
    }}
    .step-badge {{
        display: inline-block;
        background: rgba(88,166,255,0.15);
        color: #58a6ff;
        border: 1px solid rgba(88,166,255,0.3);
        border-radius: 20px;
        padding: 3px 14px;
        font-size: 12px;
        font-weight: 600;
        letter-spacing: 0.04em;
        margin-bottom: 8px;
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
        "processing": None,
        "pending_input": "",
    }


def _init():
    if "chats" not in st.session_state:
        st.session_state.chats = [_make_chat(0)]
    if "active_chat" not in st.session_state:
        st.session_state.active_chat = 0
    if "_next_chat_id" not in st.session_state:
        st.session_state._next_chat_id = 1


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
if not (os.environ.get("CEREBRAS_API_KEY") or os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_API_KEY")):
    st.error(
        "**API key not found.**\n\n"
        "Open `rag_new/.env` and set `CEREBRAS_API_KEY=your_key_here`, "
        "then restart the app. Get a free key at https://cloud.cerebras.ai"
    )
    st.stop()


# ── Survey table renderer ─────────────────────────────────────────────────────
def render_survey_section(rows: list, done_topic: str, survey_paper_text: str):
    st.markdown('<span class="step-badge">STEP 1 — LITERATURE SURVEY</span>', unsafe_allow_html=True)
    st.success(f"Analysed **{len(rows)}** papers on: *{done_topic}*")

    columns = [
        ("No.",                                                    "paper-no"),
        ("Title",                                                  "paper-title"),
        ("Authors",                                                ""),
        ("Journal Details\n(DOI / Year / Citation)",               ""),
        ("Problem Statement",                                      ""),
        ("Objective",                                              ""),
        ("Research Gap",                                           ""),
        ("Methodology\n(Algorithm / Techniques)",                  ""),
        ("Features\n(Focused)",                                    ""),
        ("Results & Discussion\n(Performance Metric / Value)",     ""),
        ("Limitations",                                            ""),
        ("Future Scope",                                           ""),
    ]
    col_keys = [
        "No.", "Title", "Authors",
        "Journal Details (DOI / Year / Citation)",
        "Problem Statement", "Objective", "Research Gap",
        "Methodology (Algorithm / Techniques)", "Features (Focused)",
        "Results & Discussion (Performance Metric / Value)",
        "Limitations", "Future Scope",
    ]

    header_html = "".join(
        f"<th>{label.replace(chr(10), '<br/>')}</th>" for label, _ in columns
    )
    rows_html = ""
    for row in rows:
        cells = ""
        for key, css in zip(col_keys, [c[1] for c in columns]):
            val = html.escape(str(row.get(key, "")))
            cells += f"<td class='{css}'>{val}</td>"
        rows_html += f"<tr>{cells}</tr>"

    st.markdown(
        f'<div class="survey-table-wrapper"><table class="survey-table">'
        f'<thead><tr>{header_html}</tr></thead>'
        f'<tbody>{rows_html}</tbody></table></div>',
        unsafe_allow_html=True,
    )

    df = pd.DataFrame(rows)
    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button(
            "Download CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name=f"survey_{done_topic[:30].replace(' ', '_')}.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with dl2:
        try:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as w:
                df.to_excel(w, index=False, sheet_name="Literature Survey")
            st.download_button(
                "Download Excel",
                data=buf.getvalue(),
                file_name=f"survey_{done_topic[:30].replace(' ', '_')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        except ImportError:
            st.caption("Run `pip install openpyxl` for Excel export.")

    if survey_paper_text:
        with st.expander("Survey-based Sample Paper (4–5 pages)", expanded=False):
            st.markdown(
                f'<div class="paper-box">{html.escape(survey_paper_text)}</div>',
                unsafe_allow_html=True,
            )
            st.download_button(
                "Download Survey Paper as TXT",
                data=survey_paper_text.encode("utf-8"),
                file_name=f"survey_paper_{done_topic[:30].replace(' ', '_')}.txt",
                mime="text/plain",
                use_container_width=True,
            )


# ── RAG paper tabs renderer ───────────────────────────────────────────────────
def render_paper_tabs(result: dict, uid: str):
    st.markdown('<span class="step-badge">STEP 2 — GENERATED PAPER</span>', unsafe_allow_html=True)
    paper_text = result.get("paper_text", "")
    n = result.get("num_papers", 0)
    strat = result.get("strategy", "N/A")
    pages = result.get("page_estimate", 0)
    st.caption(f"Based on **{n}** arXiv paper(s) · strategy: `{strat}` · ~{pages:.1f} pages")

    t_paper, t_quality, t_sources, t_compile = st.tabs(["Paper", "Quality", "Sources", "Compile"])

    with t_paper:
        if paper_text:
            st.markdown(
                f'<div class="paper-box">{html.escape(paper_text)}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.warning("No paper text was generated.")

        st.write("")
        pdf_path = result.get("pdf_path")
        if pdf_path and os.path.exists(pdf_path):
            with open(pdf_path, "rb") as f:
                st.download_button(
                    "Download IEEE PDF",
                    data=f.read(),
                    file_name=os.path.basename(pdf_path),
                    mime="application/pdf",
                    key=f"dl_{uid}",
                )
        else:
            st.caption("PDF not available.")

    with t_quality:
        c1, c2, c3, c4 = st.columns(4)
        faith = clamp_score(result.get("faithfulness"))
        rel = clamp_score(result.get("relevance"))
        with c1:
            st.metric("Faithfulness", f"{faith:.2f}/5" if faith is not None else "—")
            if faith is not None:
                st.progress(faith / 5)
        with c2:
            st.metric("Relevance", f"{rel:.2f}/5" if rel is not None else "—")
            if rel is not None:
                st.progress(rel / 5)
        with c3:
            st.metric("Sources", n)
        with c4:
            st.metric("Strategy", strat)
        timings = result.get("timings", {})
        if timings:
            st.caption(
                f"index {timings.get('index_seconds',0)}s · "
                f"retrieval {timings.get('retrieval_seconds',0)}s · "
                f"generation {timings.get('generation_seconds',0)}s · "
                f"total {timings.get('total_seconds',0)}s"
            )
        with st.expander("Evaluation reasoning"):
            if result.get("faithfulness_reasoning"):
                st.markdown("**Faithfulness**")
                st.code(result["faithfulness_reasoning"])
            if result.get("relevance_reasoning"):
                st.markdown("**Relevance**")
                st.code(result["relevance_reasoning"])

    with t_sources:
        chunks = result.get("retrieved_context", [])
        if not chunks:
            st.info("No retrieved chunks available.")
        else:
            for i, chunk in enumerate(chunks[:8], 1):
                title = chunk.get("title") or "Unknown"
                score = chunk.get("rerank_score") or chunk.get("score")
                text = re.sub(r"\s+", " ", chunk.get("text", "")).strip()
                st.markdown(f"**[{i}] {title}**")
                st.caption(f"score: {score}")
                st.write(text[:600] + ("…" if len(text) > 600 else ""))
                if i < len(chunks[:8]):
                    st.divider()
        with st.expander("Plagiarism report"):
            pr = result.get("plagiarism_report")
            if not pr:
                st.info("Not available.")
            else:
                pc1, pc2, pc3 = st.columns(3)
                pc1.metric("Avg Similarity", f"{pr.get('overall_similarity_pct',0)}%")
                pc2.metric("Max Sentence Sim", f"{pr.get('max_sentence_similarity_pct',0)}%")
                pc3.metric("8-gram Overlap", f"{pr.get('ngram_overlap_pct',0)}%")

    with t_compile:
        st.caption(f"TeX: {result.get('tex_path') or 'not generated'}")
        if result.get("latex_compile_log"):
            st.code(result["latex_compile_log"])
        else:
            st.info("No compile log.")


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("ResearchGPT")
    st.caption("Literature survey + IEEE paper generator")
    st.divider()

    if st.button("+ New Chat", use_container_width=True):
        new_chat()
        st.rerun()

    st.divider()

    if st.session_state.chats:
        st.caption("RECENT CHATS")
        for i in range(len(st.session_state.chats) - 1, -1, -1):
            c = st.session_state.chats[i]
            is_active = (i == st.session_state.active_chat)
            raw_title = c["title"]
            label = ("▶  " if is_active else "    ") + (raw_title[:30] + "…" if len(raw_title) > 30 else raw_title)
            btn_type = "primary" if is_active else "secondary"
            if st.button(label, key=f"chat_btn_{c['id']}", use_container_width=True, type=btn_type):
                if not is_active:
                    st.session_state.active_chat = i
                    st.rerun()

    st.divider()

    with st.expander("⚙️ Generation settings", expanded=False):
        strategy_ui = st.selectbox("Retrieval Strategy", ["auto", "hyde", "complex", "standard"], index=0)
        num_survey_papers = st.number_input("Survey papers", min_value=3, max_value=15, value=10)
        fast_mode = st.checkbox("Fast mode", value=True)
        refresh_sources = st.checkbox("Refresh papers from arXiv", value=False)
        generate_pdf = st.checkbox("Generate PDF output", value=True)
        use_latex_pdf = st.checkbox("Use LaTeX IEEE PDF engine", value=True)
        run_eval = st.checkbox("Run quality evaluation", value=False)
        fast_5page_mode = st.checkbox("Fast-5Page Mode", value=True)
        min_pages = st.slider("Minimum pages", min_value=2, max_value=15, value=13)

    st.divider()
    st.caption("Powered by Cerebras LLM + arXiv RAG")


# ── Main page ─────────────────────────────────────────────────────────────────
active = chat()
messages = active["messages"]
has_paper = active["has_paper"]
has_survey = active["has_survey"]
processing = active["processing"]

# ── Welcome screen ────────────────────────────────────────────────────────────
if not messages and not has_survey and processing is None:
    with st.chat_message("assistant"):
        st.markdown(
            "**Hey! I'm ResearchGPT.**\n\n"
            "Tell me your research topic and I'll:\n\n"
            "1. **Run a literature survey** — compare up to 15 real arXiv papers in a structured table\n"
            "2. **Write a full IEEE paper** — using the best retrieved context and your chosen strategy\n\n"
            "Just type your topic below. For example:\n\n"
            "- *finetuning methods for LLMs*\n"
            "- *quantum computing and its applications*\n"
            "- *transformer architectures in NLP*\n\n"
            "Once the paper is ready, keep chatting to refine it."
        )

# ── Show previous messages (refinements) ─────────────────────────────────────
for i, msg in enumerate(messages):
    with st.chat_message(msg["role"]):
        if msg["content_type"] == "text":
            st.markdown(msg["content"])
        elif msg["content_type"] == "error":
            st.error(msg["content"])

# ── Show persisted survey results ────────────────────────────────────────────
if has_survey and active["survey_rows"]:
    st.divider()
    render_survey_section(
        active["survey_rows"],
        active["topic"],
        active["survey_paper_text"],
    )

# ── Show persisted RAG paper ──────────────────────────────────────────────────
if has_paper and active["result"]:
    st.divider()
    render_paper_tabs(active["result"], uid=str(active["id"]))

# ── Processing: Step 1 — Literature Survey ────────────────────────────────────
if processing == "surveying":
    st.divider()
    st.markdown('<span class="step-badge">STEP 1 — LITERATURE SURVEY</span>', unsafe_allow_html=True)
    prog = st.progress(0)
    stat = st.empty()

    def _cb(cur, tot, msg):
        prog.progress(cur / max(tot, 1))
        stat.text(msg)

    rows = analyze_topic(
        active["topic"],
        max_papers=int(num_survey_papers),
        progress_callback=_cb,
    )
    prog.empty()
    stat.empty()

    if rows:
        with st.spinner("Generating survey-based sample paper…"):
            survey_paper = generate_sample_paper(active["topic"], rows)
        set_chat("survey_rows", rows)
        set_chat("survey_paper_text", survey_paper)
        set_chat("has_survey", True)
    else:
        st.warning("No papers found for the survey — continuing to paper generation.")

    set_chat("processing", "generating")
    st.rerun()

# ── Processing: Step 2 — RAG Paper Generation ─────────────────────────────────
if processing == "generating":
    st.divider()
    st.markdown('<span class="step-badge">STEP 2 — GENERATING PAPER</span>', unsafe_allow_html=True)
    with st.spinner(f"Searching arXiv for **{active['topic']}**, building context, and writing your paper…"):
        chosen_strategy = (
            auto_select_strategy(active["topic"])
            if strategy_ui == "auto"
            else strategy_ui
        )
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
                user_preferences="",
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
            }

    set_chat("processing", None)
    if result.get("paper_text"):
        set_chat("result", result)
        set_chat("paper_text", result["paper_text"])
        set_chat("context", result.get("retrieved_context", []))
        set_chat("has_paper", True)
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
            refine_result = refine_paper_with_instruction(
                topic=active["topic"],
                paper_text=active["paper_text"],
                context=raw_context,
                instruction=active["pending_input"],
                generate_pdf=generate_pdf,
                use_latex_pdf=use_latex_pdf,
            )

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
        }
        if generate_pdf and not (new_pdf and os.path.exists(new_pdf)):
            st.warning("PDF could not be regenerated — check the Compile tab. Text is updated.")
        set_chat("result", updated_result)
        active["messages"].append({
            "role": "assistant", "content_type": "text",
            "content": "Paper updated. Scroll up to see the revised version.",
        })
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
user_msg = st.chat_input(_placeholder)

if user_msg and user_msg.strip() and processing is None:
    user_msg = user_msg.strip()

    if not is_meaningful(user_msg):
        pass
    else:
        detected_topic = extract_topic(user_msg) if not has_survey else None

        active["messages"].append(
            {"role": "user", "content_type": "text", "content": user_msg}
        )

        if detected_topic:
            set_chat("topic", detected_topic)
            set_chat("title", detected_topic.title()[:40])
            # Reset any previous results for this chat slot
            set_chat("has_survey", False)
            set_chat("has_paper", False)
            set_chat("survey_rows", [])
            set_chat("survey_paper_text", "")
            set_chat("result", None)
            set_chat("processing", "surveying")
        elif has_paper:
            set_chat("pending_input", user_msg)
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
