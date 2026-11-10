"""Durable, human-readable archive of every paper the pipeline produces.

``data/history/`` holds JSON for the UI to reload and is git-ignored. This
module writes a second, permanent record: one Markdown file per run under
``docs/runs/``, plus an index, so completed work is visible in the repository
rather than only in a local cache.

The archive is written as soon as a draft exists and updated again once
evaluation finishes, so a run that fails late still leaves its paper behind.

E-mail addresses are redacted on the way in. A generated title page is
assembled by the model and can repeat an address from a source paper verbatim;
those belong to real people and should not be committed.
"""
import logging
import os
import re
import sys
import time
from typing import Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config.config import Config

logger = logging.getLogger(__name__)

INDEX_FILENAME = "README.md"

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# Also catch the braced form LaTeX-style title pages use:
#   {alice.smith, bob.jones}@university.edu
_BRACED_EMAIL_RE = re.compile(r"\{[^{}\n]*\}@[\w-]+\.[\w.-]+")


def _slug(text: str, limit: int = 60) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return s[:limit] or "untitled"


def redact_emails(text: str) -> tuple[str, int]:
    """Replace e-mail addresses with a placeholder. Returns (text, count)."""
    if not text:
        return text, 0
    count = 0

    def _sub(match: re.Match) -> str:
        nonlocal count
        count += 1
        return "[email redacted]"

    text = _BRACED_EMAIL_RE.sub(_sub, text)
    text = _EMAIL_RE.sub(_sub, text)
    return text, count


def _fmt(value, suffix: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:g}{suffix}"
    return f"{value}{suffix}"


def _render(topic: str, result: dict, started_at: float, redactions: int) -> str:
    plag = result.get("plagiarism_report") or {}
    rouge = result.get("rouge_l") or {}
    timings = result.get("timings") or {}
    context = result.get("retrieved_context") or []

    lines = [
        f"# {topic}",
        "",
        f"*Generated {time.strftime('%Y-%m-%d %H:%M', time.localtime(started_at))} "
        f"by {Config.active_model()} via {Config.LLM_PROVIDER}.*",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Faithfulness | {_fmt(result.get('faithfulness'))} / 5 |",
        f"| Relevance | {_fmt(result.get('relevance'))} / 5 |",
        f"| Source papers | {_fmt(result.get('num_papers'))} |",
        f"| Retrieved passages | {len(context)} |",
        f"| Retrieval strategy | {_fmt(result.get('strategy'))} |",
        f"| Estimated pages | {_fmt(result.get('page_estimate'))} |",
        f"| Sentences matching a source | {_fmt(plag.get('overall_similarity_pct'), '%')} |",
        f"| 8-gram overlap | {_fmt(plag.get('ngram_overlap_pct'), '%')} |",
        f"| ROUGE-L | {_fmt(rouge.get('avg_rouge_l'))} |",
        f"| Originality rewrites | {_fmt(result.get('ai_rewrite_passes'))} |",
        f"| Total time | {_fmt(timings.get('total_seconds'), 's')} |",
        "",
    ]

    # A draft that leans on a single paper is worth seeing at a glance.
    if context:
        by_title: dict = {}
        for c in context:
            by_title[c.get("title", "Unknown")] = by_title.get(c.get("title", "Unknown"), 0) + 1
        lines += ["## Sources", ""]
        for i, (title, n) in enumerate(sorted(by_title.items(), key=lambda kv: -kv[1]), 1):
            lines.append(f"{i}. **{title}** — {n} passage{'s' if n != 1 else ''}")
        if len(by_title) == 1:
            lines += [
                "",
                "> All retrieved passages came from a single paper, so this draft is "
                "not a synthesis across the literature.",
            ]
        lines.append("")

    if redactions:
        lines += [
            f"> {redactions} e-mail address{'es' if redactions != 1 else ''} removed from "
            "the generated text before archiving.",
            "",
        ]

    lines += ["## Paper", "", result.get("paper_text", "").strip(), ""]
    return "\n".join(lines)


def archive_paper(topic: str, result: dict, started_at: Optional[float] = None) -> Optional[str]:
    """Write (or rewrite) this run's Markdown record. Returns the path.

    Safe to call more than once for the same run: the filename is derived from
    the topic and start time, so the second call updates the first file rather
    than creating a duplicate.
    """
    if not Config.ARCHIVE_ENABLED:
        return None
    if not (result.get("paper_text") or "").strip():
        return None

    started_at = started_at or time.time()
    try:
        os.makedirs(Config.ARCHIVE_DIR, exist_ok=True)
        clean_text, redactions = redact_emails(result.get("paper_text", ""))
        safe_result = {**result, "paper_text": clean_text}

        name = f"{time.strftime('%Y-%m-%d', time.localtime(started_at))}-{_slug(topic)}.md"
        path = os.path.join(Config.ARCHIVE_DIR, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(_render(topic, safe_result, started_at, redactions))

        _write_index()
        logger.info("Archived paper to %s", path)
        return path
    except OSError as e:
        # Archiving must never take down a run that otherwise succeeded.
        logger.warning("Could not archive paper: %s", e)
        return None


def list_archive() -> list[dict]:
    """Every archived run, newest first."""
    if not os.path.isdir(Config.ARCHIVE_DIR):
        return []
    entries = []
    for fname in os.listdir(Config.ARCHIVE_DIR):
        if not fname.endswith(".md") or fname == INDEX_FILENAME:
            continue
        path = os.path.join(Config.ARCHIVE_DIR, fname)
        title = fname
        try:
            with open(path, encoding="utf-8") as f:
                first = f.readline().strip()
                if first.startswith("# "):
                    title = first[2:].strip()
        except OSError:
            pass
        entries.append(
            {
                "file": fname,
                "topic": title,
                "modified": os.path.getmtime(path),
                "bytes": os.path.getsize(path),
            }
        )
    return sorted(entries, key=lambda e: e["modified"], reverse=True)


def read_archive(fname: str) -> Optional[dict]:
    """One archived run: its metrics table parsed out, plus the raw Markdown.

    ``fname`` is matched against the archive directory listing rather than
    joined directly, so a crafted name cannot escape the folder.
    """
    if os.path.basename(fname) != fname or not fname.endswith(".md"):
        return None
    path = os.path.join(Config.ARCHIVE_DIR, fname)
    if not os.path.isfile(path):
        return None

    try:
        with open(path, encoding="utf-8") as f:
            markdown = f.read()
    except OSError as e:
        logger.warning("Could not read archive entry %s: %s", fname, e)
        return None

    topic = fname
    metrics: dict = {}
    for line in markdown.splitlines():
        line = line.strip()
        if line.startswith("# ") and topic == fname:
            topic = line[2:].strip()
        # Rows of the metrics table: | Key | Value |
        if line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) == 2 and cells[0] not in ("Metric", "---") and "---" not in cells[0]:
                metrics[cells[0]] = cells[1]

    return {
        "file": fname,
        "topic": topic,
        "metrics": metrics,
        "markdown": markdown,
        "modified": os.path.getmtime(path),
    }


def _write_index() -> None:
    entries = list_archive()
    lines = [
        "# Generated papers",
        "",
        "Every paper this pipeline has produced, written as the run completes.",
        "Each file records the paper together with the scores, timings and the "
        "sources it was built from.",
        "",
        f"{len(entries)} run{'s' if len(entries) != 1 else ''} archived.",
        "",
        "| Date | Topic | File |",
        "|---|---|---|",
    ]
    for e in entries:
        date = time.strftime("%Y-%m-%d", time.localtime(e["modified"]))
        lines.append(f"| {date} | {e['topic']} | [{e['file']}]({e['file']}) |")
    lines.append("")

    try:
        with open(os.path.join(Config.ARCHIVE_DIR, INDEX_FILENAME), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except OSError as e:
        logger.warning("Could not write archive index: %s", e)
