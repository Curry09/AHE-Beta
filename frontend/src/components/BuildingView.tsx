import type { Agent, AgentRole, Roster, Selection } from "../types";
import { BuildingTower } from "./building/BuildingTower";
import { FloorWorkspace } from "./building/FloorWorkspace";
import {
  buildFloorModels,
  resolveBuildingMode,
  titleCopy,
  type FloorModel,
  type HistoryEntry,
  type RoundFilter,
} from "./building/buildingModel";

export function getSelectedFloorModel(floors: FloorModel[], selectedFloor: AgentRole): FloorModel {
  return floors.find((floor) => floor.role === selectedFloor) ?? floors[0];
}

export function getBuildingState(params: {
  roles: { role: AgentRole; name: string }[];
  agents: Agent[];
  history: HistoryEntry[];
  allHistory: HistoryEntry[];
  roster: Roster | null;
  showDone: boolean;
  round: RoundFilter;
}) {
  const { mode, effectiveHistory, fallbackRound } = resolveBuildingMode(
    params.showDone,
    params.round,
    params.agents,
    params.history,
    params.allHistory,
  );
  const floors = buildFloorModels({
    roles: params.roles,
    agents: params.agents,
    history: effectiveHistory,
    roster: params.roster,
    mode,
  });
  return { mode, effectiveHistory, fallbackRound, floors };
}

export function BuildingView(props: {
  roles: { role: AgentRole; name: string }[];
  agents: Agent[];
  history: HistoryEntry[];
  allHistory: HistoryEntry[];
  roster: Roster | null;
  showDone: boolean;
  round: RoundFilter;
  selectedFloor: AgentRole;
  onSelectFloor: (role: AgentRole) => void;
  onSelect: (sel: Selection) => void;
}) {
  const { mode, effectiveHistory, fallbackRound, floors } = getBuildingState(props);
  const selectedFloor = getSelectedFloorModel(floors, props.selectedFloor);
  const hasAnyData = props.agents.length > 0 || effectiveHistory.length > 0;

  return (
    <section className={`building-view mode-${mode}`} aria-label="2.5D 公司大楼可视化视图">
      <div className="building-title">
        <div>
          <div className="building-kicker">Agent Company</div>
          <h2>Agent HQ</h2>
        </div>
        <p>
          <span className="building-mode-badge">
            {fallbackRound != null ? "最近" : mode === "live" ? "当前" : mode === "replay" ? "复盘" : "汇总"}
          </span>
          {titleCopy(mode, props.round, fallbackRound)}
        </p>
      </div>

      {!hasAnyData && (
        <div className="building-empty-state">
          暂无 live agent 或历史归档。需要先跑一轮闭环，或打开“+ 已完成”并选择已有轮次。
        </div>
      )}

      <div className="building-content">
        <div className="building-tower-pane">
          <BuildingTower
            floors={floors}
            mode={mode}
            selectedFloor={props.selectedFloor}
            onSelectFloor={props.onSelectFloor}
          />
        </div>
        <div className="building-floor-pane">
          <FloorWorkspace
            floor={selectedFloor}
            mode={mode}
            round={props.round}
            onSelect={props.onSelect}
          />
        </div>
      </div>
    </section>
  );
}
