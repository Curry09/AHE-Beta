import type { KeyboardEvent } from "react";
import type { AgentRole } from "../../types";
import type { BuildingMode, FloorModel } from "./buildingModel";

const FACADE_X = 42;
const FACADE_Y = 86;
const FACADE_W = 310;
const FLOOR_H = 64;
const DEPTH_X = 72;
const DEPTH_Y = -44;
const LABEL_W = 160;
const WINDOW_GAP = 8;
const FACTORY_X = 390;
const FACTORY_Y = 260;
const FACTORY_W = 190;
const FACTORY_H = 130;
const FACTORY_DEPTH_X = 42;
const FACTORY_DEPTH_Y = -26;

export interface OpenAgentsFactorySummary {
  status: "loading" | "disconnected" | "blocked" | "ready";
  handoff: number | null;
  ready: number | null;
  pulls: number | null;
  needsHuman: number | null;
  moving: boolean;
}

function countLabel(floor: FloorModel, mode: BuildingMode): string {
  if (mode === "summary") return `${floor.history.length} 条归档`;
  if (mode === "replay") return `${floor.history.length}/${floor.capacity} 归档`;
  return `${floor.liveAgents.length}/${floor.capacity} 在岗`;
}

function points(points: [number, number][]): string {
  return points.map(([x, y]) => `${x},${y}`).join(" ");
}

function activateFloor(
  event: KeyboardEvent<SVGGElement>,
  role: AgentRole,
  onSelectFloor: (role: AgentRole) => void,
) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    onSelectFloor(role);
  }
}

function activateFactory(event: KeyboardEvent<SVGGElement>, onOpenAgents: () => void) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    onOpenAgents();
  }
}

function factoryStatus(summary: OpenAgentsFactorySummary): string {
  if (summary.status === "loading") return "连接中…";
  if (summary.status === "disconnected") return "观测不可用";
  if (summary.status === "blocked") return `needs-human ${summary.needsHuman ?? 0}`;
  return "connected";
}

function metric(value: number | null): string {
  return value === null ? "—" : String(value);
}

export function BuildingTower(props: {
  floors: FloorModel[];
  mode: BuildingMode;
  selectedFloor: AgentRole;
  onSelectFloor: (role: AgentRole) => void;
  factory: OpenAgentsFactorySummary;
  onOpenAgents: () => void;
}) {
  const { floors, mode, selectedFloor, onSelectFloor, factory, onOpenAgents } = props;
  const facadeH = floors.length * FLOOR_H;
  const viewW = FACTORY_X + FACTORY_W + FACTORY_DEPTH_X + 28;
  const viewH = FACADE_Y + facadeH + 94;
  const roof = points([
    [FACADE_X, FACADE_Y],
    [FACADE_X + FACADE_W, FACADE_Y],
    [FACADE_X + FACADE_W + DEPTH_X, FACADE_Y + DEPTH_Y],
    [FACADE_X + DEPTH_X, FACADE_Y + DEPTH_Y],
  ]);
  const side = points([
    [FACADE_X + FACADE_W, FACADE_Y],
    [FACADE_X + FACADE_W + DEPTH_X, FACADE_Y + DEPTH_Y],
    [FACADE_X + FACADE_W + DEPTH_X, FACADE_Y + facadeH + DEPTH_Y],
    [FACADE_X + FACADE_W, FACADE_Y + facadeH],
  ]);
  const sideBase = points([
    [FACADE_X + FACADE_W, FACADE_Y + facadeH],
    [FACADE_X + FACADE_W + DEPTH_X, FACADE_Y + facadeH + DEPTH_Y],
    [FACADE_X + FACADE_W + DEPTH_X + 20, FACADE_Y + facadeH + DEPTH_Y + 18],
    [FACADE_X + FACADE_W + 20, FACADE_Y + facadeH + 18],
  ]);
  const factoryRoof = points([
    [FACTORY_X, FACTORY_Y],
    [FACTORY_X + FACTORY_W, FACTORY_Y],
    [FACTORY_X + FACTORY_W + FACTORY_DEPTH_X, FACTORY_Y + FACTORY_DEPTH_Y],
    [FACTORY_X + FACTORY_DEPTH_X, FACTORY_Y + FACTORY_DEPTH_Y],
  ]);
  const factorySide = points([
    [FACTORY_X + FACTORY_W, FACTORY_Y],
    [FACTORY_X + FACTORY_W + FACTORY_DEPTH_X, FACTORY_Y + FACTORY_DEPTH_Y],
    [FACTORY_X + FACTORY_W + FACTORY_DEPTH_X, FACTORY_Y + FACTORY_H + FACTORY_DEPTH_Y],
    [FACTORY_X + FACTORY_W, FACTORY_Y + FACTORY_H],
  ]);

  return (
    <div className="building-overview" aria-label="大楼总览">
      <div className="building-stage">
        <svg
          className="building-tower-svg"
          viewBox={`0 0 ${viewW} ${viewH}`}
          role="list"
          aria-label="楼层列表"
        >
          <ellipse
            className="tower-plaza"
            cx={(FACADE_X + FACTORY_X + FACTORY_W + FACTORY_DEPTH_X) / 2}
            cy={FACADE_Y + facadeH + 42}
            rx={(FACTORY_X + FACTORY_W + FACTORY_DEPTH_X - FACADE_X) / 2 + 30}
            ry="32"
          />
          <path
            className={`campus-flight-path${factory.moving ? " active" : ""}`}
            d={`M ${FACADE_X + FACADE_W + 28} ${FACADE_Y - 25} Q 455 115 505 ${FACTORY_Y + FACTORY_DEPTH_Y - 8}`}
            aria-hidden="true"
          />
          <g
            className={`campus-aircraft${factory.moving ? " moving" : ""}`}
            transform={`translate(${FACADE_X + FACADE_W + 20} ${FACADE_Y - 38})`}
            aria-hidden="true"
          >
            <text x="0" y="0">🛩️</text>
          </g>
          <g
            className={`openagents-factory status-${factory.status}`}
            role="button"
            tabIndex={0}
            aria-label={`进入 OpenAgents 交付面，${factoryStatus(factory)}`}
            onClick={onOpenAgents}
            onKeyDown={(event) => activateFactory(event, onOpenAgents)}
          >
            <polygon className="factory-side" points={factorySide} aria-hidden="true" />
            <rect
              className="factory-facade"
              x={FACTORY_X}
              y={FACTORY_Y}
              width={FACTORY_W}
              height={FACTORY_H}
              rx="7"
              aria-hidden="true"
            />
            <polygon className="factory-roof" points={factoryRoof} aria-hidden="true" />
            <rect
              className="factory-sign"
              x={FACTORY_X + 18}
              y={FACTORY_Y + 18}
              width={FACTORY_W - 36}
              height="28"
              rx="5"
              aria-hidden="true"
            />
            <text className="factory-name" x={FACTORY_X + FACTORY_W / 2} y={FACTORY_Y + 37}>
              OpenAgents
            </text>
            <text className="factory-metrics" x={FACTORY_X + FACTORY_W / 2} y={FACTORY_Y + 67}>
              handoff {metric(factory.handoff)} · ready {metric(factory.ready)} · PR {metric(factory.pulls)}
            </text>
            <circle
              className="factory-status-light"
              cx={FACTORY_X + 25}
              cy={FACTORY_Y + 90}
              r="5"
              aria-hidden="true"
            />
            <text className="factory-status" x={FACTORY_X + 37} y={FACTORY_Y + 94}>
              {factoryStatus(factory)}
            </text>
            <text className="factory-enter" x={FACTORY_X + FACTORY_W - 18} y={FACTORY_Y + 94}>
              进入 →
            </text>
            <rect
              className="factory-hit"
              x={FACTORY_X}
              y={FACTORY_Y + FACTORY_DEPTH_Y}
              width={FACTORY_W + FACTORY_DEPTH_X}
              height={FACTORY_H - FACTORY_DEPTH_Y}
              aria-hidden="true"
            />
          </g>
          <polygon className="tower-side-base" points={sideBase} aria-hidden="true" />
          <polygon className="tower-side" points={side} aria-hidden="true" />
          <rect
            className="tower-facade"
            x={FACADE_X}
            y={FACADE_Y}
            width={FACADE_W}
            height={facadeH}
            rx="10"
            aria-hidden="true"
          />
          <polygon className="tower-roof" points={roof} aria-hidden="true" />

          {floors.map((floor, index) => {
            const y = FACADE_Y + index * FLOOR_H;
            const selected = selectedFloor === floor.role;
            const windowCount = Math.max(3, Math.min(8, floor.capacity || 3));
            const windowAreaX = FACADE_X + LABEL_W;
            const windowAreaW = FACADE_W - LABEL_W - 24;
            const windowW = Math.max(9, Math.min(22, (windowAreaW - WINDOW_GAP * (windowCount - 1)) / windowCount));
            const sideBand = points([
              [FACADE_X + FACADE_W, y],
              [FACADE_X + FACADE_W + DEPTH_X, y + DEPTH_Y],
              [FACADE_X + FACADE_W + DEPTH_X, y + FLOOR_H + DEPTH_Y],
              [FACADE_X + FACADE_W, y + FLOOR_H],
            ]);
            return (
              <g
                key={floor.role}
                className={`tower-floor role-${floor.role}${selected ? " selected" : ""}`}
                role="button"
                tabIndex={0}
                aria-pressed={selected}
                aria-label={`展开 ${floor.floorNo}F ${floor.name} 工区，${countLabel(floor, mode)}`}
                onClick={() => onSelectFloor(floor.role)}
                onKeyDown={(event) => activateFloor(event, floor.role, onSelectFloor)}
              >
                <polygon className="tower-floor-side-band" points={sideBand} aria-hidden="true" />
                <rect
                  className="tower-floor-band"
                  x={FACADE_X}
                  y={y}
                  width={FACADE_W}
                  height={FLOOR_H}
                  aria-hidden="true"
                />
                <rect
                  className="tower-floor-accent"
                  x={FACADE_X + 8}
                  y={y + 10}
                  width="4"
                  height={FLOOR_H - 20}
                  rx="2"
                  aria-hidden="true"
                />
                <text className="tower-floor-no" x={FACADE_X + 22} y={y + 29}>
                  {floor.floorNo}F
                </text>
                <text className="tower-floor-name" x={FACADE_X + 62} y={y + 25}>
                  {floor.name}
                </text>
                <text className="tower-floor-count" x={FACADE_X + 62} y={y + 43}>
                  {countLabel(floor, mode)}
                </text>
                {Array.from({ length: windowCount }).map((_, i) => (
                  <rect
                    key={i}
                    className={`tower-window${i < floor.activeCount ? " on" : ""}`}
                    x={windowAreaX + i * (windowW + WINDOW_GAP)}
                    y={y + 18}
                    width={windowW}
                    height="24"
                    rx="3"
                    aria-hidden="true"
                  />
                ))}
                <rect
                  className="tower-floor-hit"
                  x={FACADE_X}
                  y={y}
                  width={FACADE_W}
                  height={FLOOR_H}
                  aria-hidden="true"
                />
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
