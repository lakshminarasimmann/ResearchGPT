"""FastAPI backend for the React frontend.

Wraps the existing pipeline modules (src/pipeline, src/history, src/output_pdf)
as HTTP endpoints. Business logic stays in those modules — this file is
routing + job orchestration only.
"""
import os
import sys
import uuid

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import re

from config.config import Config
from src.pipeline.ui_pipeline import run_rag_for_ui_pipeline, refine_paper_with_instruction
from src.output_pdf.docx_generator import generate_paper_docx, generate_survey_docx
from src.output_pdf.survey_pdf_generator import generate_survey_combined_pdf
from src.history.paper_history import save_result, list_history, load_result, delete_result
from src.generation.generator import RAGGenerator
from src.analysis.paper_analyzer import analyze_topic, generate_sample_paper

from api import jobs
from api.schemas import (
    GenerateRequest,
    RefineRequest,
    SaveHistoryRequest,
    DocxRequest,
    PdfRequest,
    FixCitationsRequest,
    AnalysisXlsxRequest,
    SurveyRequest,
    SurveyExportRequest,
)


def _auto_select_strategy(query: str) -> str:
    """Mirrors ui.py's auto_select_strategy()."""
    q = query.lower()
    if any(k in q for k in ["compare", "versus", "vs", "tradeoff", "benchmark"]) or len(query.split()) > 16:
        return "complex"
    return "hyde"


_STOP_WORDS = {
    "the", "and", "for", "with", "that", "this", "it", "by", "from", "at", "as", "be",
    "been", "have", "has", "not", "which", "they", "their", "its", "but", "than", "then",
    "also", "each", "all", "such", "these", "those", "more",
}


def _expand_keywords(topic: str) -> str:
    """Mirrors ui.py's _expand_keywords() — breaks a topic into search keywords."""
    words = re.findall(r"\b[a-zA-Z]{3,}\b", topic)
    seen: dict = {}
    for w in words:
        lw = w.lower()
        if lw not in _STOP_WORDS and lw not in seen:
            seen[lw] = w
    return ", ".join(seen.values())


def _run_survey_pipeline(topic: str, max_papers: int, progress_callback=None) -> dict:
    def _cb(cur, tot, msg):
        if progress_callback:
            progress_callback(f"{cur}/{tot}", msg)

    search_query = _expand_keywords(topic) or topic
    rows = analyze_topic(search_query, max_papers=max_papers, progress_callback=_cb)
    if not rows:
        return {"rows": [], "survey_paper_text": "", "pdf_path": None, "status": "no_papers"}

    survey_paper_text = generate_sample_paper(topic, rows)
    pdf_path = None
    if survey_paper_text:
        try:
            pdf_bytes = generate_survey_combined_pdf(rows, survey_paper_text, topic)
            safe_topic = re.sub(r"\s+", "_", topic[:30].strip())
            fname = f"survey_{safe_topic}_{uuid.uuid4().hex[:8]}.pdf"
            pdf_path = os.path.join(Config.OUTPUT_DIR, fname)
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)
        except Exception:
            pdf_path = None

    return {"rows": rows, "survey_paper_text": survey_paper_text, "pdf_path": pdf_path, "status": "ok"}

app = FastAPI(title="ResearchGPT API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/generate")
def start_generate(req: GenerateRequest):
    strategy = _auto_select_strategy(req.topic) if req.strategy == "auto" else req.strategy
    user_preferences = "\n".join(
        filter(
            None,
            [
                f"Author name: {req.author_name.strip()}" if req.author_name.strip() else "",
                f"Affiliation: {req.author_affiliation.strip()}" if req.author_affiliation.strip() else "",
                f"Email: {req.author_email.strip()}" if req.author_email.strip() else "",
            ],
        )
    )
    job_id = jobs.create_job(
        run_rag_for_ui_pipeline,
        {
            "topic": req.topic,
            "retrieval_strategy": strategy,
            "include_evaluation": req.include_evaluation,
            "fast_mode": req.fast_mode,
            "force_refresh_sources": req.force_refresh_sources,
            "run_plagiarism_check": req.run_plagiarism_check,
            "apply_ai_rewrite": req.apply_ai_rewrite,
            "apply_humanize": req.apply_humanize,
            "target_similarity_pct": req.target_similarity_pct,
            "max_rewrite_passes": req.max_rewrite_passes,
            "fast_5page_mode": req.fast_5page_mode,
            "min_pages": req.min_pages,
            "user_preferences": user_preferences,
            "retrieval_top_k": req.retrieval_top_k,
        },
    )
    return {"job_id": job_id}


@app.post("/api/survey")
def start_survey(req: SurveyRequest):
    job_id = jobs.create_job(_run_survey_pipeline, {"topic": req.topic, "max_papers": req.max_papers})
    return {"job_id": job_id}


@app.post("/api/export/survey-docx")
def export_survey_docx(req: SurveyExportRequest):
    safe_topic = req.topic[:30].strip().replace(" ", "_")
    filename = f"survey_{safe_topic}.docx"
    path = generate_survey_docx(req.rows, topic=req.topic, output_dir=Config.OUTPUT_DIR, filename=filename)
    if not path or not os.path.exists(path):
        raise HTTPException(500, "Survey DOCX generation failed")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=os.path.basename(path),
    )


@app.post("/api/export/survey-xlsx")
def export_survey_xlsx(req: SurveyExportRequest):
    import io
    import pandas as pd
    from fastapi.responses import StreamingResponse

    df = pd.DataFrame(req.rows)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Literature Survey")
    buf.seek(0)
    safe_topic = req.topic[:30].strip().replace(" ", "_")
    filename = f"survey_{safe_topic}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/refine")
def start_refine(req: RefineRequest):
    def _target(progress_callback=None):
        return refine_paper_with_instruction(
            topic=req.topic,
            paper_text=req.paper_text,
            context=req.context,
            instruction=req.instruction,
        )

    job_id = jobs.create_job(_target, {})
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str):
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


@app.get("/api/history")
def get_history(max_entries: int = 10):
    return list_history(max_entries=max_entries)


@app.get("/api/history/{fname}")
def get_history_item(fname: str):
    entry = load_result(fname)
    if entry is None:
        raise HTTPException(404, "History entry not found")
    return entry


@app.delete("/api/history/{fname}")
def remove_history_item(fname: str):
    ok = delete_result(fname)
    if not ok:
        raise HTTPException(404, "History entry not found")
    return {"deleted": True}


@app.post("/api/history/save")
def post_save_history(req: SaveHistoryRequest):
    save_result(req.topic, req.result)
    return {"saved": True}


@app.post("/api/export/docx")
def export_docx(req: DocxRequest):
    filename = f"paper_{uuid.uuid4().hex[:8]}.docx"
    path = generate_paper_docx(req.paper_text, req.title, Config.OUTPUT_DIR, filename)
    if not path or not os.path.exists(path):
        raise HTTPException(500, "DOCX generation failed")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
    )


@app.post("/api/export/pdf")
def export_pdf(req: PdfRequest):
    rag = RAGGenerator()
    if req.use_latex:
        result = rag.generate_latex_pdf_from_paper_text(req.topic, req.paper_text, [])
        path = result.get("pdf_path")
    else:
        path = rag.generate_pdf(req.topic, req.paper_text)
    if not path or not os.path.exists(path):
        raise HTTPException(500, "PDF generation failed")
    return FileResponse(path, media_type="application/pdf", filename=os.path.basename(path))


@app.post("/api/fix-citations")
def fix_citations(req: FixCitationsRequest):
    fixed = RAGGenerator.fix_citations_from_metadata(req.paper_text, req.context)
    return {"paper_text": fixed}


@app.post("/api/export/analysis-xlsx")
def export_analysis_xlsx(req: AnalysisXlsxRequest):
    import io
    import pandas as pd
    from fastapi.responses import StreamingResponse

    df = pd.DataFrame(req.rows)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Analysis Table")
    buf.seek(0)
    filename = f"analysis_{req.topic[:40].strip().replace(' ', '_') or 'paper'}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/download")
def download_file(path: str):
    """Serve a previously generated file (PDF, DOCX) by its absolute path.

    Restricted to files under Config.OUTPUT_DIR / Config.DATA_DIR to avoid
    exposing arbitrary filesystem paths.
    """
    real = os.path.realpath(path)
    allowed_roots = [os.path.realpath(Config.OUTPUT_DIR), os.path.realpath(Config.DATA_DIR)]
    if not any(real.startswith(root) for root in allowed_roots):
        raise HTTPException(403, "Path not allowed")
    if not os.path.exists(real):
        raise HTTPException(404, "File not found")
    return FileResponse(real, filename=os.path.basename(real))
