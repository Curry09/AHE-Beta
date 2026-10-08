// Spec-0025/T8 + 0029/T10：issue 的 plane / provenance / kind / 优先级 / 轮号 派生（前端展示用）。
// 与后端 backend/auto_designer/demand/issue_schema.py 的标签投影同构：优先用后端已附的字段，
// 缺省（老后端只给 labels）时按 labels 客户端兜底——保证「字段缺省退化不崩」。

import type { Issue, Plane, Provenance, TriageStatus } from "../types";

const USER_KINDS = ["bug", "feature", "chore", "document"];
const PRIORITIES = ["P0", "P1", "P2", "P3"];
const RFC_LABEL = "RFC";
// Spec-0029 终态标签（新老并集）：命中即不在任何平面。
const TERMINAL = ["declined", "merged", "rejected", "needs-info", "gate-dropped", "superseded"];
// triage 状态优先级：越决定性者胜（对齐后端 triage_status）。
const STATUS_ORDER: TriageStatus[] = [
  "rejected",
  "needs-info",
  "superseded",
  "triaged",
  "needs-triage",
];

export function issueKind(issue: Issue): string {
  if (issue.kind) return issue.kind;
  const ls = issue.labels ?? [];
  if (ls.includes(RFC_LABEL)) return "rfc";
  return USER_KINDS.find((k) => ls.includes(k)) ?? "bug";
}

export function triageStatus(issue: Issue): TriageStatus | null {
  if (issue.triage_status) return issue.triage_status;
  const ls = issue.labels ?? [];
  return STATUS_ORDER.find((s) => ls.includes(s)) ?? null;
}

export function priorityOf(issue: Issue): string | null {
  if (issue.priority) return issue.priority;
  return PRIORITIES.find((p) => (issue.labels ?? []).includes(p)) ?? null;
}

export function roundOf(issue: Issue): number | null {
  if (issue.round != null) return issue.round;
  for (const l of issue.labels ?? []) {
    const m = /^round-(\d+)$/.exec(l);
    if (m) return Number(m[1]);
  }
  return null;
}

export function isRfc(issue: Issue): boolean {
  return issueKind(issue) === "rfc";
}

// Spec-0029：三平面投影（与后端 issue_schema.plane 同构）。优先服务端字段，缺省按 labels 兜底：
// 新平面标签优先 → 终态 null → 旧标签映射（needs-triage→report、triaged|RFC→ready、divergent→proposal）。
export function planeOf(issue: Issue): Plane | null {
  if (issue.plane !== undefined) return issue.plane ?? null;
  const ls = new Set(issue.labels ?? []);
  // Spec-0032：openagents（Owner 准入交接令牌）与 ready 同属 READY 平面（vigil 盖 ready 前的窗口）。
  if (ls.has("ready") || ls.has("openagents")) return "ready";
  if (ls.has("proposal")) return "proposal";
  if (ls.has("report")) return "report";
  if (TERMINAL.some((t) => ls.has(t))) return null;
  if (ls.has("divergent")) return "proposal";
  if (ls.has("triaged") || ls.has(RFC_LABEL)) return "ready";
  if (ls.has("needs-triage")) return "report";
  return null;
}

// Spec-0029：提案来源（from-triage/from-synthesize/from-divergent）。
export function provenanceOf(issue: Issue): Provenance | null {
  if (issue.provenance !== undefined) return issue.provenance ?? null;
  const ls = issue.labels ?? [];
  for (const p of ["from-triage", "from-synthesize", "from-divergent"] as Provenance[]) {
    if (ls.includes(p)) return p;
  }
  return null;
}

// merged/declined 终态判定（已关闭票的徽标用）。
export function terminalOf(issue: Issue): string | null {
  const ls = issue.labels ?? [];
  return TERMINAL.find((t) => ls.includes(t)) ?? null;
}

// 可执行 backlog（dev 可领 / 观测计数口径）：open 且 triaged 或 RFC，且未被 needs-triage/取代/驳回排除。
export function isBacklog(issue: Issue): boolean {
  if (issue.state !== "open") return false;
  const ls = new Set(issue.labels ?? []);
  if (!(ls.has("triaged") || ls.has(RFC_LABEL))) return false;
  return !["needs-triage", "superseded", "rejected", "needs-info"].some((x) => ls.has(x));
}

// 积压龄：自创建至今的天数（backlog 项标龄用，含跨轮积压的直观信号）。无有效时间 → null。
export function ageDays(createdAt: string | null | undefined): number | null {
  if (!createdAt) return null;
  const t = new Date(createdAt).getTime();
  if (Number.isNaN(t)) return null;
  return Math.max(0, Math.floor((Date.now() - t) / 86_400_000));
}
