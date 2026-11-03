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

export type SourceStatus = "loading" | "disconnected" | "unavailable" | "ready";

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
  status: "needs-human-conflict" | "needs-human" | "conflict" | "mergeable" | "unknown";
  needsHuman: boolean;
  conflict: boolean;
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
  stationSources: {
    pulls: SourceState;
    commits: SourceState;
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
  if (response === null) return { status: "loading", label: `Loading ${label}…` };
  if (!response.connected) return { status: "disconnected", label: `${label} disconnected` };
  return { status: "ready", label: `${label} connected` };
}

function stateSource(state: RunState | null): SourceState {
  return state === null
    ? { status: "loading", label: "Loading run state…" }
    : { status: "ready", label: "Run state ready" };
}

function hasLabel(labels: string[], label: string): boolean {
  return labels.includes(label);
}

function issueStage(issue: Issue): IssueCardModel["stage"] | null {
  const labels = issue.labels ?? [];
  if (hasLabel(labels, "ready")) return "ready";
  if (hasLabel(labels, "openagents")) return "openagents";
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

function pullStatus(pull: Pull, needsHuman: boolean, conflict: boolean): PullCardModel["status"] {
  if (needsHuman && conflict) return "needs-human-conflict";
  if (needsHuman) return "needs-human";
  if (conflict) return "conflict";
  if (pull.mergeable === true) return "mergeable";
  return "unknown";
}

function pullCard(pull: Pull): PullCardModel {
  const needsHuman = hasLabel(pull.labels ?? [], "needs-human");
  const conflict = pull.mergeable === false;
  return {
    pull,
    status: pullStatus(pull, needsHuman, conflict),
    needsHuman,
    conflict,
  };
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
  if (selectedRound !== "all") return `Round ${selectedRound}`;
  if (state === null) return "Connecting";
  if (state.round <= 0) return "Not running";
  return `Round ${state.round}/${state.total_rounds}`;
}

function selectedRoundSha(state: RunState | null, selectedRound: "all" | number): string | null {
  const roundShas = state?.round_shas ?? [];
  if (selectedRound !== "all") return roundShas[selectedRound - 1] ?? null;
  return roundShas.length > 0 ? roundShas[roundShas.length - 1] : null;
}

function inSelectedRound(issue: Issue, selectedRound: "all" | number): boolean {
  return selectedRound === "all" || roundOf(issue) === selectedRound;
}

function filteredPullSource(
  delivery: DeliveryResponse | null,
  issues: IssuesResponse | null,
  selectedRound: "all" | number,
): SourceState {
  const source = apiSource(delivery, "/api/delivery");
  if (source.status !== "ready" || selectedRound === "all") return source;
  if (issues === null) return { status: "loading", label: "Loading issue-to-round links…" };
  if (!issues.connected) {
    return { status: "unavailable", label: "Issue-to-round links unavailable" };
  }
  return source;
}

function filteredCommitSource(
  commits: CommitsResponse | null,
  state: RunState | null,
  selectedRound: "all" | number,
  roundSha: string | null,
): SourceState {
  const source = apiSource(commits, "/api/commits");
  if (source.status !== "ready" || selectedRound === "all") return source;
  if (state === null) return { status: "loading", label: "Loading round SHA…" };
  if (roundSha === null) {
    return { status: "unavailable", label: `Round ${selectedRound} is missing its SHA` };
  }
  return source;
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
    selectedRound === "all"
      ? allPullItems
      : issues?.connected
        ? allPullItems.filter((pull) =>
            pull.closes_issues.some((issueNumber) => selectedIssueNumbers.has(issueNumber)),
          )
        : [];
  const pulls = pullItems.map(pullCard).sort(comparePullCards);
  const needsHumanPulls = pulls.filter((pull) => pull.needsHuman);
  const conflictPulls = pulls.filter((pull) => pull.conflict);

  const roundShas = state?.round_shas ?? [];
  const shaForSelectedRound = selectedRoundSha(state, selectedRound);
  const allCommitItems = commits?.connected ? commits.commits : [];
  const commitItems =
    selectedRound === "all"
      ? allCommitItems
      : shaForSelectedRound === null
        ? []
        : allCommitItems.filter((commit) => isRoundAnchor(commit, [shaForSelectedRound]));
  const commitCards = commitItems.map((commit) => ({
    commit,
    roundAnchor: isRoundAnchor(commit, selectedRound === "all" ? roundShas : [shaForSelectedRound ?? ""]),
  }));
  const pullSource = filteredPullSource(delivery, issues, selectedRound);
  const commitSource = filteredCommitSource(commits, state, selectedRound, shaForSelectedRound);

  return {
    sources: {
      issues: apiSource(issues, "/api/issues"),
      delivery: apiSource(delivery, "/api/delivery"),
      commits: apiSource(commits, "/api/commits"),
      state: stateSource(state),
    },
    stationSources: {
      pulls: pullSource,
      commits: commitSource,
    },
    currentRound: currentRoundLabel(state, selectedRound),
    latestRoundSha: shaForSelectedRound,
    readyIssues,
    needsHumanIssues,
    pulls,
    needsHumanPulls,
    conflictPulls,
    kpis: {
      handoff:
        issues?.connected
          ? readyIssues.filter((issue) => issue.stage === "openagents").length
          : null,
      pulls: pullSource.status === "ready" ? pulls.length : null,
      needsHuman:
        !delivery?.connected || (selectedRound !== "all" && !issues?.connected)
          ? null
          : selectedRound === "all"
            ? delivery.needs_human
            : needsHumanPulls.length + needsHumanIssues.length,
      commits: commitSource.status === "ready" ? commitCards.length : null,
    },
    commits: commitCards,
  };
}
