import glob
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

logger = logging.getLogger(__name__)


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
    target_similarity_pct: float = 25.0,
    max_rewrite_passes: int = 1,
    fast_5page_mode: bool = False,
    min_pages: int = 5,
    user_preferences: str = "",
) -> dict:
    """
    UI-safe RAG pipeline.  Returns structured output; never calls print() or input().
    """
    start_time = time.perf_counter()
    timings: dict = {}

    topic_slug = _slugify_topic(topic)
    topic_papers_dir = os.path.join(Config.PAPERS_DIR, topic_slug)
    collection_name = f"{Config.COLLECTION_NAME}_{topic_slug}"

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

    needs_reindex = force_refresh_sources or current_count == 0

    if needs_reindex:
        ingestor = ArxivIngestor(
            max_results=2 if fast_mode else 3,
            download_dir=topic_papers_dir,
        )
        downloaded = ingestor.search_and_download(topic, clear_existing=force_refresh_sources)
        logger.info("Downloaded/found %d papers for topic '%s'.", len(downloaded), topic)

        pdf_files = glob.glob(os.path.join(topic_papers_dir, "*.pdf"))

        # Build a set of paper IDs already in the vector store to enable incremental indexing
        existing_chunk_ids: set = set()
        if ve.count() > 0 and not force_refresh_sources:
            all_existing = ve.get_all_chunks()
            existing_chunk_ids = {c["metadata"].get("filepath", "") for c in all_existing}
        elif force_refresh_sources:
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

        for filepath in pdf_files:
            if filepath in existing_chunk_ids:
                logger.info("Skipping already-indexed file: %s", os.path.basename(filepath))
                continue
            try:
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
        pdf_files = glob.glob(os.path.join(topic_papers_dir, "*.pdf"))
        logger.info("Reusing existing index (%d chunks) for topic '%s'.", ve.count(), topic)

    timings["index_seconds"] = round(time.perf_counter() - start_time, 2)

    if not pdf_files:
        return _error_result(
            "No source papers were found. Try enabling source refresh or rephrasing your query.",
            status="no_sources",
        )

    # ------------------------------------------------------------------ 2. Retrieve
    retrieval_start = time.perf_counter()
    retriever = HybridRetriever(ve)

    # Fit BM25 on the full indexed corpus for hybrid retrieval
    try:
        retriever.fit_bm25()
    except Exception as e:
        logger.warning("BM25 fitting failed: %s", e)

    retrieval_top_k = 6 if fast_mode else 9
    context = retriever.retrieve(
        topic,
        top_k=retrieval_top_k,
        strategy=retrieval_strategy,
        rerank=True,
    )
    timings["retrieval_seconds"] = round(time.perf_counter() - retrieval_start, 2)

    if not context:
        return _error_result(
            "No relevant context chunks were retrieved. Try another retrieval strategy or refresh sources.",
            status="no_context",
            paper_count=len(pdf_files),
        )

    # ------------------------------------------------------------------ 3. Generate
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

    # ------------------------------------------------------------------ 4. Plagiarism check & rewrite
    rewrite_passes = 0
    plagiarism_report = None
    if run_plagiarism_check:
        plagiarism_report = Evaluator.evaluate_plagiarism_risk(paper_text, context)

    if apply_ai_rewrite:
        safe_passes = max(1, min(int(max_rewrite_passes), 3))
        for _ in range(safe_passes):
            should_rewrite = (
                not run_plagiarism_check
                or not plagiarism_report
                or plagiarism_report.get("overall_similarity_pct", 0.0) > target_similarity_pct
            )
            if not should_rewrite:
                break
            rewritten = rag.rewrite_for_originality(
                topic, paper_text, context, target_similarity_pct=target_similarity_pct
            )
            if rewritten and rewritten.strip():
                paper_text = rewritten.strip()
                rewrite_passes += 1
            if run_plagiarism_check:
                plagiarism_report = Evaluator.evaluate_plagiarism_risk(paper_text, context)

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
    if include_evaluation:
        llm = LLMClient()
        eval_context = context[:3] if fast_mode else context
        eval_text = paper_text[:7000] if fast_mode else paper_text
        try:
            faith_result = Evaluator.evaluate_faithfulness(topic, eval_text, eval_context, llm)
            rel_result = Evaluator.evaluate_relevance(topic, eval_text, llm)
            faithfulness_score = faith_result.get("score")
            relevance_score = rel_result.get("score")
            faithfulness_reasoning = faith_result.get("reasoning")
            relevance_reasoning = rel_result.get("reasoning")
        except Exception as e:
            logger.warning("LLM-based evaluation failed: %s", e)

        # Always run ROUGE-L (no LLM needed)
        rouge_l_result = Evaluator.evaluate_rouge_l(paper_text, context)

    timings["evaluation_seconds"] = round(time.perf_counter() - eval_start, 2)
    timings["total_seconds"] = round(time.perf_counter() - start_time, 2)

    # Prune stale collections now that we're done with the active one
    try:
        VectorEngine.prune_old_collections(keep=[collection_name])
    except Exception as e:
        logger.warning("Collection pruning failed (non-fatal): %s", e)

    # ------------------------------------------------------------------ 9. Build result
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

    return {
        "paper_text": paper_text,
        "pdf_path": pdf_path,
        "num_papers": len(pdf_files),
        "strategy": retrieval_strategy,
        "faithfulness": faithfulness_score,
        "relevance": relevance_score,
        "faithfulness_reasoning": faithfulness_reasoning,
        "relevance_reasoning": relevance_reasoning,
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
    }


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
