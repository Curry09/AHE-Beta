import { useMemo } from "react";
import type { Agent } from "../types";
import { health } from "../lib/agentHealth";
import { SPRITE_ROWS, SPRITE_W, SPRITE_H, skinFor, type Skin } from "./pixel";

// 把精灵矩阵编译成一组 <rect>（每个非空像素一格），viewBox 为像素网格，crispEdges 保持硬边。
function spriteRects(skin: Skin) {
  const rects: JSX.Element[] = [];
  for (let y = 0; y < SPRITE_ROWS.length; y++) {
    const row = SPRITE_ROWS[y];
    for (let x = 0; x < row.length; x++) {
      const ch = row[x] as keyof Skin | ".";
      if (ch === ".") continue;
      rects.push(<rect key={`${x}-${y}`} x={x} y={y} width={1} height={1} fill={skin[ch]} />);
    }
  }
  return rects;
}

// 纯精灵（无定位/交互），供地图小人与花名册头像共用。
export function Sprite({ label, role, size = 48 }: { label: string; role: string; size?: number }) {
  const skin = useMemo(() => skinFor(label, role), [label, role]);
  const rects = useMemo(() => spriteRects(skin), [skin]);
  return (
    <svg
      className="sprite"
      width={(size * SPRITE_W) / SPRITE_H}
      height={size}
      viewBox={`0 0 ${SPRITE_W} ${SPRITE_H}`}
      shapeRendering="crispEdges"
      aria-hidden
    >
      {rects}
    </svg>
  );
}

// 地图上的一名居民：绝对定位 + 健康态动画 + 名牌 + 活动气泡；点击选中。
export function Character({
  agent,
  now,
  x,
  y,
  selected,
  showBubble,
  onSelect,
}: {
  agent: Agent;
  now: number;
  x: number; // 世界 % 坐标
  y: number;
  selected: boolean;
  showBubble: boolean;
  onSelect: (id: string) => void;
}) {
  const h = health(agent, now);
  const bubble = showBubble && h.cls !== "idle" ? agent.status : "";
  return (
    <button
      type="button"
      className={`resident anim-${h.cls}${selected ? " selected" : ""}`}
      style={{ left: `${x}%`, top: `${y}%` }}
      onClick={() => onSelect(agent.agent_id)}
      title={`${agent.label} · ${agent.status}`}
    >
      {bubble && <span className={`bubble-tag ${h.cls}`}>{bubble}</span>}
      <span className="sprite-holder">
        <Sprite label={agent.label} role={agent.role} size={46} />
      </span>
      <span className="nameplate">{agent.label}</span>
    </button>
  );
}
