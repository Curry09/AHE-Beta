import { useState } from "react";
import type { LogEntry, Turn } from "../types";
import { fmtTime } from "../lib/format";

// Process stream: render status/assistant/tool/tool_result/tool_error by type,
// reconstructing the full workflow of assistant message → tool call → result.
export function ProcessStream({ log }: { log: LogEntry[] }) {
  if (log.length === 0) return <div className="empty">No process records yet</div>;
  return (
    <div className="stream">
      {log.map((e, i) => {
        const kind = ["status", "assistant", "tool", "tool_result", "tool_error"].includes(e.kind)
          ? e.kind
          : "tool";
        return (
          <div key={i} className={`ev ${kind}`}>
            {kind !== "assistant" && <span className="t">{fmtTime(e.t)}</span>}
            {e.text}
          </div>
        );
      })}
    </div>
  );
}

// Collapsed preview: use the first nonempty line, truncated to ~100 characters.
function previewLine(text: string): string {
  const line = text.split("\n").find((l) => l.trim()) ?? text;
  return line.length > 100 ? `${line.slice(0, 100)}…` : line;
}

// User session transcript: user messages are fully expanded; only the last harness reply is expanded by default,
// with earlier replies collapsed into clickable previews. overrides stores manual toggles; untouched items follow whether they are last.
// As new live replies stream in, expand the latest turn and collapse older ones unless the user has pinned them.
export function Turns({ turns }: { turns: Turn[] }) {
  const [overrides, setOverrides] = useState<Record<number, boolean>>({});
  if (turns.length === 0) return <div className="empty">No conversation yet</div>;

  let lastHarness = -1;
  turns.forEach((t, i) => {
    if (t.role === "harness") lastHarness = i;
  });
  const isOpen = (i: number) => overrides[i] ?? i === lastHarness;
  const toggle = (i: number) => setOverrides((prev) => ({ ...prev, [i]: !isOpen(i) }));

  return (
    <div className="turns">
      {turns.map((t, i) => {
        if (t.role === "user") {
          return (
            <div key={i} className="turn user">
              <div className="who">User</div>
              <div className="prose">{t.content}</div>
            </div>
          );
        }
        const open = isOpen(i);
        const steps = t.steps ?? [];
        return (
          <div key={i} className={`turn harness${open ? "" : " collapsed"}`}>
            <button className="who toggle" onClick={() => toggle(i)}>
              <span className="caret">{open ? "▾" : "▸"}</span>
              harness
              {steps.length > 0 && <span className="steps-count">{steps.length} steps</span>}
              {i === lastHarness && <span className="latest">Latest</span>}
            </button>
            {open ? (
              <>
                {steps.length > 0 && (
                  <details className="inner-steps">
                    <summary>Internal process ({steps.length} steps)</summary>
                    <ProcessStream log={steps} />
                  </details>
                )}
                <div className="prose">{t.content}</div>
              </>
            ) : (
              <button className="prose preview" onClick={() => toggle(i)}>
                {previewLine(t.content)}
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

// Commit diff: color lines (+ green / - red / @@ blue / file headers gray).
export function Diff({ diff }: { diff: string }) {
  if (!diff) return <div className="empty">No diff available</div>;
  const cls = (line: string) => {
    if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("diff ") || line.startsWith("index "))
      return "meta-line";
    if (line.startsWith("@@")) return "hunk";
    if (line.startsWith("+")) return "add";
    if (line.startsWith("-")) return "del";
    return "";
  };
  return (
    <div className="diff">
      {diff.split("\n").map((line, i) => (
        <div key={i} className={`line ${cls(line)}`}>
          {line || " "}
        </div>
      ))}
    </div>
  );
}
