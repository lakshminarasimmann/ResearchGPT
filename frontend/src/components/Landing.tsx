import type { ReactNode } from "react";

const EXAMPLES = [
  "Hallucination mitigation in RAG",
  "Self-healing large language models",
  "Parameter-efficient fine-tuning",
  "Vision transformers for medical imaging",
];

const STEPS = [
  { n: "01", t: "Search", d: "Finds and downloads matching papers from arXiv." },
  { n: "02", t: "Index", d: "Parses the PDFs and embeds them into a vector store." },
  { n: "03", t: "Retrieve", d: "Hybrid BM25 + vector search, reranked by a cross-encoder." },
  { n: "04", t: "Write", d: "Drafts a cited IEEE paper, then scores its own output." },
];

/**
 * First screen of a session: the composer plus enough context to know what
 * this tool does and what a good topic looks like.
 */
export default function Landing({
  composer,
  onPickExample,
  showIntro,
}: {
  composer: ReactNode;
  onPickExample: (topic: string) => void;
  showIntro: boolean;
}) {
  if (!showIntro) return <>{composer}</>;

  return (
    <div className="landing">
      <div className="landing-eyebrow">Retrieval-augmented research</div>
      <h2>From a topic to a cited paper</h2>
      <p className="landing-sub">
        Give it a research topic. It pulls real papers from arXiv, builds a literature
        survey table, and drafts an IEEE-style paper grounded in what it retrieved.
      </p>

      {composer}

      <div className="examples">
        <div className="examples-label">Try a topic</div>
        <div className="example-chips">
          {EXAMPLES.map((e) => (
            <button key={e} className="chip" onClick={() => onPickExample(e)}>
              {e}
            </button>
          ))}
        </div>
      </div>

      <div className="landing-steps">
        {STEPS.map((s) => (
          <div key={s.n} className="landing-step">
            <div className="landing-step-n">{s.n}</div>
            <div className="landing-step-t">{s.t}</div>
            <div className="landing-step-d">{s.d}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
