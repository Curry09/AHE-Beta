import type {
  Issue,
  IssueTimeline,
  IssueTimelineAnomaly,
  IssueTimelineState,
  IssueTimelineTransition,
} from "../../types";

export type LabelGroupKey =
  | "plane"
  | "source"
  | "priority"
  | "round"
  | "delivery"
  | "terminal"
  | "other";

export interface LabelGroup {
  key: LabelGroupKey;
  label: string;
  labels: string[];
}

export interface TransitionView {
  id: string;
  title: string;
  createdAt: string;
  actor: string;
  added: string[];
  removed: string[];
  from: string;
  to: string;
  severity: "normal" | "warning" | "critical";
}

export interface IssueTimelineViewModel {
  available: boolean;
  unavailableReason: string | null;
  complete: boolean;
  groups: LabelGroup[];
  transitions: TransitionView[];
  anomalies: IssueTimelineAnomaly[];
  current: IssueTimelineState | null;
  lastKnown: IssueTimeline["last_known"];
}

const GROUP_LABEL: Record<LabelGroupKey, string> = {
  plane: "Plane",
  source: "Source",
  priority: "Priority",
  round: "Round",
  delivery: "Delivery / blockers",
  terminal: "Terminal state",
  other: "Other",
};

const TERMINAL = new Set([
  "merged",
  "declined",
  "rejected",
  "needs-info",
  "gate-dropped",
  "superseded",
]);

export function groupIssueLabels(labels: string[]): LabelGroup[] {
  const grouped = new Map<LabelGroupKey, string[]>();
  for (const label of labels) {
    const key = groupOf(label);
    grouped.set(key, [...(grouped.get(key) ?? []), label]);
  }
  const order: LabelGroupKey[] = [
    "plane",
    "source",
    "priority",
    "round",
    "delivery",
    "terminal",
    "other",
  ];
  return order
    .filter((key) => (grouped.get(key)?.length ?? 0) > 0)
    .map((key) => ({ key, label: GROUP_LABEL[key], labels: grouped.get(key) ?? [] }));
}

export function buildIssueTimelineView(
  issue: Issue,
  timeline: IssueTimeline | null | undefined,
): IssueTimelineViewModel {
  const anomalyByTransition = new Map<string, IssueTimelineAnomaly[]>();
  for (const anomaly of timeline?.anomalies ?? []) {
    if (!anomaly.transition_id) continue;
    anomalyByTransition.set(anomaly.transition_id, [
      ...(anomalyByTransition.get(anomaly.transition_id) ?? []),
      anomaly,
    ]);
  }
  return {
    available: timeline?.available ?? false,
    unavailableReason: timeline?.reason ?? "Current backend does not provide a label timeline",
    complete: timeline?.complete ?? false,
    groups: groupIssueLabels(issue.labels ?? []),
    transitions: (timeline?.transitions ?? []).map((transition) =>
      transitionView(transition, anomalyByTransition.get(transition.id) ?? []),
    ),
    anomalies: timeline?.anomalies ?? [],
    current: timeline?.current ?? null,
    lastKnown: timeline?.last_known ?? {},
  };
}

function groupOf(label: string): LabelGroupKey {
  if (["report", "proposal", "ready"].includes(label)) return "plane";
  if (label.startsWith("from-")) return "source";
  if (/^P[0-3]$/.test(label)) return "priority";
  if (/^round-\d+$/.test(label)) return "round";
  if (["openagents", "needs-human"].includes(label)) return "delivery";
  if (TERMINAL.has(label)) return "terminal";
  return "other";
}

function transitionView(
  transition: IssueTimelineTransition,
  anomalies: IssueTimelineAnomaly[],
): TransitionView {
  const severity = anomalies.some((item) => item.severity === "critical")
    ? "critical"
    : anomalies.length > 0
      ? "warning"
      : "normal";
  return {
    id: transition.id,
    title: transition.title,
    createdAt: transition.created_at,
    actor: transition.actor,
    added: transition.added,
    removed: transition.removed,
    from: stateSummary(transition.before),
    to: stateSummary(transition.after),
    severity,
  };
}

function stateSummary(state: IssueTimelineState): string {
  const values = [
    state.plane,
    state.provenance,
    state.priority,
    state.round == null ? null : `round-${state.round}`,
    state.blocked ? "needs-human" : null,
    state.terminal,
  ].filter(Boolean);
  return values.length > 0 ? values.join(" · ") : "No dimension status";
}
