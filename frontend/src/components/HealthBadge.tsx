import { useEffect, useState } from "react";
import { getHealth, type HealthResponse } from "../api";

const REFRESH_MS = 30_000;

/**
 * Live status of the backend and its LLM provider.
 *
 * Generating a paper takes minutes, so a stopped Ollama daemon or a model that
 * was never pulled should be visible before the user starts — not after.
 */
export default function HealthBadge() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const check = () =>
      getHealth()
        .then((h) => {
          if (cancelled) return;
          setHealth(h);
          setFailed(false);
        })
        .catch(() => {
          if (cancelled) return;
          setHealth(null);
          setFailed(true);
        });

    check();
    const handle = window.setInterval(check, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
  }, []);

  if (!health && !failed) {
    return (
      <div className="health-badge health-loading" title="Checking the backend…">
        <span className="health-dot" />
        <span className="health-text">
          <span className="health-provider">Checking backend…</span>
        </span>
      </div>
    );
  }

  if (failed || !health) {
    return (
      <div
        className="health-badge health-bad"
        title="The API did not respond. Start it with: python -m uvicorn api.main:app --port 8001"
      >
        <span className="health-dot" />
        <span className="health-text">
          <span className="health-model">API offline</span>
          <span className="health-provider">Backend not reachable</span>
        </span>
      </div>
    );
  }

  const { llm } = health;
  return (
    <div
      className={`health-badge ${llm.ready ? "health-ok" : "health-bad"}`}
      title={llm.detail}
    >
      <span className="health-dot" />
      <span className="health-text">
        <span className="health-model">{llm.model}</span>
        <span className="health-provider">
          {llm.ready ? `via ${llm.provider}` : "not ready — hover for details"}
        </span>
      </span>
    </div>
  );
}
