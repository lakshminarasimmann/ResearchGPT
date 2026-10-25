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

export default function ResultPanel({
  result,
  topic,
  onPaperTextChange,
}: {
  result: PipelineResult;
  topic: string;
  onPaperTextChange: (text: string) => void;
}) {
  const [showChunks, setShowChunks] = useState(false);
  const [showAnalysis, setShowAnalysis] = useState(false);
  const [showPlagiarism, setShowPlagiarism] = useState(false);
  const [fixingCitations, setFixingCitations] = useState(false);
  const [bannerDismissed, setBannerDismissed] = useState(false);

  const safeName = topic.slice(0, 40).trim().replace(/\s+/g, "_") || "paper";

  const downloadDocx = async () => {
    const blob = await exportDocx(result.paper_text, topic);
    downloadBlob(blob, `${safeName}.docx`);
  };

  const downloadPdf = async (useLatex: boolean) => {
    const blob = await exportPdf(topic, result.paper_text, useLatex);
    downloadBlob(blob, `${safeName}${useLatex ? "_latex" : ""}.pdf`);
  };

  const downloadAnalysisXlsx = async () => {
    const blob = await exportAnalysisXlsx(result.analysis_table, topic);
    downloadBlob(blob, `analysis_${safeName}.xlsx`);
  };

  const runFixCitations = async () => {
    setFixingCitations(true);
    try {
      const { paper_text } = await fixCitations(result.paper_text, result.retrieved_context);
      onPaperTextChange(paper_text);
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

  return (
    <>
      <div className="result-meta">
        <ScoreBadge label="Faithfulness" score={result.faithfulness} />
        <ScoreBadge label="Relevance" score={result.relevance} />
        <div className="meta-item">{result.num_papers} papers</div>
        <div className="meta-item">~{result.page_estimate} pages</div>
        {result.ai_rewrite_passes > 0 && (
          <div className="meta-item">{result.ai_rewrite_passes} rewrite pass(es)</div>
        )}
        {result.humanize_applied && <div className="meta-item">humanized</div>}
        <div className="export-buttons">
          <button onClick={downloadDocx}>⬇ Word (.docx)</button>
          <button onClick={() => downloadPdf(false)}>⬇ PDF</button>
          <button onClick={() => downloadPdf(true)}>⬇ LaTeX PDF</button>
        </div>
      </div>

      {lowFaithfulness && !bannerDismissed && (
        <div className="warning-banner">
          <span>Low faithfulness score — the paper may cite sources loosely.</span>
          <button onClick={runFixCitations} disabled={fixingCitations}>
            {fixingCitations ? "Fixing…" : "🔧 Fix Citations"}
          </button>
          <button className="banner-dismiss" onClick={() => setBannerDismissed(true)}>
            ✕
          </button>
        </div>
      )}

      <pre className="paper-text">{result.paper_text}</pre>

      <div className="panel-row">
        <button
          className="fix-citations-btn"
          onClick={runFixCitations}
          disabled={fixingCitations}
        >
          {fixingCitations ? "Fixing…" : "🔧 Fix Citations (rebuild from source metadata)"}
        </button>
      </div>

      {result.plagiarism_report && (
        <div className="expander">
          <button className="expander-toggle" onClick={() => setShowPlagiarism(!showPlagiarism)}>
            {showPlagiarism ? "▾" : "▸"} Plagiarism report
          </button>
          {showPlagiarism && (
            <div className="expander-body plagiarism-grid">
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
          )}
        </div>
      )}

      {result.analysis_table.length > 0 && (
        <div className="expander">
          <button className="expander-toggle" onClick={() => setShowAnalysis(!showAnalysis)}>
            {showAnalysis ? "▾" : "▸"} Comparative analysis table
          </button>
          {showAnalysis && (
            <div className="expander-body table-scroll">
              <div className="panel-row">
                <button onClick={downloadAnalysisXlsx}>⬇ Download Excel</button>
              </div>
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
          )}
        </div>
      )}

      {result.retrieved_context.length > 0 && (
        <div className="expander">
          <button className="expander-toggle" onClick={() => setShowChunks(!showChunks)}>
            {showChunks ? "▾" : "▸"} View {Math.min(8, result.retrieved_context.length)} retrieved chunks
          </button>
          {showChunks && (
            <div className="expander-body">
              <div className="contribution-chart">
                {Object.entries(titleCounts).map(([title, count]) => (
                  <div key={title} className="contribution-row">
                    <div className="contribution-label" title={title}>
                      {title}
                    </div>
                    <div className="contribution-bar-track">
                      <div
                        className="contribution-bar"
                        style={{ width: `${(count / maxCount) * 100}%` }}
                      />
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
            </div>
          )}
        </div>
      )}

      <div className="refine-anchor" />
    </>
  );
}
