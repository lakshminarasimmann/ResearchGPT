import { useEffect, useState } from "react";
import { getArchiveEntry, type ArchiveDetail } from "../api";

/** Metric names worth promoting to the summary row, in display order. */
const HEADLINE = [
  "Faithfulness",
  "Relevance",
  "Source papers",
  "Similarity to sources",
  "Total time",
];

/**
 * One archived run: the permanent record written to docs/runs/ when the paper
 * finished, including the scores and the sources it was built from.
 *
 * This is deliberately the file as committed, not a re-render of live state —
 * the point is to show what was actually produced.
 */
export default function ArchivePanel({ file }: { file: string }) {
  const [entry, setEntry] = useState<ArchiveDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setEntry(null);
    setError(null);
    getArchiveEntry(file)
      .then((d) => !cancelled && setEntry(d))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [file]);

  if (error) return <div className="error-panel">Could not load archived run: {error}</div>;
  if (!entry) return <div className="progress-panel">Loading archived run…</div>;

  // The paper body starts after the "## Paper" heading.
  const split = entry.markdown.indexOf("## Paper");
  const paper = split >= 0 ? entry.markdown.slice(split + "## Paper".length).trim() : entry.markdown;

  const headline = HEADLINE.filter((k) => entry.metrics[k]);
  const rest = Object.entries(entry.metrics).filter(([k]) => !HEADLINE.includes(k));

  const download = () => {
    const blob = new Blob([entry.markdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = entry.file;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="archive-panel">
      <div className="result-meta">
        {headline.map((k) => (
          <div key={k} className="score-badge">
            <div className="score-label">{k}</div>
            <span className="score-pill score-none">{entry.metrics[k]}</span>
          </div>
        ))}
        <div className="export-buttons">
          <button onClick={download}>↓ Markdown</button>
        </div>
      </div>

      <div className="archive-note">
        Archived record — <code>docs/runs/{entry.file}</code>
      </div>

      {rest.length > 0 && (
        <div className="plagiarism-grid">
          {rest.map(([k, v]) => (
            <div key={k}>
              <div className="meta-label">{k}</div>
              <div className="meta-value">{v}</div>
            </div>
          ))}
        </div>
      )}

      <pre className="paper-text">{paper}</pre>
    </div>
  );
}
