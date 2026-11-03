import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { Agent, HistoryItem, SessionDetail, SessionProvenance } from "../../types";
import { AgentColumn } from "../AgentColumn";
import { SessionDetailView } from "./SessionDetail";
import { Charts } from "../Charts";

const result = vi.hoisted(() => ({ session: null as SessionDetail | null }));
vi.mock("../../hooks/useFetch", () => ({ useFetch: () => result.session }));

const origin: SessionProvenance = {
  contract_version: 1, run_id: "selected-run", round_no: 2, slot: 1,
  persona_id: "user-b", task_id: "orders", task_digest: "task-content-b",
  task_kind: "ordinary", interaction: "direct", harness_sha: "harness-round-two",
};
const item: HistoryItem = {
  kind: "user_session", round: 2, agent_id: "user-session-b", role: "user",
  label: "same visible persona", status: "completed", session_id: "session-b",
  turns: [], detail: null, log: [], started_at: "", archived_at: "",
  session_provenance: origin,
};
function detail() {
  return renderToStaticMarkup(<SessionDetailView item={item} onBack={() => {}} onSelect={() => {}} />);
}

describe("Spec-0073/T5 session attribution", () => {
  it("shows frozen task, persona, session, round and Harness when result is unavailable", () => {
    result.session = null;
    const html = detail();
    for (const text of ["orders", "user-b", "session-b", "task-content-b", "harness-round-two", "direct", "Round 2"]) {
      expect(html).toContain(text);
    }
  });
  it("refuses a previous session response during a selection change", () => {
    result.session = {
      session_id: "session-a", session_provenance: { ...origin, task_id: "pvlib", persona_id: "user-a" },
      created_at: "", persona: { identity: "old persona", level: "", domain: "", goal: "", speaking_style: "" },
      scenario: { description: "OLD SCENARIO" }, transcript: { turns: [{ role: "harness", content: "OLD RESPONSE" }] },
      feeling: { score: 4, reason: "OLD FEELING" }, issue_refs: [],
    };
    const html = detail();
    expect(html).toContain("orders");
    for (const text of ["pvlib", "user-a", "OLD SCENARIO", "OLD RESPONSE", "OLD FEELING"]) expect(html).not.toContain(text);
  });
  it("keeps two users of one task distinct on live and archived cards", () => {
    const agents: Agent[] = ["a", "b"].map((id) => ({
      agent_id: `user-session-${id}`, role: "user", label: "same visible persona",
      running: true, status: "working", round: 2, turns: [], detail: null, log: [],
      started_at: "", updated_at: "", meta: {
        identity: "same visible persona", level: "", domain: "", goal: "",
        session_provenance: { ...origin, persona_id: `user-${id}` },
      },
    }));
    const html = renderToStaticMarkup(<AgentColumn role="user" name="Users" agents={agents}
      history={[{ item, index: 0 }]} showDone selection={null} onSelect={() => {}} />);
    expect(html).toContain("orders · user-a");
    expect(html).toContain("orders · user-b");
    expect(html).toContain("session session-a");
    expect(html).toContain("session session-b");
    expect(html).toContain('title="harness-round-two"');
  });
  it("renders legacy sessions without inventing task provenance", () => {
    result.session = null;
    const html = renderToStaticMarkup(<SessionDetailView item={{ ...item, session_provenance: undefined }}
      onBack={() => {}} onSelect={() => {}} />);
    expect(html).not.toContain("Harness SHA");
    expect(html).not.toContain("task-content-b");
    expect(html).toContain("session-b");
  });
});

describe("Spec-0084/T1 missing experience", () => {
  it("does not replace a loaded unavailable rating with the archived score", () => {
    result.session = {
      session_id: "session-b", created_at: "", persona: { identity: "user", level: "", domain: "", goal: "", speaking_style: "" },
      scenario: { description: "task" }, transcript: { turns: [] }, feeling: null, issue_refs: [],
      feedback: {
        schema_version: 1,
        task_assessment: { status: "unknown", source: "reviewer", evidence_refs: [] },
        experience: { status: "unavailable", score: null, source: "terminal_review", reason: "gateway unavailable" },
        attribution: { status: "unknown", claims: [] }, opportunities: [],
      },
    };
    const html = renderToStaticMarkup(<SessionDetailView item={{ ...item, score: 3 }} onBack={() => {}} onSelect={() => {}} />);
    expect(html).toContain("Experience data missing (unavailable)");
    expect(html).toContain("gateway unavailable");
    expect(html).toContain("Source: terminal_review");
    expect(html).not.toContain("Experience 3");
    expect(html).not.toContain("3 / 4");
  });

  it("renders old null ratings without requiring the new feedback object", () => {
    result.session = {
      session_id: "session-b", created_at: "", persona: { identity: "user", level: "", domain: "", goal: "", speaking_style: "" },
      scenario: { description: "task" }, transcript: { turns: [] }, feeling: null, issue_refs: [],
    };
    expect(detail()).toContain("No valid self-assessment recorded");
  });

  it("shows missing sample counts separately for each input condition", () => {
    const html = renderToStaticMarkup(<Charts overview={{
      open_issue_count: 0, session_count: 5, feeling_trend: [], issue_curve: [],
      feedback_counts: {
        unavailable: { rated: 1, missing: 0, invalid: 1, unavailable: 0 },
        possible: { rated: 1, missing: 1, invalid: 0, unavailable: 1 },
      },
    }} />);
    expect(html).toContain("No follow-up input");
    expect(html).toContain("Follow-up input available");
    expect(html).toContain("Valid 1 · Not provided 0 · Invalid 1 · Unavailable 0");
    expect(html).toContain("Valid 1 · Not provided 1 · Invalid 0 · Unavailable 1");
    expect(html).not.toContain("NaN");
  });
});
