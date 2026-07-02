import type { Agent } from "../types";
import { zoneByKey } from "./layout";

// 顶部对话记录面板（斯坦福小镇左上角那块半透明绿）：
// 选中某居民 → 展示其 turns 对话；未选中 → 展示全镇活动摘要（各活动 agent 的最新 status）。
export function DialogueLog({
  agents,
  selected,
}: {
  agents: Agent[];
  selected: Agent | null;
}) {
  const zoneName = (role: string) =>
    zoneByKey(role === "developer" ? "workshop" : "cafe")?.name ?? "the Ville";

  if (selected && selected.turns.length > 0) {
    const t = new Date(selected.updated_at);
    return (
      <div className="dialoglog">
        <div className="dl-head">
          {t.toLocaleDateString()} {t.toLocaleTimeString()} 对话记录：
        </div>
        <div className="dl-loc">
          地点：the Ville，{zoneName(selected.role)} — {selected.label}
        </div>
        <div className="dl-body">
          {selected.turns.map((turn, i) => (
            <div key={i} className="dl-line">
              <b>{turn.role === "user" ? selected.label : "harness"}：</b>
              {turn.content?.trim() ? turn.content : "（空回复）"}
            </div>
          ))}
        </div>
      </div>
    );
  }

  const active = agents.filter((a) => a.running || /error|否决|异常/i.test(a.status));
  return (
    <div className="dialoglog">
      <div className="dl-head">全镇活动 · {active.length} 位居民进行中</div>
      <div className="dl-loc">地点：the Ville（点击居民查看其对话）</div>
      <div className="dl-body">
        {active.length === 0 ? (
          <div className="dl-line muted">小镇安静无人活动。</div>
        ) : (
          active.map((a) => (
            <div key={a.agent_id} className="dl-line">
              <b>{a.label}：</b>
              {a.status}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
