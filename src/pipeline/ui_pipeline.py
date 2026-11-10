import glob
import hashlib
import logging
import os
import re
import time

from config.config import Config
from src.ingestion.ingestor import ArxivIngestor, METADATA_FILENAME
from src.processing.processor import PDFProcessor, Chunker
from src.embedding.vector_store import VectorEngine
from src.retrieval.retriever import HybridRetriever
from src.generation.generator import RAGGenerator
from src.evaluation.evaluator import Evaluator
from src.generation.generator import LLMClient
from src.history.archive import archive_paper

logger = logging.getLogger(__name__)

# ── Process-level result cache ────────────────────────────────────────────────
# Survives page refreshes; cleared when the server restarts.
_pipeline_cache: dict = {}
_CACHE_TTL = 3600  # seconds


def _cache_key(topic: str, strategy: str, fast_mode: bool) -> str:
    raw = f"{topic.lower().strip()}|{strategy}|{fast_mode}"
    return hashlib.md5(raw.encode()).hexdigest()


def _get_cached(key: str) -> dict | None:
    entry = _pipeline_cache.get(key)
    if entry and (time.time() - entry["_cached_at"]) < _CACHE_TTL:
        return entry
    return None


def _store_cached(key: str, result: dict) -> None:
    _pipeline_cache[key] = {**result, "_cached_at": time.time()}


def _slugify_topic(topic: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", topic.strip().lower()).strip("_")
    return slug[:60] or "default_topic"   # cap length to prevent collection name collisions


def run_rag_for_ui_pipeline(
    topic: str,
    retrieval_strategy: str,
    include_evaluation: bool = False,
    fast_mode: bool = True,
    generate_pdf: bool = False,
    force_refresh_sources: bool = False,
    use_latex_pdf: bool = False,
    run_plagiarism_check: bool = False,
    apply_ai_rewrite: bool = False,
    apply_humanize: bool = True,
    target_similarity_pct: float = None,
    max_rewrite_passes: int = None,
    fast_5page_mode: bool = False,
    min_pages: int = 5,
    user_preferences: str = "",
    progress_callback=None,
    retrieval_top_k: int = None,
) -> dict:
    """
    UI-safe RAG pipeline.  Returns structured output; never calls print() or input().
    """
    start_time = time.perf_counter()
    started_at = time.time()
    timings: dict = {}

    if target_similarity_pct is None:
        target_similarity_pct = Config.TARGET_SIMILARITY_PCT
    if max_rewrite_passes is None:
        max_rewrite_passes = Config.MAX_REWRITE_PASSES

    # ── Cache check ───────────────────────────────────────────────────────────
    ck = _cache_key(topic, retrieval_strategy, fast_mode)
    if not force_refresh_sources and not include_evaluation:
        cached = _get_cached(ck)
        if cached:
            logger.info("Cache hit for topic '%s' strategy '%s'.", topic, retrieval_strategy)
            return {k: v for k, v in cached.items() if k != "_cached_at"}

    def _cb(step: str, detail: str = "") -> None:
        if progress_callback:
            try:
                progress_callback(step, detail)
            except Exception:
                pass

    topic_slug = _slugify_topic(topic)
    topic_papers_dir = os.path.join(Config.PAPERS_DIR, topic_slug)
    # Append a short hash of the raw topic so near-identical slugs never share a collection
    _topic_hash = hashlib.md5(topic.lower().strip().encode()).hexdigest()[:6]
    collection_name = f"{Config.COLLECTION_NAME}_{topic_slug}_{_topic_hash}"

    def _error_result(message: str, status: str, paper_count: int = 0) -> dict:
        timings["total_seconds"] = round(time.perf_counter() - start_time, 2)
        return {
            "paper_text": "",
            "pdf_path": None,
            "num_papers": paper_count,
            "strategy": retrieval_strategy,
            "faithfulness": None,
            "relevance": None,
            "faithfulness_reasoning": None,
            "relevance_reasoning": None,
            "retrieved_context": [],
            "plagiarism_report": None,
            "rouge_l": None,
            "ai_rewrite_passes": 0,
            "humanize_applied": False,
            "timings": timings,
            "status": status,
            "error": message,
            "latex_compile_log": None,
            "tex_path": None,
            "page_estimate": 0.0,
            "min_pages_target": min_pages,
            "analysis_table": [],
        }

    # ------------------------------------------------------------------ 1. Index
    processor = PDFProcessor()
    chunker = Chunker()

    # Safely initialise — stale ChromaDB state can raise on count()
    try:
        ve = VectorEngine(collection_name=collection_name)
        current_count = ve.count()
    except Exception as e:
        logger.warning("ChromaDB collection error (%s) — recreating collection.", e)
        try:
            import chromadb as _chromadb
            _client = _chromadb.PersistentClient(path=Config.DB_DIR)
            _client.delete_collection(collection_name)
        except Exception:
            pass
        ve = VectorEngine(collection_name=collection_name)
        current_count = 0

    # Only wipe + re-download when explicitly requested AND the topic folder is new or user forced it.
    # Avoids nuking a full index on every run when refresh_sources is left checked by default.
    existing_pdfs = glob.glob(os.path.join(topic_papers_dir, "*.pdf")) + \
                    glob.glob(os.path.join(topic_papers_dir, "*.txt"))
    needs_reindex = current_count == 0 or (force_refresh_sources and not existing_pdfs) or \
                    (force_refresh_sources and current_count == 0)
    needs_download = force_refresh_sources or not existing_pdfs

    if needs_download:
        _cb("fetch_start", f"Searching arXiv for **{topic}**…")
        ingestor = ArxivIngestor(
            max_results=5 if fast_mode else 8,
            download_dir=topic_papers_dir,
        )
        # Only clear existing PDFs when user explicitly requests a fresh pull
        downloaded = ingestor.search_and_download(topic, clear_existing=force_refresh_sources)
        logger.info("Downloaded/found %d papers for topic '%s'.", len(downloaded), topic)
        _cb("fetch_done", f"Fetched {len(downloaded)} paper(s) from arXiv")

    pdf_files = glob.glob(os.path.join(topic_papers_dir, "*.pdf")) + \
                glob.glob(os.path.join(topic_papers_dir, "*.txt"))

    if needs_reindex or needs_download:
        # Build a set of paper IDs already in the vector store for incremental indexing
        existing_chunk_ids: set = set()
        if ve.count() > 0 and not force_refresh_sources:
            all_existing = ve.get_all_chunks()
            existing_chunk_ids = {c["metadata"].get("filepath", "") for c in all_existing}
        elif force_refresh_sources and current_count == 0:
            ve.reset_collection()

        # Load rich metadata (authors, published dates) from the saved metadata JSON
        import json as _json
        meta_path = os.path.join(topic_papers_dir, METADATA_FILENAME)
        rich_meta_by_path: dict = {}
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta_index = _json.load(f)
                for paper in meta_index.values():
                    rich_meta_by_path[paper.get("filepath", "")] = paper
            except Exception as e:
                logger.warning("Could not load rich metadata: %s", e)

        _cb("index_start", f"Building vector index for {len(pdf_files)} paper(s)…")
        for filepath in pdf_files:
            if filepath in existing_chunk_ids:
                logger.info("Skipping already-indexed file: %s", os.path.basename(filepath))
                continue
            try:
                _cb("index_file", f"Indexing: {os.path.basename(filepath)}")
                text = processor.parse_pdf(filepath)
                base_meta = rich_meta_by_path.get(filepath, {})
                metadata = {
                    "filepath": filepath,
                    "title": base_meta.get("title", os.path.basename(filepath)),
                    "authors": base_meta.get("authors", []),
                    "published": base_meta.get("published", ""),
                    "arxiv_id": base_meta.get("arxiv_id", ""),
                }
                chunks = chunker.chunk_text(text, metadata)
                ve.add_chunks(chunks)
            except Exception as e:
                logger.error("Error processing %s: %s", filepath, e)
    else:
        logger.info("Reusing existing index (%d chunks) for topic '%s'.", ve.count(), topic)

    _cb("index_done", f"Index ready ({ve.count()} chunks)")
    timings["index_seconds"] = round(time.perf_counter() - start_time, 2)

    if not pdf_files:
        return _error_result(
            "No papers could be downloaded from arXiv (PDF and HTML both failed). Try more specific technical keywords, or retry.",
            status="no_sources",
        )

    # ------------------------------------------------------------------ 2. Retrieve
    _cb("retrieve_start", "Retrieving relevant chunks with hybrid search…")
    retrieval_start = time.perf_counter()
    retriever = HybridRetriever(ve)

    # Fit BM25 on the full indexed corpus for hybrid retrieval
    try:
        retriever.fit_bm25()
    except Exception as e:
        logger.warning("BM25 fitting failed: %s", e)

    retrieval_top_k = retrieval_top_k if retrieval_top_k else (6 if fast_mode else 9)
    context = retriever.retrieve(
        topic,
        top_k=retrieval_top_k,
        strategy=retrieval_strategy,
        rerank=True,
    )
    _cb("retrieve_done", f"Retrieved {len(context)} chunk(s) — reranked with cross-encoder")
    timings["retrieval_seconds"] = round(time.perf_counter() - retrieval_start, 2)

    if not context:
        return _error_result(
            "No relevant context chunks were retrieved. Try another retrieval strategy or refresh sources.",
            status="no_context",
            paper_count=len(pdf_files),
        )

    # ------------------------------------------------------------------ 3. Generate
    _cb("generate_start", "Generating paper with LLM — this takes 1–3 minutes…")
    generation_start = time.perf_counter()
    rag = RAGGenerator()

    review = rag.generate_review(
        topic,
        context,
        refine_context=not fast_mode,
        fast_generation=fast_mode,
        generate_pdf_output=False,
        user_preferences=user_preferences,
    )
    timings["generation_seconds"] = round(time.perf_counter() - generation_start, 2)
    paper_text = review["paper_text"]

    # Remove any author identity the model lifted from the source papers
    # before the text is shown, exported or archived.
    paper_text = rag.sanitize_title_block(paper_text, context, user_preferences)

    _cb("generate_done", f"Paper generated ({len(paper_text.split())} words)")

    # Archive the draft as soon as it exists, so a failure in a later stage
    # (rewrite, evaluation) does not lose the work.
    archive_paper(topic, {"paper_text": paper_text, "strategy": retrieval_strategy,
                          "num_papers": len(pdf_files), "retrieved_context": [
                              {"title": c.get("metadata", {}).get("title", "Unknown")} for c in context
                          ]}, started_at)

    # ── Analysis table (best-effort — failures don't block the paper) ─────────
    _cb("analysis_start", "Building comparative analysis table…")
    analysis_table: list = []
    try:
        analysis_table = rag.generate_analysis_table(topic, context)
    except Exception as e:
        logger.warning("Analysis table generation failed (non-fatal): %s", e)

    # ------------------------------------------------------------------ 4. Plagiarism check & rewrite
    _cb("postprocess_start", "Post-processing: originality rewrite…")
    rewrite_passes = 0
    plagiarism_report = None
    if run_plagiarism_check:
        plagiarism_report = Evaluator.evaluate_plagiarism_risk(paper_text, context)

    if apply_ai_rewrite:
        safe_passes = max(1, min(int(max_rewrite_passes), 4))
        for _ in range(safe_passes):
            current_similarity = (plagiarism_report or {}).get("overall_similarity_pct", 0.0)
            should_rewrite = (
                not run_plagiarism_check
                or not plagiarism_report
                or current_similarity > target_similarity_pct
            )
            if not should_rewrite:
                break
            rewritten = rag.rewrite_for_originality(
                topic, paper_text, context, target_similarity_pct=target_similarity_pct
            )
            if not rewritten or not rewritten.strip():
                break
            if run_plagiarism_check:
                new_report = Evaluator.evaluate_plagiarism_risk(rewritten.strip(), context)
                new_similarity = new_report.get("overall_similarity_pct", 0.0)
                if new_similarity < current_similarity:
                    paper_text = rewritten.strip()
                    plagiarism_report = new_report
                    rewrite_passes += 1
                else:
                    logger.info(
                        "Rewrite did not improve similarity (%.1f%% → %.1f%%) — discarding.",
                        current_similarity, new_similarity,
                    )
                    break
            else:
                paper_text = rewritten.strip()
                rewrite_passes += 1

    # ------------------------------------------------------------------ 5. Humanize writing
    humanize_applied = False
    if apply_humanize and not fast_mode:
        try:
            humanized = rag.humanize_writing(paper_text)
            if humanized and humanized.strip():
                paper_text = humanized.strip()
                humanize_applied = True
        except Exception as e:
            logger.warning("Humanize pass failed: %s", e)

    # ------------------------------------------------------------------ 6. Page expansion
    if fast_5page_mode:
        paper_text = rag.expand_to_min_pages(
            topic, paper_text, context,
            min_pages=max(1, int(min_pages)),
            max_passes=1,
        )
        if run_plagiarism_check:
            plagiarism_report = Evaluator.evaluate_plagiarism_risk(paper_text, context)

    # ------------------------------------------------------------------ 7. PDF generation
    _cb("pdf_start", "Generating IEEE PDF…")
    latex_compile_log = None
    tex_path = None
    pdf_path = None
    if generate_pdf:
        if use_latex_pdf:
            latex_result = rag.generate_latex_pdf_from_paper_text(topic, paper_text, context)
            pdf_path = latex_result.get("pdf_path")
            latex_compile_log = latex_result.get("compile_log")
            tex_path = latex_result.get("tex_path")
        else:
            pdf_path = rag.generate_pdf(topic, paper_text)

    # ------------------------------------------------------------------ 8. Evaluation
    faithfulness_score = None
    relevance_score = None
    faithfulness_reasoning = None
    relevance_reasoning = None
    rouge_l_result = None

    eval_start = time.perf_counter()
    evaluation_error = None
    if include_evaluation:
        llm = LLMClient()
        eval_context = context[:Config.EVAL_MAX_CONTEXT_CHUNKS] if fast_mode else context
        eval_text = paper_text[:Config.EVAL_MAX_CHARS] if fast_mode else paper_text
        try:
            faith_result = Evaluator.evaluate_faithfulness(topic, eval_text, eval_context, llm)
            rel_result = Evaluator.evaluate_relevance(topic, eval_text, llm)
            faithfulness_score = faith_result.get("score")
            relevance_score = rel_result.get("score")
            faithfulness_reasoning = faith_result.get("reasoning")
            relevance_reasoning = rel_result.get("reasoning")
        except Exception as e:
            logger.warning("LLM-based evaluation failed: %s", e)
            evaluation_error = str(e)

        # Always run ROUGE-L (no LLM needed)
        rouge_l_result = Evaluator.evaluate_rouge_l(paper_text, context)

    timings["evaluation_seconds"] = round(time.perf_counter() - eval_start, 2)
    timings["total_seconds"] = round(time.perf_counter() - start_time, 2)
    _cb("done", f"Complete in {timings['total_seconds']}s")

    # Prune stale collections now that we're done with the active one
    try:
        VectorEngine.prune_old_collections(keep=[collection_name])
    except Exception as e:
        logger.warning("Collection pruning failed (non-fatal): %s", e)

    # ------------------------------------------------------------------ 9. Build result  (cache before return)
    retrieved_context = []
    for item in context:
        meta = item.get("metadata", {})
        retrieved_context.append(
            {
                "title": meta.get("title", "Unknown"),
                "authors": meta.get("authors", ""),
                "published": meta.get("published", ""),
                "filepath": meta.get("filepath", ""),
                "source": item.get("source", "vector"),
                "score": item.get("score"),
                "rerank_score": item.get("rerank_score"),
                "text": item.get("text", ""),
            }
        )

    result = {
        "paper_text": paper_text,
        "pdf_path": pdf_path,
        "num_papers": len(pdf_files),
        "strategy": retrieval_strategy,
        "faithfulness": faithfulness_score,
        "relevance": relevance_score,
        "faithfulness_reasoning": faithfulness_reasoning,
        "relevance_reasoning": relevance_reasoning,
        "evaluation_error": evaluation_error,
        "retrieved_context": retrieved_context,
        "plagiarism_report": plagiarism_report,
        "rouge_l": rouge_l_result,
        "ai_rewrite_passes": rewrite_passes,
        "humanize_applied": humanize_applied,
        "timings": timings,
        "status": "ok",
        "error": None,
        "latex_compile_log": latex_compile_log,
        "tex_path": tex_path,
        "page_estimate": rag.estimate_page_count(paper_text),
        "min_pages_target": max(1, int(min_pages)) if fast_5page_mode else None,
        "analysis_table": analysis_table,
    }
    if not include_evaluation and result.get("status") == "ok":
        _store_cached(ck, result)

    # Rewrite the archive entry now that scores and timings are known.
    result["archive_path"] = archive_paper(topic, result, started_at)
    return result


def refine_paper_with_instruction(
    topic: str,
    paper_text: str,
    context: list,
    instruction: str,
    generate_pdf: bool = False,
    use_latex_pdf: bool = False,
) -> dict:
    """
    Apply a single user refinement instruction to an already-generated paper.
    Optionally regenerates the PDF with the updated text.
    """
    rag = RAGGenerator()
    try:
        refined = rag.refine_paper(topic, paper_text, context, instruction)

        pdf_path = None
        latex_compile_log = None
        tex_path = None

        if generate_pdf and refined:
            if use_latex_pdf:
                latex_result = rag.generate_latex_pdf_from_paper_text(topic, refined, context)
                pdf_path = latex_result.get("pdf_path")
                latex_compile_log = latex_result.get("compile_log")
                tex_path = latex_result.get("tex_path")
            else:
                pdf_path = rag.generate_pdf(topic, refined)

        return {
            "paper_text": refined,
            "pdf_path": pdf_path,
            "latex_compile_log": latex_compile_log,
            "tex_path": tex_path,
            "status": "ok",
            "error": None,
        }
    except Exception as e:
        logger.error("Refinement failed: %s", e)
        return {
            "paper_text": paper_text,
            "pdf_path": None,
            "latex_compile_log": None,
            "tex_path": None,
            "status": "error",
            "error": str(e),
        }
