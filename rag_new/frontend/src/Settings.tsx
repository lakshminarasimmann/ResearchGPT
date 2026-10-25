import type { Settings } from "./api";

const STRATEGY_DESC: Record<string, string> = {
  auto: "Automatically picks the best strategy for your query.",
  hyde: "Generates a hypothetical answer first — best for open-ended topics.",
  complex: "Breaks your query into sub-questions — best for comparisons & benchmarks.",
  standard: "Plain hybrid BM25 + vector search — fastest.",
};

export default function SettingsPanel({
  settings,
  onChange,
  onClose,
}: {
  settings: Settings;
  onChange: (s: Settings) => void;
  onClose: () => void;
}) {
  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-panel" onClick={(e) => e.stopPropagation()}>
        <div className="settings-header">
          <h2>Settings</h2>
          <button className="settings-close" onClick={onClose}>
            ✕
          </button>
        </div>

        <label className="settings-field">
          <span>Full name</span>
          <input
            type="text"
            placeholder="e.g. Jane Smith"
            value={settings.authorName}
            onChange={(e) => onChange({ ...settings, authorName: e.target.value })}
          />
        </label>

        <label className="settings-field">
          <span>Affiliation</span>
          <input
            type="text"
            placeholder="e.g. MIT"
            value={settings.authorAffiliation}
            onChange={(e) => onChange({ ...settings, authorAffiliation: e.target.value })}
          />
        </label>

        <label className="settings-field">
          <span>Email</span>
          <input
            type="text"
            placeholder="e.g. jsmith@mit.edu"
            value={settings.authorEmail}
            onChange={(e) => onChange({ ...settings, authorEmail: e.target.value })}
          />
        </label>

        <label className="settings-field">
          <span>Survey papers: {settings.surveyPapers}</span>
          <input
            type="range"
            min={3}
            max={15}
            value={settings.surveyPapers}
            onChange={(e) => onChange({ ...settings, surveyPapers: Number(e.target.value) })}
          />
          <p className="settings-hint">How many arXiv papers to fetch for the literature survey.</p>
        </label>

        <div className="settings-divider" />

        <label className="settings-field">
          <span>Retrieval Strategy</span>
          <select
            value={settings.strategy}
            onChange={(e) => onChange({ ...settings, strategy: e.target.value })}
          >
            <option value="auto">auto</option>
            <option value="hyde">hyde</option>
            <option value="complex">complex</option>
            <option value="standard">standard</option>
          </select>
          <p className="settings-hint">{STRATEGY_DESC[settings.strategy]}</p>
        </label>

        <label className="settings-field">
          <span>Retrieval chunks (top-k): {settings.topK}</span>
          <input
            type="range"
            min={3}
            max={12}
            value={settings.topK}
            onChange={(e) => onChange({ ...settings, topK: Number(e.target.value) })}
          />
          <p className="settings-hint">Chunks retrieved for paper generation. Higher = richer context, slower.</p>
        </label>

        <label className="settings-checkbox">
          <input
            type="checkbox"
            checked={settings.refreshSources}
            onChange={(e) => onChange({ ...settings, refreshSources: e.target.checked })}
          />
          <span>Refresh papers from arXiv</span>
        </label>
        <p className="settings-hint">Force re-download papers. Enable if results used too few sources.</p>

        <label className="settings-checkbox">
          <input
            type="checkbox"
            checked={settings.runEval}
            onChange={(e) => onChange({ ...settings, runEval: e.target.checked })}
          />
          <span>Run quality evaluation</span>
        </label>
        <p className="settings-hint">Score faithfulness and relevance. Adds ~30s.</p>

        <button className="settings-save" onClick={onClose}>
          ✓ Save & return
        </button>
      </div>
    </div>
  );
}
