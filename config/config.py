import os
import logging
import logging.handlers

from dotenv import load_dotenv

# Load .env from the project root (the folder that holds main.py / api / src).
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))


def _env_str(name: str, default: str) -> str:
    """os.getenv that also treats an empty/whitespace value as 'unset'."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env_str(name, str(default)))
    except ValueError:
        logging.getLogger(__name__).warning("%s is not an integer - using %s.", name, default)
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env_str(name, str(default)))
    except ValueError:
        logging.getLogger(__name__).warning("%s is not a number - using %s.", name, default)
        return default


def _env_bool(name: str, default: bool) -> bool:
    return _env_str(name, "true" if default else "false").lower() in ("1", "true", "yes", "on")


class Config:
    # -- Paths ---------------------------------------------------------------
    BASE_DIR = _PROJECT_ROOT
    DATA_DIR = os.path.join(BASE_DIR, "data")
    ASSETS_DIR = os.path.join(BASE_DIR, "assets")
    PAPERS_DIR = os.path.join(DATA_DIR, "papers")
    DB_DIR = os.path.join(DATA_DIR, "vector_db")
    HISTORY_DIR = os.path.join(DATA_DIR, "history")
    OUTPUT_DIR = os.path.join(BASE_DIR, "output")
    UI_BACKGROUND_IMAGE_PATH = _env_str(
        "RAG_UI_BACKGROUND_IMAGE",
        os.path.join(ASSETS_DIR, "background.png"),
    )

    # -- Ingestion -----------------------------------------------------------
    MAX_PAPERS = _env_int("RAG_MAX_PAPERS", 5)
    MAX_RETRIES = _env_int("RAG_MAX_RETRIES", 3)
    RETRY_DELAY = _env_float("RAG_RETRY_DELAY", 2.0)                  # seconds, doubles each retry
    DOWNLOAD_RATE_LIMIT = _env_float("RAG_DOWNLOAD_RATE_LIMIT", 1.0)  # seconds between downloads

    # -- Chunking ------------------------------------------------------------
    CHUNK_SIZE = _env_int("RAG_CHUNK_SIZE", 1000)
    CHUNK_OVERLAP = _env_int("RAG_CHUNK_OVERLAP", 350)

    # -- Embedding -----------------------------------------------------------
    EMBEDDING_MODEL_NAME = _env_str("RAG_EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
    CROSS_ENCODER_MODEL = _env_str("RAG_CROSS_ENCODER_MODEL", "cross-encoder/ms-marco-MiniLM-L-12-v2")

    # -- Vector DB -----------------------------------------------------------
    COLLECTION_NAME = _env_str("RAG_COLLECTION_NAME", "rag_papers")
    MAX_STALE_COLLECTIONS = _env_int("RAG_MAX_STALE_COLLECTIONS", 10)  # delete oldest after this

    # -- Retrieval -----------------------------------------------------------
    TOP_K = _env_int("RAG_TOP_K", 5)
    RETRIEVAL_WINDOW_SIZE = _env_int("RAG_RETRIEVAL_WINDOW_SIZE", 20)
    BM25_ALPHA = _env_float("RAG_BM25_ALPHA", 0.5)                    # 0=pure BM25, 1=pure vector
    BM25_ALPHA_HYDE = _env_float("RAG_BM25_ALPHA_HYDE", 0.7)          # semantic queries -> vectors
    BM25_ALPHA_COMPLEX = _env_float("RAG_BM25_ALPHA_COMPLEX", 0.45)   # decomposition -> BM25 matters
    BM25_ALPHA_STANDARD = _env_float("RAG_BM25_ALPHA_STANDARD", 0.5)  # plain hybrid
    RETRIEVAL_SCORE_THRESHOLD = _env_float("RAG_SCORE_THRESHOLD", 0.0)  # min rerank score to keep

    # -- Generation / LLM provider -------------------------------------------
    # "ollama" -> a model served by a local Ollama daemon (default)
    # "openai" -> any OpenAI-compatible HTTP API (Cerebras by default)
    LLM_PROVIDER = _env_str("RAG_LLM_PROVIDER", "ollama").lower()

    # Ollama (local)
    OLLAMA_BASE_URL = _env_str("RAG_OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    OLLAMA_MODEL = _env_str("RAG_OLLAMA_MODEL", "mistral:7b")
    # Context window the model is loaded with. Ollama defaults to a small window
    # (4096) which silently truncates the long RAG prompts this pipeline builds,
    # so the model would answer from a fraction of the retrieved context.
    OLLAMA_NUM_CTX = _env_int("RAG_OLLAMA_NUM_CTX", 16384)
    # Keep the model resident between calls so each request does not reload 4+ GB.
    OLLAMA_KEEP_ALIVE = _env_str("RAG_OLLAMA_KEEP_ALIVE", "30m")
    OLLAMA_TIMEOUT = _env_int("RAG_OLLAMA_TIMEOUT", 900)  # seconds - a 7B on CPU is slow

    # OpenAI-compatible endpoint
    OPENAI_MODEL = _env_str("RAG_OPENAI_MODEL", "gpt-oss-120b")
    CEREBRAS_API_KEY = _env_str("CEREBRAS_API_KEY", "")
    CEREBRAS_BASE_URL = _env_str("RAG_OPENAI_BASE_URL", "https://api.cerebras.ai/v1")

    LLM_TEMPERATURE = _env_float("RAG_LLM_TEMPERATURE", 0.2)
    LLM_MAX_TOKENS = _env_int("RAG_LLM_MAX_TOKENS", 4096)          # max tokens generated per call
    MAX_CONTEXT_TOKENS = _env_int("RAG_MAX_CONTEXT_TOKENS", 2000)  # chars per chunk sent to LLM
    SECTION_MIN_WORDS = _env_int("RAG_SECTION_MIN_WORDS", 150)
    SECTION_MAX_WORDS = _env_int("RAG_SECTION_MAX_WORDS", 600)

    # -- Plagiarism / evaluation ---------------------------------------------
    PLAGIARISM_SENTENCE_THRESHOLD = _env_float("RAG_PLAGIARISM_THRESHOLD", 0.65)
    NGRAM_SIZE = _env_int("RAG_NGRAM_SIZE", 8)

    # -- Survey settings -----------------------------------------------------
    SURVEY_MAX_PAPERS = _env_int("RAG_SURVEY_MAX_PAPERS", 15)
    SURVEY_MIN_PAPERS = _env_int("RAG_SURVEY_MIN_PAPERS", 3)
    SURVEY_DEFAULT_PAPERS = _env_int("RAG_SURVEY_DEFAULT_PAPERS", 10)
    SURVEY_PAPER_CONTEXT_ROWS = _env_int("RAG_SURVEY_CONTEXT_ROWS", 10)
    SURVEY_EXTRACT_MAX_CHARS = _env_int("RAG_SURVEY_EXTRACT_CHARS", 7000)

    # -- Generation context limits -------------------------------------------
    MAX_CHUNKS_FAST = _env_int("RAG_MAX_CHUNKS_FAST", 6)
    MAX_CHUNKS_FULL = _env_int("RAG_MAX_CHUNKS_FULL", 8)
    MAX_CHARS_FAST = _env_int("RAG_MAX_CHARS_FAST", 1800)

    # -- Page settings -------------------------------------------------------
    MIN_PAGES_DEFAULT = _env_int("RAG_MIN_PAGES_DEFAULT", 13)
    MIN_PAGES_MIN = _env_int("RAG_MIN_PAGES_MIN", 2)
    MIN_PAGES_MAX = _env_int("RAG_MIN_PAGES_MAX", 15)

    # -- Evaluation ----------------------------------------------------------
    EVAL_MAX_CHARS = _env_int("RAG_EVAL_MAX_CHARS", 7000)
    EVAL_MAX_CONTEXT_CHUNKS = _env_int("RAG_EVAL_MAX_CONTEXT_CHUNKS", 3)

    # -- API server ----------------------------------------------------------
    API_HOST = _env_str("RAG_API_HOST", "127.0.0.1")
    API_PORT = _env_int("RAG_API_PORT", 8001)
    # Origins allowed to call the API. Comma-separated; "*" allows any.
    CORS_ORIGINS = [
        o.strip()
        for o in _env_str(
            "RAG_CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,"
            "http://localhost:4173,http://127.0.0.1:4173",
        ).split(",")
        if o.strip()
    ]
    JOB_RETENTION_SECONDS = _env_int("RAG_JOB_RETENTION_SECONDS", 7200)

    # -- Logging -------------------------------------------------------------
    LOG_LEVEL = _env_str("RAG_LOG_LEVEL", "INFO")
    LOG_FILE = _env_str("RAG_LOG_FILE", os.path.join(BASE_DIR, "logs", "rag.log"))

    # -- Helpers -------------------------------------------------------------
    @staticmethod
    def ensure_dirs() -> None:
        for d in (Config.PAPERS_DIR, Config.DB_DIR, Config.OUTPUT_DIR, Config.HISTORY_DIR):
            os.makedirs(d, exist_ok=True)

    @staticmethod
    def active_model() -> str:
        """The model name actually in use for the configured provider."""
        return Config.OLLAMA_MODEL if Config.LLM_PROVIDER == "ollama" else Config.OPENAI_MODEL

    @staticmethod
    def setup_logging() -> None:
        level = getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO)
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        root = logging.getLogger()
        root.setLevel(level)

        # Guard against duplicate handlers when this module is re-imported
        # (Streamlit reruns, uvicorn --reload, test collection).
        if any(getattr(h, "_researchgpt", False) for h in root.handlers):
            return

        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        ch._researchgpt = True          # type: ignore[attr-defined]
        root.addHandler(ch)

        try:
            os.makedirs(os.path.dirname(Config.LOG_FILE), exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(
                Config.LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
            fh.setFormatter(fmt)
            fh._researchgpt = True      # type: ignore[attr-defined]
            root.addHandler(fh)
        except OSError as e:
            root.warning("Could not open log file %s: %s", Config.LOG_FILE, e)


Config.ensure_dirs()
Config.setup_logging()
