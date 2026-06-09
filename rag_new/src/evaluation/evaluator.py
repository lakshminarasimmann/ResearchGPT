import logging
import re
from difflib import SequenceMatcher
from typing import List, Dict

import numpy as np

logger = logging.getLogger(__name__)


def _rouge_l_score(hypothesis: str, reference: str) -> float:
    """
    Computes ROUGE-L F1 between two strings using the LCS approach.
    Falls back gracefully if rouge-score is not installed.
    """
    try:
        from rouge_score import rouge_scorer
        scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)
        result = scorer.score(reference, hypothesis)
        return round(result["rougeL"].fmeasure, 4)
    except ImportError:
        # Manual LCS fallback
        h_tokens = hypothesis.lower().split()
        r_tokens = reference.lower().split()
        if not h_tokens or not r_tokens:
            return 0.0
        m, n = len(h_tokens), len(r_tokens)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if h_tokens[i - 1] == r_tokens[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1] + 1
                else:
                    dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
        lcs = dp[m][n]
        precision = lcs / m if m else 0.0
        recall = lcs / n if n else 0.0
        if precision + recall == 0:
            return 0.0
        return round(2 * precision * recall / (precision + recall), 4)


class Evaluator:

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", text.lower())).strip()

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        """
        Splits text into sentences, handling common abbreviations to avoid
        false splits (e.g. "Dr. Smith", "et al.", "Fig. 3").
        """
        # Protect common abbreviations
        protected = re.sub(
            r"\b(Dr|Mr|Mrs|Ms|Prof|Fig|et al|vs|i\.e|e\.g|cf|approx|eq|Eq)\.",
            lambda m: m.group(0).replace(".", "<DOT>"),
            text,
        )
        raw = re.split(r"(?<=[.!?])\s+|\n{2,}", protected)
        sentences = []
        for s in raw:
            s = s.replace("<DOT>", ".").strip()
            if len(s) >= 40:
                sentences.append(s)
        return sentences

    @staticmethod
    def _word_ngrams(text: str, n: int = 8) -> set:
        words = Evaluator._normalize_text(text).split()
        if len(words) < n:
            return set()
        return {" ".join(words[i: i + n]) for i in range(len(words) - n + 1)}

    # ------------------------------------------------------------------
    # Retrieval metrics
    # ------------------------------------------------------------------
    @staticmethod
    def hit_rate(retrieved_chunks_list: List[List[Dict]], relevant_ids_list: List[List[str]]) -> float:
        hits = 0
        for retrieved, relevant in zip(retrieved_chunks_list, relevant_ids_list):
            retrieved_ids = [r["metadata"].get("title", "") for r in retrieved]
            if any(rel in retrieved_ids for rel in relevant):
                hits += 1
        return hits / len(retrieved_chunks_list) if retrieved_chunks_list else 0.0

    @staticmethod
    def mrr(retrieved_chunks_list: List[List[Dict]], relevant_ids_list: List[List[str]]) -> float:
        reciprocal_ranks = []
        for retrieved, relevant in zip(retrieved_chunks_list, relevant_ids_list):
            retrieved_ids = [r["metadata"].get("title", "") for r in retrieved]
            rank = 0
            for i, rid in enumerate(retrieved_ids):
                if rid in relevant:
                    rank = i + 1
                    break
            reciprocal_ranks.append(1.0 / rank if rank > 0 else 0.0)
        return float(np.mean(reciprocal_ranks)) if reciprocal_ranks else 0.0

    # ------------------------------------------------------------------
    # LLM-based quality metrics (G-Eval)
    # ------------------------------------------------------------------
    @staticmethod
    def evaluate_faithfulness(query: str, response: str, context: List[Dict], llm_client) -> Dict:
        # Truncate to avoid overwhelming the LLM context window
        context_text = "\n".join([c["text"] for c in context])[:3000]
        response_snippet = response[:2500]
        prompt = f"""You are an impartial judge evaluating a RAG system.
Task: Evaluate the Faithfulness of the ANSWER to the provided CONTEXT.

CONTEXT (excerpt):
{context_text}

ANSWER (excerpt):
{response_snippet}

INSTRUCTIONS:
1. Read the Context and the Answer.
2. Identify any claims in the Answer that contradict or are unsupported by the Context.
3. Output a score from 1 to 5:
   - 1: Entirely hallucinated or contradicts context.
   - 3: Mostly supported but has minor unverified details.
   - 5: Fully supported by context.

Reasoning: [one paragraph]
Score: [single digit 1-5]"""
        eval_output = llm_client.generate(prompt).strip()
        return Evaluator._parse_geval_output(eval_output)

    @staticmethod
    def evaluate_relevance(query: str, response: str, llm_client) -> Dict:
        response_snippet = response[:2500]
        prompt = f"""You are an impartial judge evaluating a RAG system.
Task: Evaluate the Relevance of the ANSWER to the QUERY.

QUERY:
{query}

ANSWER (excerpt):
{response_snippet}

INSTRUCTIONS:
1. Does the Answer directly address the Query topic?
2. Output a score from 1 to 5:
   - 1: Completely irrelevant or off-topic.
   - 3: Partially relevant but misses key aspects.
   - 5: Highly relevant and comprehensive.

Reasoning: [one paragraph]
Score: [single digit 1-5]"""
        eval_output = llm_client.generate(prompt).strip()
        return Evaluator._parse_geval_output(eval_output)

    @staticmethod
    def _parse_geval_output(text: str) -> Dict:
        # Try progressively looser patterns
        patterns = [
            r"Score:\s*\**(\d)\**",          # Score: 3  or  Score: **3**
            r"\bscore[:\s]+\**(\d)\**",       # case-insensitive score:3
            r"\*\*Score\*\*[:\s]+(\d)",       # **Score**: 3
            r"(\d)\s*/\s*5",                  # 3/5
            r"\b([1-5])\b(?![\d])",           # lone digit 1-5 anywhere
        ]
        score = None
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                val = int(m.group(1))
                if 1 <= val <= 5:
                    score = val
                    break
        if score is None:
            logger.warning("Could not parse G-Eval score from: %s", text[:200])
            score = None  # let the UI show — instead of 0
        return {"reasoning": text, "score": score}

    # ------------------------------------------------------------------
    # ROUGE-L against retrieved context
    # ------------------------------------------------------------------
    @staticmethod
    def evaluate_rouge_l(response: str, context: List[Dict]) -> Dict:
        """
        Computes average ROUGE-L between the response and each context chunk.
        High ROUGE-L means the paper closely mirrors the source — useful as a
        complement to the plagiarism check.
        """
        if not response or not context:
            return {"avg_rouge_l": 0.0, "max_rouge_l": 0.0}
        scores = []
        for chunk in context:
            ref = chunk.get("text", "")
            if ref:
                scores.append(_rouge_l_score(response, ref))
        if not scores:
            return {"avg_rouge_l": 0.0, "max_rouge_l": 0.0}
        return {
            "avg_rouge_l": round(float(np.mean(scores)), 4),
            "max_rouge_l": round(float(max(scores)), 4),
        }

    # ------------------------------------------------------------------
    # Plagiarism risk
    # ------------------------------------------------------------------
    @staticmethod
    def evaluate_plagiarism_risk(
        response: str,
        context: List[Dict],
        sentence_threshold: float = None,   # defaults to Config value
        max_flagged: int = 8,
        max_response_sentences: int = 120,
        max_source_sentences_per_chunk: int = 40,
    ) -> Dict:
        """
        Lightweight plagiarism-risk estimate against retrieved context.
        Threshold lowered from 0.82 → Config.PLAGIARISM_SENTENCE_THRESHOLD (0.65)
        so near-paraphrases are caught too, not just verbatim copies.
        """
        # Import here to avoid circular at module load
        from config.config import Config as _Config
        if sentence_threshold is None:
            sentence_threshold = _Config.PLAGIARISM_SENTENCE_THRESHOLD

        response_sentences = Evaluator._split_sentences(response)[:max_response_sentences]
        source_units = []
        for chunk in context:
            title = chunk.get("metadata", {}).get("title", "Unknown")
            for sent in Evaluator._split_sentences(chunk.get("text", ""))[:max_source_sentences_per_chunk]:
                source_units.append((title, sent))

        if not response_sentences or not source_units:
            return {
                "overall_similarity_pct": 0.0,
                "max_sentence_similarity_pct": 0.0,
                "ngram_overlap_pct": 0.0,
                "flagged_sentences": [],
                "status": "insufficient_text",
            }

        sentence_scores = []
        flagged = []
        for sentence in response_sentences:
            best_ratio = 0.0
            best_title = "Unknown"
            best_source = ""
            for title, source_sent in source_units:
                ratio = SequenceMatcher(
                    None,
                    Evaluator._normalize_text(sentence),
                    Evaluator._normalize_text(source_sent),
                ).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_title = title
                    best_source = source_sent
            sentence_scores.append(best_ratio)
            if best_ratio >= sentence_threshold and len(flagged) < max_flagged:
                flagged.append(
                    {
                        "paper_sentence": sentence,
                        "matched_source_title": best_title,
                        "matched_source_excerpt": best_source[:280],
                        "similarity_pct": round(best_ratio * 100, 2),
                    }
                )

        from config.config import Config as _Config2
        response_ngrams = Evaluator._word_ngrams(response, n=_Config2.NGRAM_SIZE)
        context_ngrams: set = set()
        for chunk in context:
            context_ngrams |= Evaluator._word_ngrams(chunk.get("text", ""), n=_Config2.NGRAM_SIZE)

        overlap = response_ngrams & context_ngrams
        ngram_overlap_pct = (
            (len(overlap) / len(response_ngrams)) * 100 if response_ngrams else 0.0
        )
        overall_similarity_pct = float(np.mean(sentence_scores) * 100) if sentence_scores else 0.0
        max_sentence_similarity_pct = float(max(sentence_scores) * 100) if sentence_scores else 0.0

        return {
            "overall_similarity_pct": round(overall_similarity_pct, 2),
            "max_sentence_similarity_pct": round(max_sentence_similarity_pct, 2),
            "ngram_overlap_pct": round(ngram_overlap_pct, 2),
            "flagged_sentences": flagged,
            "status": "ok",
        }
