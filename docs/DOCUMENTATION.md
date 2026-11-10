# ResearchGPT — Project Documentation

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [UI Features](#ui-features)
4. [Backend Pipeline](#backend-pipeline)
   - [Ingestion](#1-ingestion)
   - [Processing & Chunking](#2-processing--chunking)
   - [Embedding & Vector Store](#3-embedding--vector-store)
   - [Retrieval](#4-retrieval)
   - [Generation](#5-generation)
   - [Evaluation](#6-evaluation)
   - [Analysis](#7-analysis)
   - [Output Generation](#8-output-generation)
   - [History & Caching](#9-history--caching)
5. [Configuration](#configuration)
6. [How to Run](#how-to-run)

---

## Overview

**ResearchGPT** is an agentic Retrieval-Augmented Generation (RAG) system that transforms a research topic into a fully formatted IEEE research paper or literature survey. It fetches real academic papers from arXiv, retrieves relevant content using hybrid search, generates grounded papers via an LLM, and evaluates output quality — all through an interactive Streamlit web UI.

---

## Architecture

```
User Query
    │
    ▼
[Ingestion] ──── arXiv API ────► Download PDFs
    │
    ▼
[Processing] ───────────────────► Extract text, clean, chunk
    │
    ▼
[Embedding] ────────────────────► BAAI/bge-base-en-v1.5 → ChromaDB
    │
    ▼
[Retrieval] ────────────────────► Hybrid BM25 + Vector → Cross-Encoder Rerank
    │
    ▼
[Generation] ───────────────────► LLM (local Ollama, or any OpenAI-compatible API)
    │
    ▼
[Evaluation] ───────────────────► G-Eval (Faithfulness, Relevance), ROUGE-L, Plagiarism
    │
    ▼
[Output] ───────────────────────► IEEE PDF, Word (.docx), CSV/Excel
```

---

## UI Features

### Session Management
- **Recent Research sidebar** — lists all past topics with reload support
- **New Research button** — creates an isolated chat session per topic
- **Persistent history** — previously generated papers and surveys reload from disk

### Home Screen
- Clickable example topic pills for quick-start suggestions
- Welcome message and app tagline

### Settings Panel (⚙)

| Setting | Options | Default |
|---|---|---|
| Author Name / Affiliation / Email | Free text | — |
| Retrieval Strategy | `auto`, `hyde`, `complex`, `standard` | `auto` |
| Survey Paper Count | 3–15 | 10 |
| Top-K Retrieval Chunks | 3–12 | 5 |
| Refresh from arXiv | Toggle | Off |
| Run Quality Evaluation | Toggle | On |

### Main Result View (Three Tabs)

#### Tab 1 — Paper
- Full IEEE-formatted paper with section navigation anchors
- Faithfulness quality badge (Good / Fair / Poor) in the header
- **Quick-edit chips** for one-click refinements:
  - Lengthen Paper
  - Deeper Methodology
  - Strengthen Results
  - Expand Future Work
  - Formal IEEE Tone
  - Rewrite Abstract
- PDF and Word (.docx) download buttons
- Section-to-source attribution (which papers contributed to each section)
- Citation rebuild tool (fixes broken citations from source metadata)

#### Tab 2 — Survey & Analysis
- Structured comparison table for all analyzed papers across 8 fields:
  1. Problem Statement
  2. Objective
  3. Research Gap
  4. Methodology
  5. Features (Focused)
  6. Results & Discussion
  7. Limitations
  8. Future Scope
- Export as CSV or Excel
- Toggle between Table view and Card view
- Direct arXiv links per paper
- Research Gap summary panel

#### Tab 3 — Quality & Sources
- Gauge charts for **Faithfulness** and **Relevance** (scored 1–5)
- LLM-generated reasoning behind each score
- Pipeline stats: source paper count, strategy used, timing breakdown
- Retrieval analytics: chunks retrieved, BM25 vs vector blend ratio, min/avg/max scores
- Paper contribution chart (chunks per source paper)
- Retrieved chunks viewer with individual scores
- Plagiarism report with sentence-level similarity and n-gram overlap

---

## Backend Pipeline

### 1. Ingestion

**File:** `src/ingestion/ingestor.py`

- Fetches papers from arXiv via the `arxiv` Python library with a direct Atom API fallback
- Exponential backoff retries on download failures (2 → 4 → 8 → 16s)
- Rate limiting between downloads (1s default)
- Validates downloaded files (>1000 bytes minimum)
- Falls back to arXiv HTML if PDF is unavailable
- Persists metadata to `_papers_metadata.json` to skip re-downloads on repeat runs

**Key parameters:**

| Parameter | Default |
|---|---|
| RAG_MAX_PAPERS | 5 (fast) / 8 (full) |
| RAG_MAX_RETRIES | 3 |
| RAG_RETRY_DELAY | 2.0s (doubles each retry) |
| DOWNLOAD_RATE_LIMIT | 1.0s between downloads |

---

### 2. Processing & Chunking

**File:** `src/processing/processor.py`

- **PDF extraction** via PyMuPDF (`fitz`) — handles text, tables, and multi-page documents
- Cleans junk lines: page numbers, running headers, arXiv/proceedings boilerplate
- **Chunking** via LangChain `RecursiveCharacterTextSplitter`
- Detects section headings per chunk (Abstract, Introduction, Methodology, etc.)
- Propagates full paper metadata to every chunk

**Chunking parameters:**

| Parameter | Value |
|---|---|
| RAG_CHUNK_SIZE | 1000 chars |
| RAG_CHUNK_OVERLAP | 350 chars (35% overlap) |
| Separators | `\n\n`, `\n`, `. `, ` `, `` |

---

### 3. Embedding & Vector Store

**File:** `src/embedding/vector_store.py`

- **Embedding model:** `BAAI/bge-base-en-v1.5` (via sentence-transformers)
- **Vector database:** ChromaDB (persistent, disk-backed)
- One collection per research topic (e.g., `rag_papers_finetuning_abc123`)
- Supports upsert, semantic query, reset, and bulk retrieval (for BM25 fitting)
- Automatically prunes old collections (keeps 10 most recent)

---

### 4. Retrieval

**File:** `src/retrieval/retriever.py`

All strategies use **Hybrid BM25 + Vector Search**, with strategy-specific blending ratios.

#### Retrieval Strategies

| Strategy | How It Works | BM25 Weight |
|---|---|---|
| **HyDE** | LLM generates a hypothetical answer; that answer is embedded and used for search | 30% |
| **Complex** | Query is decomposed into 2–3 sub-questions; each is retrieved independently and merged | 55% |
| **Standard** | Direct embedding of the raw query + BM25 | 50% |
| **Auto** | Automatically selects strategy based on query characteristics | Varies |

#### Hybrid Merge
- Vector distances are normalized (L2 → inverted similarity)
- BM25 scores are normalized
- Combined: `score = alpha × vector_norm + (1 - alpha) × bm25_norm`
- Deduplication by first 100 characters of document text

#### Cross-Encoder Re-ranking
- Model: `ms-marco-MiniLM-L-12-v2`
- Rescores all 20 candidates with (query, document) pairs
- Section-aware bonus (+0.1) for high-value sections: Results, Methodology, Conclusion, Discussion, Experiment, Evaluation, Analysis, Findings
- Returns top-K after reranking (default: 5)

---

### 5. Generation

**Files:** `src/generation/llm_client.py`, `src/generation/generator.py`

#### LLM Provider Support
- **Ollama** (local, default): `mistral:7b` served at `http://localhost:11434`
- **OpenAI-compatible** (cloud): e.g. Cerebras at `https://api.cerebras.ai/v1`
- **Ollama** (local): via `http://localhost:11434/api/generate`
- Selected with the `RAG_LLM_PROVIDER` environment variable (`ollama` | `openai`)

#### Generation Features
- Context refinement: extracts only query-relevant sentences from each chunk before sending to LLM
- Citation validation: removes hallucinated `[N]` citations not backed by actual sources
- Markdown cleanup: strips bold, italic, code, and heading markers
- Generates full IEEE papers: 8 sections, roman numeral headings, numbered citations
- Streaming support for long responses
- Exponential backoff on rate limits and timeouts (up to 4 retries)

**Key parameters:**

| Parameter | Value |
|---|---|
| LLM_TEMPERATURE | 0.2 |
| LLM_MAX_TOKENS | 8192 |
| MAX_CONTEXT_TOKENS | 3000 chars |
| SECTION_MIN_WORDS | 150 |
| SECTION_MAX_WORDS | 600 |

---

### 6. Evaluation

**File:** `src/evaluation/evaluator.py`

#### LLM-Based Metrics (G-Eval)

| Metric | Scale | Question Asked |
|---|---|---|
| Faithfulness | 1–5 | Are all claims supported by the retrieved context? |
| Relevance | 1–5 | Does the paper address the specific research query? |

Both metrics include a one-paragraph LLM reasoning explanation.

#### Traditional Metrics

| Metric | Description |
|---|---|
| ROUGE-L | F1 score between generated text and source chunks (LCS-based) |
| Hit Rate | Whether retrieved chunks include the expected relevant papers |
| MRR | Mean Reciprocal Rank — position of first relevant result |

#### Plagiarism Detection
- Sentence-level cosine similarity scoring (threshold: 0.65)
- 8-gram overlap detection
- Reports: overall similarity %, max sentence similarity %, n-gram overlap %
- Flags suspicious sentences with matched source

---

### 7. Analysis

**File:** `src/analysis/paper_analyzer.py`

- Fetches papers directly from arXiv Atom API
- Downloads and extracts PDF text (up to 10 pages per paper)
- LLM extracts 8 structured fields per paper (Problem Statement, Objective, Research Gap, Methodology, Features, Results & Discussion, Limitations, Future Scope)
- Falls back to abstract if PDF extraction fails
- Generates a sample IEEE overview paper from the combined survey data
- 1-second delay between LLM calls to avoid rate limits

---

### 8. Output Generation

**Directory:** `src/output_pdf/`

| Output Format | Library | Notes |
|---|---|---|
| IEEE PDF | ReportLab | Two-column layout, proper typography |
| LaTeX → PDF | ReportLab + pdflatex | Full LaTeX template with equations and tables |
| Word (.docx) | python-docx | Editable, preserves IEEE structure |
| CSV / Excel | pandas | Survey analysis table |
| Survey PDF | ReportLab | Combined analysis table + sample overview paper |

---

### 9. History & Caching

**File:** `src/history/paper_history.py`

- Results persisted to disk keyed by topic + strategy + fast_mode hash
- Saved data includes: paper text, evaluation scores, retrieved context, survey rows, timing metrics
- In-process cache with 1-hour TTL to skip re-running the full pipeline
- Base64-encoded PDFs embedded in history JSON for portability
- Load and delete operations supported

---

## Configuration

All settings live in `config/config.py` and are read from the project-root `.env` file.
Every value has a working default, so `.env` only needs the ones you want to change.
Environment variable names are the `RAG_`-prefixed names in the table below.

| Category | Parameter | Default |
|---|---|---|
| Ingestion | RAG_MAX_PAPERS | 5 |
| Ingestion | RAG_MAX_RETRIES | 3 |
| Ingestion | RAG_RETRY_DELAY | 2.0s |
| Chunking | RAG_CHUNK_SIZE | 1000 |
| Chunking | RAG_CHUNK_OVERLAP | 350 |
| Embedding | RAG_EMBEDDING_MODEL | BAAI/bge-base-en-v1.5 |
| Retrieval | RAG_CROSS_ENCODER_MODEL | ms-marco-MiniLM-L-12-v2 |
| Retrieval | RAG_TOP_K | 5 |
| Retrieval | RAG_RETRIEVAL_WINDOW_SIZE | 20 |
| Retrieval | RAG_BM25_ALPHA_HYDE | 0.7 |
| Retrieval | RAG_BM25_ALPHA_COMPLEX | 0.45 |
| Retrieval | RAG_BM25_ALPHA_STANDARD | 0.5 |
| Generation | RAG_LLM_PROVIDER | ollama |
| Generation | RAG_OLLAMA_MODEL | mistral:7b |
| Generation | RAG_OLLAMA_BASE_URL | http://localhost:11434 |
| Generation | RAG_OLLAMA_NUM_CTX | 16384 |
| Generation | RAG_OLLAMA_KEEP_ALIVE | 30m |
| Generation | RAG_OLLAMA_TIMEOUT | 900s |
| Generation | RAG_OPENAI_MODEL | gpt-oss-120b |
| Generation | RAG_LLM_TEMPERATURE | 0.2 |
| Generation | RAG_LLM_MAX_TOKENS | 4096 |
| API | RAG_API_HOST / RAG_API_PORT | 127.0.0.1 / 8001 |
| API | RAG_CORS_ORIGINS | Vite dev + preview origins |
| Survey | RAG_SURVEY_DEFAULT_PAPERS | 10 |
| Survey | RAG_SURVEY_MIN_PAPERS | 3 |
| Survey | RAG_SURVEY_MAX_PAPERS | 15 |
| Evaluation | RAG_PLAGIARISM_THRESHOLD | 0.65 |
| Vector DB | RAG_MAX_STALE_COLLECTIONS | 10 |

---

## How to Run

### Start the Web App

Two processes, from the project root.

```bash
python -m uvicorn api.main:app --port 8001
```

```bash
npm --prefix frontend run dev
```

Then open <http://localhost:5173>. Check the backend with
`curl http://127.0.0.1:8001/api/health`.

The original Streamlit interface is kept as `ui.py` (`streamlit run ui.py`); the React
frontend is the supported UI.

### CLI Commands
```bash
# Run the full pipeline
python main.py run_all --query "your research topic"

# Individual pipeline stages
python main.py ingest --query "topic"       # Download papers only
python main.py index                         # Build vector index only
python main.py retrieve --query "topic"      # Retrieve chunks only
python main.py generate --topic "topic"      # Generate paper only
python main.py evaluate --query "topic"      # Evaluate only
```

### Programmatic Usage
```python
from src.pipeline.ui_pipeline import run_rag_for_ui_pipeline

result = run_rag_for_ui_pipeline(
    topic="Finetuning methods for large language models",
    retrieval_strategy="hyde",
    include_evaluation=True,
    fast_mode=True,
)

print(result["paper_text"])
print(result["faithfulness"])   # 1-5 score
print(result["relevance"])      # 1-5 score
```

### LLM Provider Configuration (`.env`)

```env
# Local Ollama (default - no API key needed)
RAG_LLM_PROVIDER=ollama
RAG_OLLAMA_MODEL=mistral:7b
RAG_OLLAMA_BASE_URL=http://localhost:11434
# Ollama defaults to a 4096-token window, which truncates this pipeline's
# prompts. Keep this raised or the model writes without its retrieved context.
RAG_OLLAMA_NUM_CTX=16384

# OR an OpenAI-compatible API (cloud)
RAG_LLM_PROVIDER=openai
CEREBRAS_API_KEY=your_key_here
RAG_OPENAI_BASE_URL=https://api.cerebras.ai/v1
RAG_OPENAI_MODEL=gpt-oss-120b
```
