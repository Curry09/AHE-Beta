// Spec-0032/T7: delivery panel: open PR list + needs-human backlog alert (vigil's work view, read-only observations).
// The developer column was removed with dev retirement: show delivery progress per PR (issue → PR → status), then move merged entries to Main.

import type { DeliveryResponse, Pull } from "../types";

const STATE_BADGE: Record<Pull["state"], string> = {
  open: "In progress",
  merged: "Merged",
  closed: "Closed",
};

export function DeliveryPanel({ delivery }: { delivery: DeliveryResponse | null }) {
  if (!delivery) return null;
  return (
    <>
      <div className="side-section-head">
        Delivery · PRs
        {/* needs-human is the unattended loop's only stalled-issue queue requiring human cleanup; highlight any nonzero count. */}
        {delivery.needs_human > 0 && (
          <span
            className="chip"
            style={{ color: "var(--red)", fontWeight: 600 }}
            title="Issues and PRs handed off for human action. Resolve them in Gitea and remove needs-human to resume."
          >
            needs-human {delivery.needs_human}
          </span>
        )}
      </div>
      {!delivery.connected && (
        <div className="disconnected">Gitea is disconnected; delivery PRs are unavailable.</div>
      )}
      {delivery.connected && delivery.pulls.length === 0 && (
        <div className="empty">No open PRs</div>
      )}
      {delivery.pulls.map((p) => (
        <a
          key={p.number}
          className="row"
          href={p.url || undefined}
          target="_blank"
          rel="noreferrer"
          title={`head: ${p.head_branch}`}
        >
          <span className="num">PR#{p.number}</span>
          <span className="row-title">{p.title}</span>
          <span className="chip" title={`Status: ${p.state}`}>
            {STATE_BADGE[p.state] ?? p.state}
          </span>
          {p.closes_issues.map((n) => (
            <span key={n} className="chip tag" title="Issues automatically closed on merge by closing keywords">
              →#{n}
            </span>
          ))}
          {p.mergeable === false && (
            <span className="chip" style={{ color: "var(--amber)" }} title="Merge conflict; awaiting a delivery-side rebase">
              Conflict
            </span>
          )}
          {p.labels.includes("needs-human") && (
            <span className="chip" style={{ color: "var(--red)" }} title="Handed off for human action">
              needs-human
            </span>
          )}
        </a>
      ))}
    </>
  );
}
