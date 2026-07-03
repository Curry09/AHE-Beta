import { useEffect, useState } from "react";
import { getSession, getSessions } from "../api";
import type { Agent, AgentRole, SessionDetail, SessionSummary } from "../types";

const ROLE_ZH: Record<AgentRole, string> = {
  user: "用户",
  designer: "设计师",
  developer: "开发者",
};

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleTimeString("zh-CN", { hour12: false });
}

function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString("zh-CN", { hour12: false });
}

function TurnBubbles(props: { turns: { role: string; content: string }[] }) {
  return (
    <>
      {props.turns.map((t, i) => (
        <div key={i} className={`bubble ${t.role}`}>
          <strong>{t.role === "user" ? "用户" : "harness"}</strong>
          {t.content}
        </div>
      ))}
    </>
  );
}

/** 单条历史会话：折叠行，展开时懒加载完整 transcript + 体感 + issue。 */
function HistorySession(props: { row: SessionSummary }) {
  const { row } = props;
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [failed, setFailed] = useState(false);

  const load = () => {
    if (detail || failed) return;
    getSession(row.session_id)
      .then(setDetail)
      .catch(() => setFailed(true));
  };

  return (
    <details className="hist-item" onToggle={(e) => e.currentTarget.open && load()}>
      <summary>
        <span className="hist-time">{fmtDateTime(row.created_at)}</span>
        <span className="hist-scenario">{row.scenario}</span>
        <span className="hist-meta">
          体感 {row.score} · issue {row.n_issues}
        </span>
      </summary>
      {failed && <div className="empty">加载失败</div>}
      {!detail && !failed && <div className="empty">加载中…</div>}
      {detail && (
        <div className="hist-body">
          <TurnBubbles turns={detail.transcript.turns} />
          <div className="hist-feeling">
            体感 {detail.feeling.score}/4：{detail.feeling.reason || "（无理由）"}
            {detail.issue_refs.length > 0 && (
              <>
                {" "}
                · 提了 issue{" "}
                {detail.issue_refs.map((r) => (
                  <a key={r.number} href={r.url} target="_blank" rel="noreferrer">
                    #{r.number}
                  </a>
                ))}
              </>
            )}
          </div>
        </div>
      )}
    </details>
  );
}

// 点击小人后，覆盖右侧（Issue/main 面板）：
// - 用户 agent：当前会话完整对话 + 该 persona 的全部历史会话（SessionStore 落盘，逐条展开看全文）。
// - 开发者/设计师：工作过程时间线（log，含逐工具调用步骤）+ 最终报告（detail，默认展开）。
export default function ConversationPanel(props: { agent: Agent; onClose: () => void }) {
  const { agent, onClose } = props;
  const log = agent.log ?? [];
  const hasTurns = agent.turns.length > 0;
  const [history, setHistory] = useState<SessionSummary[]>([]);

  // 历史会话 = 该 persona（identity=label）落盘的所有 session，含已跑完的往局。
  useEffect(() => {
    if (agent.role !== "user") return;
    let alive = true;
    getSessions()
      .then((rows) => {
        if (alive) setHistory(rows.filter((r) => r.persona_identity === agent.label));
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [agent.role, agent.label]);

  return (
    <div className="conv">
      <div className="conv-head">
        <div className="conv-id">
          <span className={`conv-dot ${agent.running ? "on" : "off"}`} />
          <b>{agent.label}</b>
          <span className={`role role-${agent.role}`}>{ROLE_ZH[agent.role] ?? agent.role}</span>
        </div>
        <button className="conv-close" onClick={onClose} title="返回 Issue / main">
          ✕
        </button>
      </div>
      <div className="conv-status">{agent.status || "（无状态）"}</div>

      <div className="conv-body">
        {agent.role === "user" ? (
          <>
            <div className="conv-section">当前会话</div>
            {hasTurns ? <TurnBubbles turns={agent.turns} /> : <div className="empty">暂无对话</div>}
            <div className="conv-section">历史会话（{history.length}）</div>
            {history.length === 0 && <div className="empty">暂无落盘会话</div>}
            {history.map((row) => (
              <HistorySession key={row.session_id} row={row} />
            ))}
          </>
        ) : (
          <div className="conv-log">
            <div className="conv-section">工作过程（{log.length}）</div>
            {log.length === 0 && <div className="empty">暂无工作记录</div>}
            {log.map((e, i) => (
              <div key={i} className="conv-log-row">
                <span className="conv-log-time">{fmtTime(e.t)}</span>
                <span className="conv-log-text">{e.text}</span>
              </div>
            ))}
          </div>
        )}
        {agent.detail && (
          <details className="conv-detail" open={agent.role !== "user"}>
            <summary>{agent.role === "user" ? "原始明细" : "最终报告"}</summary>
            <pre>{agent.detail}</pre>
          </details>
        )}
      </div>
    </div>
  );
}
