import fitz  # PyMuPDF
import logging
import os
import re
import sys
from typing import List, Dict

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config.config import Config

logger = logging.getLogger(__name__)

# Patterns that indicate non-content lines (page numbers, running headers/footers)
_JUNK_LINE_RE = re.compile(
    r"^\s*(\d{1,4})\s*$"            # bare page numbers
    r"|^\s*page\s+\d+\s*$"          # "Page 3"
    r"|^\s*[-–—]{2,}\s*$"           # horizontal rules
    r"|^(arxiv|preprint|accepted|submitted|proceedings|conference|journal)",
    re.IGNORECASE,
)

# Section-heading detector (e.g. "I. Introduction", "3. Methodology", "Abstract")
_SECTION_HEAD_RE = re.compile(
    r"^(?:[IVXLC]+\.|[0-9]+\.)\s+[A-Z]"
    r"|^(?:Abstract|Introduction|Related Work|Methodology|Conclusion|References)\b",
    re.IGNORECASE,
)


class PDFProcessor:
    def __init__(self):
        pass

    def parse_pdf(self, filepath: str) -> str:
        """
        Extracts cleaned text from a PDF.
        - Removes page numbers and running headers/footers.
        - Appends a plain-text representation of tables.
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")

        doc = fitz.open(filepath)
        page_texts = []
        for page_idx, page in enumerate(doc):
            raw = page.get_text()
            cleaned = self._clean_page_text(raw)
            if cleaned.strip():
                page_texts.append(cleaned)

            # Extract tables as tab-separated rows
            table_text = self._extract_tables(page, page_idx)
            if table_text:
                page_texts.append(table_text)

        doc.close()
        return "\n\n".join(page_texts)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _clean_page_text(self, text: str) -> str:
        """Remove junk lines (page numbers, running headers) from page text."""
        lines = text.split("\n")
        cleaned_lines = []
        for line in lines:
            if _JUNK_LINE_RE.match(line.strip()):
                continue
            cleaned_lines.append(line)
        return "\n".join(cleaned_lines)

    def _extract_tables(self, page, page_idx: int) -> str:
        """
        Extracts tables from a page using PyMuPDF's block-level text.
        Returns a plain-text block like:
          [Table on page N]
          col1\tcol2\tcol3
          val1\tval2\tval3
        """
        try:
            blocks = page.get_text("blocks")  # list of (x0,y0,x1,y1,text,block_no,block_type)
            # block_type 1 = image, 0 = text
            text_blocks = [b for b in blocks if b[6] == 0]

            # Heuristic: a table has many short blocks clustered in columns
            # Use PyMuPDF's find_tables if available (>=1.23.0)
            if hasattr(page, "find_tables"):
                tables = page.find_tables()
                if not tables or not tables.tables:
                    return ""
                rows_out = [f"[Table on page {page_idx + 1}]"]
                for tbl in tables.tables:
                    try:
                        for row in tbl.extract():
                            cells = [str(c).strip() if c else "" for c in row]
                            rows_out.append("\t".join(cells))
                    except Exception:
                        pass
                return "\n".join(rows_out) if len(rows_out) > 1 else ""
        except Exception as e:
            logger.debug("Table extraction skipped on page %d: %s", page_idx + 1, e)
        return ""


class Chunker:
    def __init__(self, chunk_size=Config.CHUNK_SIZE, chunk_overlap=Config.CHUNK_OVERLAP):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_text(self, text: str, metadata: Dict) -> List[Dict]:
        """
        Splits text into overlapping chunks using LangChain's RecursiveCharacterTextSplitter.
        Metadata is propagated to every chunk; section headings detected in the chunk
        are stored as chunk-level metadata.
        """
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

        chunks = text_splitter.split_text(text)
        filename = os.path.basename(metadata.get("filepath", "unknown_source"))

        chunked_data = []
        for i, chunk in enumerate(chunks):
            chunk_meta = dict(metadata)  # copy all rich metadata (authors, published, etc.)
            chunk_meta["chunk_index"] = i
            # Detect dominant section in this chunk
            section = self._detect_section(chunk)
            if section:
                chunk_meta["section"] = section
            chunked_data.append(
                {
                    "id": f"{filename}_{i}",
                    "text": chunk,
                    "metadata": chunk_meta,
                }
            )

        return chunked_data

    def _detect_section(self, text: str) -> str:
        """Returns the first section heading found in the chunk, or empty string."""
        for line in text.split("\n")[:5]:   # only check first 5 lines of chunk
            if _SECTION_HEAD_RE.match(line.strip()):
                return line.strip()[:80]
        return ""


if __name__ == "__main__":
    processor = PDFProcessor()
    chunker = Chunker()
    print("Processor and Chunker initialized.")
