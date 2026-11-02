import { describe, expect, it } from "vitest";
import type { Issue, IssueTimeline } from "../../types";
import { buildIssueTimelineView, groupIssueLabels } from "./issueTimelineModel";

const issue: Issue = {
  number: 7,
  title: "test",
  body: "",
  labels: ["ready", "from-architect", "P1", "round-1", "openagents", "needs-human", "bug"],
  state: "open",
  created_at: "2026-08-09T10:00:00Z",
  closed_at: null,
  url: "",
};

function state(overrides = {}) {
  return {
    labels: [],
    plane: "ready" as const,
    provenance: "from-architect" as const,
    priority: "P1",
    round: 1,
    handoff: false,
    delivery_active: true,
    blocked: false,
    terminal: null,
    conflicts: [],
    ...overrides,
  };
}

it("groups orthogonal labels instead of rendering one pile", () => {
  expect(groupIssueLabels(issue.labels).map((group) => [group.key, group.labels])).toEqual([
    ["plane", ["ready"]],
    ["source", ["from-architect"]],
    ["priority", ["P1"]],
    ["round", ["round-1"]],
    ["delivery", ["openagents", "needs-human"]],
    ["other", ["bug"]],
  ]);
});

describe("buildIssueTimelineView", () => {
  it("marks metadata-destroying transition as critical", () => {
    const timeline: IssueTimeline = {
      available: true,
      reason: null,
      complete: true,
      events: [],
      current: state({
        labels: ["needs-human"],
        plane: null,
        provenance: null,
        priority: null,
        round: null,
        delivery_active: false,
        blocked: true,
      }),
      historical: null,
      last_known: { plane: "ready", provenance: "from-architect", priority: "P1", round: 1 },
      anomalies: [
        {
          id: "blocking-destroyed-metadata:transition-1",
          code: "blocking-destroyed-metadata",
          severity: "critical",
          message: "metadata lost",
          transition_id: "transition-1",
          dimensions: ["plane", "provenance"],
        },
      ],
      transitions: [
        {
          id: "transition-1",
          created_at: "2026-08-09T10:02:00Z",
          actor: "designer",
          title: "标签完整性异常",
          added: ["needs-human"],
          removed: ["ready", "from-architect", "P1", "round-1"],
          before: state(),
          after: state({
            plane: null,
            provenance: null,
            priority: null,
            round: null,
            blocked: true,
          }),
          anomaly_ids: ["blocking-destroyed-metadata:transition-1"],
        },
      ],
    };

    const view = buildIssueTimelineView(issue, timeline);
    expect(view.transitions[0].severity).toBe("critical");
    expect(view.transitions[0].from).toContain("from-architect");
    expect(view.transitions[0].to).toBe("needs-human");
    expect(view.lastKnown.round).toBe(1);
  });

  it("fails visibly when timeline is unavailable", () => {
    const view = buildIssueTimelineView(issue, undefined);
    expect(view.available).toBe(false);
    expect(view.unavailableReason).toContain("未提供");
    expect(view.transitions).toEqual([]);
  });
});
