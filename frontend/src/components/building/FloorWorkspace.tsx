import type { AgentRole, Selection } from "../../types";
import type { BuildingMode, FloorModel, RoundFilter } from "./buildingModel";
import { historyLabel, shortStatus } from "./buildingModel";

function modeLabel(mode: BuildingMode, round: RoundFilter): string {
  if (mode === "live") return "当前办公";
  if (mode === "replay" && round !== "all") return `第 ${round} 轮复盘`;
  return "全部轮次汇总";
}

const WORKSPACE_KIND: Record<AgentRole, { label: string; hint: string }> = {
  user: { label: "USER LAB", hint: "体验舱 / 访谈台" },
  triager: { label: "TRIAGE DESK", hint: "队列 / 分诊台" },
  architect: { label: "ARCHITECT", hint: "白板 / 方案墙" },
  divergent: { label: "DIVERGENT ROOM", hint: "灵感板 / 候选池" },
  owner: { label: "OWNER GATE", hint: "准入台 / Ready 队列" },
  developer: { label: "DELIVERY BOUNDARY", hint: "openagents 交接令牌" },
};

export function FloorWorkspace(props: {
  floor: FloorModel;
  mode: BuildingMode;
  round: RoundFilter;
  onSelect: (sel: Selection) => void;
}) {
  const { floor, mode, round, onSelect } = props;
  const latest = floor.history[floor.history.length - 1]?.item;
  const workspace = WORKSPACE_KIND[floor.role];

  return (
    <div className={`floor-workspace role-${floor.role} mode-${mode}`}>
      <div className="floor-workspace-head">
        <div className="floor-workspace-title">
          <span className="floor-workspace-icon" aria-hidden="true">
            {floor.icon}
          </span>
          <div>
            <div className="building-kicker">{floor.floorNo}F · {modeLabel(mode, round)}</div>
            <h2>{floor.name}工区</h2>
            <p>{floor.subtitle}</p>
          </div>
        </div>
        <div className="floor-workspace-meta">
          <span>{workspace.label}</span>
          <em>{workspace.hint}</em>
          <strong>{mode === "summary" ? `${floor.history.length} 条归档` : `${floor.activeCount}/${floor.capacity} 使用中`}</strong>
        </div>
      </div>

      <div className="floor-seat-grid">
        {mode === "live" &&
          floor.liveAgents.map((agent) => (
            <button
              key={agent.agent_id}
              className="floor-seat-card active"
              title={agent.meta?.goal ?? agent.status}
              onClick={() => onSelect({ type: "agent", agentId: agent.agent_id })}
            >
              <span className="seat-avatar" aria-hidden="true">{floor.icon}</span>
              <span className="seat-monitor" aria-hidden="true" />
              <span className="seat-main">
                <span className="seat-name">
                  {agent.running ? <span className="dot on" /> : <span className={`role-dot ${floor.role}`} />}
                  <strong>{agent.label}</strong>
                </span>
                <span>{shortStatus(agent.status || "待命中")}</span>
                {agent.round != null && agent.round > 0 && <em>第 {agent.round} 轮</em>}
              </span>
            </button>
          ))}

        {mode === "replay" &&
          floor.history.map(({ item, index }) => (
            <button
              key={`${item.agent_id}-${item.archived_at}`}
              className="floor-seat-card archived"
              title={item.status}
              onClick={() => onSelect({ type: "history", index })}
            >
              <span className="seat-avatar" aria-hidden="true">{floor.icon}</span>
              <span className="seat-monitor archived" aria-hidden="true" />
              <span className="seat-main">
                <span className="seat-name">
                  <span className={`role-dot ${floor.role}`} />
                  <strong>{item.label}</strong>
                </span>
                <span>{shortStatus(item.status || "已归档")}</span>
                <em>第 {item.round} 轮 · {historyLabel(item)}</em>
              </span>
            </button>
          ))}

        {mode === "summary" && (
          <>
            <div className="floor-summary-room">
              <div className="summary-num">{floor.history.length}</div>
              <div>
                <strong>全部轮次产出</strong>
                <p>当前 live：{floor.liveAgents.length} 个 agent</p>
                <p>{latest ? `最近：第 ${latest.round} 轮 · ${latest.label} · ${historyLabel(latest)}` : "暂无历史归档"}</p>
              </div>
            </div>
            {floor.history.slice(-12).reverse().map(({ item, index }) => (
              <button
                key={`${item.agent_id}-${item.archived_at}`}
                className="floor-seat-card archived"
                title={item.status}
                onClick={() => onSelect({ type: "history", index })}
              >
                <span className="seat-avatar" aria-hidden="true">{floor.icon}</span>
                <span className="seat-monitor archived" aria-hidden="true" />
                <span className="seat-main">
                  <span className="seat-name">
                    <span className={`role-dot ${floor.role}`} />
                    <strong>{item.label}</strong>
                  </span>
                  <span>{shortStatus(item.status || "已归档")}</span>
                  <em>第 {item.round} 轮 · {historyLabel(item)}</em>
                </span>
              </button>
            ))}
          </>
        )}

        {Array.from({ length: floor.emptySeats }).map((_, i) => (
          <div key={`${floor.role}-empty-${i}`} className="floor-empty-seat" aria-hidden="true">
            <span className="seat-avatar empty">○</span>
            <span className="seat-monitor" />
            <span>空工位</span>
          </div>
        ))}

        {mode !== "summary" && floor.activeCount === 0 && floor.emptySeats === 0 && (
          <div className="floor-empty">该楼层当前没有可展示工位</div>
        )}
      </div>

      <div className="floor-log-list">
        <div className="block-title">最近动态</div>
        {floor.recentLogs.length === 0 && <div className="empty">暂无动态</div>}
        {floor.recentLogs.map((log, i) => (
          <div key={`${log.source}-${i}-${log.t ?? ""}`} className={`floor-log-row ${log.kind}`}>
            <span>{log.source}</span>
            <p>{shortStatus(log.text)}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
