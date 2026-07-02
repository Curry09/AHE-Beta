import type { Zone } from "./layout";

// 一栋像素建筑：俯视外墙 + 顶部招牌（emoji + 名称）+ 可选角标计数。点击可触发面板（如公告板→issues）。
export function Building({
  zone,
  count,
  onClick,
}: {
  zone: Zone;
  count?: number;
  onClick?: () => void;
}) {
  const clickable = !!onClick;
  return (
    <div
      className={`building${clickable ? " clickable" : ""}`}
      style={{ left: `${zone.x}%`, top: `${zone.y}%`, width: `${zone.w}%`, height: `${zone.h}%` }}
      onClick={onClick}
      role={clickable ? "button" : undefined}
    >
      <div className="building-sign">
        <span className="building-emoji">{zone.emoji}</span>
        <span className="building-name">{zone.name}</span>
        {count != null && <span className="building-count">{count}</span>}
      </div>
      <div className="building-sub">{zone.sub}</div>
    </div>
  );
}
