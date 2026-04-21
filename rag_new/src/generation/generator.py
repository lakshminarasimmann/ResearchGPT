import json
import logging
import os
import re
import sys
from typing import Dict, Generator, List

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config.config import Config
from src.output_pdf.pdf_generator import generate_ieee_pdf
from src.output_pdf.latex_generator import generate_ieee_latex_pdf

logger = logging.getLogger(__name__)

# Approximate chars per token for token-budget estimation
_CHARS_PER_TOKEN = 4


class LLMClient:
    def __init__(self, provider=Config.LLM_PROVIDER):
        self.provider = provider

    # ------------------------------------------------------------------
    # Token helpers
    # ------------------------------------------------------------------
    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Fast approximation: 1 token ≈ 4 characters."""
        return max(1, len(text) // _CHARS_PER_TOKEN)

    @staticmethod
    def truncate_to_token_budget(text: str, max_tokens: int) -> str:
        max_chars = max_tokens * _CHARS_PER_TOKEN
        if len(text) <= max_chars:
            return text
        return text[:max_chars]

    # ------------------------------------------------------------------
    # Generation (non-streaming)
    # ------------------------------------------------------------------
    def generate(self, prompt: str) -> str:
        token_est = self.estimate_tokens(prompt)
        logger.debug("Generating with ~%d prompt tokens.", token_est)
        if self.provider == "ollama":
            return self._generate_ollama(prompt)
        elif self.provider == "openai":
            return self._generate_openai(prompt)
        else:
            raise ValueError(f"Unknown LLM provider: {self.provider}")

    def _generate_ollama(self, prompt: str) -> str:
        url = "http://localhost:11434/api/generate"
        payload = {
            "model": Config.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": Config.LLM_TEMPERATURE,
                "num_predict": Config.LLM_MAX_TOKENS,
            },
        }
        try:
            response = requests.post(url, json=payload, timeout=600)
            response.raise_for_status()
            return response.json().get("response", "No response from model.")
        except Exception as e:
            raise RuntimeError(f"Ollama timeout or failure: {e}")

    def _generate_openai(self, prompt: str) -> str:
        from openai import OpenAI
        api_key = Config.CEREBRAS_API_KEY or os.environ.get("CEREBRAS_API_KEY")
        client = OpenAI(api_key=api_key, base_url=Config.CEREBRAS_BASE_URL)
        response = client.chat.completions.create(
            model=Config.OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=Config.LLM_TEMPERATURE,
            max_tokens=Config.LLM_MAX_TOKENS,
        )
        return response.choices[0].message.content or ""

    # ------------------------------------------------------------------
    # Streaming generation
    # ------------------------------------------------------------------
    def stream(self, prompt: str) -> Generator[str, None, None]:
        """Yields text chunks as they arrive from the model."""
        if self.provider == "ollama":
            yield from self._stream_ollama(prompt)
        elif self.provider == "openai":
            yield from self._stream_openai(prompt)
        else:
            raise ValueError(f"Unknown LLM provider: {self.provider}")

    def _stream_ollama(self, prompt: str) -> Generator[str, None, None]:
        url = "http://localhost:11434/api/generate"
        payload = {
            "model": Config.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": Config.LLM_TEMPERATURE,
                "num_predict": Config.LLM_MAX_TOKENS,
            },
        }
        with requests.post(url, json=payload, stream=True, timeout=600) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line:
                    try:
                        chunk = json.loads(line)
                        token = chunk.get("response", "")
                        if token:
                            yield token
                        if chunk.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue

    def _stream_openai(self, prompt: str) -> Generator[str, None, None]:
        from openai import OpenAI
        api_key = Config.CEREBRAS_API_KEY or os.environ.get("CEREBRAS_API_KEY")
        client = OpenAI(api_key=api_key, base_url=Config.CEREBRAS_BASE_URL)
        with client.chat.completions.create(
            model=Config.OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=Config.LLM_TEMPERATURE,
            max_tokens=Config.LLM_MAX_TOKENS,
            stream=True,
        ) as stream:
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta


# ======================================================================
class RAGGenerator:
    def __init__(self):
        self.llm = LLMClient()

    # ------------------------------------------------------------------
    # Markdown cleanup (small models often ignore "no markdown" instruction)
    # ------------------------------------------------------------------
    @staticmethod
    def strip_markdown(text: str) -> str:
        """Remove markdown artifacts that smaller models tend to insert."""
        # Remove bold/italic markers: **text** → text, *text* → text
        text = re.sub(r'\*{1,3}([^*\n]+?)\*{1,3}', r'\1', text)
        # Remove heading hashes: ## Heading → Heading
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        # Remove inline code backticks: `code` → code
        text = re.sub(r'`([^`\n]+?)`', r'\1', text)
        # Remove bullet/dash list markers at line start: - item or * item
        text = re.sub(r'^\s*[-*]\s+', '', text, flags=re.MULTILINE)
        # Remove horizontal rules: ---
        text = re.sub(r'^\s*-{3,}\s*$', '', text, flags=re.MULTILINE)
        # Collapse 3+ blank lines to 2
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    # ------------------------------------------------------------------
    # Context management
    # ------------------------------------------------------------------
    def refine_contexts(self, query: str, context_chunks: List[Dict]) -> List[Dict]:
        refined = []
        for chunk in context_chunks:
            text = self.llm.truncate_to_token_budget(chunk["text"], 800)
            prompt = (
                f'Extract only the sentences from the following text that are directly relevant '
                f'to the query: "{query}"\n'
                f'If the text contains no relevant information, output "IRRELEVANT".\n\n'
                f'TEXT:\n{text}\n\nRELEVANT SENTENCES:'
            )
            result = self.llm.generate(prompt).strip()
            if "IRRELEVANT" not in result and len(result) > 10:
                refined_chunk = chunk.copy()
                refined_chunk["text"] = result
                refined.append(refined_chunk)
        return refined if refined else context_chunks

    def _compact_context(
        self,
        context_chunks: List[Dict],
        max_chunks: int = 5,
        max_chars_per_chunk: int = 1800,
    ) -> List[Dict]:
        compacted = []
        for chunk in context_chunks[:max_chunks]:
            updated = chunk.copy()
            updated["text"] = (updated.get("text") or "")[:max_chars_per_chunk]
            compacted.append(updated)
        return compacted

    # ------------------------------------------------------------------
    # Citation validation
    # ------------------------------------------------------------------
    def validate_citations(self, paper_text: str, context_chunks: List[Dict]) -> str:
        """
        Removes hallucinated [N] citations that cannot be matched to any
        source title in the retrieved context.  Returns cleaned paper text.
        """
        source_titles = [
            (c.get("metadata", {}).get("title") or "").lower()
            for c in context_chunks
        ]
        num_sources = len(source_titles)
        if num_sources == 0:
            return paper_text

        def _keep_citation(m: re.Match) -> str:
            num = int(m.group(1))
            # Keep if citation number is within the range of actual sources
            return m.group(0) if 1 <= num <= num_sources else ""

        return re.sub(r"\[(\d+)\]", _keep_citation, paper_text)

    # ------------------------------------------------------------------
    # Prompt assembly with section-balance guidance
    # ------------------------------------------------------------------
    def assemble_prompt(
        self, query: str, context_chunks: List[Dict], user_preferences: str = ""
    ) -> str:
        context_str = "\n\n".join(
            f"Source [{i+1}]: {c['metadata'].get('title', 'Unknown')}\nText: {c['text']}"
            for i, c in enumerate(context_chunks)
        )
        min_w = Config.SECTION_MIN_WORDS
        max_w = Config.SECTION_MAX_WORDS

        preferences_block = ""
        if user_preferences and user_preferences.strip():
            preferences_block = f"""
AUTHOR PREFERENCES (follow these exactly while writing):
{user_preferences.strip()}

"""

        prompt = f"""You are an expert university researcher writing a formal IEEE conference paper.

TASK:
Write a COMPLETE IEEE-style research paper using ONLY the provided source context below.

ABSOLUTE CONSTRAINTS:
- Output ONLY plain academic text — no markdown, no bullet points, no numbered lists inside paragraphs
- Do NOT include or reference figures, tables, images, charts, or equations
- Do NOT include placeholders for figures or tables
- Use formal third-person academic writing throughout
- Use Roman numerals for all main section headings
- Do NOT fabricate results, statistics, or claims not present in the source context
- Every factual claim must be backed by an inline citation [1], [2], etc.
- References MUST come ONLY from the given source context
- Do NOT invent citations

SECTION LENGTH GUIDANCE:
Each section should be between {min_w} and {max_w} words.
Distribute content evenly; no single section should be disproportionately long.
{preferences_block}
SECTION-BY-SECTION GUIDANCE:
- Abstract: State the research problem, methodology, and key findings in ~150 words.
- Index Terms: 5–8 IEEE-style keywords from the source material.
- I. INTRODUCTION: Motivate the topic. State the problem being addressed and why it matters. End with a brief outline of the paper's contributions.
- II. LITERATURE REVIEW: Summarise prior work from the source context. Cite every source. Group related approaches together.
- III. PROBLEM DEFINITION: Define the core technical or research problem precisely, drawing on the problem statements in the source context.
- IV. RELATED WORK: Identify research gaps in existing approaches and explain how the surveyed works relate to and differ from each other.
- V. METHODOLOGY: Describe the algorithms, techniques, and models used across the source papers. Group similar approaches.
- VI. RESULTS: Report exact performance metrics and values from the source context. Cite the source for every number. Do not invent any metric.
- VII. DISCUSSION: Analyse the results and limitations of existing approaches. Connect limitations to open research gaps.
- VIII. CONCLUSION: Synthesise key findings and state concrete future directions suggested by the source papers.
- REFERENCES: IEEE numeric format. One entry per cited source.

MANDATORY PAPER STRUCTURE:

Title (Centered, Title Case)

Author Name(s)
Affiliation
Email

Abstract—

Index Terms—

I. INTRODUCTION

II. LITERATURE REVIEW

III. PROBLEM DEFINITION

IV. RELATED WORK

V. METHODOLOGY

VI. RESULTS

VII. DISCUSSION

VIII. CONCLUSION

REFERENCES

RESEARCH QUERY:
{query}

SOURCE CONTEXT:
{context_str}

Generate the full IEEE conference-style paper now."""
        return prompt

    # ------------------------------------------------------------------
    # Rewrite pass 1 — reduce verbatim overlap with sources
    # ------------------------------------------------------------------
    def rewrite_for_originality(
        self,
        query: str,
        paper_text: str,
        context_chunks: List[Dict],
        target_similarity_pct: float = 25.0,
    ) -> str:
        context_titles = ", ".join(
            c.get("metadata", {}).get("title", "Unknown") for c in context_chunks
        )
        prompt = f"""You are an academic writing editor focused on ORIGINALITY.
Your only goal: reduce verbatim overlap between the paper and its source documents.

RULES:
- Paraphrase sentences that closely mirror source text
- Vary sentence structure: split long sentences, merge short ones
- Use synonyms for repeated technical terms where meaning is preserved
- Keep all factual claims, citation numbers [1][2], and section headings intact
- Do NOT invent new facts or references
- Do NOT change the IEEE section structure
- Target average sentence similarity ≈ {target_similarity_pct}% (not zero — just not copy-paste)

QUERY: {query}
SOURCE TITLES: {context_titles}

PAPER:
{paper_text}

OUTPUT:
Return only the rewritten full paper text."""
        return self.llm.generate(prompt).strip()

    # ------------------------------------------------------------------
    # Rewrite pass 2 — humanise the writing style
    # ------------------------------------------------------------------
    def humanize_writing(self, paper_text: str) -> str:
        prompt = f"""You are a writing coach improving the naturalness of an academic paper.
Your only goal: make the writing sound like a real researcher wrote it, not an AI.

RULES:
- Vary sentence length: mix short punchy sentences with longer analytical ones
- Remove overused AI phrases such as:
  "it is worth noting", "it is important to", "it is crucial", "furthermore",
  "in conclusion", "this paper aims to", "leverages", "delves into",
  "in the realm of", "showcases", "underscores", "highlights the importance"
- Prefer active voice where natural; avoid passive when it makes prose stiff
- Do NOT start consecutive paragraphs with the same word
- Keep all citation numbers [1][2], section headings, and factual claims intact
- Do NOT invent new content or references
- Maintain IEEE academic register — formal but readable, not robotic

PAPER:
{paper_text}

OUTPUT:
Return only the revised full paper text."""
        return self.llm.generate(prompt).strip()

    # ------------------------------------------------------------------
    # Page-count utilities
    # ------------------------------------------------------------------
    def estimate_page_count(self, paper_text: str, words_per_page: int = 500) -> float:
        words = re.findall(r"\b\w+\b", paper_text or "")
        return round(len(words) / max(words_per_page, 1), 2) if words else 0.0

    def expand_to_min_pages(
        self,
        query: str,
        paper_text: str,
        context_chunks: List[Dict],
        min_pages: int = 5,
        max_passes: int = 1,
    ) -> str:
        target_words = max(1200, int(min_pages * 500))
        current_words = len(re.findall(r"\b\w+\b", paper_text or ""))
        if current_words >= target_words:
            return paper_text

        context_titles = ", ".join(
            c.get("metadata", {}).get("title", "Unknown") for c in context_chunks
        )
        expanded = paper_text
        for _ in range(max(1, min(max_passes, 2))):
            if len(re.findall(r"\b\w+\b", expanded or "")) >= target_words:
                break
            prompt = f"""You are an IEEE academic writing assistant.
Expand the PAPER to at least {target_words} words while preserving technical accuracy.
Keep the same paper topic and structure. Expand methodology, related work, and discussion.
Do not use markdown/code fences. Do not invent references outside source context.

QUERY: {query}
SOURCE TITLES: {context_titles}

CURRENT PAPER:
{expanded}

OUTPUT:
Return only the expanded full paper text."""
            candidate = self.llm.generate(prompt).strip()
            if candidate and len(candidate) > len(expanded):
                expanded = candidate
        return expanded

    # ------------------------------------------------------------------
    # Structured / LaTeX generation
    # ------------------------------------------------------------------
    def clean_title(self, title: str) -> str:
        return title.title()

    def safe_filename(self, text: str, fallback: str = "paper") -> str:
        sanitized = re.sub(r"\s+", "_", text.strip())
        sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", sanitized)
        sanitized = re.sub(r"_+", "_", sanitized).strip("._")
        return sanitized or fallback

    def generate_pdf(self, query: str, paper_text: str) -> str:
        safe_name = self.safe_filename(query, fallback="ieee_paper")
        pdf_path = generate_ieee_pdf(
            paper_text,
            title=self.clean_title(query),
            output_dir=Config.OUTPUT_DIR,
            filename=f"{safe_name}_IEEE",
        )
        return str(pdf_path) if pdf_path else None

    def generate_structured_ieee(self, query: str, context_chunks: List[Dict]) -> Dict:
        def _extract_json_block(text: str):
            if not text:
                return None
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
                cleaned = re.sub(r"\s*```$", "", cleaned)
            try:
                return json.loads(cleaned)
            except Exception:
                pass
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(cleaned[start: end + 1])
                except Exception:
                    pass
            return None

        def _normalize_structured(obj: Dict) -> Dict:
            title = obj.get("title", self.clean_title(query))
            author = obj.get("author", "ResearchGPT")
            if isinstance(author, list):
                author = ", ".join(str(a) for a in author if a)
            keywords = obj.get("keywords", [])
            if not isinstance(keywords, list):
                keywords = [str(keywords)]
            sections = []
            for sec in (obj.get("sections") or []):
                if not isinstance(sec, dict):
                    continue
                t = str(sec.get("title", "")).strip()
                c = str(sec.get("content", "")).strip()
                if t and c:
                    sections.append({"title": t, "content": c})
            references = []
            for ref in (obj.get("references") or []):
                if isinstance(ref, dict) and ref.get("text"):
                    references.append({"text": str(ref["text"])})
            return {
                "title": str(title),
                "author": str(author) if author else "ResearchGPT",
                "abstract": str(obj.get("abstract", "")).strip(),
                "keywords": [str(k).strip() for k in keywords if str(k).strip()],
                "sections": sections,
                "references": references,
            }

        context_str = "\n\n".join(
            f"Source: {c['metadata'].get('title', 'Unknown')}\nText: {c['text'][:1500]}"
            for c in context_chunks
        )
        prompt = f"""Return ONLY valid JSON with keys:
title, author, abstract, keywords (array), sections (array of {{title, content}}), references (array of {{text}})
Keep IEEE style and use only grounded context.
References rules:
- unique references only (no duplicates)
- each reference must be complete in one line
- do not output numbered prefixes like [1], [2]

Query:
{query}

Context:
{context_str}"""
        raw = self.llm.generate(prompt).strip()
        parsed = _extract_json_block(raw)
        if parsed and isinstance(parsed, dict):
            normalized = _normalize_structured(parsed)
            if normalized["sections"] and normalized["abstract"]:
                return normalized

        fallback_intro = " ".join(
            (c.get("text") or "")[:700].strip()
            for c in context_chunks[:3]
            if c.get("text")
        )
        fallback_intro = re.sub(r"\s+", " ", fallback_intro).strip()
        return {
            "title": self.clean_title(query),
            "author": "ResearchGPT",
            "abstract": "This paper surveys methodologies using retrieved academic sources.",
            "keywords": ["RAG", "IEEE", "Literature Review"],
            "sections": [{"title": "Introduction", "content": fallback_intro or "No content generated."}],
            "references": [{"text": c.get("metadata", {}).get("title", "Unknown")} for c in context_chunks],
        }

    def generate_latex_pdf(self, query: str, context_chunks: List[Dict]) -> Dict:
        safe_name = self.safe_filename(query, fallback="ieee_latex_paper")
        structured = self.generate_structured_ieee(query, context_chunks)
        return generate_ieee_latex_pdf(
            structured=structured,
            output_dir=Config.OUTPUT_DIR,
            filename=f"{safe_name}_IEEE_LATEX",
        )

    def generate_latex_pdf_from_paper_text(
        self, query: str, paper_text: str, context_chunks: List[Dict]
    ) -> Dict:
        safe_name = self.safe_filename(query, fallback="ieee_latex_paper")
        abstract = ""
        sections = []
        references = [
            {"text": c.get("metadata", {}).get("title", "Unknown")}
            for c in context_chunks
            if c.get("metadata", {}).get("title")
        ]

        text = (paper_text or "").replace("\r\n", "\n")
        m = re.search(r"(?is)\bABSTRACT\b[:\s-]*(.*?)(?:\n\s*I\.\s|$)", text)
        if m:
            abstract = m.group(1).strip()

        # Skip REFERENCES section as a body section — but capture its content for bibliography
        _SKIP_TITLES = {"references", "reference", "bibliography"}
        inline_refs: List[Dict] = []

        section_pat = re.compile(
            r"(?ms)^\s*([IVXLC]+)\.\s+([^\n]+)\n(.*?)(?=^\s*[IVXLC]+\.\s+[^\n]+\n|\Z)"
        )
        for sm in section_pat.finditer(text):
            title = sm.group(2).strip()
            body = sm.group(3).strip()
            if title.lower().strip() in _SKIP_TITLES:
                # Parse individual reference entries like "[1] Author et al., ..."
                for ref_line in re.findall(r'\[\d+\]\s+([^\[]+)', body):
                    cleaned = ref_line.strip().rstrip()
                    if cleaned:
                        inline_refs.append({"text": cleaned})
                continue
            # Strip any inline [N] reference lines at the end of a section body
            body = re.sub(r'\n\s*\[\d+\][^\n]*', '', body).strip()
            if body:
                sections.append({"title": title.title(), "content": body})

        # Prefer references parsed from the paper text; fall back to context chunk titles
        if inline_refs:
            references = inline_refs

        if not sections:
            sections = [{"title": "Main Discussion", "content": text[:12000]}]
        if not abstract:
            abstract = "This paper presents a literature review based on retrieved academic context."

        structured = {
            "title": self.clean_title(query),
            "author": "ResearchGPT",
            "abstract": abstract,
            "keywords": ["RAG", "IEEE", "Literature Review"],
            "sections": sections,
            "references": references,
        }
        return generate_ieee_latex_pdf(
            structured=structured,
            output_dir=Config.OUTPUT_DIR,
            filename=f"{safe_name}_IEEE_LATEX",
        )

    # ------------------------------------------------------------------
    # Post-generation refinement
    # ------------------------------------------------------------------
    def refine_paper(
        self,
        topic: str,
        paper_text: str,
        context_chunks: List[Dict],
        instruction: str,
    ) -> str:
        """Apply a targeted user instruction to edit the existing paper."""
        context_titles = ", ".join(
            c.get("metadata", {}).get("title", "Unknown") for c in context_chunks[:5]
        )
        context_sample = "\n\n".join(
            f"Source [{i+1}]: {c.get('metadata', {}).get('title', 'Unknown')}\n"
            f"{(c.get('text') or '')[:800]}"
            for i, c in enumerate(context_chunks[:3])
        )
        prompt = f"""You are an expert academic editor working on an IEEE research paper about "{topic}".

USER INSTRUCTION: {instruction}

Apply the instruction precisely and return the complete revised paper.
- Keep all sections that are NOT affected by the instruction unchanged
- Preserve all [N] citation numbers and section headings
- Do NOT use markdown, bullet points, or code fences
- Maintain IEEE academic writing style
- If the instruction asks to add content, draw from the SOURCE CONTEXT below

SOURCE CONTEXT (for reference if expanding content):
{context_sample}

AVAILABLE SOURCES: {context_titles}

CURRENT PAPER:
{paper_text}

OUTPUT:
Return only the complete revised paper text."""
        result = self.strip_markdown(self.llm.generate(prompt))
        return result if result else paper_text

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def generate_review(
        self,
        query: str,
        context_chunks: List[Dict],
        refine_context: bool = False,
        fast_generation: bool = False,
        generate_pdf_output: bool = False,
        user_preferences: str = "",
    ) -> Dict:
        contexts = context_chunks
        if refine_context:
            logger.info("Refining context chunks…")
            contexts = self.refine_contexts(query, context_chunks)
            logger.info("Context refined: %d → %d chunks.", len(context_chunks), len(contexts))

        max_chunks = 6 if fast_generation else 9
        max_chars = 1800 if fast_generation else Config.MAX_CONTEXT_TOKENS
        contexts = self._compact_context(contexts, max_chunks=max_chunks, max_chars_per_chunk=max_chars)

        # Check token budget
        prompt = self.assemble_prompt(query, contexts, user_preferences=user_preferences)
        token_est = LLMClient.estimate_tokens(prompt)
        logger.info("Prompt token estimate: ~%d tokens.", token_est)

        paper_text = self.llm.generate(prompt)

        # Strip any markdown the model may have inserted despite instructions
        paper_text = self.strip_markdown(paper_text)

        # Validate citations against actual sources
        paper_text = self.validate_citations(paper_text, contexts)

        pdf_path = None
        if generate_pdf_output:
            pdf_path = self.generate_pdf(query, paper_text)

        return {"paper_text": paper_text, "pdf_path": pdf_path}

    def stream_review(
        self,
        query: str,
        context_chunks: List[Dict],
        fast_generation: bool = False,
        user_preferences: str = "",
    ) -> Generator[str, None, None]:
        """
        Streaming variant of generate_review.
        Yields text tokens as they arrive from the model.
        """
        max_chunks = 6 if fast_generation else 9
        max_chars = 1800 if fast_generation else Config.MAX_CONTEXT_TOKENS
        contexts = self._compact_context(context_chunks, max_chunks=max_chunks, max_chars_per_chunk=max_chars)
        prompt = self.assemble_prompt(query, contexts, user_preferences=user_preferences)
        yield from self.llm.stream(prompt)
