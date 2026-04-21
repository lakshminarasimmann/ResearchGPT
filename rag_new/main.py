import argparse
import glob
import logging
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config.config import Config
from src.ingestion.ingestor import ArxivIngestor
from src.processing.processor import PDFProcessor, Chunker
from src.embedding.vector_store import VectorEngine
from src.retrieval.retriever import HybridRetriever
from src.generation.generator import RAGGenerator

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ CLI
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RAG Pipeline CLI")
    subs = parser.add_subparsers(dest="command", help="Available commands")

    ingest_p = subs.add_parser("ingest", help="Search and download papers from arXiv")
    ingest_p.add_argument("--query", required=True, help="Search query for arXiv")
    ingest_p.add_argument("--max", type=int, default=Config.MAX_PAPERS, help="Max papers to download")

    subs.add_parser("index", help="Parse and index downloaded papers")

    ret_p = subs.add_parser("retrieve", help="Retrieve relevant chunks")
    ret_p.add_argument("--query", required=True, help="Query for retrieval")
    ret_p.add_argument("--k", type=int, default=Config.TOP_K, help="Number of chunks to return")
    ret_p.add_argument("--strategy", default="hyde", choices=["hyde", "complex", "naive", "hybrid"])

    gen_p = subs.add_parser("generate", help="Generate an IEEE-style paper")
    gen_p.add_argument("--topic", required=True, help="Topic / query for the paper")

    eval_p = subs.add_parser("evaluate", help="Run evaluation metrics")
    eval_p.add_argument("--query", required=True, help="Test query")

    run_p = subs.add_parser("run_all", help="Run full pipeline: Ingest → Index → Generate → Eval")
    run_p.add_argument("--query", required=True, help="Topic / query for the pipeline")
    run_p.add_argument("--max", type=int, default=Config.MAX_PAPERS, help="Max papers")

    return parser


def main():
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    # ---- Ingest ----
    if args.command == "ingest":
        logger.info("Mode: Ingestion")
        ingestor = ArxivIngestor(max_results=args.max)
        papers = ingestor.search_and_download(args.query)
        print(f"Downloaded {len(papers)} papers.")

    # ---- Index ----
    elif args.command == "index":
        logger.info("Mode: Indexing")
        processor = PDFProcessor()
        chunker = Chunker()
        ve = VectorEngine()
        ve.reset_collection()

        pdf_files = glob.glob(os.path.join(Config.PAPERS_DIR, "*.pdf"))
        print(f"Found {len(pdf_files)} PDFs to process.")
        for filepath in pdf_files:
            try:
                print(f"Processing: {os.path.basename(filepath)}")
                text = processor.parse_pdf(filepath)
                metadata = {"filepath": filepath, "title": os.path.basename(filepath)}
                chunks = chunker.chunk_text(text, metadata)
                ve.add_chunks(chunks)
            except Exception as e:
                logger.error("Error processing %s: %s", filepath, e)
        print("Indexing complete.")

    # ---- Retrieve ----
    elif args.command == "retrieve":
        logger.info("Mode: Retrieval")
        ve = VectorEngine()
        retriever = HybridRetriever(ve)
        retriever.fit_bm25()

        results = retriever.retrieve(args.query, top_k=args.k, strategy=args.strategy)
        for i, res in enumerate(results):
            print(f"\n[Result {i+1}] (rerank_score: {res.get('rerank_score', 'N/A'):.3f})")
            print(f"Source : {res['metadata'].get('title')}")
            print(f"Snippet: {res['text'][:200]}...")

    # ---- Generate ----
    elif args.command == "generate":
        logger.info("Mode: Generation")
        ve = VectorEngine()
        retriever = HybridRetriever(ve)
        retriever.fit_bm25()
        rag = RAGGenerator()

        print(f"Retrieving context for topic: {args.topic}…")
        context = retriever.retrieve(args.topic, top_k=5)

        print("Generating paper…")
        review = rag.generate_review(args.topic, context)
        paper_text = review["paper_text"]

        output_path = os.path.join(Config.OUTPUT_DIR, "literature_review.txt")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(paper_text)
        print(f"Paper saved to: {output_path}")
        print(f"\n--- Preview ---\n{paper_text[:500]}...")

    # ---- Evaluate ----
    elif args.command == "evaluate":
        logger.info("Mode: Evaluation")
        from src.evaluation.evaluator import Evaluator
        from src.generation.generator import LLMClient

        ve = VectorEngine()
        retriever = HybridRetriever(ve)
        retriever.fit_bm25()
        llm = LLMClient()

        print(f"Evaluating query: {args.query}")
        context = retriever.retrieve(args.query, top_k=5)
        rag = RAGGenerator()
        review = rag.generate_review(args.query, context)
        paper_text = review["paper_text"]

        faith_result = Evaluator.evaluate_faithfulness(args.query, paper_text, context, llm)
        rel_result = Evaluator.evaluate_relevance(args.query, paper_text, llm)
        rouge_l = Evaluator.evaluate_rouge_l(paper_text, context)
        plag = Evaluator.evaluate_plagiarism_risk(paper_text, context)

        print(f"\nFaithfulness : {faith_result['score']}/5")
        print(f"Relevance    : {rel_result['score']}/5")
        print(f"ROUGE-L avg  : {rouge_l['avg_rouge_l']:.4f}")
        print(f"Plagiarism   : {plag['overall_similarity_pct']:.1f}% sentence similarity")
        print(f"Reasoning    : {rel_result['reasoning'][:200]}...")

    # ---- Run all ----
    elif args.command == "run_all":
        from src.pipeline.ui_pipeline import run_rag_for_ui_pipeline
        result = run_rag_for_ui_pipeline(
            topic=args.query,
            retrieval_strategy="hyde",
            include_evaluation=True,
            fast_mode=False,
            run_plagiarism_check=True,
            apply_ai_rewrite=True,
            apply_humanize=True,
        )
        if result["status"] != "ok":
            print(f"Pipeline error: {result['error']}")
        else:
            print(f"\nPaper generated ({result['page_estimate']} pages).")
            print(f"Faithfulness  : {result['faithfulness']}/5")
            print(f"Relevance     : {result['relevance']}/5")
            if result.get("rouge_l"):
                print(f"ROUGE-L avg   : {result['rouge_l']['avg_rouge_l']:.4f}")
            if result.get("plagiarism_report"):
                print(f"Plagiarism    : {result['plagiarism_report']['overall_similarity_pct']:.1f}%")
            print(f"Timings       : {result['timings']}")


if __name__ == "__main__":
    main()
