import chromadb
import json
import logging
import os
import sys
from chromadb.utils import embedding_functions
from typing import List, Dict, Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config.config import Config

logger = logging.getLogger(__name__)

# Loading SentenceTransformerEmbeddingFunction re-downloads/reloads the model
# (including HF Hub network round-trips) every time it's constructed. Since the
# model is the same for every collection, build it once per process and reuse it.
_embedding_fn_cache: dict = {}


def _get_embedding_fn(model_name: str):
    if model_name not in _embedding_fn_cache:
        _embedding_fn_cache[model_name] = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=model_name
        )
    return _embedding_fn_cache[model_name]


def _deserialize_metadata(meta: dict) -> dict:
    """Recover list fields that were stored as JSON strings."""
    out = {}
    for k, v in meta.items():
        if isinstance(v, str) and v.startswith("["):
            try:
                out[k] = json.loads(v)
                continue
            except (json.JSONDecodeError, ValueError):
                pass
        out[k] = v
    return out


class VectorEngine:
    def __init__(self, collection_name=Config.COLLECTION_NAME):
        self.client = chromadb.PersistentClient(path=Config.DB_DIR)
        self.embedding_fn = _get_embedding_fn(Config.EMBEDDING_MODEL_NAME)
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=self.embedding_fn,
        )
        logger.info("VectorEngine ready — collection '%s' (%d chunks).",
                    collection_name, self.collection.count())

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------
    def reset_collection(self):
        try:
            self.client.delete_collection(self.collection.name)
            self.collection = self.client.create_collection(
                name=self.collection.name,
                embedding_function=self.embedding_fn,
            )
            logger.info("Collection '%s' reset.", self.collection.name)
        except Exception as e:
            logger.error("Error resetting collection: %s", e)

    def add_chunks(self, chunks: List[Dict]):
        if not chunks:
            return
        ids = [chunk["id"] for chunk in chunks]
        documents = [chunk["text"] for chunk in chunks]
        # ChromaDB metadata values must be str/int/float/bool — serialize lists as JSON
        metadatas = []
        for chunk in chunks:
            meta = {}
            for k, v in chunk["metadata"].items():
                if isinstance(v, list):
                    meta[k] = json.dumps(v)
                elif v is None:
                    meta[k] = ""
                else:
                    meta[k] = v
            metadatas.append(meta)

        self.collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        logger.info("Upserted %d chunks to '%s'.", len(chunks), self.collection.name)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    def query(self, query_text: str, n_results=Config.TOP_K):
        results = self.collection.query(query_texts=[query_text], n_results=n_results)
        if results.get("metadatas"):
            results["metadatas"] = [
                [_deserialize_metadata(meta or {}) for meta in metas] for metas in results["metadatas"]
            ]
        return results

    def count(self) -> int:
        return self.collection.count()

    def get_all_chunks(self) -> List[Dict]:
        """
        Returns all stored chunks as a list of {text, metadata} dicts.
        Used for fitting BM25 on the full corpus.
        """
        total = self.collection.count()
        if total == 0:
            return []
        result = self.collection.get(include=["documents", "metadatas"])
        chunks = []
        for doc, meta in zip(result["documents"], result["metadatas"]):
            chunks.append({"text": doc, "metadata": _deserialize_metadata(meta or {})})
        return chunks

    # ------------------------------------------------------------------
    # Collection lifecycle management
    # ------------------------------------------------------------------
    @staticmethod
    def list_topic_collections() -> List[str]:
        """Returns all collection names that belong to this RAG project."""
        client = chromadb.PersistentClient(path=Config.DB_DIR)
        prefix = Config.COLLECTION_NAME
        return [c.name for c in client.list_collections() if c.name.startswith(prefix)]

    @staticmethod
    def prune_old_collections(keep: Optional[List[str]] = None):
        """
        Deletes topic collections beyond MAX_STALE_COLLECTIONS.
        Collections in `keep` are never deleted.
        """
        client = chromadb.PersistentClient(path=Config.DB_DIR)
        prefix = Config.COLLECTION_NAME
        all_cols = [c.name for c in client.list_collections() if c.name.startswith(prefix)]
        keep = set(keep or [])
        deletable = [c for c in all_cols if c not in keep]

        if len(deletable) <= Config.MAX_STALE_COLLECTIONS:
            return

        to_delete = deletable[: len(deletable) - Config.MAX_STALE_COLLECTIONS]
        for name in to_delete:
            try:
                client.delete_collection(name)
                logger.info("Pruned stale collection '%s'.", name)
            except Exception as e:
                logger.warning("Could not prune '%s': %s", name, e)


if __name__ == "__main__":
    ve = VectorEngine()
    print("Vector Engine initialized.")
