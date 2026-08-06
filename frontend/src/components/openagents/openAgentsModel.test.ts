import { describe, expect, it } from "vitest";
import type {
  Commit,
  CommitsResponse,
  DeliveryResponse,
  Issue,
  IssuesResponse,
  Pull,
  RunState,
} from "../../types";
import { buildOpenAgentsSnapshot } from "./openAgentsModel";

function issue(number: number, labels: string[]): Issue {
  return {
    number,
    title: `issue ${number}`,
    body: "",
    labels,
    state: "open",
    created_at: "2026-08-01T00:00:00Z",
    closed_at: null,
    url: `https://gitea.example/issues/${number}`,
  };
}

function pull(params: {
  number: number;
  labels?: string[];
  mergeable?: boolean | null;
  closesIssues?: number[];
}): Pull {
  return {
    number: params.number,
    title: `pull ${params.number}`,
    state: "open",
    head_branch: `openagents/issue-${params.number}`,
    mergeable: params.mergeable ?? true,
    labels: params.labels ?? [],
    closes_issues: params.closesIssues ?? [],
    url: `https://gitea.example/pulls/${params.number}`,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
  };
}

function commit(sha: string): Commit {
  return {
    sha,
    short_sha: sha.slice(0, 7),
    message: "test commit",
    author: "tester",
    date: "2026-08-01T00:00:00Z",
    url: `https://gitea.example/commit/${sha}`,
    tags: [],
  };
}

const EMPTY_DELIVERY: DeliveryResponse = {
  connected: true,
  pulls: [],
  needs_human: 0,
};

const EMPTY_COMMITS: CommitsResponse = {
  connected: true,
  commits_url: null,
  commits: [],
};

const EMPTY_STATE: RunState = {
  running: false,
  round: 0,
  total_rounds: 0,
  round_shas: [],
  started_at: null,
  updated_at: null,
};

describe("buildOpenAgentsSnapshot", () => {
  it("counts only pre-intake openagents issues as handoff", () => {
    const issues: IssuesResponse = {
      connected: true,
      board_url: null,
      issues: [
        issue(1, ["openagents", "round-1"]),
        issue(2, ["openagents", "ready", "round-1"]),
        issue(3, ["ready", "round-1"]),
      ],
    };

    const snapshot = buildOpenAgentsSnapshot({
      issues,
      delivery: EMPTY_DELIVERY,
      commits: EMPTY_COMMITS,
      state: EMPTY_STATE,
    });

    expect(snapshot.readyIssues.map((item) => item.stage)).toEqual([
      "openagents",
      "ready",
      "ready",
    ]);
    expect(snapshot.kpis.handoff).toBe(1);
  });

  it("keeps needs-human and conflict as overlapping PR dimensions", () => {
    const delivery: DeliveryResponse = {
      connected: true,
      pulls: [pull({ number: 7, labels: ["needs-human"], mergeable: false })],
      needs_human: 1,
    };

    const snapshot = buildOpenAgentsSnapshot({
      issues: { connected: true, board_url: null, issues: [] },
      delivery,
      commits: EMPTY_COMMITS,
      state: EMPTY_STATE,
    });

    expect(snapshot.pulls[0].status).toBe("needs-human-conflict");
    expect(snapshot.needsHumanPulls.map((item) => item.pull.number)).toEqual([7]);
    expect(snapshot.conflictPulls.map((item) => item.pull.number)).toEqual([7]);
  });

  it("does not leak all PRs when round issue links are unavailable", () => {
    const snapshot = buildOpenAgentsSnapshot({
      issues: { connected: false, board_url: null, issues: [] },
      delivery: {
        connected: true,
        pulls: [pull({ number: 8, closesIssues: [1] })],
        needs_human: 0,
      },
      commits: EMPTY_COMMITS,
      state: EMPTY_STATE,
      round: 1,
    });

    expect(snapshot.pulls).toEqual([]);
    expect(snapshot.stationSources.pulls.status).toBe("unavailable");
    expect(snapshot.kpis.pulls).toBeNull();
  });

  it("does not leak commits when the selected round has no SHA", () => {
    const snapshot = buildOpenAgentsSnapshot({
      issues: { connected: true, board_url: null, issues: [] },
      delivery: EMPTY_DELIVERY,
      commits: {
        connected: true,
        commits_url: null,
        commits: [commit("abcdef0123456789")],
      },
      state: EMPTY_STATE,
      round: 1,
    });

    expect(snapshot.commits).toEqual([]);
    expect(snapshot.stationSources.commits.status).toBe("unavailable");
    expect(snapshot.kpis.commits).toBeNull();
  });
});
