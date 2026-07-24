import type { ReactNode } from "react";
import type { AgentRole } from "../types";

// 极简卡片：一行头（角色点/呼吸点 + 名字）+ 可选副行（persona 水平·领域）+ status + meta 行。
// 左缘按角色着色（role-${role}）。整卡可点开详情。
export function Card(props: {
  role: AgentRole;
  label: string;
  status: string;
  running?: boolean;
  selected: boolean;
  onClick: () => void;
  meta?: ReactNode;
  subline?: string; // Spec-0026/T4：用户卡副行（水平·领域），缺省不渲染
  titleAttr?: string; // 悬浮 tooltip（如 persona goal）
}) {
  const { role, label, status, running, selected, onClick, meta, subline, titleAttr } = props;
  return (
    <button
      className={`card role-${role}${selected ? " selected" : ""}`}
      onClick={onClick}
      title={titleAttr}
    >
      <div className="head">
        {running ? <span className="dot on" /> : <span className={`role-dot ${role}`} />}
        <span className="label">{label}</span>
      </div>
      {subline && <div className="subline">{subline}</div>}
      {status && <div className="status">{status}</div>}
      {meta && <div className="meta">{meta}</div>}
    </button>
  );
}
