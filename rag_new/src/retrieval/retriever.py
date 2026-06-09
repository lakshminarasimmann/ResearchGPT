import logging
import os
import re
import sys
from functools import lru_cache
from typing import List, Dict

import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

_BM25_STOPWORDS = frozenset({
    "the", "a", "an", "of", "in", "is", "are", "was", "were", "be", "been",
    "being", "and", "or", "but", "to", "for", "with", "on", "at", "by",
    "from", "as", "into", "that", "this", "these", "those", "it", "its",
    "which", "we", "our", "their", "have", "has", "had", "do", "does",
    "can", "could", "will", "would", "may", "might", "shall", "should",
})

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config.config import Config
from src.embedding.vector_store import VectorEngine
from src.generation.generator import LLMClient

logger = logging.getLogger(__name__)


@lru_cache(maxsize=2)
def _get_cross_encoder(model_name: str) -> CrossEncoder:
    return CrossEncoder(model_name)


class HybridRetriever:
    def __init__(self, vector_engine: VectorEngine):
        self.vector_engine = vector_engine
        self.bm25: BM25Okapi | None = None
        self.bm25_docs: List[str] = []
        self.bm25_metadatas: List[Dict] = []
        self.cross_encoder = _get_cross_encoder(Config.CROSS_ENCODER_MODEL)
        self.llm_client = LLMClient()

    # ------------------------------------------------------------------
    # Tokenization
    # ------------------------------------------------------------------
    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """
        Tokenize for BM25: lowercase, keep hyphenated compounds intact,
        strip punctuation, remove stopwords and single-char tokens.
        """
        tokens = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text.lower())
        return [t for t in tokens if t not in _BM25_STOPWORDS and len(t) > 1]

    # ------------------------------------------------------------------
    # BM25 management
    # ------------------------------------------------------------------
    def fit_bm25(self, chunks: List[Dict] | None = None):
        """
        Fits BM25 on the given chunks, or loads all chunks from the vector
        engine if none are supplied.
        """
        if chunks is None:
            chunks = self.vector_engine.get_all_chunks()
        if not chunks:
            logger.warning("No chunks available for BM25 fitting.")
            return
        self.bm25_docs = [c["text"] for c in chunks]
        self.bm25_metadatas = [c["metadata"] for c in chunks]
        tokenized = [self._tokenize(doc) for doc in self.bm25_docs]
        self.bm25 = BM25Okapi(tokenized)
        logger.info("BM25 fitted on %d documents.", len(self.bm25_docs))

    def _ensure_bm25(self):
        """Auto-fit BM25 from the vector engine if not already done."""
        if self.bm25 is None:
            self.fit_bm25()

    # ------------------------------------------------------------------
    # Query expansion helpers
    # ------------------------------------------------------------------
    def generate_hypothetical_answer(self, query: str) -> str:
        prompt = f"""You are a helpful expert research assistant.
Provide a hypothetical answer to the following question.
Focus on scientific terminology that would appear in a relevant paper.
Do not say "I don't know". Hallucinate a plausible-sounding scientific answer.

QUESTION: {query}

HYPOTHETICAL ANSWER:"""
        return self.llm_client.generate(prompt).strip()

    def generate_sub_questions(self, query: str) -> List[str]:
        prompt = f"""You are a helpful expert research assistant.
Break down the following complex question into 2-3 simple, independent sub-questions
that can be searched for in a scientific database.

Complex: "{query}"

SUB-QUESTIONS (one per line):"""
        response = self.llm_client.generate(prompt)
        sub_qs = [q.strip().lstrip("- 123.") for q in response.split("\n") if q.strip()]
        return sub_qs[:3]

    # ------------------------------------------------------------------
    # Core retrieval
    # ------------------------------------------------------------------
    def _vector_search(self, query_text: str, n: int) -> List[Dict]:
        results = self.vector_engine.query(query_text, n_results=n)
        candidates = []
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        dists = results["distances"][0]
        ids = results.get("ids", [[None] * len(docs)])[0]
        for i in range(len(docs)):
            candidates.append(
                {
                    "id": ids[i],
                    "text": docs[i],
                    "metadata": metas[i],
                    "vector_score": float(dists[i]),
                    "source": "vector",
                }
            )
        return candidates

    def _bm25_search(self, query: str, n: int) -> List[Dict]:
        self._ensure_bm25()
        if self.bm25 is None or not self.bm25_docs:
            return []
        tokenized_query = self._tokenize(query)
        scores = self.bm25.get_scores(tokenized_query)
        top_indices = np.argsort(scores)[::-1][:n]
        candidates = []
        for idx in top_indices:
            if scores[idx] <= 0:
                continue
            candidates.append(
                {
                    "id": f"bm25_{idx}",
                    "text": self.bm25_docs[idx],
                    "metadata": self.bm25_metadatas[idx],
                    "bm25_score": float(scores[idx]),
                    "source": "bm25",
                }
            )
        return candidates

    def _hybrid_merge(
        self,
        vector_candidates: List[Dict],
        bm25_candidates: List[Dict],
        alpha: float,
    ) -> List[Dict]:
        """
        Combines vector and BM25 results using min-max normalised scores.
        Final score = alpha * vector_norm + (1 - alpha) * bm25_norm
        Lower vector_score = better (distance); higher bm25_score = better.
        """
        # Normalise vector distances (lower = better → invert after normalisation)
        v_scores = np.array([c["vector_score"] for c in vector_candidates], dtype=float)
        if v_scores.size > 0:
            v_min, v_max = v_scores.min(), v_scores.max()
            v_range = v_max - v_min if v_max != v_min else 1.0
            v_norm = 1.0 - (v_scores - v_min) / v_range   # invert so higher=better
        else:
            v_norm = np.array([])

        # Normalise BM25 scores (higher = better)
        b_scores = np.array([c["bm25_score"] for c in bm25_candidates], dtype=float)
        if b_scores.size > 0:
            b_min, b_max = b_scores.min(), b_scores.max()
            b_range = b_max - b_min if b_max != b_min else 1.0
            b_norm = (b_scores - b_min) / b_range
        else:
            b_norm = np.array([])

        merged: Dict[str, Dict] = {}

        for i, c in enumerate(vector_candidates):
            key = c["text"][:100]
            entry = dict(c)
            entry["hybrid_score"] = alpha * float(v_norm[i])
            merged[key] = entry

        for i, c in enumerate(bm25_candidates):
            key = c["text"][:100]
            if key in merged:
                merged[key]["hybrid_score"] += (1 - alpha) * float(b_norm[i])
                merged[key]["source"] = "hybrid"
            else:
                entry = dict(c)
                entry["hybrid_score"] = (1 - alpha) * float(b_norm[i])
                merged[key] = entry

        results = sorted(merged.values(), key=lambda x: x.get("hybrid_score", 0), reverse=True)
        # Expose as generic 'score' for downstream consumers
        for r in results:
            r["score"] = r.get("hybrid_score", r.get("vector_score", 0.0))
        return results

    def retrieve(
        self,
        query: str,
        top_k: int = Config.TOP_K,
        alpha: float = Config.BM25_ALPHA,
        strategy: str = "hyde",
        rerank: bool = True,
    ) -> List[Dict]:
        """
        Retrieval dispatcher.
        strategies: 'hyde', 'complex', 'hybrid', 'naive'
        All strategies now pass through BM25 hybrid merging unless strategy=='naive'.
        """
        window = Config.RETRIEVAL_WINDOW_SIZE
        candidates: List[Dict] = []

        if strategy == "complex":
            logger.info("Strategy: Sub-Question Decomposition for '%s'", query)
            sub_qs = self.generate_sub_questions(query)
            logger.info("Sub-questions: %s", sub_qs)
            seen_ids: set = set()
            for sub_q in sub_qs:
                for c in self._vector_search(sub_q, window):
                    key = c["text"][:100]
                    if key not in seen_ids:
                        seen_ids.add(key)
                        candidates.append(c)

        elif strategy == "hyde":
            logger.info("Generating HyDE hypothetical answer for: '%s'", query)
            hyde_query = self.generate_hypothetical_answer(query)
            logger.info("HyDE preview: %s...", hyde_query[:100])
            candidates = self._vector_search(hyde_query, window)

        else:  # 'naive' or 'hybrid' — both start with plain vector search
            candidates = self._vector_search(query, window)

        # ---- BM25 hybrid merge (skip only for 'naive') ----
        if strategy != "naive":
            bm25_candidates = self._bm25_search(query, window)
            if bm25_candidates:
                # Use per-strategy alpha when caller hasn't overridden the global default
                if alpha == Config.BM25_ALPHA:
                    alpha = {
                        "hyde": Config.BM25_ALPHA_HYDE,
                        "complex": Config.BM25_ALPHA_COMPLEX,
                    }.get(strategy, Config.BM25_ALPHA_STANDARD)
                candidates = self._hybrid_merge(candidates, bm25_candidates, alpha)
                logger.info(
                    "Hybrid merge: %d vector + %d BM25 → %d unique (alpha=%.2f, strategy=%s).",
                    len(candidates), len(bm25_candidates), len(candidates), alpha, strategy,
                )

        if not rerank:
            return candidates[:top_k]

        # ---- Cross-encoder re-ranking ----
        logger.info("Re-ranking %d candidates…", len(candidates))
        reranked = self._rerank(query, candidates)

        # ---- Optional relevance threshold ----
        threshold = Config.RETRIEVAL_SCORE_THRESHOLD
        if threshold > 0.0:
            reranked = [c for c in reranked if c.get("rerank_score", 0.0) >= threshold]

        return reranked[:top_k]

    _HIGH_VALUE_SECTIONS = frozenset({
        "results", "methodology", "conclusion", "discussion",
        "experiment", "evaluation", "analysis", "findings",
    })

    def _rerank(self, query: str, candidates: List[Dict]) -> List[Dict]:
        if not candidates:
            return []
        pairs = [[query, doc["text"]] for doc in candidates]
        scores = self.cross_encoder.predict(pairs)
        if len(scores) != len(candidates):
            logger.warning(
                "Cross-encoder returned %d scores for %d candidates — truncating to shorter list.",
                len(scores), len(candidates),
            )
        for i, doc in enumerate(candidates[:len(scores)]):
            base = max(0.0, min(1.0, float(scores[i])))
            section = (doc.get("metadata", {}).get("section") or "").lower()
            boost = 0.1 if any(kw in section for kw in self._HIGH_VALUE_SECTIONS) else 0.0
            doc["rerank_score"] = min(1.0, base + boost)
        # candidates beyond scores list get a score of 0
        for doc in candidates[len(scores):]:
            doc["rerank_score"] = 0.0
        return sorted(candidates, key=lambda x: x["rerank_score"], reverse=True)


if __name__ == "__main__":
    pass
