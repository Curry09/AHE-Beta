import { Fragment, type ReactNode } from "react";
import type { Agent, AgentRole, HistoryItem, Selection } from "../types";
import { Card } from "./Card";

// User card subtitle: persona level · domain (Spec-0026/T4). Missing meta (older backends / other roles) → empty; card displays identity only.
function personaSubline(agent: Agent): string | undefined {
  const m = agent.meta;
  if (!m) return undefined;
  return [m.level, m.domain].filter(Boolean).join(" · ") || undefined;
}

// Completed work item metadata: show the most useful at-a-glance information for each role by kind.
function historyMeta(item: HistoryItem): ReactNode {
  if (item.kind === "user_session") {
    const origin = item.session_provenance;
    return (
      <>
        {origin && <span>{origin.task_id} · {origin.persona_id}</span>}
        {origin && <span title={origin.harness_sha}>Harness {origin.harness_sha.slice(0, 8)}</span>}
        {item.session_id && <span>session {item.session_id}</span>}
        {item.score != null && <span className={`score s${item.score}`}>Experience {item.score}</span>}
      </>
    );
  }
  if (item.kind === "dev_run") {
    return (
      <>
        {item.issue_number != null && <span>#{item.issue_number}</span>}
        {item.tag && <span className="chip tag">{item.tag}</span>}
        <span>{item.committed ? "Main updated" : "Main unchanged"}</span>
      </>
    );
  }
  // Spec-0029: triager results already appear in the status row (proposal promotion / rejection counts); avoid duplication in meta; owner shows admissions.
  if (item.kind === "triager_run") return null;
  if (item.kind === "owner_run") return <span>{(item.proposals ?? []).length} admissions</span>;
  if (item.kind === "divergent_run") return <span>{(item.proposals ?? []).length} candidates</span>;
  return <span>{(item.proposals ?? []).length} proposals</span>;
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

  // Group completed work items by round (newest round first; preserve archive order within a round).
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
          {showDone ? ` · Completed ${doneCount}` : ""}
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
            meta={
              <>
                {a.round != null && a.round > 0 && <span>Round {a.round}</span>}
                {a.meta?.session_provenance && (
                  <>
                    <span>{a.meta.session_provenance.task_id} · {a.meta.session_provenance.persona_id}</span>
                    <span>session {a.meta.session_id ?? a.agent_id.replace(/^user-/, "")}</span>
                    <span title={a.meta.session_provenance.harness_sha}>Harness {a.meta.session_provenance.harness_sha.slice(0, 8)}</span>
                  </>
                )}
              </>
            }
            subline={personaSubline(a)}
            titleAttr={a.meta?.goal ?? undefined}
          />
        ))}
        {agents.length === 0 && !showDone && <div className="empty">No activity yet</div>}
        {showDone &&
          roundsDesc.map((r) => (
            <Fragment key={r}>
              <div className="round-divider">Round {r}</div>
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
          <div className="empty">No activity yet</div>
        )}
      </div>
    </section>
  );
}
