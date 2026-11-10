import { useEffect, useState } from "react";
import type { JobProgressStep } from "../api";

function useElapsed(active: boolean): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!active) return;
    const started = Date.now();
    setSeconds(0);
    const handle = window.setInterval(
      () => setSeconds(Math.floor((Date.now() - started) / 1000)),
      1000
    );
    return () => window.clearInterval(handle);
  }, [active]);
  return seconds;
}

function format(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
}

/**
 * The live job log, rendered as a timeline.
 *
 * `title` is the phase (shown once, at the top); `steps` are the progress
 * events the backend has reported so far, newest last and highlighted.
 */
export default function ProgressPanel({
  title,
  steps,
  hint,
  fallback = "Starting…",
}: {
  title: string;
  steps: JobProgressStep[];
  hint?: string;
  fallback?: string;
}) {
  const elapsed = useElapsed(true);

  return (
    <div className="progress-panel">
      <div className="progress-head">
        {title}
        <span className="progress-elapsed">{format(elapsed)}</span>
      </div>

      {steps.length === 0 && <div className="progress-step">{fallback}</div>}
      {steps.map((p, i) => (
        <div key={i} className="progress-step">
          {p.detail || p.step}
        </div>
      ))}

      {hint && <div className="progress-hint">{hint}</div>}
    </div>
  );
}
