import { useState } from "react";
import {
  exportSurveyDocx,
  exportSurveyXlsx,
  downloadServerFile,
  type SurveyRow,
} from "./api";

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function extractArxivLink(row: SurveyRow): string {
  const jd = String(row["Journal Details (DOI / Year / Citation)"] || "");
  const m = jd.match(/arXiv:(\S+)/i);
  if (m) return `https://arxiv.org/abs/${m[1].replace(/\.$/, "")}`;
  return "";
}

function toCsv(rows: SurveyRow[]): string {
  if (rows.length === 0) return "";
  const headers = Object.keys(rows[0]);
  const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const lines = [headers.map(esc).join(",")];
  for (const row of rows) {
    lines.push(headers.map((h) => esc(row[h])).join(","));
  }
  return lines.join("\n");
}

const TABLE_COLS = [
  "No.",
  "Title",
  "Authors",
  "Journal Details (DOI / Year / Citation)",
  "Problem Statement",
  "Objective",
  "Research Gap",
  "Methodology (Algorithm / Techniques)",
  "Features (Focused)",
  "Results & Discussion (Performance Metric / Value)",
  "Limitations",
  "Future Scope",
];

export default function SurveyPanel({
  rows,
  topic,
  surveyPaperText,
  pdfPath,
}: {
  rows: SurveyRow[];
  topic: string;
  surveyPaperText: string;
  pdfPath: string | null;
}) {
  const [showGaps, setShowGaps] = useState(false);
  const [showPaper, setShowPaper] = useState(false);
  const safeTopic = topic.slice(0, 30).trim().replace(/\s+/g, "_") || "survey";

  const gaps = rows
    .map((r, i) => ({ title: String(r["Title"] || `Paper ${i + 1}`).slice(0, 55), gap: String(r["Research Gap"] || "") }))
    .filter((g) => g.gap && !["", "not mentioned"].includes(g.gap.trim().toLowerCase()));

  const downloadCsv = () => {
    const blob = new Blob([toCsv(rows)], { type: "text/csv" });
    downloadBlob(blob, `survey_${safeTopic}.csv`);
  };

  const downloadXlsx = async () => {
    const blob = await exportSurveyXlsx(rows, topic);
    downloadBlob(blob, `survey_${safeTopic}.xlsx`);
  };

  const downloadDocx = async () => {
    const blob = await exportSurveyDocx(rows, topic);
    downloadBlob(blob, `survey_${safeTopic}.docx`);
  };

  const downloadPdf = async () => {
    if (!pdfPath) return;
    const blob = await downloadServerFile(pdfPath);
    downloadBlob(blob, `survey_${safeTopic}_ieee.pdf`);
  };

  return (
    <div className="survey-panel">
      <div className="survey-success">
        <span>
          Literature survey — analysed <strong>{rows.length}</strong> papers on: <em>{topic}</em>
        </span>
        {gaps.length > 0 && (
          <span className="meta-item">{gaps.length} with a stated research gap</span>
        )}
      </div>

      <div className="table-scroll survey-table-wrapper">
        <table className="analysis-table">
          <thead>
            <tr>
              {TABLE_COLS.map((c) => (
                <th key={c}>{c}</th>
              ))}
              <th>Link</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => {
              const link = extractArxivLink(row);
              return (
                <tr key={i}>
                  {TABLE_COLS.map((c) => (
                    <td key={c}>{String(row[c] ?? "")}</td>
                  ))}
                  <td>
                    {link ? (
                      <a href={link} target="_blank" rel="noreferrer">
                        arXiv
                      </a>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {gaps.length > 0 && (
        <div className="expander">
          <button className="expander-toggle" onClick={() => setShowGaps(!showGaps)}>
            {showGaps ? "▾" : "▸"} Research Gap Summary ({gaps.length} papers)
          </button>
          {showGaps && (
            <div className="expander-body">
              {gaps.map((g, i) => (
                <div key={i} className="gap-item">
                  <span className="gap-title">
                    [{i + 1}] {g.title}
                  </span>
                  <div className="gap-text">{g.gap}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {surveyPaperText && (
        <div className="expander">
          <button className="expander-toggle" onClick={() => setShowPaper(!showPaper)}>
            {showPaper ? "▾" : "▸"} Sample survey paper (draft)
          </button>
          {showPaper && (
            <div className="expander-body">
              <pre className="paper-text">{surveyPaperText}</pre>
            </div>
          )}
        </div>
      )}

      <div className="export-buttons survey-export-row">
        <button onClick={downloadCsv}>↓ CSV</button>
        <button onClick={downloadXlsx}>↓ Excel</button>
        <button onClick={downloadDocx}>↓ Word (.docx)</button>
        {pdfPath && <button onClick={downloadPdf}>↓ PDF (IEEE)</button>}
      </div>
    </div>
  );
}
