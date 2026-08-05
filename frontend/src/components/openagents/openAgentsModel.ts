import { ageDays, issueKind, planeOf, priorityOf, roundOf } from "../../lib/issueMeta";
import type {
  Commit,
  CommitsResponse,
  DeliveryResponse,
  Issue,
  IssuesResponse,
  Pull,
  RunState,
} from "../../types";

export type SourceStatus = "loading" | "disconnected" | "ready";

export interface SourceState {
  status: SourceStatus;
  label: string;
}

export interface IssueCardModel {
  issue: Issue;
  kind: string;
  priority: string | null;
  round: number | null;
  age: number | null;
  stage: "openagents" | "ready" | "ready-plane";
}

export interface PullCardModel {
  pull: Pull;
  status: "needs-human" | "conflict" | "mergeable" | "unknown";
}

export interface CommitCardModel {
  commit: Commit;
  roundAnchor: boolean;
}

export interface OpenAgentsSnapshot {
  sources: {
    issues: SourceState;
    delivery: SourceState;
    commits: SourceState;
    state: SourceState;
  };
  currentRound: string;
  latestRoundSha: string | null;
  readyIssues: IssueCardModel[];
  needsHumanIssues: IssueCardModel[];
  pulls: PullCardModel[];
  needsHumanPulls: PullCardModel[];
  conflictPulls: PullCardModel[];
  commits: CommitCardModel[];
  kpis: {
    handoff: number | null;
    pulls: number | null;
    needsHuman: number | null;
    commits: number | null;
  };
}

function apiSource<T extends { connected: boolean }>(response: T | null, label: string): SourceState {
  if (response === null) return { status: "loading", label: `读取 ${label}…` };
  if (!response.connected) return { status: "disconnected", label: `${label} 未连接` };
  return { status: "ready", label: `${label} connected` };
}

function stateSource(state: RunState | null): SourceState {
  return state === null
    ? { status: "loading", label: "读取 run state…" }
    : { status: "ready", label: "Run state ready" };
}

function hasLabel(labels: string[], label: string): boolean {
  return labels.includes(label);
}

function issueStage(issue: Issue): IssueCardModel["stage"] | null {
  const labels = issue.labels ?? [];
  if (hasLabel(labels, "openagents")) return "openagents";
  if (hasLabel(labels, "ready")) return "ready";
  return planeOf(issue) === "ready" ? "ready-plane" : null;
}

function issueCard(issue: Issue): IssueCardModel {
  const stage = issueStage(issue) ?? "ready-plane";
  return {
    issue,
    kind: issueKind(issue),
    priority: priorityOf(issue),
    round: roundOf(issue),
    age: ageDays(issue.created_at),
    stage,
  };
}

const PRIORITY_RANK: Record<string, number> = { P0: 0, P1: 1, P2: 2, P3: 3 };
const STAGE_RANK: Record<IssueCardModel["stage"], number> = {
  openagents: 0,
  ready: 1,
  "ready-plane": 2,
};

function compareIssueCards(a: IssueCardModel, b: IssueCardModel): number {
  const stage = STAGE_RANK[a.stage] - STAGE_RANK[b.stage];
  if (stage !== 0) return stage;
  const ap = a.priority ? PRIORITY_RANK[a.priority] ?? 9 : 9;
  const bp = b.priority ? PRIORITY_RANK[b.priority] ?? 9 : 9;
  if (ap !== bp) return ap - bp;
  return b.issue.number - a.issue.number;
}

function pullStatus(pull: Pull): PullCardModel["status"] {
  if (hasLabel(pull.labels ?? [], "needs-human")) return "needs-human";
  if (pull.mergeable === false) return "conflict";
  if (pull.mergeable === true) return "mergeable";
  return "unknown";
}

function pullCard(pull: Pull): PullCardModel {
  return { pull, status: pullStatus(pull) };
}

function comparePullCards(a: PullCardModel, b: PullCardModel): number {
  const at = new Date(a.pull.updated_at).getTime();
  const bt = new Date(b.pull.updated_at).getTime();
  if (!Number.isNaN(at) && !Number.isNaN(bt) && at !== bt) return bt - at;
  return b.pull.number - a.pull.number;
}

function isRoundAnchor(commit: Commit, roundShas: string[]): boolean {
  return roundShas.some(
    (sha) =>
      commit.sha.startsWith(sha) ||
      sha.startsWith(commit.sha) ||
      commit.short_sha.startsWith(sha) ||
      sha.startsWith(commit.short_sha),
  );
}

function currentRoundLabel(state: RunState | null, selectedRound: "all" | number): string {
  if (selectedRound !== "all") return `第 ${selectedRound} 轮`;
  if (state === null) return "连接中";
  if (state.round <= 0) return "未运行";
  return `第 ${state.round}/${state.total_rounds} 轮`;
}

function selectedRoundSha(state: RunState | null, selectedRound: "all" | number): string | null {
  const roundShas = state?.round_shas ?? [];
  if (selectedRound !== "all") return roundShas[selectedRound - 1] ?? null;
  return roundShas.length > 0 ? roundShas[roundShas.length - 1] : null;
}

function inSelectedRound(issue: Issue, selectedRound: "all" | number): boolean {
  return selectedRound === "all" || roundOf(issue) === selectedRound;
}

export function buildOpenAgentsSnapshot(params: {
  issues: IssuesResponse | null;
  delivery: DeliveryResponse | null;
  commits: CommitsResponse | null;
  state: RunState | null;
  round?: "all" | number;
}): OpenAgentsSnapshot {
  const { issues, delivery, commits, state } = params;
  const selectedRound = params.round ?? "all";
  const allIssueItems = issues?.connected ? issues.issues : [];
  const issueItems = allIssueItems.filter((issue) => inSelectedRound(issue, selectedRound));
  const selectedIssueNumbers = new Set(issueItems.map((issue) => issue.number));
  const readyIssues = issueItems
    .filter((issue) => issue.state === "open" && issueStage(issue) !== null)
    .map(issueCard)
    .sort(compareIssueCards);
  const needsHumanIssues = issueItems
    .filter((issue) => issue.state === "open" && hasLabel(issue.labels ?? [], "needs-human"))
    .map(issueCard)
    .sort(compareIssueCards);

  const allPullItems = delivery?.connected ? delivery.pulls : [];
  const pullItems =
    selectedRound === "all" || !issues?.connected
      ? allPullItems
      : allPullItems.filter((pull) =>
          pull.closes_issues.some((issueNumber) => selectedIssueNumbers.has(issueNumber)),
        );
  const pulls = pullItems.map(pullCard).sort(comparePullCards);
  const needsHumanPulls = pulls.filter((pull) => pull.status === "needs-human");
  const conflictPulls = pulls.filter((pull) => pull.status === "conflict");

  const roundShas = state?.round_shas ?? [];
  const shaForSelectedRound = selectedRoundSha(state, selectedRound);
  const allCommitItems = commits?.connected ? commits.commits : [];
  const commitItems =
    selectedRound === "all" || shaForSelectedRound === null
      ? allCommitItems
      : allCommitItems.filter((commit) => isRoundAnchor(commit, [shaForSelectedRound]));
  const commitCards = commitItems.map((commit) => ({
    commit,
    roundAnchor: isRoundAnchor(commit, selectedRound === "all" ? roundShas : [shaForSelectedRound ?? ""]),
  }));

  return {
    sources: {
      issues: apiSource(issues, "/api/issues"),
      delivery: apiSource(delivery, "/api/delivery"),
      commits: apiSource(commits, "/api/commits"),
      state: stateSource(state),
    },
    currentRound: currentRoundLabel(state, selectedRound),
    latestRoundSha: shaForSelectedRound,
    readyIssues,
    needsHumanIssues,
    pulls,
    needsHumanPulls,
    conflictPulls,
    kpis: {
      handoff: issues === null ? null : readyIssues.length,
      pulls: delivery === null ? null : pulls.length,
      needsHuman:
        delivery === null
          ? null
          : selectedRound === "all"
            ? delivery.needs_human
            : needsHumanPulls.length + needsHumanIssues.length,
      commits: commits === null ? null : commitCards.length,
    },
    commits: commitCards,
  };
}
