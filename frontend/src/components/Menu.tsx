import { useEffect, useRef, useState, type ReactNode } from "react";

/**
 * A top-bar dropdown: a trigger button plus a panel anchored under it.
 *
 * Closes on outside click, on Escape, and whenever the caller signals that the
 * action inside it is finished (`closeSignal`).
 */
export default function Menu({
  label,
  count,
  align = "left",
  children,
  disabled,
}: {
  label: string;
  count?: number;
  align?: "left" | "right";
  children: (close: () => void) => ReactNode;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;

    const onPointerDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };

    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div className="menu-wrap" ref={wrapRef}>
      <button
        className={`nav-item ${open ? "is-open" : ""}`}
        onClick={() => setOpen((o) => !o)}
        disabled={disabled}
        aria-expanded={open}
        aria-haspopup="menu"
      >
        {label}
        {count !== undefined && count > 0 && <span className="nav-count">{count}</span>}
        <span className="nav-caret" aria-hidden="true">
          ▾
        </span>
      </button>

      {open && (
        <div className={`menu-panel ${align === "right" ? "align-right" : ""}`} role="menu">
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}
