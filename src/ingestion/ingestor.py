import arxiv
import json
import logging
import os
import ssl
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
import certifi
import urllib.request

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config.config import Config

logger = logging.getLogger(__name__)

METADATA_FILENAME = "_papers_metadata.json"


class ArxivIngestor:
    def __init__(self, max_results=Config.MAX_PAPERS, download_dir=None):
        self.max_results = max_results
        self.download_dir = download_dir or Config.PAPERS_DIR

        self.ssl_context = ssl.create_default_context(cafile=certifi.where())
        if not os.environ.get("VERIFY_SSL", "True") == "True":
            self.ssl_context = ssl._create_unverified_context()

    # ------------------------------------------------------------------
    # Metadata helpers — persist arxiv metadata so we can skip duplicates
    # ------------------------------------------------------------------
    def _metadata_path(self) -> str:
        return os.path.join(self.download_dir, METADATA_FILENAME)

    def _load_existing_metadata(self) -> dict:
        """Returns {arxiv_id: paper_dict} from the saved metadata file."""
        path = self._metadata_path()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_metadata(self, papers: list):
        """Merges new papers into the metadata file (keyed by arxiv_id)."""
        existing = self._load_existing_metadata()
        for p in papers:
            aid = p.get("arxiv_id")
            if aid:
                existing[aid] = p
        try:
            with open(self._metadata_path(), "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning("Could not save metadata JSON: %s", e)

    # ------------------------------------------------------------------
    # Fallback search via urllib (avoids the arxiv library's 100-result page requests)
    # ------------------------------------------------------------------
    _ARXIV_NS = "http://www.w3.org/2005/Atom"

    def _fallback_search(self, query: str) -> list:
        """
        Query the arXiv Atom API directly with urllib.
        Returns a list of mock result objects with .title, .pdf_url, .get_short_id(),
        .authors, .published, and .summary attributes so the caller code is unchanged.
        """
        url = (
            "http://export.arxiv.org/api/query?"
            f"search_query=all:{urllib.parse.quote(query)}"
            f"&start=0&max_results={self.max_results}"
            "&sortBy=relevance&sortOrder=descending"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, context=self.ssl_context, timeout=30) as resp:
                xml_data = resp.read()
        except Exception as e:
            logger.error("Fallback arXiv search also failed: %s", e)
            return []

        class _FakeAuthor:
            def __init__(self, name): self.name = name

        class _FakeResult:
            def __init__(self, arxiv_id, title, pdf_url, authors, published, summary):
                self._id       = arxiv_id
                self.title     = title
                self.pdf_url   = pdf_url
                self.authors   = authors
                self.published = published
                self.summary   = summary
            def get_short_id(self): return self._id

        ns = self._ARXIV_NS
        root = ET.fromstring(xml_data)
        results = []
        for entry in root.findall(f"{{{ns}}}entry"):
            arxiv_id_full = (entry.findtext(f"{{{ns}}}id") or "").strip()
            arxiv_id = arxiv_id_full.split("/abs/")[-1].strip()
            title = (entry.findtext(f"{{{ns}}}title") or "").replace("\n", " ").strip()
            summary = (entry.findtext(f"{{{ns}}}summary") or "").replace("\n", " ").strip()
            published = (entry.findtext(f"{{{ns}}}published") or "")[:10]
            authors = [
                _FakeAuthor((a.findtext(f"{{{ns}}}name") or "").strip())
                for a in entry.findall(f"{{{ns}}}author")
            ]
            pdf_url = ""
            for link in entry.findall(f"{{{ns}}}link"):
                if link.attrib.get("type") == "application/pdf":
                    pdf_url = link.attrib.get("href", "")
                    break
            if not pdf_url and arxiv_id:
                pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
            if title and arxiv_id:
                results.append(_FakeResult(arxiv_id, title, pdf_url, authors, published, summary))
        logger.info("Fallback search returned %d results.", len(results))
        return results

    # ------------------------------------------------------------------
    # Download helpers
    # ------------------------------------------------------------------
    def _clean_download_dir(self):
        if os.path.exists(self.download_dir):
            for fname in os.listdir(self.download_dir):
                if fname == METADATA_FILENAME:
                    continue   # keep metadata across refreshes
                fpath = os.path.join(self.download_dir, fname)
                try:
                    if os.path.isfile(fpath):
                        os.unlink(fpath)
                except Exception as e:
                    logger.warning("Error deleting %s: %s", fpath, e)
        else:
            os.makedirs(self.download_dir, exist_ok=True)

    def _fetch_html_text(self, arxiv_id: str) -> str:
        """Fetch the arXiv HTML version of a paper and return plain text."""
        import re as _re
        url = f"https://arxiv.org/html/{arxiv_id}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, context=self.ssl_context, timeout=30) as resp:
                raw_html = resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            logger.warning("HTML fallback failed for %s: %s", arxiv_id, e)
            return ""

        # Strip script/style blocks
        raw_html = _re.sub(r"<(script|style)[^>]*>.*?</\1>", "", raw_html, flags=_re.DOTALL | _re.IGNORECASE)
        # Strip all remaining tags
        text = _re.sub(r"<[^>]+>", " ", raw_html)
        # Collapse whitespace
        text = _re.sub(r"\s{3,}", "\n\n", text)
        text = text.strip()
        if len(text) < 500:
            logger.warning("HTML text too short for %s (%d chars) — likely a redirect.", arxiv_id, len(text))
            return ""
        logger.info("HTML fallback succeeded for %s (%d chars).", arxiv_id, len(text))
        return text

    def _download_with_retry(self, url: str, filepath: str) -> bool:
        """Download a single URL to filepath with exponential-backoff retries."""
        delay = Config.RETRY_DELAY
        for attempt in range(1, Config.MAX_RETRIES + 1):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, context=self.ssl_context) as resp, \
                        open(filepath, "wb") as out:
                    out.write(resp.read())
                if os.path.getsize(filepath) < 1000:
                    logger.warning("Downloaded file too small (%d bytes), deleting.", os.path.getsize(filepath))
                    os.remove(filepath)
                    return False
                return True
            except Exception as e:
                logger.warning("Attempt %d/%d failed for %s: %s", attempt, Config.MAX_RETRIES, url, e)
                if attempt < Config.MAX_RETRIES:
                    time.sleep(delay)
                    delay *= 2   # exponential backoff
        return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def search_and_download(self, query: str, clear_existing: bool = True) -> list:
        """
        Searches arXiv and downloads PDFs.
        When clear_existing=True, old papers are removed AFTER successful downloads
        so that a network failure never leaves the directory empty.
        Returns list of paper metadata dicts (includes authors, published date).
        """
        os.makedirs(self.download_dir, exist_ok=True)
        existing_meta = self._load_existing_metadata()

        logger.info("Searching arXiv for: %s", query)
        # page_size = max_results so the library only requests what we need (avoids 503s from
        # requesting 100 results per page when arXiv is already handling the survey step queries)
        client = arxiv.Client(
            page_size=self.max_results,
            delay_seconds=5,
            num_retries=3,
        )
        search = arxiv.Search(
            query=query,
            max_results=self.max_results,
            sort_by=arxiv.SortCriterion.Relevance,
        )

        try:
            results = list(client.results(search))
        except Exception as e:
            logger.warning("arxiv library failed (%s) — falling back to urllib.", e)
            results = self._fallback_search(query)

        if not results:
            logger.error("arXiv search returned 0 results for: %s", query)
            return []

        downloaded_papers = []
        new_filepaths: set = set()

        for result in results:
            arxiv_id = result.get_short_id()
            safe_title = "".join(
                c for c in result.title if c.isalnum() or c in (" ", "-", "_")
            ).rstrip()
            filename = f"{safe_title}.pdf"
            filepath = os.path.join(self.download_dir, filename)

            skip_download = False
            if not clear_existing:
                # Reuse existing files when not forcing a refresh
                if os.path.exists(filepath) and os.path.getsize(filepath) >= 1000:
                    logger.info("Already on disk, skipping: %s", result.title)
                    skip_download = True
                elif arxiv_id in existing_meta and os.path.exists(
                    existing_meta[arxiv_id].get("filepath", "")
                ):
                    logger.info("Already indexed (by ID), skipping: %s", result.title)
                    filepath = existing_meta[arxiv_id]["filepath"]
                    skip_download = True

            if not skip_download:
                logger.info("Downloading PDF: %s", result.title)
                ok = self._download_with_retry(result.pdf_url, filepath)
                if not ok:
                    logger.warning("PDF failed for %s — trying HTML fallback.", result.title)
                    html_text = self._fetch_html_text(arxiv_id)
                    if html_text:
                        txt_filepath = filepath.replace(".pdf", ".txt")
                        try:
                            with open(txt_filepath, "w", encoding="utf-8") as tf:
                                tf.write(html_text)
                            filepath = txt_filepath
                            logger.info("Saved HTML fallback text: %s", txt_filepath)
                        except Exception as e:
                            logger.warning("Could not save HTML text: %s", e)
                            continue
                    else:
                        continue
                else:
                    time.sleep(Config.DOWNLOAD_RATE_LIMIT)

            new_filepaths.add(filepath)
            paper_meta = {
                "arxiv_id": arxiv_id,
                "title": result.title,
                "filepath": filepath,
                "summary": result.summary,
                "authors": [a.name for a in result.authors],
                "published": str(result.published)[:10],   # handles both datetime and string
                "url": result.pdf_url,
            }
            downloaded_papers.append(paper_meta)

        # Remove stale files from previous queries ONLY after we have new ones.
        # This prevents losing all papers when a network failure causes 0 downloads.
        if clear_existing and downloaded_papers:
            for fname in os.listdir(self.download_dir):
                if fname == METADATA_FILENAME:
                    continue
                fpath = os.path.join(self.download_dir, fname)
                if os.path.isfile(fpath) and fpath not in new_filepaths:
                    try:
                        os.unlink(fpath)
                    except Exception as e:
                        logger.warning("Error removing stale file %s: %s", fpath, e)

        self._save_metadata(downloaded_papers)
        logger.info("Ingestion complete. %d papers ready.", len(downloaded_papers))
        return downloaded_papers


if __name__ == "__main__":
    ingestor = ArxivIngestor(max_results=3)
    papers = ingestor.search_and_download("RAG Retrieval Augmented Generation")
    print(f"Downloaded {len(papers)} papers.")
