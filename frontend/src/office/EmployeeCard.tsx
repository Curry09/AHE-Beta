import type { Agent } from "../types";
import { health } from "../lib/agentHealth";
import { roleMeta } from "./roles";

// 员工工位卡片：头像 + 姓名(label) + 健康徽标 + 一行当前活动。点击打开详情抽屉。
export function EmployeeCard({
  agent,
  now,
  selected,
  onSelect,
}: {
  agent: Agent;
  now: number;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const meta = roleMeta(agent.role);
  const h = health(agent, now);
  return (
    <button
      className={`emp ${selected ? "selected" : ""} h-${h.cls}`}
      onClick={() => onSelect(agent.agent_id)}
      title={agent.status}
    >
      <span className="emp-avatar" style={{ background: `${meta.accent}1a`, color: meta.accent }}>
        {meta.emoji}
        <i className={`emp-dot h-${h.cls}`} />
      </span>
      <span className="emp-main">
        <span className="emp-name">{agent.label}</span>
        <span className="emp-status">{agent.status || "空闲"}</span>
      </span>
      <span className={`badge ${h.cls}`}>{h.text}</span>
    </button>
  );
}
