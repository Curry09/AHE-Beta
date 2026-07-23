import type { ReactElement } from "react";
import type {
  Agent,
  Commit,
  CommitsResponse,
  HistoryItem,
  Issue,
  IssuesResponse,
  Selection,
} from "../types";
import { fmtDate } from "../lib/format";
import {
  ageDays,
  isRfc,
  issueKind,
  priorityOf,
  roundOf,
  triageStatus,
} from "../lib/issueMeta";
import { AgentRunDetail } from "./detail/AgentRunDetail";
import { CommitDetailView } from "./detail/CommitDetail";
import { IssueDetailView } from "./detail/IssueDetail";
import { SessionDetailView } from "./detail/SessionDetail";

// 第四栏：无选中时 = Issues + Main 两段列表；点了任意方块 = 该对象的完整信息（可返回）。
export function SidePanel(props: {
  selection: Selection | null;
  onSelect: (sel: Selection | null) => void;
  agents: Agent[];
  history: HistoryItem[];
  issues: IssuesResponse | null;
  commits: CommitsResponse | null;
}) {
  const { selection, onSelect, agents, history, issues, commits } = props;
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
      <FallbackDetail onBack={back} text="该 agent 的实时槽位已不存在（可能已开新一轮 run）。" />
    );
  } else if (selection?.type === "history") {
    const item = history[selection.index];
    if (!item) {
      detail = <FallbackDetail onBack={back} text="归档记录不存在（可能已被新一轮 run 清空）。" />;
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
              <div className="disconnected">未连接 Gitea（issue 列表不可用）。</div>
            )}
            {issues?.connected && issues.issues.length === 0 && (
              <div className="empty">暂无 issue</div>
            )}
            {/* Spec-0025/T8：按 triage 状态 / type 分组——RFC 区突出、可执行 backlog、待 triage、
                其它、已驳回/取代。各组仅在非空时出现。 */}
            <IssueGroups issues={issues?.issues ?? []} onSelect={onSelect} />

            <div className="side-section-head">
              Main
              {commits?.commits_url && (
                <a href={commits.commits_url} target="_blank" rel="noreferrer">
                  Gitea ↗
                </a>
              )}
            </div>
            {commits && !commits.connected && (
              <div className="disconnected">未连接 Gitea（commit 列表不可用）。</div>
            )}
            {commits?.connected && commitList.length === 0 && (
              <div className="empty">暂无 commit</div>
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

// 优先级徽标配色（内联，避免改 styles.css——非本 task 分配文件）。P0 红、P1 琥珀、其余淡。
const PRIORITY_COLOR: Record<string, string> = {
  P0: "var(--red)",
  P1: "var(--amber)",
  P2: "var(--text-dim)",
  P3: "var(--text-faint)",
};

// 把 issue 分到五组：RFC / 可执行 backlog / 待 triage / 其它 / 已驳回·取代。组内按票号升序。
function groupIssues(issues: Issue[]) {
  const rfc: Issue[] = [];
  const backlog: Issue[] = [];
  const untriaged: Issue[] = [];
  const rejected: Issue[] = [];
  const other: Issue[] = [];
  for (const it of issues) {
    const st = triageStatus(it);
    if (isRfc(it)) rfc.push(it);
    else if (st === "rejected" || st === "needs-info" || st === "superseded") rejected.push(it);
    else if (st === "triaged") backlog.push(it);
    else if (st === "needs-triage") untriaged.push(it);
    else other.push(it);
  }
  const byNum = (a: Issue, b: Issue) => a.number - b.number;
  return {
    rfc: rfc.sort(byNum),
    backlog: backlog.sort(byNum),
    untriaged: untriaged.sort(byNum),
    other: other.sort(byNum),
    rejected: rejected.sort(byNum),
  };
}

function IssueGroups(props: { issues: Issue[]; onSelect: (sel: Selection) => void }) {
  const g = groupIssues(props.issues);
  const { onSelect } = props;
  return (
    <>
      <IssueGroup title="RFC · 结构提案" issues={g.rfc} onSelect={onSelect} highlight />
      <IssueGroup title="Backlog · 可执行" issues={g.backlog} onSelect={onSelect} />
      <IssueGroup title="待 triage" issues={g.untriaged} onSelect={onSelect} />
      <IssueGroup title="其它" issues={g.other} onSelect={onSelect} />
      <IssueGroup title="已驳回 · 取代" issues={g.rejected} onSelect={onSelect} dim />
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

function IssueRow(props: { issue: Issue; onSelect: (sel: Selection) => void }) {
  const { issue, onSelect } = props;
  const kind = issueKind(issue);
  const prio = priorityOf(issue);
  const round = roundOf(issue);
  const st = triageStatus(issue);
  const age = st === "triaged" && issue.state === "open" ? ageDays(issue.created_at) : null;
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
      {prio && (
        <span className="chip" style={{ color: PRIORITY_COLOR[prio] }} title={`优先级 ${prio}`}>
          {prio}
        </span>
      )}
      {round != null && (
        <span className="chip" title={`第 ${round} 轮提出`}>
          r{round}
        </span>
      )}
      {age != null && age > 0 && (
        <span className="chip" title={`已挂 ${age} 天（积压龄）`}>
          {age}d
        </span>
      )}
      {/* RFC 显覆盖清单；被 RFC 覆盖显 ⊂ #N；被取代/驳回给标注 */}
      {(issue.covers?.length ?? 0) > 0 && (
        <span className="chip tag" title="该 RFC 综合/取代的 issue">
          覆盖 {issue.covers!.map((n) => `#${n}`).join(" ")}
        </span>
      )}
      {issue.covered_by != null && (
        <span className="chip" title={`已被 RFC #${issue.covered_by} 覆盖`}>
          ⊂ #{issue.covered_by}
        </span>
      )}
      {st === "superseded" && (
        <span className="chip" title="被 RFC 取代">
          取代
        </span>
      )}
      {issue.reject_reason && (
        <span className="chip" title={issue.reject_reason}>
          驳回
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
          ‹ 返回
        </button>
        <span className="detail-title">未找到</span>
      </div>
      <div className="detail-body">
        <div className="empty">{text}</div>
      </div>
    </div>
  );
}
