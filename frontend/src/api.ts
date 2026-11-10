// Base URL of the FastAPI backend. Set VITE_API_URL in .env / .env.development.
// The fallback keeps a production build working when the var is not injected.
const API_URL = ((import.meta.env.VITE_API_URL as string | undefined) || "http://127.0.0.1:8001")
  .replace(/\/+$/, "");

export { API_URL };

export interface LlmHealth {
  provider: string;
  model: string;
  ready: boolean;
  detail: string;
  base_url?: string;
  num_ctx?: number;
  available_models?: string[];
}

export interface HealthResponse {
  status: "ok" | "degraded";
  llm: LlmHealth;
  settings: {
    survey_default_papers: number;
    survey_min_papers: number;
    survey_max_papers: number;
    top_k: number;
    min_pages_default: number;
    embedding_model: string;
  };
}

export interface GenerateOptions {
  topic: string;
  strategy?: string;
  include_evaluation?: boolean;
  fast_mode?: boolean;
  force_refresh_sources?: boolean;
  run_plagiarism_check?: boolean;
  apply_ai_rewrite?: boolean;
  apply_humanize?: boolean;
  retrieval_top_k?: number;
  author_name?: string;
  author_affiliation?: string;
  author_email?: string;
}

export interface Settings {
  strategy: string;
  topK: number;
  refreshSources: boolean;
  runEval: boolean;
  authorName: string;
  authorAffiliation: string;
  authorEmail: string;
  surveyPapers: number;
}

export const DEFAULT_SETTINGS: Settings = {
  strategy: "auto",
  topK: 6,
  refreshSources: true,
  runEval: true,
  authorName: "",
  authorAffiliation: "",
  authorEmail: "",
  surveyPapers: 10,
};

export interface RefineResult {
  paper_text: string;
  status: string;
  error: string | null;
}

export interface JobProgressStep {
  step: string;
  detail: string;
  at: number;
}

export interface RetrievedChunk {
  title: string;
  authors: string;
  published: string;
  filepath: string;
  source: string;
  score: number | null;
  rerank_score: number | null;
  text: string;
}

export interface PlagiarismReport {
  overall_similarity_pct: number;
  max_sentence_similarity_pct: number;
  ngram_overlap_pct: number;
}

export interface RougeL {
  avg_rouge_l: number;
}

export interface AnalysisRow {
  [key: string]: string;
}

export interface PipelineResult {
  paper_text: string;
  num_papers: number;
  strategy: string;
  faithfulness: number | null;
  relevance: number | null;
  faithfulness_reasoning?: string | null;
  relevance_reasoning?: string | null;
  // Set when the LLM-as-judge step itself failed; the paper is still valid.
  evaluation_error?: string | null;
  pdf_path?: string | null;
  page_estimate: number;
  status: string;
  error: string | null;
  retrieved_context: RetrievedChunk[];
  timings: Record<string, number>;
  plagiarism_report: PlagiarismReport | null;
  rouge_l: RougeL | null;
  ai_rewrite_passes: number;
  humanize_applied: boolean;
  analysis_table: AnalysisRow[];
}

export interface Job {
  status: "running" | "done" | "error";
  progress: JobProgressStep[];
  result: PipelineResult | null;
  error: string | null;
}

export interface SurveyRow {
  [key: string]: string | number;
}

export interface SurveyResult {
  rows: SurveyRow[];
  survey_paper_text: string;
  pdf_path: string | null;
  status: string;
}

export interface SurveyJob {
  status: "running" | "done" | "error";
  progress: JobProgressStep[];
  result: SurveyResult | null;
  error: string | null;
}

export interface HistoryEntry {
  topic: string;
  saved_at: number;
  fname: string;
  page_estimate: number;
  strategy: string;
}

async function jsonFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

export function getHealth(): Promise<HealthResponse> {
  return jsonFetch("/api/health");
}

export function startGenerate(opts: GenerateOptions): Promise<{ job_id: string }> {
  return jsonFetch("/api/generate", { method: "POST", body: JSON.stringify(opts) });
}

export function getJob(jobId: string): Promise<Job> {
  return jsonFetch(`/api/jobs/${jobId}`);
}

export interface RefineJob {
  status: "running" | "done" | "error";
  progress: JobProgressStep[];
  result: RefineResult | null;
  error: string | null;
}

export function getRefineJob(jobId: string): Promise<RefineJob> {
  return jsonFetch(`/api/jobs/${jobId}`);
}

export function startRefine(
  topic: string,
  paperText: string,
  context: PipelineResult["retrieved_context"],
  instruction: string
): Promise<{ job_id: string }> {
  return jsonFetch("/api/refine", {
    method: "POST",
    body: JSON.stringify({ topic, paper_text: paperText, context, instruction }),
  });
}

export function getHistory(): Promise<HistoryEntry[]> {
  return jsonFetch("/api/history");
}

export function deleteHistory(fname: string): Promise<{ deleted: boolean }> {
  return jsonFetch(`/api/history/${fname}`, { method: "DELETE" });
}

export function loadHistoryItem(fname: string): Promise<PipelineResult & { topic: string }> {
  return jsonFetch(`/api/history/${fname}`);
}

export function saveHistory(topic: string, result: PipelineResult): Promise<{ saved: boolean }> {
  return jsonFetch("/api/history/save", { method: "POST", body: JSON.stringify({ topic, result }) });
}

export async function exportDocx(paperText: string, title: string): Promise<Blob> {
  const res = await fetch(`${API_URL}/api/export/docx`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paper_text: paperText, title }),
  });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.blob();
}

export async function exportPdf(topic: string, paperText: string, useLatex = false): Promise<Blob> {
  const res = await fetch(`${API_URL}/api/export/pdf`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic, paper_text: paperText, use_latex: useLatex }),
  });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.blob();
}

export function fixCitations(paperText: string, context: RetrievedChunk[]): Promise<{ paper_text: string }> {
  return jsonFetch("/api/fix-citations", {
    method: "POST",
    body: JSON.stringify({ paper_text: paperText, context }),
  });
}

export function startSurvey(topic: string, maxPapers: number): Promise<{ job_id: string }> {
  return jsonFetch("/api/survey", { method: "POST", body: JSON.stringify({ topic, max_papers: maxPapers }) });
}

export function getSurveyJob(jobId: string): Promise<SurveyJob> {
  return jsonFetch(`/api/jobs/${jobId}`);
}

export async function exportSurveyDocx(rows: SurveyRow[], topic: string): Promise<Blob> {
  const res = await fetch(`${API_URL}/api/export/survey-docx`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rows, topic }),
  });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.blob();
}

export async function exportSurveyXlsx(rows: SurveyRow[], topic: string): Promise<Blob> {
  const res = await fetch(`${API_URL}/api/export/survey-xlsx`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rows, topic }),
  });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.blob();
}

export async function downloadServerFile(path: string): Promise<Blob> {
  const res = await fetch(`${API_URL}/api/download?path=${encodeURIComponent(path)}`);
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.blob();
}

export async function exportAnalysisXlsx(rows: AnalysisRow[], topic: string): Promise<Blob> {
  const res = await fetch(`${API_URL}/api/export/analysis-xlsx`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rows, topic }),
  });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.blob();
}
