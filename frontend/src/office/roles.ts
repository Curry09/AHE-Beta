import type { Agent } from "../types";

// 角色 → 公司部门元信息：部门中文名、员工头像 emoji、强调色。
// 用户 agent = 用户部（体验反馈），开发者 agent = 开发部（直推 main）。
export const ROLE_META: Record<
  string,
  { dept: string; role: string; emoji: string; accent: string }
> = {
  user: { dept: "用户部", role: "用户", emoji: "🧑‍💻", accent: "#c2660f" },
  developer: { dept: "开发部", role: "开发者", emoji: "🛠️", accent: "#1560bd" },
};

export const DEPT_ORDER = ["user", "developer"];

export function roleMeta(role: string) {
  return ROLE_META[role] ?? { dept: role, role, emoji: "👤", accent: "#57606a" };
}

// 按部门（role）分组，保持稳定顺序：用户部在前、开发部在后。
export function groupByDept(agents: Agent[]): { role: string; agents: Agent[] }[] {
  return DEPT_ORDER.map((role) => ({
    role,
    agents: agents.filter((a) => a.role === role),
  })).filter((g) => g.agents.length > 0);
}
