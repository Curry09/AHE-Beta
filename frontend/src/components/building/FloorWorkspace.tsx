import type { AgentRole, Selection } from "../../types";
import type { BuildingMode, FloorModel, RoundFilter } from "./buildingModel";
import { historyLabel, shortStatus } from "./buildingModel";

function modeLabel(mode: BuildingMode, round: RoundFilter): string {
  if (mode === "live") return "Currently working";
  if (mode === "replay" && round !== "all") return `Round ${round} retrospective`;
  return "All rounds summary";
}

const WORKSPACE_KIND: Record<AgentRole, { label: string; hint: string }> = {
  user: { label: "USER LAB", hint: "Experience lab / Interview desk" },
  triager: { label: "TRIAGE DESK", hint: "Queue / Triage desk" },
  architect: { label: "ARCHITECT", hint: "Whiteboard / Proposal wall" },
  divergent: { label: "DIVERGENT ROOM", hint: "Idea board / Candidate pool" },
  owner: { label: "OWNER GATE", hint: "Admission desk / Ready Queue" },
  developer: { label: "DELIVERY BOUNDARY", hint: "openagents Handoff token" },
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
            <h2>{floor.name} workspace</h2>
            <p>{floor.subtitle}</p>
          </div>
        </div>
        <div className="floor-workspace-meta">
          <span>{workspace.label}</span>
          <em>{workspace.hint}</em>
          <strong>{mode === "summary" ? `${floor.history.length} archived entries` : `${floor.activeCount}/${floor.capacity} occupied`}</strong>
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
                <span>{shortStatus(agent.status || "On standby")}</span>
                {agent.round != null && agent.round > 0 && <em>Round {agent.round}</em>}
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
                <span>{shortStatus(item.status || "Archived")}</span>
                <em>Round {item.round} · {historyLabel(item)}</em>
              </span>
            </button>
          ))}

        {mode === "summary" && (
          <>
            <div className="floor-summary-room">
              <div className="summary-num">{floor.history.length}</div>
              <div>
                <strong>All rounds output</strong>
                <p>Current live: {floor.liveAgents.length} Items agent</p>
                <p>{latest ? `Latest: round ${latest.round} · ${latest.label} · ${historyLabel(latest)}` : "No historical archives"}</p>
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
                  <span>{shortStatus(item.status || "Archived")}</span>
                  <em>Round {item.round} · {historyLabel(item)}</em>
                </span>
              </button>
            ))}
          </>
        )}

        {Array.from({ length: floor.emptySeats }).map((_, i) => (
          <div key={`${floor.role}-empty-${i}`} className="floor-empty-seat" aria-hidden="true">
            <span className="seat-avatar empty">○</span>
            <span className="seat-monitor" />
            <span>Empty workstation</span>
          </div>
        ))}

        {mode !== "summary" && floor.activeCount === 0 && floor.emptySeats === 0 && (
          <div className="floor-empty">No workstations to display on this floor</div>
        )}
      </div>

      <div className="floor-log-list">
        <div className="block-title">Recent activity</div>
        {floor.recentLogs.length === 0 && <div className="empty">No recent activity</div>}
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
