// Spec-0025/T8 + 0029/T10: derive issue plane / provenance / kind / priority / round for frontend display.
// Mirrors the backend/ahe_beta/demand/issue_schema.py label projection: prefer fields supplied by the backend,
// and fall back to client-side label inference when absent (older backends only provide labels), ensuring graceful degradation.

import type { Issue, Plane, Provenance, TriageStatus } from "../types";

const USER_KINDS = ["bug", "feature", "chore", "document"];
const PRIORITIES = ["P0", "P1", "P2", "P3"];
const RFC_LABEL = "RFC";
// Spec-0029 terminal labels (old and new): matching issues belong to no plane.
const TERMINAL = ["declined", "merged", "rejected", "needs-info", "gate-dropped", "superseded"];
// Triage status precedence: the most decisive status wins (aligned with backend triage_status).
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

// Spec-0029: three-plane projection (mirrors backend issue_schema.plane). Prefer server fields; fall back to labels:
// New plane labels take precedence → terminal null → legacy label mapping (needs-triage→report, triaged|RFC→ready, divergent→proposal).
export function planeOf(issue: Issue): Plane | null {
  if (issue.plane !== undefined) return issue.plane ?? null;
  const ls = new Set(issue.labels ?? []);
  // Spec-0032: openagents (Owner admission handoff token) shares the READY plane with ready, before vigil applies ready.
  if (ls.has("ready") || ls.has("openagents")) return "ready";
  if (ls.has("proposal")) return "proposal";
  if (ls.has("report")) return "report";
  if (TERMINAL.some((t) => ls.has(t))) return null;
  if (ls.has("divergent")) return "proposal";
  if (ls.has("triaged") || ls.has(RFC_LABEL)) return "ready";
  if (ls.has("needs-triage")) return "report";
  return null;
}

// Spec-0029: proposal provenance (from-triage/from-architect/from-divergent).
export function provenanceOf(issue: Issue): Provenance | null {
  if (issue.provenance !== undefined) return issue.provenance ?? null;
  const ls = issue.labels ?? [];
  for (const p of ["from-triage", "from-architect", "from-divergent"] as Provenance[]) {
    if (ls.includes(p)) return p;
  }
  return null;
}

// Detect merged/declined terminal states for closed-issue badges.
export function terminalOf(issue: Issue): string | null {
  const ls = issue.labels ?? [];
  return TERMINAL.find((t) => ls.includes(t)) ?? null;
}

// Executable backlog (claimable by dev / observation counts): open and triaged or RFC, excluding needs-triage/superseded/rejected issues.
export function isBacklog(issue: Issue): boolean {
  if (issue.state !== "open") return false;
  const ls = new Set(issue.labels ?? []);
  if (!(ls.has("triaged") || ls.has(RFC_LABEL))) return false;
  return !["needs-triage", "superseded", "rejected", "needs-info"].some((x) => ls.has(x));
}

// Backlog age: days since creation, including carryover across rounds. Invalid timestamps → null.
export function ageDays(createdAt: string | null | undefined): number | null {
  if (!createdAt) return null;
  const t = new Date(createdAt).getTime();
  if (Number.isNaN(t)) return null;
  return Math.max(0, Math.floor((Date.now() - t) / 86_400_000));
}
