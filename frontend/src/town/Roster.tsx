import type { Agent } from "../types";
import { health } from "../lib/agentHealth";
import { Sprite } from "./Character";

// 底部花名册：全体居民头像 + 名字，点击选中（同步高亮地图 + 对话面板）。
export function Roster({
  agents,
  now,
  selectedId,
  onSelect,
}: {
  agents: Agent[];
  now: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="roster">
      {agents.map((a) => {
        const h = health(a, now);
        return (
          <button
            key={a.agent_id}
            className={`roster-item${selectedId === a.agent_id ? " selected" : ""}`}
            onClick={() => onSelect(a.agent_id)}
            title={`${a.label} · ${h.text}`}
          >
            <span className={`roster-face anim-${h.cls === "idle" ? "idle" : "still"}`}>
              <Sprite label={a.label} role={a.role} size={30} />
            </span>
            <span className="roster-name">{a.label}</span>
          </button>
        );
      })}
      {agents.length === 0 && <span className="muted">尚无居民（跑闭环后出现）</span>}
    </div>
  );
}
