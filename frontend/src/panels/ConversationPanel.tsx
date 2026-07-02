import type { Agent, AgentRole } from "../types";

const ROLE_ZH: Record<AgentRole, string> = {
  user: "用户",
  designer: "设计师",
  developer: "开发者",
};

// 点击小人后，完整对话覆盖右侧（Issue/main 面板）。
export default function ConversationPanel(props: { agent: Agent; onClose: () => void }) {
  const { agent, onClose } = props;
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
        {agent.turns.length === 0 && <div className="empty">暂无对话</div>}
        {agent.turns.map((t, i) => (
          <div key={i} className={`bubble ${t.role}`}>
            <strong>{t.role === "user" ? "用户" : "harness"}</strong>
            {t.content}
          </div>
        ))}
        {agent.detail && (
          <details className="conv-detail">
            <summary>原始明细</summary>
            <pre>{agent.detail}</pre>
          </details>
        )}
      </div>
    </div>
  );
}
