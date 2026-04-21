import re
import time
import logging
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from typing import List, Dict

import fitz
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.generation.generator import LLMClient

logger = logging.getLogger(__name__)
ARXIV_NS = "http://www.w3.org/2005/Atom"


def fetch_arxiv_papers(topic: str, max_papers: int = 15) -> List[Dict]:
    query = urllib.parse.quote(topic)
    url = (
        f"http://export.arxiv.org/api/query?"
        f"search_query=all:{query}&start=0&max_results={max_papers}"
        f"&sortBy=relevance&sortOrder=descending"
    )
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            xml_data = resp.read()
    except Exception as e:
        logger.error("arXiv fetch failed: %s", e)
        return []

    root = ET.fromstring(xml_data)
    papers = []
    for entry in root.findall(f"{{{ARXIV_NS}}}entry"):
        arxiv_id_full = (entry.findtext(f"{{{ARXIV_NS}}}id") or "").strip()
        arxiv_id = arxiv_id_full.split("/abs/")[-1].strip()
        title = (entry.findtext(f"{{{ARXIV_NS}}}title") or "").replace("\n", " ").strip()
        abstract = (entry.findtext(f"{{{ARXIV_NS}}}summary") or "").replace("\n", " ").strip()
        published = (entry.findtext(f"{{{ARXIV_NS}}}published") or "")[:4]

        authors = [
            a.findtext(f"{{{ARXIV_NS}}}name") or ""
            for a in entry.findall(f"{{{ARXIV_NS}}}author")
        ]
        authors_str = ", ".join(authors[:3])
        if len(authors) > 3:
            authors_str += " et al."

        first_author_last = authors[0].split()[-1] if authors else "Unknown"
        citation_str = f"{first_author_last} et al. ({published}). {title[:50]}... arXiv:{arxiv_id}"

        pdf_url = ""
        for link in entry.findall(f"{{{ARXIV_NS}}}link"):
            if link.attrib.get("type") == "application/pdf":
                pdf_url = link.attrib.get("href", "")
                break
        if not pdf_url and arxiv_id:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

        papers.append({
            "title":    title,
            "authors":  authors_str,
            "year":     published,
            "doi":      f"arXiv:{arxiv_id}",
            "citation": citation_str,
            "abstract": abstract,
            "pdf_url":  pdf_url,
        })
    return papers


def download_pdf_text(pdf_url: str, max_pages: int = 10) -> str:
    try:
        req = urllib.request.Request(pdf_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            pdf_bytes = resp.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = ""
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            text += page.get_text()
        doc.close()
        return re.sub(r"\s+", " ", text).strip()
    except Exception as e:
        logger.warning("PDF download failed: %s", e)
        return ""


EXTRACT_PROMPT = """You are an expert academic analyst. Read the research paper below carefully and extract EXACTLY these 8 fields.
Rules:
- 1 to 3 sentences per field. Be specific — include names, numbers, and exact terms from the text.
- If a field is genuinely not present anywhere in the text, write "Not mentioned".
- Do NOT paraphrase vaguely. Do NOT write generic statements like "the paper discusses X". Quote or closely paraphrase actual content.
- Respond ONLY in the exact format below. No preamble, no extra lines, no markdown.

PROBLEM_STATEMENT: <1-3 sentences: the concrete problem or challenge this paper addresses>
OBJECTIVE: <1-3 sentences: the specific goal or contribution the authors aim to achieve>
RESEARCH_GAP: <1-3 sentences: what was missing or insufficient in prior work that this paper fills>
METHODOLOGY: <1-3 sentences: the exact algorithms, model architectures, datasets, or techniques used>
FEATURES_FOCUSED: <1-3 sentences: the specific input features, signals, or aspects the work focuses on>
RESULTS_DISCUSSION: <1-3 sentences: exact metric names and numeric values reported (e.g. "achieved 94.3% accuracy on X benchmark")>
LIMITATIONS: <1-3 sentences: explicit limitations or failure cases the authors acknowledge>
FUTURE_SCOPE: <1-3 sentences: concrete future directions the authors suggest>

PAPER TITLE: {title}
PAPER TEXT:
{text}
"""


def extract_fields(title: str, text: str, llm: LLMClient) -> Dict[str, str]:
    default = {
        "problem_statement":  "Not mentioned",
        "objective":          "Not mentioned",
        "research_gap":       "Not mentioned",
        "methodology":        "Not mentioned",
        "features_focused":   "Not mentioned",
        "results_discussion": "Not mentioned",
        "limitations":        "Not mentioned",
        "future_scope":       "Not mentioned",
    }

    input_text = text[:7000] if text else ""
    if not input_text:
        return default

    try:
        response = llm.generate(EXTRACT_PROMPT.format(title=title, text=input_text))
    except Exception as e:
        logger.error("LLM extraction failed: %s", e)
        return default

    patterns = {
        "problem_statement":  r"PROBLEM_STATEMENT:\s*(.+?)(?=\nOBJECTIVE:|\Z)",
        "objective":          r"OBJECTIVE:\s*(.+?)(?=\nRESEARCH_GAP:|\Z)",
        "research_gap":       r"RESEARCH_GAP:\s*(.+?)(?=\nMETHODOLOGY:|\Z)",
        "methodology":        r"METHODOLOGY:\s*(.+?)(?=\nFEATURES_FOCUSED:|\Z)",
        "features_focused":   r"FEATURES_FOCUSED:\s*(.+?)(?=\nRESULTS_DISCUSSION:|\Z)",
        "results_discussion": r"RESULTS_DISCUSSION:\s*(.+?)(?=\nLIMITATIONS:|\Z)",
        "limitations":        r"LIMITATIONS:\s*(.+?)(?=\nFUTURE_SCOPE:|\Z)",
        "future_scope":       r"FUTURE_SCOPE:\s*(.+?)(?=\Z)",
    }

    fields = default.copy()
    for key, pat in patterns.items():
        m = re.search(pat, response, re.DOTALL | re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if val:
                fields[key] = val
    return fields


def analyze_topic(topic: str, max_papers: int = 15, progress_callback=None) -> List[Dict]:
    llm = LLMClient()

    if progress_callback:
        progress_callback(0, max_papers, "Fetching papers from arXiv...")

    papers = fetch_arxiv_papers(topic, max_papers=max_papers)
    if not papers:
        return []

    rows = []
    for i, paper in enumerate(papers):
        if progress_callback:
            progress_callback(i, len(papers), f"[{i+1}/{len(papers)}] Analysing: {paper['title'][:55]}...")

        full_text = download_pdf_text(paper["pdf_url"])
        if not full_text:
            full_text = paper["abstract"]

        fields = extract_fields(paper["title"], full_text, llm)

        rows.append({
            "No."                                              : i + 1,
            "Title"                                            : paper["title"],
            "Authors"                                          : paper["authors"],
            "Journal Details (DOI / Year / Citation)"          : f"DOI: {paper['doi']} | Year: {paper['year']} | Citation: {paper['citation']}",
            "Problem Statement"                                : fields["problem_statement"],
            "Objective"                                        : fields["objective"],
            "Research Gap"                                     : fields["research_gap"],
            "Methodology (Algorithm / Techniques)"             : fields["methodology"],
            "Features (Focused)"                               : fields["features_focused"],
            "Results & Discussion (Performance Metric / Value)": fields["results_discussion"],
            "Limitations"                                      : fields["limitations"],
            "Future Scope"                                     : fields["future_scope"],
        })

        time.sleep(1)

    if progress_callback:
        progress_callback(len(papers), len(papers), f"Done! Analysed {len(papers)} papers.")

    return rows

def generate_sample_paper(topic: str, rows: List[Dict]) -> str:
    """Generate a 4-5 page IEEE sample paper from the analysed rows."""
    llm = LLMClient()

    # Build a condensed summary of all analysed papers using all extracted fields
    context_lines = []
    for idx, row in enumerate(rows[:10], start=1):  # use top 10 papers as context
        context_lines.append(
            f"[{idx}] Paper: {row['Title']} ({row['Authors']})\n"
            f"    Journal Details: {row['Journal Details (DOI / Year / Citation)']}\n"
            f"    Problem Statement: {row['Problem Statement']}\n"
            f"    Objective: {row['Objective']}\n"
            f"    Research Gap: {row['Research Gap']}\n"
            f"    Methodology: {row['Methodology (Algorithm / Techniques)']}\n"
            f"    Features Focused: {row['Features (Focused)']}\n"
            f"    Results & Discussion: {row['Results & Discussion (Performance Metric / Value)']}\n"
            f"    Limitations: {row['Limitations']}\n"
            f"    Future Scope: {row['Future Scope']}\n"
        )
    context_str = "\n---\n".join(context_lines)

    prompt = f"""You are an expert academic researcher writing a formal IEEE-style survey/research paper.
Using ONLY the information extracted from the source papers listed below, write a complete IEEE research paper on the topic: "{topic}"

SECTION-BY-SECTION GUIDANCE (use the extracted fields as indicated):
- Abstract: Summarise the overall theme, the research gaps identified across papers, key methodologies, and major findings. (~150 words)
- Index Terms: 5–8 relevant keywords drawn from the papers.
- I. INTRODUCTION: Motivate the topic using the Problem Statements and Objectives of the source papers. Cite each paper inline as [1], [2], etc.
- II. LITERATURE REVIEW: For each source paper, briefly describe its Objective, Methodology, and Results. Organise chronologically or thematically. Cite all papers.
- III. PROBLEM DEFINITION: Synthesise the recurring Problem Statements across papers into a unified problem definition for the topic.
- IV. RELATED WORK: Discuss Research Gaps identified by each paper. Highlight how the works are connected and where they diverge.
- V. METHODOLOGY: Summarise the Methodologies and Features Focused on across the papers. Group similar algorithmic or technical approaches together.
- VI. RESULTS: Report exact performance metrics and values from the Results & Discussion field of each paper. Never invent numbers. Cite the source paper for every metric.
- VII. DISCUSSION: Analyse the Limitations of existing approaches. Connect limitations to the Research Gaps and explain implications for the field.
- VIII. CONCLUSION: Synthesise key findings and tie together the Future Scope suggestions from the papers into a forward-looking closing statement.
- REFERENCES: List all cited papers in IEEE reference format using the journal details provided (DOI, year, authors, title).

STRICT REQUIREMENTS:
- Length: 4 to 5 pages (approximately 2000 to 2500 words)
- Write in formal academic third-person style
- Do NOT use markdown formatting, bullet points, or numbered lists inside section bodies — use continuous prose paragraphs only
- Every factual claim must be backed by an inline citation [1]–[{len(rows[:10])}]
- Do NOT fabricate any results, statistics, or claims not present in the source papers
- Each section must contain at least two well-developed paragraphs

SOURCE PAPERS:
{context_str}

Write the full IEEE paper now:"""

    return llm.generate(prompt).strip()