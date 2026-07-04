import { useEffect, useRef, useState } from "react";
import { useLogStore } from "../store/log";
import type { LogEntry, LogKind } from "../store/log";
import "./ActivityLog.css";

const KIND_ICON: Record<LogKind, string> = {
  info:     "·",
  success:  "✓",
  warn:     "⚠",
  progress: "↻",
  debug:    "»",
};

export type Level = "none" | "errors" | "scan" | "all" | "debug";

const LEVELS: { value: Level; label: string; title: string }[] = [
  { value: "none",   label: "Off",    title: "Hide activity log" },
  { value: "errors", label: "Errors", title: "Warnings and errors only" },
  { value: "scan",   label: "Scan",   title: "Scan progress, completions, and warnings" },
  { value: "all",    label: "All",    title: "All events" },
  { value: "debug",  label: "Debug",  title: "All events including per-file scan detail" },
];

function visible(entry: LogEntry, level: Level): boolean {
  if (level === "none")   return false;
  if (level === "debug")  return true;
  if (level === "all")    return entry.kind !== "debug";
  if (level === "scan")   return entry.kind === "progress" || entry.kind === "success" || entry.kind === "warn";
  /* errors */            return entry.kind === "warn";
}

function fmt(ts: number): string {
  const d = new Date(ts);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}

function Row({ entry }: { entry: LogEntry }) {
  return (
    <div className={`activity-log__row activity-log__row--${entry.kind}`}>
      <span className="activity-log__icon">{KIND_ICON[entry.kind]}</span>
      <span className="activity-log__time">{fmt(entry.ts)}</span>
      <span className="activity-log__msg">{entry.message}</span>
    </div>
  );
}

// Persist level across renders (not across sessions — localStorage would work
// but session memory is enough for this preference).
let _savedLevel: Level = "all";

export function ActivityLog() {
  const entries = useLogStore((s) => s.entries);
  const clear   = useLogStore((s) => s.clear);
  const [open,  setOpen]  = useState(false);
  const [level, setLevel] = useState<Level>(_savedLevel);

  const bottomRef      = useRef<HTMLDivElement>(null);
  const listRef        = useRef<HTMLDivElement>(null);
  const wasAtBottom    = useRef(true);

  function handleScroll() {
    const el = listRef.current;
    if (!el) return;
    wasAtBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 20;
  }

  function changeLevel(l: Level) {
    _savedLevel = l;
    setLevel(l);
    if (l === "none") setOpen(false);
  }

  const filtered = entries.filter((e) => visible(e, level));

  useEffect(() => {
    if (open && wasAtBottom.current) {
      bottomRef.current?.scrollIntoView({ block: "end" });
    }
  }, [filtered, open]);

  const last = entries[entries.length - 1];
  const showBar = level !== "none";

  if (!showBar) {
    // Render a minimal strip that still lets the user re-enable.
    return (
      <div className="activity-log activity-log--hidden">
        <div className="activity-log__bar">
          <span className="activity-log__bar-label">Activity</span>
          <div className="activity-log__levels" onClick={(e) => e.stopPropagation()}>
            {LEVELS.map((l) => (
              <button
                key={l.value}
                type="button"
                className={`activity-log__level-btn${level === l.value ? " activity-log__level-btn--active" : ""}`}
                onClick={() => changeLevel(l.value)}
                title={l.title}
              >
                {l.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`activity-log${open ? " activity-log--open" : ""}`}>
      <div className="activity-log__bar" onClick={() => setOpen((o) => !o)}>
        <span className="activity-log__chevron">{open ? "▾" : "▴"}</span>
        <span className="activity-log__bar-label">Activity</span>

        <div className="activity-log__levels" onClick={(e) => e.stopPropagation()}>
          {LEVELS.map((l) => (
            <button
              key={l.value}
              type="button"
              className={`activity-log__level-btn${level === l.value ? " activity-log__level-btn--active" : ""}`}
              onClick={() => changeLevel(l.value)}
              title={l.title}
            >
              {l.label}
            </button>
          ))}
        </div>

        {!open && last && visible(last, level) && (
          <span className={`activity-log__bar-last activity-log__bar-last--${last.kind}`}>
            <span>{KIND_ICON[last.kind]}</span>
            <span>{last.message}</span>
          </span>
        )}

        {entries.length > 0 && (
          <button
            type="button"
            className="activity-log__clear"
            onClick={(e) => { e.stopPropagation(); clear(); }}
            title="Clear log"
          >
            Clear
          </button>
        )}
      </div>

      {open && (
        <div className="activity-log__list" ref={listRef} onScroll={handleScroll}>
          {filtered.length === 0 ? (
            <div className="activity-log__empty">
              {entries.length === 0
                ? "No activity yet."
                : "No entries match the current filter."}
            </div>
          ) : (
            filtered.map((e) => <Row key={e.id} entry={e} />)
          )}
          <div ref={bottomRef} />
        </div>
      )}
    </div>
  );
}
