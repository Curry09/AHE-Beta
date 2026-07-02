// 确定性 emoji 头像：hash(label) 定脸（同一 agent 恒定同脸），role 定角标。零依赖。

// 一组表情各异的脸；数量取质数附近，减少 label 长度规律撞脸。
const FACES = [
  "🧑", "👩", "🧔", "👨", "👵", "🧓", "👳", "🧕",
  "👲", "🧑‍🦰", "👩‍🦱", "🧑‍🦳", "👱", "🕵️", "🦸", "🧙",
  "🧑‍🚀", "🧑‍🔬", "🧑‍🎓", "🧑‍🏫", "🧑‍💼",
];

// 简单确定性字符串哈希（FNV-1a 变体），非加密用途，仅用于稳定选脸。
function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

// role 角标：用户叠 🙋、开发者叠 🛠️，其余留空。
function badgeFor(role: string): string {
  if (role === "user") return "🙋";
  if (role === "developer") return "🛠️";
  return "";
}

export function avatarFor(label: string, role: string): { face: string; badge: string } {
  return { face: FACES[hash(label) % FACES.length], badge: badgeFor(role) };
}
