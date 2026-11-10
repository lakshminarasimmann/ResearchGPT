# ResearchGPT

Turn a research topic into a **literature survey table** and a **cited, IEEE-style paper**, grounded in real papers pulled from arXiv.

Runs fully offline against a local **Ollama** model (`mistral:7b` by default) — no API key required.

```
Topic ──▶ arXiv search ──▶ PDF parse + chunk ──▶ embed (ChromaDB)
                                                     │
                       hybrid BM25 + vector search ◀─┘
                                │
                   cross-encoder rerank ──▶ LLM drafts the paper
                                │
          self-evaluation (faithfulness / relevance / ROUGE-L / similarity)
                                │
                    PDF · LaTeX PDF · Word · Excel · CSV
```

---

## 1. Requirements

| | |
|---|---|
| Python | 3.10+ (tested on 3.13) |
| Node.js | 18+ (for the web UI) |
| [Ollama](https://ollama.com) | running locally, with a model pulled |
| `pdflatex` | *optional* — only for the "LaTeX PDF" export |

---

## 2. Setup

```bash
pip install -r requirements.txt
```

```bash
npm --prefix frontend install
```

Pull the model (this is the one `.env` is configured for):

```bash
ollama pull mistral:7b
```

Configuration lives in [`.env`](.env) — it is already set up for local Ollama. Copy
[`.env.example`](.env.example) if you ever need to start over. Nothing else needs editing.

---

## 3. Run

Two processes: the API and the web UI.

**Terminal 1 — API** (http://127.0.0.1:8001)

```bash
python -m uvicorn api.main:app --port 8001
```

**Terminal 2 — Web UI** (http://localhost:5173)

```bash
npm --prefix frontend run dev
```

Then open <http://localhost:5173>. The sidebar shows a live status badge: green means
the API is up and Ollama is serving the configured model.

Check the backend on its own at any time:

```bash
curl http://127.0.0.1:8001/api/health
```

### Command line (no UI)

```bash
python main.py run_all --query "Self-Healing Large Language Models"
```

| Command | Arguments | Description |
| :--- | :--- | :--- |
| `run_all` | `--query "..."` | Full pipeline: ingest → index → generate → evaluate. |
| `ingest` | `--query "..." --max 5` | Search arXiv and download PDFs. |
| `index` | *(none)* | Parse PDFs and rebuild the vector index. |
| `retrieve` | `--query "..." --k 5` | Debug retrieval: HyDE, candidates, rerank scores. |
| `generate` | `--topic "..."` | Generate a paper from the current index. |
| `evaluate` | `--query "..."` | Run the evaluation metrics. |

### Legacy Streamlit UI

`ui.py` is the original single-file Streamlit interface, kept for reference. The React
frontend is the supported UI.

```bash
streamlit run ui.py
```

---

## 4. Configuration

Everything is read from `.env` by [`config/config.py`](config/config.py); every value has a
working default, so you only set what you want to change.

### LLM provider

| Variable | Default | Notes |
|---|---|---|
| `RAG_LLM_PROVIDER` | `ollama` | `ollama` (local) or `openai` (any OpenAI-compatible API) |
| `RAG_OLLAMA_BASE_URL` | `http://localhost:11434` | Where the Ollama daemon listens |
| `RAG_OLLAMA_MODEL` | `mistral:7b` | Must match a model from `ollama list` |
| `RAG_OLLAMA_NUM_CTX` | `16384` | **Important** — see below |
| `RAG_OLLAMA_KEEP_ALIVE` | `30m` | Keeps the model in memory between calls |
| `RAG_OLLAMA_TIMEOUT` | `900` | Seconds per request |
| `RAG_LLM_MAX_TOKENS` | `4096` | Max tokens generated per call |
| `RAG_LLM_TEMPERATURE` | `0.2` | |

> **Why `num_ctx` matters.** Ollama loads models with a small default context window
> (4096 tokens). This pipeline builds long prompts containing the retrieved papers, so
> with the default the model would silently receive only a fraction of its context and
> write from almost nothing. `RAG_OLLAMA_NUM_CTX=16384` fixes that. Lower it to `8192`
> if you are short on RAM or VRAM.

To use a remote OpenAI-compatible API instead:

```ini
RAG_LLM_PROVIDER=openai
CEREBRAS_API_KEY=your-key
RAG_OPENAI_BASE_URL=https://api.cerebras.ai/v1
RAG_OPENAI_MODEL=gpt-oss-120b
```

### Retrieval & pipeline

| Variable | Default | Notes |
|---|---|---|
| `RAG_TOP_K` | `5` | Chunks kept after reranking |
| `RAG_MAX_PAPERS` | `5` | Papers downloaded per topic |
| `RAG_SURVEY_DEFAULT_PAPERS` | `10` | Papers in the survey table |
| `RAG_CHUNK_SIZE` / `RAG_CHUNK_OVERLAP` | `1000` / `350` | |
| `RAG_EMBEDDING_MODEL` | `BAAI/bge-base-en-v1.5` | |
| `RAG_CROSS_ENCODER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-12-v2` | Reranker |
| `RAG_BM25_ALPHA` | `0.5` | 0 = pure BM25, 1 = pure vector |

### Server

| Variable | Default |
|---|---|
| `RAG_API_HOST` / `RAG_API_PORT` | `127.0.0.1` / `8001` |
| `RAG_CORS_ORIGINS` | the Vite dev and preview origins |
| `RAG_LOG_LEVEL` | `INFO` |

The frontend reads `VITE_API_URL` from `frontend/.env` (production build) and
`frontend/.env.development` (dev server).

---

## 5. Project layout

```text
ResearchGPT/
├── .env                 # active configuration (Ollama + mistral:7b)
├── .env.example         # template
├── main.py              # CLI entry point
├── ui.py                # legacy Streamlit UI
├── requirements.txt
│
├── api/                 # FastAPI backend
│   ├── main.py          #   routes, health, exports
│   ├── jobs.py          #   in-memory background job runner
│   └── schemas.py       #   request models
│
├── config/config.py     # every setting, read from .env
│
├── src/
│   ├── ingestion/       # arXiv search + download
│   ├── processing/      # PDF parsing + chunking
│   ├── embedding/       # ChromaDB vector store
│   ├── retrieval/       # hybrid search, HyDE, reranking
│   ├── generation/      # llm_client.py (transport) + generator.py (prompts)
│   ├── evaluation/      # G-Eval, ROUGE-L, similarity
│   ├── analysis/        # survey table extraction
│   ├── output_pdf/      # PDF / LaTeX / DOCX writers
│   ├── history/         # saved results
│   └── pipeline/        # end-to-end orchestration
│
├── frontend/            # React + TypeScript + Vite UI
│   └── src/
│       ├── App.tsx      #   shell, sessions, job polling
│       ├── api.ts       #   typed backend client
│       ├── components/  #   health badge, progress, landing, theme
│       ├── index.css    #   design tokens (light + dark)
│       └── App.css      #   component styles
│
├── tests/               # Playwright suites (react/ + legacy Streamlit)
├── scripts/             # documentation PDF generators
├── docs/                # DOCUMENTATION.md, paper source, generated PDFs
│
├── data/                # downloaded papers, vector DB, history  (git-ignored)
├── output/              # generated papers                       (git-ignored)
└── logs/                # rotating log file                      (git-ignored)
```

### How the pieces fit

* **`src/generation/llm_client.py`** is the only place that talks to an LLM. It handles
  both providers, retries, timeouts and the Ollama `num_ctx` / `keep_alive` options, and
  exposes `LLMClient.health()`, which backs `/api/health`.
* **`src/generation/generator.py`** builds prompts and post-processes output. It
  re-exports `LLMClient` so older imports keep working.
* **`api/jobs.py`** runs long pipeline calls on daemon threads; the frontend polls
  `/api/jobs/{id}` for progress. Finished jobs are pruned after
  `RAG_JOB_RETENTION_SECONDS`.

---

## 6. Tests

```bash
npx playwright test --config=playwright.react.config.ts
```

25 end-to-end tests covering the React UI against a mocked backend — no model or network
needed. `playwright.config.ts` targets the legacy Streamlit UI instead.

---

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Sidebar badge says **API offline** | The backend is not running. Start uvicorn (step 3). |
| Badge is red, "not ready" | Hover it. Usually Ollama is stopped (`ollama serve`) or the model was never pulled (`ollama pull mistral:7b`). |
| Generation is very slow | A 7B model on CPU is slow; this is expected. Lower `RAG_SURVEY_DEFAULT_PAPERS` and `RAG_TOP_K`, or lower `RAG_OLLAMA_NUM_CTX`. |
| Paper ignores the retrieved sources | `RAG_OLLAMA_NUM_CTX` is too small for the prompt — raise it. |
| "LaTeX PDF" export fails | `pdflatex` is not installed. The normal PDF export does not need it. |
| Out of memory loading the model | Lower `RAG_OLLAMA_NUM_CTX` to `8192`, or use a smaller model. |
| Word / Excel export fails | `pip install -r requirements.txt` — `python-docx` and `openpyxl` are required. |

---

## 8. How it works

**HyDE** — short questions embed poorly against long technical papers, so the model first
drafts a hypothetical abstract and *that* is embedded to find real matches.

**Hybrid retrieval** — BM25 (exact terms) and vector search (meaning) are blended with
`RAG_BM25_ALPHA`, then a cross-encoder rescores the shortlist by reading query and
passage together.

**Sub-question decomposition** — "compare X and Y" is split into independent retrievals
per sub-question, then synthesised.

**G-Eval** — a second LLM pass scores the draft 1–5 for *faithfulness* (is every claim
supported by the retrieved text?) and *relevance* (does it answer the topic?). Both
scores, and the judge's reasoning, are shown in the UI.

Scores of 4–5 are good; 3 means the context was thin; 1–2 points at a retrieval problem
rather than a generation one.
