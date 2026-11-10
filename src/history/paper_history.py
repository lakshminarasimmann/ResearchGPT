import base64
import json
import logging
import os
import re
import sys
import time
from typing import Dict, List, Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config.config import Config

logger = logging.getLogger(__name__)

_HISTORY_DIR = os.path.join(Config.DATA_DIR, "history")
_HISTORY_MAX_AGE_DAYS = 30
_KEPT_RESULT_KEYS = {
    "paper_text", "num_papers", "strategy", "page_estimate",
    "faithfulness", "relevance", "faithfulness_reasoning", "relevance_reasoning",
    "evaluation_error", "retrieved_context", "plagiarism_report",
    "timings", "status", "analysis_table",
    "latex_compile_log", "tex_path", "pdf_path",
    "rouge_l", "ai_rewrite_passes", "humanize_applied", "min_pages_target",
}


def _ensure_dir() -> str:
    os.makedirs(_HISTORY_DIR, exist_ok=True)
    return _HISTORY_DIR


def _slug(topic: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", topic.strip().lower()).strip("_")[:50]


def save_result(topic: str, result: dict) -> None:
    d = _ensure_dir()
    slug = _slug(topic)
    entry = {
        "topic": topic,
        "slug": slug,
        "saved_at": time.time(),
    }
    for k in _KEPT_RESULT_KEYS:
        entry[k] = result.get(k)

    fname = f"{slug}_{int(entry['saved_at'])}.json"
    path = os.path.join(d, fname)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)
        logger.info("Saved paper history: %s", fname)
    except Exception as e:
        logger.warning("Failed to save paper history: %s", e)


def save_session(
    topic: str,
    result: dict,
    survey_rows: list = None,
    survey_paper_text: str = "",
    survey_pdf_bytes: bytes = None,
) -> None:
    """Save the full session including survey data and paper result."""
    d = _ensure_dir()
    slug = _slug(topic)
    entry = {
        "topic": topic,
        "slug": slug,
        "saved_at": time.time(),
        "survey_rows": survey_rows or [],
        "survey_paper_text": survey_paper_text or "",
        "survey_pdf_b64": base64.b64encode(survey_pdf_bytes).decode() if survey_pdf_bytes else "",
    }
    for k in _KEPT_RESULT_KEYS:
        entry[k] = result.get(k)

    fname = f"{slug}_{int(entry['saved_at'])}.json"
    path = os.path.join(d, fname)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)
        logger.info("Saved full session history: %s", fname)
    except Exception as e:
        logger.warning("Failed to save session history: %s", e)


def list_history(max_entries: int = 20) -> List[Dict]:
    d = _ensure_dir()
    cutoff = time.time() - _HISTORY_MAX_AGE_DAYS * 86400
    try:
        files = sorted(
            [f for f in os.listdir(d) if f.endswith(".json")],
            reverse=True,
        )[:max_entries * 2]
    except OSError:
        return []

    entries = []
    for fname in files:
        try:
            with open(os.path.join(d, fname), encoding="utf-8") as f:
                data = json.load(f)
            if data.get("saved_at", 0) < cutoff:
                continue
            entries.append({
                "topic":        data.get("topic", "Unknown"),
                "saved_at":     data.get("saved_at", 0),
                "fname":        fname,
                "page_estimate": data.get("page_estimate", 0.0),
                "strategy":     data.get("strategy", ""),
            })
        except Exception:
            continue
        if len(entries) >= max_entries:
            break
    return entries


def delete_result(fname: str) -> bool:
    d = _ensure_dir()
    path = os.path.join(d, fname)
    try:
        os.remove(path)
        logger.info("Deleted history entry: %s", fname)
        return True
    except Exception as e:
        logger.warning("Failed to delete history entry '%s': %s", fname, e)
        return False


def load_result(fname: str) -> Optional[Dict]:
    d = _ensure_dir()
    path = os.path.join(d, fname)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Failed to load history entry '%s': %s", fname, e)
        return None
