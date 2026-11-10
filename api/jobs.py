"""In-memory background job runner for long-running pipeline calls.

FastAPI serves one process; jobs run on daemon threads and report progress
through a list that the frontend polls. Good enough for a single-user /
small-team deployment — swap for a real task queue (Celery/RQ) if this needs
to scale to concurrent multi-worker usage.
"""
import logging
import threading
import time
import uuid
from typing import Callable

from config.config import Config

logger = logging.getLogger(__name__)

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def create_job(target: Callable, kwargs: dict) -> str:
    # Jobs live in memory; drop finished ones before adding another.
    prune_old_jobs(Config.JOB_RETENTION_SECONDS)
    job_id = uuid.uuid4().hex
    with _lock:
        _jobs[job_id] = {
            "status": "running",
            "progress": [],
            "result": None,
            "error": None,
            "created_at": time.time(),
        }

    def _progress_cb(step: str, detail: str = "") -> None:
        with _lock:
            _jobs[job_id]["progress"].append({"step": step, "detail": detail, "at": time.time()})

    def _run():
        try:
            result = target(progress_callback=_progress_cb, **kwargs)
            with _lock:
                _jobs[job_id]["result"] = result
                _jobs[job_id]["status"] = "done"
        except Exception as e:
            logger.exception("Job %s failed", job_id)
            with _lock:
                _jobs[job_id]["error"] = str(e)
                _jobs[job_id]["status"] = "error"

    threading.Thread(target=_run, daemon=True).start()
    return job_id


def get_job(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def prune_old_jobs(max_age_seconds: int = 3600) -> None:
    cutoff = time.time() - max_age_seconds
    with _lock:
        stale = [jid for jid, j in _jobs.items() if j.get("created_at", 0) < cutoff]
        for jid in stale:
            del _jobs[jid]
