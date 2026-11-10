import { useState } from "react";
import { exportDocx, exportPdf, fixCitations, exportAnalysisXlsx, type PipelineResult } from "./api";

function ScoreBadge({ label, score }: { label: string; score: number | null }) {
  let tone: "good" | "fair" | "poor" | "none" = "none";
  if (score !== null) {
    tone = score >= 4 ? "good" : score >= 3 ? "fair" : "poor";
  }
  return (
    <div className="score-badge">
      <div className="score-label">{label}</div>
      <span className={`score-pill score-${tone}`}>{score !== null ? `${score.toFixed(1)}/5` : "—"}</span>
    </div>
  );
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** A collapsible section. Keeps the `.expander` hooks the tests rely on. */
function Expander({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="expander">
      <button className="expander-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
        {open ? "▾" : "▸"} {label}
      </button>
      {open && <div className="expander-body">{children}</div>}
    </div>
  );
}

export default function ResultPanel({
  result,
  topic,
  onPaperTextChange,
}: {
  result: PipelineResult;
  topic: string;
  onPaperTextChange: (text: string) => void;
}) {
  const [fixingCitations, setFixingCitations] = useState(false);
  const [bannerDismissed, setBannerDismissed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const safeName = topic.slice(0, 40).trim().replace(/\s+/g, "_") || "paper";

  // Exports hit the backend and can fail (no LaTeX toolchain, for example);
  // surface that instead of letting the click do nothing.
  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setExportError(null);
    try {
      await fn();
    } catch (e) {
      setExportError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const downloadDocx = () =>
    run("docx", async () => {
      const blob = await exportDocx(result.paper_text, topic);
      downloadBlob(blob, `${safeName}.docx`);
    });

  const downloadPdf = (useLatex: boolean) =>
    run(useLatex ? "latex" : "pdf", async () => {
      const blob = await exportPdf(topic, result.paper_text, useLatex);
      downloadBlob(blob, `${safeName}${useLatex ? "_latex" : ""}.pdf`);
    });

  const downloadAnalysisXlsx = () =>
    run("xlsx", async () => {
      const blob = await exportAnalysisXlsx(result.analysis_table, topic);
      downloadBlob(blob, `analysis_${safeName}.xlsx`);
    });

  const runFixCitations = async () => {
    setFixingCitations(true);
    setExportError(null);
    try {
      const { paper_text } = await fixCitations(result.paper_text, result.retrieved_context);
      onPaperTextChange(paper_text);
    } catch (e) {
      setExportError(e instanceof Error ? e.message : String(e));
    } finally {
      setFixingCitations(false);
    }
  };

  if (result.status !== "ok") {
    return <div className="error-panel">{result.error}</div>;
  }

  const lowFaithfulness = result.faithfulness !== null && result.faithfulness < 3;

  const titleCounts: Record<string, number> = {};
  for (const c of result.retrieved_context) {
    titleCounts[c.title] = (titleCounts[c.title] || 0) + 1;
  }
  const maxCount = Math.max(1, ...Object.values(titleCounts));

  const wordCount = result.paper_text.trim().split(/\s+/).filter(Boolean).length;
  const timings = Object.entries(result.timings ?? {});

  return (
    <>
      <div className="result-meta">
        <ScoreBadge label="Faithfulness" score={result.faithfulness} />
        <ScoreBadge label="Relevance" score={result.relevance} />
        <div className="meta-item">{result.num_papers} papers</div>
        <div className="meta-item">~{result.page_estimate} pages</div>
        <div className="meta-item">{wordCount.toLocaleString()} words</div>
        <div className="meta-item">{result.strategy}</div>
        {result.ai_rewrite_passes > 0 && (
          <div className="meta-item">{result.ai_rewrite_passes} rewrite pass(es)</div>
        )}
        {result.humanize_applied && <div className="meta-item">humanized</div>}
        <div className="export-buttons">
          <button onClick={downloadDocx} disabled={busy === "docx"}>
            {busy === "docx" ? "Preparing…" : "⬇ Word (.docx)"}
          </button>
          <button onClick={() => downloadPdf(false)} disabled={busy === "pdf"}>
            {busy === "pdf" ? "Preparing…" : "⬇ PDF"}
          </button>
          <button onClick={() => downloadPdf(true)} disabled={busy === "latex"}>
            {busy === "latex" ? "Preparing…" : "⬇ LaTeX PDF"}
          </button>
        </div>
      </div>

      {exportError && <div className="error-panel">Export failed: {exportError}</div>}

      {lowFaithfulness && !bannerDismissed && (
        <div className="warning-banner">
          <span>Low faithfulness score — the paper may cite sources loosely.</span>
          <button onClick={runFixCitations} disabled={fixingCitations}>
            {fixingCitations ? "Fixing…" : "🔧 Fix Citations"}
          </button>
          <button className="banner-dismiss" onClick={() => setBannerDismissed(true)} aria-label="Dismiss">
            ✕
          </button>
        </div>
      )}

      <pre className="paper-text">{result.paper_text}</pre>

      <div className="panel-row">
        <button className="fix-citations-btn" onClick={runFixCitations} disabled={fixingCitations}>
          {fixingCitations ? "Fixing…" : "🔧 Fix Citations (rebuild from source metadata)"}
        </button>
      </div>

      {(result.faithfulness_reasoning || result.relevance_reasoning || result.evaluation_error ||
        timings.length > 0) && (
        <Expander label="Evaluation notes & timings">
          {result.evaluation_error && (
            <div className="error-panel">Evaluation could not run: {result.evaluation_error}</div>
          )}
          {result.faithfulness_reasoning && (
            <div className="gap-item">
              <span className="gap-title">Faithfulness</span>
              <div className="gap-text">{result.faithfulness_reasoning}</div>
            </div>
          )}
          {result.relevance_reasoning && (
            <div className="gap-item">
              <span className="gap-title">Relevance</span>
              <div className="gap-text">{result.relevance_reasoning}</div>
            </div>
          )}
          {timings.length > 0 && (
            <div className="plagiarism-grid">
              {timings.map(([k, v]) => (
                <div key={k}>
                  <div className="meta-label">{k.replace(/_seconds$/, "").replace(/_/g, " ")}</div>
                  <div className="meta-value">{typeof v === "number" ? `${v}s` : String(v)}</div>
                </div>
              ))}
            </div>
          )}
        </Expander>
      )}

      {result.plagiarism_report && (
        <Expander label="Plagiarism report">
          <div className="plagiarism-grid">
            <div>
              <div className="meta-label">Avg Similarity</div>
              <div className="meta-value">{result.plagiarism_report.overall_similarity_pct}%</div>
            </div>
            <div>
              <div className="meta-label">Max Sentence Sim</div>
              <div className="meta-value">{result.plagiarism_report.max_sentence_similarity_pct}%</div>
            </div>
            <div>
              <div className="meta-label">8-gram Overlap</div>
              <div className="meta-value">{result.plagiarism_report.ngram_overlap_pct}%</div>
            </div>
            {result.rouge_l && (
              <div>
                <div className="meta-label">ROUGE-L avg</div>
                <div className="meta-value">{result.rouge_l.avg_rouge_l.toFixed(3)}</div>
              </div>
            )}
          </div>
          <p className="settings-hint">
            Similarity is measured against the retrieved source chunks, not the whole web.
          </p>
        </Expander>
      )}

      {result.analysis_table.length > 0 && (
        <Expander label="Comparative analysis table">
          <div className="panel-row">
            <button onClick={downloadAnalysisXlsx} disabled={busy === "xlsx"}>
              {busy === "xlsx" ? "Preparing…" : "⬇ Download Excel"}
            </button>
          </div>
          <div className="table-scroll">
            <table className="analysis-table">
              <thead>
                <tr>
                  {Object.keys(result.analysis_table[0]).map((k) => (
                    <th key={k}>{k}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.analysis_table.map((row, i) => (
                  <tr key={i}>
                    {Object.keys(result.analysis_table[0]).map((k) => (
                      <td key={k}>{row[k]}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Expander>
      )}

      {result.retrieved_context.length > 0 && (
        <Expander label={`View ${Math.min(8, result.retrieved_context.length)} retrieved chunks`}>
          <div className="contribution-chart">
            {Object.entries(titleCounts).map(([title, count]) => (
              <div key={title} className="contribution-row">
                <div className="contribution-label" title={title}>
                  {title}
                </div>
                <div className="contribution-bar-track">
                  <div className="contribution-bar" style={{ width: `${(count / maxCount) * 100}%` }} />
                </div>
                <div className="contribution-count">{count}</div>
              </div>
            ))}
          </div>
          {result.retrieved_context.slice(0, 8).map((chunk, i) => (
            <div key={i} className="chunk-item">
              <div className="chunk-title">
                [{i + 1}] {chunk.title || "Unknown"}
              </div>
              <div className="chunk-score">score: {chunk.rerank_score ?? chunk.score ?? "—"}</div>
              <div className="chunk-text">
                {chunk.text.replace(/\s+/g, " ").slice(0, 600)}
                {chunk.text.length > 600 ? "…" : ""}
              </div>
            </div>
          ))}
        </Expander>
      )}

      <div className="refine-anchor" />
    </>
  );
}
