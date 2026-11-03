import type { ReactNode } from "react";
import type { AgentRole, Commit, LogEntry, Selection, Turn } from "../../types";
import { ProcessStream, Turns } from "../Stream";

// A dev/architect work segment (live slot or archived snapshot), plus the intermediate session state of a live user agent:
// metadata + full conversation/process stream + final report, with cross-navigation for issues/tags.
export function AgentRunDetail(props: {
  role: AgentRole;
  label: string;
  running?: boolean;
  status: string;
  round: number | null;
  turns: Turn[];
  log: LogEntry[];
  detail: string | null;
  issueNumber?: number | null;
  tag?: string | null;
  committed?: boolean;
  proposals?: number[];
  score?: number | null;
  endReason?: string;
  commits: Commit[];
  onSelect: (sel: Selection) => void;
  onBack: () => void;
}) {
  const {
    role,
    label,
    running,
    status,
    round,
    turns,
    log,
    detail,
    issueNumber,
    tag,
    committed,
    proposals,
    score,
    endReason,
    commits,
    onSelect,
    onBack,
  } = props;

  const tagCommit = tag ? commits.find((c) => c.tags.includes(tag)) : undefined;

  const rows: [string, ReactNode][] = [];
  if (round != null && round > 0) rows.push(["Round", `Round ${round}`]);
  rows.push(["Status", status]);
  if (score != null) rows.push(["Experience", <span className={`score s${score}`}>{score} / 4</span>]);
  if (endReason) rows.push(["End reason", endReason]);
  if (issueNumber != null)
    rows.push([
      "issue",
      <button className="link" onClick={() => onSelect({ type: "issue", number: issueNumber })}>
        #{issueNumber}
      </button>,
    ]);
  if (tag)
    rows.push([
      "tag",
      tagCommit ? (
        <button className="link" onClick={() => onSelect({ type: "commit", sha: tagCommit.sha })}>
          {tag} · {tagCommit.short_sha}
        </button>
      ) : (
        <span className="chip tag">{tag}</span>
      ),
    ]);
  if (committed !== undefined) rows.push(["main", committed ? "Main updated" : "Main unchanged"]);
  if (proposals && proposals.length > 0)
    rows.push([
      "Proposal",
      <span>
        {proposals.map((n) => (
          <button key={n} className="link" onClick={() => onSelect({ type: "issue", number: n })}>
            #{n}
          </button>
        ))}
      </span>,
    ]);

  return (
    <div className="detail">
      <div className="detail-head">
        <button className="back" onClick={onBack}>
          ‹ Back
        </button>
        {running ? <span className="dot on" /> : <span className={`role-dot ${role}`} />}
        <span className="detail-title">{label}</span>
      </div>
      <div className="detail-body">
        <dl className="kv">
          {rows.map(([k, v], i) => (
            <div key={i} style={{ display: "contents" }}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
        {turns.length > 0 && (
          <div className="block">
            <div className="block-title">Conversation</div>
            <Turns turns={turns} />
          </div>
        )}
        {role !== "user" && (
          <div className="block">
            <div className="block-title">Work process</div>
            <ProcessStream log={log} />
          </div>
        )}
        {detail && (
          <div className="block">
            <div className="block-title">Final report</div>
            <div className="prose">{detail}</div>
          </div>
        )}
      </div>
    </div>
  );
}
