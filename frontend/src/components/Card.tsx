import type { ReactNode } from "react";
import type { AgentRole } from "../types";

// Minimal card: header row (role dot / pulse dot + name) + optional subtitle (persona level · domain) + status + metadata row.
// Color the left edge by role (role-${role}). Click anywhere on the card to open details.
export function Card(props: {
  role: AgentRole;
  label: string;
  status: string;
  running?: boolean;
  selected: boolean;
  onClick: () => void;
  meta?: ReactNode;
  subline?: string; // Spec-0026/T4: user card subtitle (level · domain); omit when absent.
  titleAttr?: string; // Hover tooltip (such as persona goal)
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
