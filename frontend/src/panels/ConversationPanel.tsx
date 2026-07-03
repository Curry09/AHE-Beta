import type { Agent, AgentRole } from "../types";

const ROLE_ZH: Record<AgentRole, string> = {
  user: "用户",
  designer: "设计师",
  developer: "开发者",
};

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleTimeString("zh-CN", { hour12: false });
}

// 点击小人后，覆盖右侧（Issue/main 面板）：用户 agent 展示完整对话；
// 开发者/设计师无 turns，展示工作过程时间线（log）+ 最终报告（detail，默认展开）。
export default function ConversationPanel(props: { agent: Agent; onClose: () => void }) {
  const { agent, onClose } = props;
  const log = agent.log ?? [];
  const hasTurns = agent.turns.length > 0;
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
        {hasTurns ? (
          agent.turns.map((t, i) => (
            <div key={i} className={`bubble ${t.role}`}>
              <strong>{t.role === "user" ? "用户" : "harness"}</strong>
              {t.content}
            </div>
          ))
        ) : (
          <div className="conv-log">
            <div className="conv-section">工作过程</div>
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
          <details className="conv-detail" open={!hasTurns}>
            <summary>{hasTurns ? "原始明细" : "最终报告"}</summary>
            <pre>{agent.detail}</pre>
          </details>
        )}
      </div>
    </div>
  );
}
