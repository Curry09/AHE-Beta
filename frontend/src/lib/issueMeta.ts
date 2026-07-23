// Spec-0025/T8：issue 的 kind / triage 状态 / 优先级 / 轮号 派生（前端展示用）。
// 与后端 backend/auto_designer/designer/issue_schema.py 的标签投影同构：优先用后端已附的字段
// （T7），缺省（老后端只给 labels）时按 labels 客户端兜底——保证「字段缺省退化不崩」。

import type { Issue, TriageStatus } from "../types";

const USER_KINDS = ["bug", "feature", "chore", "document"];
const PRIORITIES = ["P0", "P1", "P2", "P3"];
const RFC_LABEL = "RFC";
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
