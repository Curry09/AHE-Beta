import type { Agent } from "../types";

// 小镇分区：全部用世界框的百分比坐标，随容器自适应缩放，免去手写缩放数学。
export interface Zone {
  key: string;
  name: string;
  sub: string;
  emoji: string;
  // 建筑外框
  x: number;
  y: number;
  w: number;
  h: number;
  // 居民落座区（建筑内的可站位子区域，相对世界的 %）
  padTop: number;
}

export const ZONES: Zone[] = [
  { key: "cafe", name: "用户广场·咖啡馆", sub: "居民在此使用 harness", emoji: "☕", x: 3, y: 52, w: 30, h: 42, padTop: 18 },
  { key: "harness", name: "Harness 中枢", sub: "被进化的 harness (main)", emoji: "🏭", x: 39, y: 16, w: 22, h: 52, padTop: 22 },
  { key: "workshop", name: "开发工坊", sub: "开发者领 issue 直推 main", emoji: "🔧", x: 67, y: 12, w: 30, h: 70, padTop: 30 },
  { key: "board", name: "Issue 公告板", sub: "Gitea open issues", emoji: "📋", x: 39, y: 74, w: 22, h: 18, padTop: 6 },
];

export const zoneByKey = (key: string): Zone | undefined => ZONES.find((z) => z.key === key);

// role → 所属分区。
function zoneForRole(role: string): string {
  if (role === "developer") return "workshop";
  return "cafe"; // user 及其它默认落在咖啡馆
}

export interface Placed {
  agent: Agent;
  x: number;
  y: number;
}

// 把 agent 铺在其分区内：按数量算列数，网格落位，避免重叠。返回世界 % 坐标。
export function placeAgents(agents: Agent[]): Placed[] {
  const byZone = new Map<string, Agent[]>();
  for (const a of agents) {
    const zk = zoneForRole(a.role);
    (byZone.get(zk) ?? byZone.set(zk, []).get(zk)!).push(a);
  }
  const out: Placed[] = [];
  for (const [zk, list] of byZone) {
    const z = zoneByKey(zk);
    if (!z) continue;
    const cols = Math.max(1, Math.min(4, Math.ceil(Math.sqrt(list.length))));
    const rows = Math.ceil(list.length / cols);
    const areaX = z.x + 3;
    const areaW = z.w - 6;
    const areaY = z.y + z.padTop;
    const areaH = z.h - z.padTop - 6;
    list.forEach((agent, i) => {
      const c = i % cols;
      const r = Math.floor(i / cols);
      const x = areaX + (areaW * (c + 0.5)) / cols;
      const y = areaY + (areaH * (r + 0.5)) / Math.max(1, rows);
      out.push({ agent, x, y });
    });
  }
  return out;
}
