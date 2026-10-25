import { useEffect, useRef, useState } from "react";
import {
  startGenerate,
  getJob,
  getHistory,
  deleteHistory,
  loadHistoryItem,
  saveHistory,
  startRefine,
  getRefineJob,
  startSurvey,
  getSurveyJob,
  DEFAULT_SETTINGS,
  type Job,
  type PipelineResult,
  type HistoryEntry,
  type Settings,
  type SurveyJob,
  type SurveyResult,
} from "./api";
import SettingsPanel from "./Settings";
import ResultPanel from "./ResultPanel";
import SurveyPanel from "./SurveyPanel";
import "./App.css";

interface ChatSession {
  id: number;
  topic: string;
  running: boolean;
  phase: "survey" | "generate" | null;
  job: Job | null;
  surveyJob: SurveyJob | null;
  surveyResult: SurveyResult | null;
  result: PipelineResult | null;
}

const POLL_MS = 1500;
// Consecutive failed status checks tolerated before a job is treated as lost.
const MAX_POLL_FAILURES = 3;

const errorMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));

// Polls a job until it leaves "running". Returns the interval handle.
function pollJob<T extends { status: string }>(
  fetchJob: () => Promise<T>,
  onUpdate: (job: T) => void,
  onFinish: (job: T) => void,
  onFail: (message: string) => void
): number {
  let failures = 0;
  let busy = false;
  const handle = window.setInterval(async () => {
    if (busy) return;
    busy = true;
    try {
      const job = await fetchJob();
      failures = 0;
      onUpdate(job);
      if (job.status !== "running") {
        window.clearInterval(handle);
        onFinish(job);
      }
    } catch (e) {
      if (++failures >= MAX_POLL_FAILURES) {
        window.clearInterval(handle);
        onFail(`Lost contact with the server: ${errorMessage(e)}`);
      }
    } finally {
      busy = false;
    }
  }, POLL_MS);
  return handle;
}

function makeChat(id: number): ChatSession {
  return {
    id,
    topic: "",
    running: false,
    phase: null,
    job: null,
    surveyJob: null,
    surveyResult: null,
    result: null,
  };
}

export default function App() {
  const [chats, setChats] = useState<ChatSession[]>([makeChat(0)]);
  const [activeChatId, setActiveChatId] = useState(0);
  const nextChatId = useRef(1);

  const [topicInput, setTopicInput] = useState("");
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [showSettings, setShowSettings] = useState(false);
  const [instruction, setInstruction] = useState("");
  const [refining, setRefining] = useState(false);
  const [refineError, setRefineError] = useState<string | null>(null);

  const pollRefs = useRef<Map<number, number>>(new Map());
  const refinePollRef = useRef<number | null>(null);

  const active = chats.find((c) => c.id === activeChatId) ?? chats[0];

  const updateChat = (id: number, patch: Partial<ChatSession>) => {
    setChats((cs) => cs.map((c) => (c.id === id ? { ...c, ...patch } : c)));
  };

  const refreshHistory = () => getHistory().then(setHistory).catch(() => {});

  useEffect(() => {
    refreshHistory();
  }, []);

  useEffect(() => {
    const polls = pollRefs.current;
    return () => {
      polls.forEach((h) => window.clearInterval(h));
      if (refinePollRef.current) window.clearInterval(refinePollRef.current);
    };
  }, []);

  const saveToHistory = (topic: string, result: PipelineResult) =>
    saveHistory(topic, result).then(refreshHistory).catch(() => {});

  const newChat = () => {
    const id = nextChatId.current++;
    setChats((cs) => [...cs, makeChat(id)]);
    setActiveChatId(id);
    setTopicInput("");
  };

  const closeChat = (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
    const h = pollRefs.current.get(id);
    if (h) window.clearInterval(h);
    setChats((cs) => {
      const rest = cs.filter((c) => c.id !== id);
      const next = rest.length > 0 ? rest : [makeChat(nextChatId.current++)];
      if (id === activeChatId) setActiveChatId(next[0].id);
      return next;
    });
  };

  const runRagPhase = (chatId: number, t: string) => {
    updateChat(chatId, {
      phase: "generate",
      job: { status: "running", progress: [], result: null, error: null },
    });

    const fail = (message: string) => {
      pollRefs.current.delete(chatId);
      updateChat(chatId, {
        running: false,
        job: { status: "error", progress: [], result: null, error: message },
      });
    };

    startGenerate({
      topic: t,
      strategy: settings.strategy,
      retrieval_top_k: settings.topK,
      force_refresh_sources: settings.refreshSources,
      include_evaluation: settings.runEval,
      author_name: settings.authorName,
      author_affiliation: settings.authorAffiliation,
      author_email: settings.authorEmail,
    })
      .then(({ job_id }) => {
        const handle = pollJob(
          () => getJob(job_id),
          (j) => updateChat(chatId, { job: j }),
          (j) => {
            pollRefs.current.delete(chatId);
            updateChat(chatId, { running: false });
            if (j.status === "done" && j.result) {
              updateChat(chatId, { result: j.result });
              if (j.result.status === "ok") saveToHistory(t, j.result);
            }
          },
          fail
        );
        pollRefs.current.set(chatId, handle);
      })
      .catch((e) => fail(`Could not start paper generation: ${errorMessage(e)}`));
  };

  const runGeneration = (chatId: number, t: string) => {
    if (!t.trim()) return;
    updateChat(chatId, {
      running: true,
      topic: t,
      result: null,
      surveyResult: null,
      phase: "survey",
      surveyJob: { status: "running", progress: [], result: null, error: null },
    });

    // A failed survey is reported but doesn't block paper generation.
    const fail = (message: string) => {
      pollRefs.current.delete(chatId);
      updateChat(chatId, { surveyJob: { status: "error", progress: [], result: null, error: message } });
      runRagPhase(chatId, t);
    };

    startSurvey(t, settings.surveyPapers)
      .then(({ job_id }) => {
        const handle = pollJob(
          () => getSurveyJob(job_id),
          (j) => updateChat(chatId, { surveyJob: j }),
          (j) => {
            pollRefs.current.delete(chatId);
            if (j.status === "done" && j.result) {
              updateChat(chatId, { surveyResult: j.result });
            }
            runRagPhase(chatId, t);
          },
          fail
        );
        pollRefs.current.set(chatId, handle);
      })
      .catch((e) => fail(`Could not start survey: ${errorMessage(e)}`));
  };

  const openHistoryItem = async (fname: string) => {
    const entry = await loadHistoryItem(fname);
    const id = nextChatId.current++;
    setChats((cs) => [...cs, { ...makeChat(id), topic: entry.topic, result: entry }]);
    setActiveChatId(id);
  };

  const removeHistoryItem = async (fname: string, e: React.MouseEvent) => {
    e.stopPropagation();
    await deleteHistory(fname);
    refreshHistory();
  };

  const applyRefine = () => {
    if (!active.result || !instruction.trim() || refining) return;
    setRefining(true);
    setRefineError(null);
    const chatId = active.id;
    const topic = active.topic;
    const baseResult = active.result;

    const fail = (message: string) => {
      refinePollRef.current = null;
      setRefining(false);
      setRefineError(message);
    };

    startRefine(topic, baseResult.paper_text, baseResult.retrieved_context, instruction)
      .then(({ job_id }) => {
        refinePollRef.current = pollJob(
          () => getRefineJob(job_id),
          () => {},
          (j) => {
            refinePollRef.current = null;
            setRefining(false);
            if (j.status === "done" && j.result && j.result.status === "ok") {
              const merged: PipelineResult = { ...baseResult, paper_text: j.result.paper_text };
              setChats((cs) => cs.map((c) => (c.id === chatId ? { ...c, result: merged } : c)));
              setInstruction("");
              saveToHistory(topic, merged);
            } else {
              setRefineError(j.error || j.result?.error || "Refinement failed.");
            }
          },
          fail
        );
      })
      .catch((e) => fail(`Could not start refinement: ${errorMessage(e)}`));
  };

  return (
    <div className="layout">
      <aside className="sidebar">
        <button className="new-btn" onClick={newChat}>
          + New Research
        </button>

        <div className="chat-tabs">
          {chats
            .slice()
            .reverse()
            .map((c) => (
              <div
                key={c.id}
                className={`chat-tab ${c.id === activeChatId ? "active" : ""}`}
                onClick={() => setActiveChatId(c.id)}
              >
                <div className="chat-tab-topic">{c.topic || "New chat"}</div>
                {c.running && <span className="chat-tab-spinner">●</span>}
                {chats.length > 1 && (
                  <button className="history-delete" onClick={(e) => closeChat(c.id, e)}>
                    ✕
                  </button>
                )}
              </div>
            ))}
        </div>

        <div className="sidebar-divider" />
        <div className="sidebar-label">History</div>
        <div className="history-list">
          {history.map((h) => (
            <div key={h.fname} className="history-item" onClick={() => openHistoryItem(h.fname)}>
              <div className="history-topic">{h.topic}</div>
              <button className="history-delete" onClick={(e) => removeHistoryItem(h.fname, e)}>
                ✕
              </button>
            </div>
          ))}
        </div>
      </aside>

      <main className="main">
        <div className="main-header">
          <h1>ResearchGPT</h1>
          <button className="settings-gear" onClick={() => setShowSettings(true)} title="Settings">
            ⚙
          </button>
        </div>

        {showSettings && (
          <SettingsPanel settings={settings} onChange={setSettings} onClose={() => setShowSettings(false)} />
        )}

        {!active.result && !active.running && (
          <div className="topic-input-row">
            <input
              className="topic-input"
              placeholder="Enter a research topic…"
              value={topicInput}
              onChange={(e) => setTopicInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runGeneration(active.id, topicInput)}
            />
            <button
              onClick={() => runGeneration(active.id, topicInput)}
              disabled={!topicInput.trim()}
            >
              Generate
            </button>
          </div>
        )}

        {active.phase === "survey" && active.surveyJob && active.surveyJob.status === "running" && (
          <div className="progress-panel">
            <div className="progress-step">Running literature survey…</div>
            {active.surveyJob.progress.map((p, i) => (
              <div key={i} className="progress-step">
                {p.detail || p.step}
              </div>
            ))}
          </div>
        )}

        {active.surveyJob && active.surveyJob.status === "error" && (
          <div className="error-panel">Survey error: {active.surveyJob.error}</div>
        )}

        {active.surveyResult && active.surveyResult.rows.length > 0 && (
          <SurveyPanel
            rows={active.surveyResult.rows}
            topic={active.topic}
            surveyPaperText={active.surveyResult.survey_paper_text}
            pdfPath={active.surveyResult.pdf_path}
          />
        )}

        {active.phase === "generate" && active.job && active.job.status === "running" && (
          <div className="progress-panel">
            {active.job.progress.length === 0 && <div className="progress-step">Starting…</div>}
            {active.job.progress.map((p, i) => (
              <div key={i} className="progress-step">
                {p.detail || p.step}
              </div>
            ))}
          </div>
        )}

        {active.job && active.job.status === "error" && (
          <div className="error-panel">Error: {active.job.error}</div>
        )}

        {active.result && (
          <div className="result-panel">
            <ResultPanel
              result={active.result}
              topic={active.topic}
              onPaperTextChange={(text) => updateChat(active.id, { result: { ...active.result!, paper_text: text } })}
            />

            <div className="refine-row">
              <input
                className="topic-input"
                placeholder="Refine the paper — e.g. 'add more on limitations'…"
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && applyRefine()}
                disabled={refining}
              />
              <button onClick={applyRefine} disabled={refining || !instruction.trim()}>
                {refining ? "Refining…" : "Apply"}
              </button>
            </div>
            {refineError && <div className="error-panel">Refine error: {refineError}</div>}
          </div>
        )}
      </main>
    </div>
  );
}
