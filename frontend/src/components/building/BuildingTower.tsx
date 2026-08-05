import type { KeyboardEvent } from "react";
import type { AgentRole } from "../../types";
import type { BuildingMode, FloorModel } from "./buildingModel";

const FACADE_X = 20;
const FACADE_Y = 86;
const FACADE_W = 310;
const FLOOR_H = 64;
const DEPTH_X = 72;
const DEPTH_Y = -44;
const LABEL_W = 160;
const WINDOW_GAP = 8;
const FACTORY_X = 470;
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
  const towerHelipad = points([
    [145, 70],
    [225, 70],
    [260, 49],
    [180, 49],
  ]);
  const factoryHelipad = points([
    [535, 251],
    [590, 251],
    [612, 238],
    [557, 238],
  ]);
  const campusTop = points([
    [8, 405],
    [570, 322],
    [722, 415],
    [150, 510],
  ]);
  const campusFront = points([
    [150, 510],
    [722, 415],
    [722, 434],
    [150, 531],
  ]);
  const campusLeft = points([
    [8, 405],
    [150, 510],
    [150, 531],
    [8, 425],
  ]);
  const campusBoundary = points([
    [22, 408],
    [566, 329],
    [705, 416],
    [153, 503],
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
          <defs>
            <pattern id="campus-grid" width="28" height="28" patternUnits="userSpaceOnUse">
              <path className="campus-grid-line" d="M 28 0 L 0 0 0 28" />
            </pattern>
          </defs>
          <ellipse
            className="tower-plaza"
            cx="365"
            cy={viewH - 25}
            rx="342"
            ry="22"
          />
          <polygon className="campus-base-front" points={campusFront} aria-hidden="true" />
          <polygon className="campus-base-left" points={campusLeft} aria-hidden="true" />
          <polygon className="campus-base-top" points={campusTop} aria-hidden="true" />
          <polygon
            className="campus-base-grid"
            points={campusTop}
            fill="url(#campus-grid)"
            aria-hidden="true"
          />
          <polygon className="campus-boundary" points={campusBoundary} aria-hidden="true" />
          <path
            className="campus-road"
            d="M 255 478 Q 385 442 510 390"
            aria-hidden="true"
          />
          <path
            className="campus-road-center"
            d="M 255 478 Q 385 442 510 390"
            aria-hidden="true"
          />
          <path
            className={`campus-flight-path${factory.moving ? " active" : ""}`}
            d="M 247 55 C 325 8 410 12 462 82 C 515 150 553 205 575 242"
            aria-hidden="true"
          />
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
            <polygon className="tower-helipad-pad" points={factoryHelipad} aria-hidden="true" />
            <text className="tower-helipad-mark factory-helipad-mark" x="574" y="249" aria-hidden="true">
              H
            </text>
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
          <g className="tower-helipad" aria-hidden="true">
            <polygon className="tower-helipad-pad" points={towerHelipad} />
            <text className="tower-helipad-mark" x="202" y="65">
              H
            </text>
          </g>

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
          <g
            className={`campus-aircraft${factory.moving ? " moving" : ""}`}
            transform="translate(247 55)"
            aria-hidden="true"
          >
            <g className="campus-aircraft-body">
              <path d="M 0 -10 L 4 -3 L 15 0 L 15 4 L 4 3 L 1 11 L -3 11 L -2 3 L -14 5 L -16 2 L -3 -2 L -3 -9 Z" />
            </g>
          </g>
        </svg>
      </div>
    </div>
  );
}
