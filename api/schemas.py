from pydantic import BaseModel

from config.config import Config


class GenerateRequest(BaseModel):
    topic: str
    # "auto" is resolved to hyde/complex by the API before being passed to the
    # pipeline — mirrors ui.py's auto_select_strategy().
    strategy: str = "auto"
    include_evaluation: bool = True
    fast_mode: bool = True
    force_refresh_sources: bool = False
    run_plagiarism_check: bool = True
    apply_ai_rewrite: bool = True
    apply_humanize: bool = True
    target_similarity_pct: float = 25.0
    max_rewrite_passes: int = 1
    fast_5page_mode: bool = True
    min_pages: int = Config.MIN_PAGES_DEFAULT
    author_name: str = ""
    author_affiliation: str = ""
    author_email: str = ""
    retrieval_top_k: int | None = None


class RefineRequest(BaseModel):
    topic: str
    paper_text: str
    context: list[dict]
    instruction: str


class SaveHistoryRequest(BaseModel):
    topic: str
    result: dict


class DocxRequest(BaseModel):
    paper_text: str
    title: str


class PdfRequest(BaseModel):
    topic: str
    paper_text: str
    use_latex: bool = False


class FixCitationsRequest(BaseModel):
    paper_text: str
    context: list[dict]


class AnalysisXlsxRequest(BaseModel):
    rows: list[dict]
    topic: str


class SurveyRequest(BaseModel):
    topic: str
    max_papers: int = Config.SURVEY_DEFAULT_PAPERS


class SurveyExportRequest(BaseModel):
    rows: list[dict]
    topic: str
