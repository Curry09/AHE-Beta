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

// 第四栏：无选中时 = Issues + Main 两段列表；点了任意方块 = 该对象的完整信息（可返回）。
export function SidePanel(props: {
  selection: Selection | null;
  onSelect: (sel: Selection | null) => void;
  agents: Agent[];
  history: HistoryItem[];
  issues: IssuesResponse | null;
  commits: CommitsResponse | null;
  funnel?: { report: number; proposal: number; ready: number } | null;
  delivery?: DeliveryResponse | null; // Spec-0032/T7：交付面（PR + needs-human）
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
            {/* Spec-0029/T10：三平面漏斗条（report→proposal→ready 当前量；超软阈值高亮示警）。 */}
            {funnel && <FunnelBar funnel={funnel} />}
            {/* Spec-0029/T10：按三平面分组——报告 / 提案(带来源徽标) / Ready / 已关闭终态。 */}
            <IssueGroups issues={issues?.issues ?? []} onSelect={onSelect} />

            {/* Spec-0032/T7：交付面——open PR + needs-human 积压（vigil 的工作切面）。 */}
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

// 背压软阈值（与后端 run.py 缺省一致；仅前端示警高亮，权威告警在后端 stdout/状态）。
const DEPTH_SOFT_ALARM = 20;

function FunnelBar({ funnel }: { funnel: { report: number; proposal: number; ready: number } }) {
  const seg = (label: string, n: number, warn: boolean) => (
    <span
      className="chip"
      style={warn ? { color: "var(--red)", fontWeight: 600 } : undefined}
      title={warn ? `${label} 深度 ${n} 超软阈值 ${DEPTH_SOFT_ALARM}（背压示警）` : `${label} 当前量`}
    >
      {label} {n}
    </span>
  );
  return (
    <div className="side-section-head" title="三平面漏斗：报告 → 提案 → Ready">
      {seg("报告", funnel.report, false)}
      <span style={{ color: "var(--text-faint)" }}>→</span>
      {seg("提案", funnel.proposal, funnel.proposal > DEPTH_SOFT_ALARM)}
      <span style={{ color: "var(--text-faint)" }}>→</span>
      {seg("Ready", funnel.ready, funnel.ready > DEPTH_SOFT_ALARM)}
    </div>
  );
}

// 把 issue 分到四组（三平面 + 已关闭终态）。组内按票号升序。
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
    else closed.push(it);  // 已关闭（done/merged/declined 等终态）或无平面
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
      <IssueGroup title="Ready · 可领" issues={g.ready} onSelect={onSelect} highlight />
      <IssueGroup title="提案 · 待准入" issues={g.proposal} onSelect={onSelect} />
      <IssueGroup title="报告 · 待分诊" issues={g.report} onSelect={onSelect} />
      <IssueGroup title="已关闭" issues={g.closed} onSelect={onSelect} dim />
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

// 提案来源徽标文案（provenance → 短名）。
const PROVENANCE_BADGE: Record<string, string> = {
  "from-triage": "分诊",
  "from-architect": "结构",
  "from-divergent": "发散",
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
        <span className="chip tag" title={`提案来源：${prov}`}>
          {PROVENANCE_BADGE[prov] ?? prov}
        </span>
      )}
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
      {/* 结构提案显覆盖建议清单；被覆盖显 ⊂ #N；merged/declined 等终态给标注 */}
      {(issue.covers?.length ?? 0) > 0 && (
        <span className="chip tag" title="该提案建议覆盖的票（合并由准入裁决）">
          覆盖 {issue.covers!.map((n) => `#${n}`).join(" ")}
        </span>
      )}
      {issue.covered_by != null && (
        <span className="chip" title={`被 #${issue.covered_by} 的 covers 引用`}>
          ⊂ #{issue.covered_by}
        </span>
      )}
      {(terminal === "merged" || terminal === "superseded" || terminal === "gate-dropped") && (
        <span className="chip" title="已被合并/取代到主票">
          合并
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
