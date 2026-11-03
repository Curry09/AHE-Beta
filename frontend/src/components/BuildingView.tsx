import type {
  Agent,
  AgentRole,
  DeliveryResponse,
  IssuesResponse,
  Roster,
  Selection,
} from "../types";
import { BuildingTower, type OpenAgentsFactorySummary } from "./building/BuildingTower";
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

function getOpenAgentsFactorySummary(
  issues: IssuesResponse | null,
  delivery: DeliveryResponse | null,
): OpenAgentsFactorySummary {
  const issueItems = issues?.connected ? issues.issues : [];
  const openIssues = issueItems.filter((issue) => issue.state === "open");
  const handoff = openIssues.filter(
    (issue) => issue.labels.includes("openagents") && !issue.labels.includes("ready"),
  ).length;
  const ready = openIssues.filter((issue) => issue.labels.includes("ready")).length;
  const loading = issues === null || delivery === null;
  const disconnected = issues?.connected === false || delivery?.connected === false;
  return {
    status: loading ? "loading" : disconnected ? "disconnected" : delivery.needs_human > 0 ? "blocked" : "ready",
    handoff: issues?.connected ? handoff : null,
    ready: issues?.connected ? ready : null,
    pulls: delivery?.connected ? delivery.pulls.length : null,
    needsHuman: delivery?.connected ? delivery.needs_human : null,
    moving: handoff > 0,
  };
}

export function BuildingView(props: {
  roles: { role: AgentRole; name: string }[];
  agents: Agent[];
  history: HistoryEntry[];
  allHistory: HistoryEntry[];
  roster: Roster | null;
  showDone: boolean;
  round: RoundFilter;
  issues: IssuesResponse | null;
  delivery: DeliveryResponse | null;
  selectedFloor: AgentRole;
  onSelectFloor: (role: AgentRole) => void;
  onSelect: (sel: Selection) => void;
  onOpenAgents: () => void;
}) {
  const { mode, effectiveHistory, fallbackRound, floors } = getBuildingState(props);
  const selectedFloor = getSelectedFloorModel(floors, props.selectedFloor);
  const hasAnyData = props.agents.length > 0 || effectiveHistory.length > 0;
  const factory = getOpenAgentsFactorySummary(props.issues, props.delivery);

  return (
    <section className={`building-view mode-${mode}`} aria-label="2.5D office building view">
      <div className="building-title">
        <div>
          <div className="building-kicker">Agent Company</div>
          <h2>Agent Campus</h2>
        </div>
        <p>
          <span className="building-mode-badge">
            {fallbackRound != null ? "Recent" : mode === "live" ? "Current" : mode === "replay" ? "Retrospective" : "Summary"}
          </span>
          {titleCopy(mode, props.round, fallbackRound)}
        </p>
      </div>

      {!hasAnyData && (
        <div className="building-empty-state">
          No live agents or archived runs yet. Run one complete round, or enable “+ Completed” and select an existing round.
        </div>
      )}

      <div className="building-content">
        <div className="building-tower-pane">
          <BuildingTower
            floors={floors}
            mode={mode}
            selectedFloor={props.selectedFloor}
            onSelectFloor={props.onSelectFloor}
            factory={factory}
            onOpenAgents={props.onOpenAgents}
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
