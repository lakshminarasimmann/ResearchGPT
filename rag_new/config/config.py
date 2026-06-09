import os
import logging
import logging.handlers
from dotenv import load_dotenv

# Load .env from the project root (rag_new/.env)
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))


class Config:
    # Paths
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR = os.path.join(BASE_DIR, "data")
    ASSETS_DIR = os.path.join(BASE_DIR, "assets")
    PAPERS_DIR = os.path.join(DATA_DIR, "papers")
    DB_DIR = os.path.join(DATA_DIR, "vector_db")
    OUTPUT_DIR = os.path.join(BASE_DIR, "output")
    UI_BACKGROUND_IMAGE_PATH = os.getenv(
        "RAG_UI_BACKGROUND_IMAGE",
        os.path.join(ASSETS_DIR, "background.png"),
    )

    # Ingestion
    MAX_PAPERS = int(os.getenv("RAG_MAX_PAPERS", "5"))
    MAX_RETRIES = int(os.getenv("RAG_MAX_RETRIES", "3"))
    RETRY_DELAY = float(os.getenv("RAG_RETRY_DELAY", "2.0"))   # seconds, doubles on each retry
    DOWNLOAD_RATE_LIMIT = float(os.getenv("RAG_DOWNLOAD_RATE_LIMIT", "1.0"))  # seconds between downloads

    # Chunking
    CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "1000"))
    CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "350"))

    # Embedding
    EMBEDDING_MODEL_NAME = os.getenv("RAG_EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
    CROSS_ENCODER_MODEL = os.getenv("RAG_CROSS_ENCODER_MODEL", "cross-encoder/ms-marco-MiniLM-L-12-v2")

    # Vector DB
    COLLECTION_NAME = os.getenv("RAG_COLLECTION_NAME", "rag_papers")
    MAX_STALE_COLLECTIONS = int(os.getenv("RAG_MAX_STALE_COLLECTIONS", "10"))  # delete oldest after this

    # Retrieval
    TOP_K = int(os.getenv("RAG_TOP_K", "5"))
    RETRIEVAL_WINDOW_SIZE = int(os.getenv("RAG_RETRIEVAL_WINDOW_SIZE", "20"))
    BM25_ALPHA = float(os.getenv("RAG_BM25_ALPHA", "0.5"))          # 0=pure BM25, 1=pure vector (global default)
    BM25_ALPHA_HYDE = float(os.getenv("RAG_BM25_ALPHA_HYDE", "0.7"))      # semantic queries → trust vectors more
    BM25_ALPHA_COMPLEX = float(os.getenv("RAG_BM25_ALPHA_COMPLEX", "0.45"))  # sub-question decomp → BM25 matters more
    BM25_ALPHA_STANDARD = float(os.getenv("RAG_BM25_ALPHA_STANDARD", "0.5"))  # plain hybrid
    RETRIEVAL_SCORE_THRESHOLD = float(os.getenv("RAG_SCORE_THRESHOLD", "0.0"))  # min rerank score to keep

    # Generation
    LLM_PROVIDER = os.getenv("RAG_LLM_PROVIDER", "openai")
    OLLAMA_MODEL = os.getenv("RAG_OLLAMA_MODEL", "mistral:7b")
    OPENAI_MODEL = os.getenv("RAG_OPENAI_MODEL", "gpt-oss-120b")
    CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")
    CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"
    LLM_TEMPERATURE = float(os.getenv("RAG_LLM_TEMPERATURE", "0.2"))
    LLM_MAX_TOKENS = int(os.getenv("RAG_LLM_MAX_TOKENS", "8192"))
    MAX_CONTEXT_TOKENS = int(os.getenv("RAG_MAX_CONTEXT_TOKENS", "3000"))  # chars per chunk sent to LLM
    SECTION_MIN_WORDS = int(os.getenv("RAG_SECTION_MIN_WORDS", "150"))
    SECTION_MAX_WORDS = int(os.getenv("RAG_SECTION_MAX_WORDS", "600"))

    # Plagiarism / evaluation
    PLAGIARISM_SENTENCE_THRESHOLD = float(os.getenv("RAG_PLAGIARISM_THRESHOLD", "0.65"))
    NGRAM_SIZE = int(os.getenv("RAG_NGRAM_SIZE", "8"))

    # Survey settings
    SURVEY_MAX_PAPERS = int(os.getenv("RAG_SURVEY_MAX_PAPERS", "15"))
    SURVEY_MIN_PAPERS = int(os.getenv("RAG_SURVEY_MIN_PAPERS", "3"))
    SURVEY_DEFAULT_PAPERS = int(os.getenv("RAG_SURVEY_DEFAULT_PAPERS", "10"))
    SURVEY_PAPER_CONTEXT_ROWS = int(os.getenv("RAG_SURVEY_CONTEXT_ROWS", "10"))
    SURVEY_EXTRACT_MAX_CHARS = int(os.getenv("RAG_SURVEY_EXTRACT_CHARS", "7000"))

    # Generation context limits
    MAX_CHUNKS_FAST = int(os.getenv("RAG_MAX_CHUNKS_FAST", "6"))
    MAX_CHUNKS_FULL = int(os.getenv("RAG_MAX_CHUNKS_FULL", "9"))
    MAX_CHARS_FAST = int(os.getenv("RAG_MAX_CHARS_FAST", "1800"))

    # Page settings
    MIN_PAGES_DEFAULT = int(os.getenv("RAG_MIN_PAGES_DEFAULT", "13"))
    MIN_PAGES_MIN = int(os.getenv("RAG_MIN_PAGES_MIN", "2"))
    MIN_PAGES_MAX = int(os.getenv("RAG_MIN_PAGES_MAX", "15"))

    # Evaluation
    EVAL_MAX_CHARS = int(os.getenv("RAG_EVAL_MAX_CHARS", "7000"))
    EVAL_MAX_CONTEXT_CHUNKS = int(os.getenv("RAG_EVAL_MAX_CONTEXT_CHUNKS", "3"))

    # Logging
    LOG_LEVEL = os.getenv("RAG_LOG_LEVEL", "INFO")

    @staticmethod
    def ensure_dirs():
        os.makedirs(Config.PAPERS_DIR, exist_ok=True)
        os.makedirs(Config.DB_DIR, exist_ok=True)
        os.makedirs(Config.OUTPUT_DIR, exist_ok=True)

    LOG_FILE = os.getenv("RAG_LOG_FILE", os.path.join(BASE_DIR, "logs", "rag.log"))

    @staticmethod
    def setup_logging():
        level = getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO)
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        root = logging.getLogger()
        root.setLevel(level)

        if not root.handlers:
            # Console handler
            ch = logging.StreamHandler()
            ch.setFormatter(fmt)
            root.addHandler(ch)

        # Rotating file handler — 5 MB per file, keep 3 backups
        log_dir = os.path.dirname(Config.LOG_FILE)
        os.makedirs(log_dir, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            Config.LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)


Config.ensure_dirs()
Config.setup_logging()
