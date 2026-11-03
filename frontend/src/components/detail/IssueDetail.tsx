import { getIssue } from "../../api";
import { useFetch } from "../../hooks/useFetch";
import { fmtDate } from "../../lib/format";
import {
  issueKind,
  planeOf,
  priorityOf,
  provenanceOf,
  roundOf,
  terminalOf,
  triageStatus,
} from "../../lib/issueMeta";
import type { IssueComment } from "../../types";
import { Markdown } from "../Markdown";
import { buildIssueTimelineView } from "./issueTimelineModel";

// Triage status → Chinese display label.
const STATUS_LABEL: Record<string, string> = {
  "needs-triage": "Pending triage",
  triaged: "Triaged (actionable)",
  rejected: "Rejected",
  "needs-info": "Insufficient information",
  superseded: "Superseded by RFC",
};

// Spec-0020/T5: derive detail-page coverage directly from existing data (no new endpoints).
// Parse covers from machine-readable body lines (produced by T1; last line wins); parse covered_by from T1's covered-by comments.
function parseCovers(body: string): number[] {
  const lines = [...(body ?? "").matchAll(/^covers:((?:\s*#\d+)+)\s*$/gm)];
  if (lines.length === 0) return [];
  const last = lines[lines.length - 1][1];
  return [...last.matchAll(/#(\d+)/g)].map((m) => Number(m[1]));
}

function coveredByFrom(comments: IssueComment[]): number | null {
  for (let i = comments.length - 1; i >= 0; i--) {
    const m = /^covered-by:\s*#(\d+)\s*$/.exec((comments[i].body ?? "").trim());
    if (m) return Number(m[1]);
  }
  return null;
}

// Full issue: title/labels/state/body + comment timeline (including progress notes left by dev on close).
export function IssueDetailView(props: { number: number; onBack: () => void }) {
  const { number, onBack } = props;
  const data = useFetch(() => getIssue(number), [number]);
  const issue = data?.issue ?? null;
  const covers = issue ? parseCovers(issue.body) : [];
  const coveredBy = coveredByFrom(data?.comments ?? []);
  // The detail endpoint omits platform-derived fields (provided by the /api/issues list); infer them from labels on the client here.
  const kind = issue ? issueKind(issue) : "";
  const status = issue ? triageStatus(issue) : null;
  const prio = issue ? priorityOf(issue) : null;
  const round = issue ? roundOf(issue) : null;
  // Spec-0029/T10: three planes / provenance / terminal states.
  const pl = issue ? planeOf(issue) : null;
  const prov = issue ? provenanceOf(issue) : null;
  const terminal = issue ? terminalOf(issue) : null;
  const timelineView = issue ? buildIssueTimelineView(issue, data?.timeline) : null;
  const delivery = issue?.labels.includes("needs-human")
    ? "Blocked · needs-human"
    : issue?.labels.includes("ready")
      ? "In progress · ready"
      : issue?.labels.includes("openagents")
        ? "Pending intake · openagents"
        : "—";
  const planeLabel: Record<string, string> = {
    report: "Report (awaiting triage)",
    proposal: "Proposal (awaiting admission)",
    ready: "Ready (claimable)",
  };

  return (
    <div className="detail">
      <div className="detail-head">
        <button className="back" onClick={onBack}>
          ‹ Back
        </button>
        <span className="detail-title">
          #{number} {issue?.title ?? ""}
        </span>
        {issue && <span className={`chip ${issue.state}`}>{issue.state}</span>}
      </div>
      <div className="detail-body">
        {!data && <div className="empty">Loading…</div>}
        {data && !data.connected && (
          <div className="disconnected">Gitea is disconnected; issue details are unavailable.</div>
        )}
        {data && issue && (
          <>
            <div className="issue-dimensions" aria-label="Current issue status dimensions">
              <div className="issue-dimension">
                <span>Plane</span>
                <strong>{pl ? (planeLabel[pl] ?? pl) : terminal ? `Terminal state · ${terminal}` : "—"}</strong>
              </div>
              <div className="issue-dimension">
                <span>Source</span>
                <strong>{prov ?? "—"}</strong>
              </div>
              <div className="issue-dimension">
                <span>Priority</span>
                <strong>{prio ?? "—"}</strong>
              </div>
              <div className="issue-dimension">
                <span>Generation round</span>
                <strong>{round == null ? "—" : `round-${round}`}</strong>
              </div>
              <div className="issue-dimension">
                <span>delivery</span>
                <strong>{delivery}</strong>
              </div>
              <div className="issue-dimension">
                <span>Type / Triage</span>
                <strong>{status ? `${kind} · ${STATUS_LABEL[status] ?? status}` : kind}</strong>
              </div>
            </div>

            {timelineView && timelineView.anomalies.length > 0 && (
              <div className="timeline-alerts" role="alert">
                <div className="block-title">Status integrity warning · {timelineView.anomalies.length}</div>
                {timelineView.anomalies.map((anomaly) => (
                  <div key={anomaly.id} className={`timeline-alert ${anomaly.severity}`}>
                    <strong>{anomaly.code}</strong>
                    <span>{anomaly.message}</span>
                  </div>
                ))}
                {Object.values(timelineView.lastKnown).some((value) => value != null) && (
                  <div className="timeline-compare">
                    <span>
                      Last known historical status: {timelineView.lastKnown.plane ?? "—"} ·{" "}
                      {timelineView.lastKnown.provenance ?? "—"} ·{" "}
                      {timelineView.lastKnown.priority ?? "—"} ·{" "}
                      {timelineView.lastKnown.round == null
                        ? "—"
                        : `round-${timelineView.lastKnown.round}`}
                    </span>
                    <span>
                      Current Gitea: {pl ?? terminal ?? "No plane"} · {prov ?? "No source"} ·{" "}
                      {prio ?? "No priority"} · {round == null ? "No round" : `round-${round}`}
                    </span>
                  </div>
                )}
              </div>
            )}

            <div className="block issue-timeline-block">
              <div className="block-title">
                Status evolution
                {timelineView?.available && !timelineView.complete && (
                  <span className="timeline-confidence">History incomplete</span>
                )}
              </div>
              {!timelineView?.available && (
                <div className="timeline-unavailable">
                  Label timeline unavailable: {timelineView?.unavailableReason ?? "Unknown reason"}
                </div>
              )}
              {timelineView?.available && timelineView.transitions.length === 0 && (
                <div className="empty">No label transitions observed yet</div>
              )}
              {timelineView?.available && timelineView.transitions.length > 0 && (
                <div className="issue-timeline">
                  {timelineView.transitions.map((transition) => {
                    const raw = data.timeline?.transitions.find((item) => item.id === transition.id);
                    return (
                      <div key={transition.id} className={`timeline-step ${transition.severity}`}>
                        <div className="timeline-marker" />
                        <div className="timeline-step-body">
                          <div className="timeline-step-head">
                            <strong>{transition.title}</strong>
                            <span>{fmtDate(transition.createdAt)}</span>
                            <span>{transition.actor || "Unknown operator"}</span>
                          </div>
                          <div className="timeline-state-change">
                            <span>{transition.from}</span>
                            <b>→</b>
                            <span>{transition.to}</span>
                          </div>
                          <div className="timeline-label-change">
                            {transition.added.map((label) => (
                              <code key={`add-${label}`} className="label-add">
                                +{label}
                              </code>
                            ))}
                            {transition.removed.map((label) => (
                              <code key={`remove-${label}`} className="label-remove">
                                -{label}
                              </code>
                            ))}
                          </div>
                          {raw && (
                            <details className="timeline-debug">
                              <summary>State snapshot</summary>
                              <pre>{JSON.stringify({ before: raw.before, after: raw.after }, null, 2)}</pre>
                            </details>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            <dl className="kv issue-secondary-meta">
              {coveredBy != null && (
                <>
                  <dt>Covered by</dt>
                  <dd>
                    <span className="chip" title={`Covered by architecture proposal #${coveredBy}`}>
                      ⊂ #{coveredBy}
                    </span>
                  </dd>
                </>
              )}
              {covers.length > 0 && (
                <>
                  <dt>Covers</dt>
                  <dd>
                    {covers.map((n) => (
                      <span key={n} className="chip" style={{ marginRight: 4 }}>
                        #{n}
                      </span>
                    ))}
                  </dd>
                </>
              )}
              <dt>Created</dt>
              <dd>{fmtDate(issue.created_at)}</dd>
              {issue.closed_at && (
                <>
                  <dt>Closed</dt>
                  <dd>{fmtDate(issue.closed_at)}</dd>
                </>
              )}
              {issue.url && (
                <>
                  <dt>Gitea</dt>
                  <dd>
                    <a className="link" href={issue.url} target="_blank" rel="noreferrer">
                      Open ↗
                    </a>
                  </dd>
                </>
              )}
            </dl>
            <div className="block">
              <div className="block-title">Body text</div>
              {issue.body ? <Markdown>{issue.body}</Markdown> : <div className="prose">(No body)</div>}
            </div>
            <div className="block">
              <div className="block-title">Comments · {data.comments.length}</div>
              {data.comments.length === 0 && <div className="empty">No comments yet</div>}
              <div className="turns">
                {data.comments.map((c, i) => (
                  <div key={i} className="comment">
                    <div className="who">
                      {c.author}
                      <span className="when">{fmtDate(c.created_at)}</span>
                    </div>
                    <Markdown dim>{c.body}</Markdown>
                  </div>
                ))}
              </div>
            </div>
            <details className="block issue-debug">
              <summary>Debug · Raw labels and events</summary>
              <div className="debug-label-groups">
                {(timelineView?.groups ?? []).map((group) => (
                  <div key={group.key}>
                    <span>{group.label}</span>
                    <div>
                      {group.labels.map((label) => (
                        <code key={label}>{label}</code>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              {(data.timeline?.events.length ?? 0) > 0 && (
                <div className="raw-events">
                  {data.timeline?.events.map((event, index) => (
                    <div key={`${event.id ?? "event"}-${index}`}>
                      <span>{fmtDate(event.created_at)}</span>
                      <span>{event.actor || "—"}</span>
                      <code>
                        {event.operation === "unknown"
                          ? event.type
                          : `${event.operation === "add" ? "+" : "-"}${event.label}`}
                      </code>
                    </div>
                  ))}
                </div>
              )}
            </details>
          </>
        )}
      </div>
    </div>
  );
}
