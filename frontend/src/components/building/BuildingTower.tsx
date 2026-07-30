import type { KeyboardEvent } from "react";
import type { AgentRole } from "../../types";
import type { BuildingMode, FloorModel } from "./buildingModel";

const FACADE_X = 110;
const FACADE_Y = 86;
const FACADE_W = 310;
const FLOOR_H = 64;
const DEPTH_X = 72;
const DEPTH_Y = -44;
const LABEL_W = 160;
const WINDOW_GAP = 8;

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

export function BuildingTower(props: {
  floors: FloorModel[];
  mode: BuildingMode;
  selectedFloor: AgentRole;
  onSelectFloor: (role: AgentRole) => void;
}) {
  const { floors, mode, selectedFloor, onSelectFloor } = props;
  const facadeH = floors.length * FLOOR_H;
  const viewW = FACADE_X + FACADE_W + DEPTH_X + 70;
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
            cx={FACADE_X + FACADE_W / 2 + DEPTH_X / 2}
            cy={FACADE_Y + facadeH + 42}
            rx={FACADE_W / 2 + DEPTH_X + 50}
            ry="32"
          />
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
