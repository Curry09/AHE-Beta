import type { ReactElement } from "react";
import type {
  Agent,
  Commit,
  CommitsResponse,
  DeliveryResponse,
  HistoryItem,
  Issue,
  IssuesResponse,
  Selection,
} from "../types";
import { fmtDate } from "../lib/format";
import {
  ageDays,
  issueKind,
  planeOf,
  priorityOf,
  provenanceOf,
  roundOf,
  terminalOf,
} from "../lib/issueMeta";
import { AgentRunDetail } from "./detail/AgentRunDetail";
import { DeliveryPanel } from "./DeliveryPanel";
import { CommitDetailView } from "./detail/CommitDetail";
import { IssueDetailView } from "./detail/IssueDetail";
import { SessionDetailView } from "./detail/SessionDetail";

// Fourth column: with no selection, show Issues + Main lists; selecting a card shows its full details with back navigation.
export function SidePanel(props: {
  selection: Selection | null;
  onSelect: (sel: Selection | null) => void;
  agents: Agent[];
  history: HistoryItem[];
  issues: IssuesResponse | null;
  commits: CommitsResponse | null;
  funnel?: { report: number; proposal: number; ready: number } | null;
  delivery?: DeliveryResponse | null; // Spec-0032/T7: delivery view (PR + needs-human)
}) {
  const { selection, onSelect, agents, history, issues, commits, funnel, delivery } = props;
  const commitList: Commit[] = commits?.commits ?? [];
  const back = () => onSelect(null);

  let detail: ReactElement | null = null;
  if (selection?.type === "agent") {
    const a = agents.find((x) => x.agent_id === selection.agentId);
    detail = a ? (
      <AgentRunDetail
        role={a.role}
        label={a.label}
        running={a.running}
        status={a.status}
        round={a.round}
        turns={a.turns}
        log={a.log}
        detail={a.detail}
        commits={commitList}
        onSelect={onSelect}
        onBack={back}
      />
    ) : (
      <FallbackDetail onBack={back} text="This live agent slot no longer exists. A new run may have started." />
    );
  } else if (selection?.type === "history") {
    const item = history[selection.index];
    if (!item) {
      detail = <FallbackDetail onBack={back} text="Archived record not found. A new run may have cleared it." />;
    } else if (item.kind === "user_session") {
      detail = <SessionDetailView item={item} onSelect={onSelect} onBack={back} />;
    } else {
      detail = (
        <AgentRunDetail
          role={item.role}
          label={item.label}
          status={item.status}
          round={item.round}
          turns={item.turns}
          log={item.log}
          detail={item.detail}
          issueNumber={item.issue_number}
          tag={item.tag}
          committed={item.kind === "dev_run" ? item.committed : undefined}
          proposals={item.proposals}
          commits={commitList}
          onSelect={onSelect}
          onBack={back}
        />
      );
    }
  } else if (selection?.type === "issue") {
    detail = <IssueDetailView number={selection.number} onBack={back} />;
  } else if (selection?.type === "commit") {
    detail = <CommitDetailView sha={selection.sha} onBack={back} />;
  }

  return (
    <section className="column">
      {detail ?? (
        <>
          <div className="column-head">
            Issues · Main
            <span className="count">
              {issues ? issues.issues.filter((i) => i.state === "open").length : "—"} open
            </span>
          </div>
          <div className="column-body">
            <div className="side-section-head">
              Issues
              {issues?.board_url && (
                <a href={issues.board_url} target="_blank" rel="noreferrer">
                  Gitea ↗
                </a>
              )}
            </div>
            {issues && !issues.connected && (
              <div className="disconnected">Gitea is disconnected; issues are unavailable.</div>
            )}
            {issues?.connected && issues.issues.length === 0 && (
              <div className="empty">No issues yet</div>
            )}
            {/* Spec-0029/T10: three-plane funnel bar (current report→proposal→ready counts; highlight soft-threshold warnings). */}
            {funnel && <FunnelBar funnel={funnel} />}
            {/* Spec-0029/T10: group by plane: reports / proposals (with provenance badges) / Ready / closed terminal states. */}
            <IssueGroups issues={issues?.issues ?? []} onSelect={onSelect} />

            {/* Spec-0032/T7: delivery view: open PR + needs-human backlog (vigil's work view). */}
            <DeliveryPanel delivery={delivery ?? null} />

            <div className="side-section-head">
              Main
              {commits?.commits_url && (
                <a href={commits.commits_url} target="_blank" rel="noreferrer">
                  Gitea ↗
                </a>
              )}
            </div>
            {commits && !commits.connected && (
              <div className="disconnected">Gitea is disconnected; commits are unavailable.</div>
            )}
            {commits?.connected && commitList.length === 0 && (
              <div className="empty">No commits yet</div>
            )}
            {commitList.map((c) => (
              <button
                key={c.sha}
                className="row"
                onClick={() => onSelect({ type: "commit", sha: c.sha })}
                title={fmtDate(c.date)}
              >
                <span className="num">{c.short_sha}</span>
                <span className="row-title">{c.message}</span>
                {c.tags.map((t) => (
                  <span key={t} className="chip tag">
                    {t}
                  </span>
                ))}
              </button>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

// Priority badge colors (inline to avoid editing styles.css, outside this task's file allocation): P0 red, P1 amber, others muted.
const PRIORITY_COLOR: Record<string, string> = {
  P0: "var(--red)",
  P1: "var(--amber)",
  P2: "var(--text-dim)",
  P3: "var(--text-faint)",
};

// Backpressure soft thresholds (match backend run.py defaults; frontend highlights only; authoritative alerts appear in backend stdout/state).
const DEPTH_SOFT_ALARM = 20;

function FunnelBar({ funnel }: { funnel: { report: number; proposal: number; ready: number } }) {
  const seg = (label: string, n: number, warn: boolean) => (
    <span
      className="chip"
      style={warn ? { color: "var(--red)", fontWeight: 600 } : undefined}
      title={warn ? `${label} count ${n} exceeds the soft limit ${DEPTH_SOFT_ALARM} (backpressure warning)` : `Current ${label} count`}
    >
      {label} {n}
    </span>
  );
  return (
    <div className="side-section-head" title="Three-plane funnel: Report → Proposal → Ready">
      {seg("Report", funnel.report, false)}
      <span style={{ color: "var(--text-faint)" }}>→</span>
      {seg("Proposal", funnel.proposal, funnel.proposal > DEPTH_SOFT_ALARM)}
      <span style={{ color: "var(--text-faint)" }}>→</span>
      {seg("Ready", funnel.ready, funnel.ready > DEPTH_SOFT_ALARM)}
    </div>
  );
}

// Divide issues into four groups (three planes + closed terminal states). Sort each group by issue number ascending.
function groupIssues(issues: Issue[]) {
  const report: Issue[] = [];
  const proposal: Issue[] = [];
  const ready: Issue[] = [];
  const closed: Issue[] = [];
  for (const it of issues) {
    const p = it.state === "open" ? planeOf(it) : null;
    if (p === "report") report.push(it);
    else if (p === "proposal") proposal.push(it);
    else if (p === "ready") ready.push(it);
    else closed.push(it);  // Closed (done/merged/declined or other terminal states) or no plane.
  }
  const byNum = (a: Issue, b: Issue) => a.number - b.number;
  return {
    report: report.sort(byNum),
    proposal: proposal.sort(byNum),
    ready: ready.sort(byNum),
    closed: closed.sort(byNum),
  };
}

function IssueGroups(props: { issues: Issue[]; onSelect: (sel: Selection) => void }) {
  const g = groupIssues(props.issues);
  const { onSelect } = props;
  return (
    <>
      <IssueGroup title="Ready · Available to claim" issues={g.ready} onSelect={onSelect} highlight />
      <IssueGroup title="Proposal · Awaiting admission" issues={g.proposal} onSelect={onSelect} />
      <IssueGroup title="Report · Awaiting triage" issues={g.report} onSelect={onSelect} />
      <IssueGroup title="Closed" issues={g.closed} onSelect={onSelect} dim />
    </>
  );
}

function IssueGroup(props: {
  title: string;
  issues: Issue[];
  onSelect: (sel: Selection) => void;
  highlight?: boolean;
  dim?: boolean;
}) {
  const { title, issues, onSelect, highlight, dim } = props;
  if (issues.length === 0) return null;
  return (
    <>
      <div
        className="side-section-head"
        style={highlight ? { color: "var(--amber)" } : dim ? { color: "var(--text-faint)" } : undefined}
      >
        {title}
        <span className="count">{issues.length}</span>
      </div>
      {issues.map((issue) => (
        <IssueRow key={issue.number} issue={issue} onSelect={onSelect} />
      ))}
    </>
  );
}

// Proposal provenance badge text (provenance → short name).
const PROVENANCE_BADGE: Record<string, string> = {
  "from-triage": "Triage",
  "from-architect": "Architect",
  "from-divergent": "Divergent PM",
};

function IssueRow(props: { issue: Issue; onSelect: (sel: Selection) => void }) {
  const { issue, onSelect } = props;
  const kind = issueKind(issue);
  const prio = priorityOf(issue);
  const round = roundOf(issue);
  const prov = provenanceOf(issue);
  const terminal = terminalOf(issue);
  const age =
    planeOf(issue) === "ready" && issue.state === "open" ? ageDays(issue.created_at) : null;
  return (
    <button
      className={`row ${issue.state}`}
      onClick={() => onSelect({ type: "issue", number: issue.number })}
    >
      <span className="num">#{issue.number}</span>
      <span className="row-title">{issue.title}</span>
      <span className="chip" title={`kind: ${kind}`}>
        {kind}
      </span>
      {prov && (
        <span className="chip tag" title={`Proposal source: ${prov}`}>
          {PROVENANCE_BADGE[prov] ?? prov}
        </span>
      )}
      {prio && (
        <span className="chip" style={{ color: PRIORITY_COLOR[prio] }} title={`Priority ${prio}`}>
          {prio}
        </span>
      )}
      {round != null && (
        <span className="chip" title={`Proposed in round ${round}`}>
          r{round}
        </span>
      )}
      {age != null && age > 0 && (
        <span className="chip" title={`Queued for ${age} days (backlog age)`}>
          {age}d
        </span>
      )}
      {/* Show coverage suggestions for structural proposals, ⊂ #N for covered issues, and labels for merged/declined terminal states. */}
      {(issue.covers?.length ?? 0) > 0 && (
        <span className="chip tag" title="Issues this proposal recommends covering; admission determines merges">
          Cover {issue.covers!.map((n) => `#${n}`).join(" ")}
        </span>
      )}
      {issue.covered_by != null && (
        <span className="chip" title={`Referenced by covers in #${issue.covered_by}`}>
          ⊂ #{issue.covered_by}
        </span>
      )}
      {(terminal === "merged" || terminal === "superseded" || terminal === "gate-dropped") && (
        <span className="chip" title="Merged into or superseded by the parent issue">
          Merge
        </span>
      )}
      {issue.reject_reason && (
        <span className="chip" title={issue.reject_reason}>
          Reject
        </span>
      )}
    </button>
  );
}

function FallbackDetail({ onBack, text }: { onBack: () => void; text: string }) {
  return (
    <div className="detail">
      <div className="detail-head">
        <button className="back" onClick={onBack}>
          ‹ Back
        </button>
        <span className="detail-title">Not found</span>
      </div>
      <div className="detail-body">
        <div className="empty">{text}</div>
      </div>
    </div>
  );
}
