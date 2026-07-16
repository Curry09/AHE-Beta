import type { ReactElement } from "react";
import type {
  Agent,
  Commit,
  CommitsResponse,
  HistoryItem,
  IssuesResponse,
  Selection,
} from "../types";
import { fmtDate } from "../lib/format";
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
            {(issues?.issues ?? []).map((issue) => (
              <button
                key={issue.number}
                className={`row ${issue.state}`}
                onClick={() => onSelect({ type: "issue", number: issue.number })}
              >
                <span className="num">#{issue.number}</span>
                <span className="row-title">{issue.title}</span>
                {issue.labels.slice(0, 2).map((l) => (
                  <span key={l} className="chip">
                    {l}
                  </span>
                ))}
                {/* Spec-0020/T5 覆盖徽标：bug 被 design 覆盖显 ⊂ #N；design 显其覆盖清单 */}
                {issue.covered_by != null && (
                  <span className="chip" title={`已被设计票 #${issue.covered_by} 覆盖`}>
                    ⊂ #{issue.covered_by}
                  </span>
                )}
                {(issue.covers?.length ?? 0) > 0 && (
                  <span className="chip" title="该设计票覆盖的 bug">
                    覆盖 {issue.covers!.map((n) => `#${n}`).join(" ")}
                  </span>
                )}
                <span className={`chip ${issue.state}`}>{issue.state}</span>
              </button>
            ))}

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
