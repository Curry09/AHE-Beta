// 零依赖像素小人：12×14 像素矩阵 + 按 label hash 确定性上色（同一 agent 恒定同装扮）。
// 斯坦福 AI 小镇画风：俯视像素居民。不引任何外部图集。

// 精灵矩阵（每行 12 字符）。字符 → 调色板键：
//   H 头发 · S 皮肤 · E 眼睛 · B 上衣(hash 变色) · P 裤子 · O 鞋
export const SPRITE_ROWS = [
  "....HHHH....",
  "...HHHHHH...",
  "..HHHHHHHH..",
  "..HSSSSSSH..",
  "..SSESSESS..",
  "..SSSSSSSS..",
  "...BBBBBB...",
  "..SBBBBBBS..",
  "..SBBBBBBS..",
  "...BBBBBB...",
  "...PPPPPP...",
  "...PP..PP...",
  "...PP..PP...",
  "...OO..OO...",
];
export const SPRITE_W = 12;
export const SPRITE_H = SPRITE_ROWS.length; // 14

// 简单确定性字符串哈希（FNV-1a 变体），非加密，仅用于稳定选色。
export function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

const SKIN = ["#f6d3b0", "#e8b98c", "#c98a5e", "#a8663c", "#8a4f2d"];
const HAIR = ["#2b2119", "#4a2f1a", "#6b4423", "#0f0f10", "#8a6a3a", "#b5651d", "#5a3d7a"];
const PANTS = ["#3a4a63", "#43506b", "#4b4b52", "#2f3e2f", "#5a3b3b"];

export interface Skin {
  H: string;
  S: string;
  E: string;
  B: string;
  P: string;
  O: string;
}

// role 决定上衣色相基调：user 暖橙红系、developer 冷青蓝系；再按 hash 微扰，保证同角色可辨又各具个性。
export function skinFor(label: string, role: string): Skin {
  const h = hash(label);
  const base = role === "developer" ? 200 : role === "user" ? 20 : 280;
  const hue = (base + ((h >> 3) % 60) - 30 + 360) % 360;
  return {
    H: HAIR[h % HAIR.length],
    S: SKIN[(h >> 5) % SKIN.length],
    E: "#1b1b1b",
    B: `hsl(${hue} 62% 54%)`,
    P: PANTS[(h >> 7) % PANTS.length],
    O: "#33322f",
  };
}

// role → 名牌与角标配色（保留可辨识度而不破坏像素画风）。
export const ROLE_META: Record<string, { cn: string; plate: string; ink: string }> = {
  user: { cn: "居民·用户", plate: "#ffd9b0", ink: "#8a4a12" },
  developer: { cn: "工匠·开发者", plate: "#bfe3ff", ink: "#134a7a" },
};
