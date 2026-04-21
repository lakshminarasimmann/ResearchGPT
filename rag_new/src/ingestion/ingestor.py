import arxiv
import json
import logging
import os
import ssl
import sys
import time
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
        client = arxiv.Client()
        search = arxiv.Search(
            query=query,
            max_results=self.max_results,
            sort_by=arxiv.SortCriterion.Relevance,
        )

        try:
            results = list(client.results(search))
        except Exception as e:
            logger.error("Error fetching arXiv results: %s", e)
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
                logger.info("Downloading: %s", result.title)
                ok = self._download_with_retry(result.pdf_url, filepath)
                if not ok:
                    logger.warning("Failed to download: %s", result.title)
                    continue
                # Rate-limit between downloads to avoid IP bans
                time.sleep(Config.DOWNLOAD_RATE_LIMIT)

            new_filepaths.add(filepath)
            paper_meta = {
                "arxiv_id": arxiv_id,
                "title": result.title,
                "filepath": filepath,
                "summary": result.summary,
                "authors": [a.name for a in result.authors],
                "published": str(result.published),
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
