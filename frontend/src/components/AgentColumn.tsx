import { Fragment, type ReactNode } from "react";
import type { Agent, AgentRole, HistoryItem, Selection } from "../types";
import { Card } from "./Card";

// 已完成工作项的 meta 行：按 kind 给出各角色最要紧的一眼信息。
function historyMeta(item: HistoryItem): ReactNode {
  if (item.kind === "user_session") {
    return (
      <>
        {item.score != null && <span className={`score s${item.score}`}>体感 {item.score}</span>}
        {item.end_reason && <span>{item.end_reason}</span>}
      </>
    );
  }
  if (item.kind === "dev_run") {
    return (
      <>
        {item.issue_number != null && <span>#{item.issue_number}</span>}
        {item.tag && <span className="chip tag">{item.tag}</span>}
        <span>{item.committed ? "已推进 main" : "未推进"}</span>
      </>
    );
  }
  return <span>{(item.proposals ?? []).length} 条提案</span>;
}

export function AgentColumn(props: {
  role: AgentRole;
  name: string;
  agents: Agent[];
  history: { item: HistoryItem; index: number }[];
  showDone: boolean;
  selection: Selection | null;
  onSelect: (sel: Selection) => void;
}) {
  const { role, name, agents, history, showDone, selection, onSelect } = props;

  // 已完成工作项按轮分组（新轮在前，轮内保持归档先后）。
  const byRound = new Map<number, { item: HistoryItem; index: number }[]>();
  if (showDone) {
    for (const entry of history) {
      const list = byRound.get(entry.item.round) ?? [];
      list.push(entry);
      byRound.set(entry.item.round, list);
    }
  }
  const roundsDesc = [...byRound.keys()].sort((a, b) => b - a);
  const doneCount = history.length;

  return (
    <section className="column">
      <div className="column-head">
        <span className={`role-dot ${role}`} />
        {name}
        <span className="count">
          {agents.length}
          {showDone ? ` · 完成 ${doneCount}` : ""}
        </span>
      </div>
      <div className="column-body">
        {agents.map((a) => (
          <Card
            key={a.agent_id}
            role={role}
            label={a.label}
            status={a.status}
            running={a.running}
            selected={selection?.type === "agent" && selection.agentId === a.agent_id}
            onClick={() => onSelect({ type: "agent", agentId: a.agent_id })}
            meta={a.round != null && a.round > 0 ? <span>第 {a.round} 轮</span> : undefined}
          />
        ))}
        {agents.length === 0 && !showDone && <div className="empty">暂无活动</div>}
        {showDone &&
          roundsDesc.map((r) => (
            <Fragment key={r}>
              <div className="round-divider">第 {r} 轮</div>
              {(byRound.get(r) ?? []).map(({ item, index }) => (
                <Card
                  key={`${item.agent_id}-${item.archived_at}`}
                  role={role}
                  label={item.label}
                  status={item.status}
                  selected={selection?.type === "history" && selection.index === index}
                  onClick={() => onSelect({ type: "history", index })}
                  meta={historyMeta(item)}
                />
              ))}
            </Fragment>
          ))}
        {showDone && agents.length === 0 && doneCount === 0 && (
          <div className="empty">暂无活动</div>
        )}
      </div>
    </section>
  );
}
