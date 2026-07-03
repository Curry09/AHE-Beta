import type { ReactNode } from "react";
import type { AgentRole } from "../types";

// 极简卡片：一行头（角色点/呼吸点 + 名字）+ status + meta 行。整卡可点开详情。
export function Card(props: {
  role: AgentRole;
  label: string;
  status: string;
  running?: boolean;
  selected: boolean;
  onClick: () => void;
  meta?: ReactNode;
}) {
  const { role, label, status, running, selected, onClick, meta } = props;
  return (
    <button className={selected ? "card selected" : "card"} onClick={onClick}>
      <div className="head">
        {running ? <span className="dot on" /> : <span className={`role-dot ${role}`} />}
        <span className="label">{label}</span>
      </div>
      {status && <div className="status">{status}</div>}
      {meta && <div className="meta">{meta}</div>}
    </button>
  );
}
