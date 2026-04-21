import os
import logging
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
    BM25_ALPHA = float(os.getenv("RAG_BM25_ALPHA", "0.5"))          # 0=pure BM25, 1=pure vector
    RETRIEVAL_SCORE_THRESHOLD = float(os.getenv("RAG_SCORE_THRESHOLD", "0.0"))  # min rerank score to keep

    # Generation
    LLM_PROVIDER = os.getenv("RAG_LLM_PROVIDER", "openai")
    OLLAMA_MODEL = os.getenv("RAG_OLLAMA_MODEL", "mistral:7b")
    OPENAI_MODEL = os.getenv("RAG_OPENAI_MODEL", "llama3.1-8b")
    CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")
    CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"
    LLM_TEMPERATURE = float(os.getenv("RAG_LLM_TEMPERATURE", "0.2"))
    LLM_MAX_TOKENS = int(os.getenv("RAG_LLM_MAX_TOKENS", "2048"))
    MAX_CONTEXT_TOKENS = int(os.getenv("RAG_MAX_CONTEXT_TOKENS", "3000"))  # chars per chunk sent to LLM
    SECTION_MIN_WORDS = int(os.getenv("RAG_SECTION_MIN_WORDS", "150"))
    SECTION_MAX_WORDS = int(os.getenv("RAG_SECTION_MAX_WORDS", "600"))

    # Plagiarism / evaluation
    PLAGIARISM_SENTENCE_THRESHOLD = float(os.getenv("RAG_PLAGIARISM_THRESHOLD", "0.65"))
    NGRAM_SIZE = int(os.getenv("RAG_NGRAM_SIZE", "8"))

    # Logging
    LOG_LEVEL = os.getenv("RAG_LOG_LEVEL", "INFO")

    @staticmethod
    def ensure_dirs():
        os.makedirs(Config.PAPERS_DIR, exist_ok=True)
        os.makedirs(Config.DB_DIR, exist_ok=True)
        os.makedirs(Config.OUTPUT_DIR, exist_ok=True)

    @staticmethod
    def setup_logging():
        level = getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO)
        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


Config.ensure_dirs()
Config.setup_logging()
