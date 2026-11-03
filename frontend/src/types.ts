// Data contract: fields match responses from backend/ahe_beta/web/api.py one-to-one; update both sides together.

export type AgentRole = "user" | "triager" | "divergent" | "architect" | "owner" | "developer";
export type ViewMode = "dashboard" | "building" | "openagents";

// Spec-0029: three-plane projection and proposal provenance (backend /api/issues fields; issueMeta infers from labels for older backends).
export type Plane = "report" | "proposal" | "ready";
export type Provenance = "from-triage" | "from-architect" | "from-divergent";

// Spec-0026/T1: optional persona summary on user agent activity slots (read-only display; defaults to null).
export interface PersonaMeta {
  identity: string;
  level: string;
  domain: string;
  goal: string;
  session_provenance?: SessionProvenance | null;
  session_id?: string | null;
}

export interface Turn {
  role: "user" | "harness";
  content: string;
  // Harness turns only: inner iteration stream for this turn (model messages / tool calls / results). content is the final answer for the user,
  // while steps contains the full inner process, visible when expanded in the observation view. Absent means none (old data / no process).
  steps?: LogEntry[];
}

// Process stream entries: status (state changes) / assistant (model messages) / tool (tool calls) / tool_result / tool_error
// Optional t: dev/architect live logs include timestamps; harness inner steps do not.
export interface LogEntry {
  t?: string;
  kind: string;
  text: string;
}

// Frozen identity shared by session results, usage, live observations and evidence.
export interface SessionProvenance {
  contract_version: number;
  run_id: string;
  round_no: number;
  slot: number;
  persona_id: string;
  task_id: string;
  task_digest: string;
  task_kind: string;
  interaction: string;
  harness_sha: string;
}

export interface Agent {
  agent_id: string;
  role: AgentRole;
  label: string;
  running: boolean;
  status: string;
  round: number | null;
  meta?: PersonaMeta | null; // Spec-0026: user agents include a persona summary; other roles / older backends use null.
  turns: Turn[];
  detail: string | null;
  log: LogEntry[];
  started_at: string;
  updated_at: string;
}

export interface AgentsResponse {
  agents: Agent[];
}

export interface UsageTotals {
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  cached_input_tokens: number;
  total_tokens: number;
}

export interface UsageGroup extends UsageTotals {
  event_count: number;
  unavailable_count: number;
}

export interface UsageSummary extends UsageTotals {
  event_count: number;
  unavailable_count: number;
  by_role: Record<string, UsageGroup>;
  by_agent: Record<string, UsageGroup>;
  by_session: Record<string, UsageGroup>;
  by_instance: Record<string, UsageGroup>;
  by_interaction: Record<string, UsageGroup>;
}

export interface UsageEvent {
  timestamp: string;
  session_id: string | null;
  instance_id: string | null;
  interaction_id: string | null;
  turn_no: number | null;
  agent_id: string | null;
  role: string | null;
  model: string | null;
  operation: string | null;
  usage_source: "reported" | "estimated" | "unavailable";
  input_tokens: number | null;
  output_tokens: number | null;
  reasoning_tokens: number | null;
  cached_input_tokens: number | null;
  total_tokens: number | null;
}

export interface UsageEventsResponse { events: UsageEvent[] }

// Runtime state of the entire run (data/live/run.json)
export interface RunState {
  running: boolean;
  round: number;
  total_rounds: number;
  round_shas: string[];
  started_at: string | null;
  updated_at: string | null;
}

// Completed work items archived by round (data/live/history.json)
export type HistoryKind =
  | "user_session"
  | "triager_run"
  | "architect_run"
  | "divergent_run"
  | "owner_run"
  | "dev_run";

export interface HistoryItem {
  kind: HistoryKind;
  round: number;
  agent_id: string;
  role: AgentRole;
  label: string;
  status: string;
  turns: Turn[];
  detail: string | null;
  log: LogEntry[];
  started_at: string | null;
  archived_at: string;
  // user_session
  session_id?: string | null;
  session_provenance?: SessionProvenance | null;
  score?: number | null;
  end_reason?: string;
  // dev_run
  issue_number?: number | null;
  tag?: string | null;
  committed?: boolean;
  // architect_run
  proposals?: number[];
}

export interface HistoryResponse {
  items: HistoryItem[];
}

// Triage status (Spec-0025/T7 backend label projection; absent on older backends → infer from labels on the client).
export type TriageStatus =
  | "needs-triage"
  | "triaged"
  | "rejected"
  | "needs-info"
  | "superseded";

export interface Issue {
  number: number;
  title: string;
  body: string;
  labels: string[];
  state: string;
  created_at: string;
  closed_at: string | null;
  url: string;
  // Spec-0025/T7 + 0029/T9 platform label projection (absent on older backends → infer from labels on the frontend; see lib/issueMeta):
  kind?: string; // bug/feature/chore/document or rfc (RFC overrides type)
  round?: number | null; // N from round-N
  triage_status?: TriageStatus | null;
  priority?: string | null; // P0-P3
  reject_reason?: string | null; // Rejection/decline reason (authoritative reason in detail comments)
  plane?: Plane | null; // Spec-0029: three-plane projection (report/proposal/ready; null for terminal states)
  provenance?: Provenance | null; // Spec-0029: proposal provenance (from-triage/from-architect/from-divergent)
  // Coverage: covers = triaged issue numbers an RFC declares it covers; covered_by = the open RFC covering this issue.
  covers?: number[];
  covered_by?: number | null;
}

export interface IssuesResponse {
  connected: boolean;
  board_url: string | null;
  issues: Issue[];
}

export interface IssueComment {
  author: string;
  body: string;
  created_at: string;
}

export interface IssueTimelineState {
  labels: string[];
  plane: Plane | null;
  provenance: Provenance | null;
  priority: string | null;
  round: number | null;
  handoff: boolean;
  delivery_active: boolean;
  blocked: boolean;
  terminal: string | null;
  conflicts: string[];
}

export interface IssueTimelineEvent {
  id: string | number | null;
  created_at: string;
  actor: string;
  type: string;
  label: string;
  operation: "add" | "remove" | "unknown";
  body: string;
}

export interface IssueTimelineTransition {
  id: string;
  created_at: string;
  actor: string;
  title: string;
  added: string[];
  removed: string[];
  before: IssueTimelineState;
  after: IssueTimelineState;
  anomaly_ids: string[];
}

export interface IssueTimelineAnomaly {
  id: string;
  code: string;
  severity: "warning" | "critical" | string;
  message: string;
  transition_id: string | null;
  dimensions: string[];
}

export interface IssueTimeline {
  available: boolean;
  reason: string | null;
  complete: boolean;
  events: IssueTimelineEvent[];
  transitions: IssueTimelineTransition[];
  current: IssueTimelineState | null;
  historical: IssueTimelineState | null;
  last_known: Partial<Pick<IssueTimelineState, "plane" | "provenance" | "priority" | "round">>;
  anomalies: IssueTimelineAnomaly[];
}

export interface IssueDetailResponse {
  connected: boolean;
  issue: Issue | null;
  comments: IssueComment[];
  timeline?: IssueTimeline;
}

export interface Commit {
  sha: string;
  short_sha: string;
  message: string;
  author: string;
  date: string;
  url: string;
  tags: string[];
}

export interface CommitsResponse {
  connected: boolean;
  commits_url: string | null;
  commits: Commit[];
}

export interface CommitDetail extends Commit {
  stats: { additions: number; deletions: number; total: number };
  files: { filename: string; status: string }[];
  diff: string;
}

export interface CommitDetailResponse {
  connected: boolean;
  commit: CommitDetail | null;
}

export interface PersonaCallTrace {
  role: string;
  system: string;
  user: string;
  raw: string;
  parsed: Record<string, unknown>;
  steps?: LogEntry[];
}

export interface SimTurn {
  turn: number;
  phase: string;
  perceive: string;
  verdict: string;
  action: string;
  message: string;
  executor: string;
  channel: string;
  patience: number;
  trust: string;
  harness_output?: string;
  persona_trace?: PersonaCallTrace[];
}

export interface SimTrace {
  persona_id: string;
  end_reason: string;
  turns: SimTurn[];
  signals: string[];
  persona_tail?: PersonaCallTrace[];
}

export interface SessionDetail {
  session_provenance?: SessionProvenance | null;
  session_id: string;
  created_at: string;
  persona: {
    identity: string;
    level: string;
    domain: string;
    goal: string;
    speaking_style: string;
  };
  scenario: { description: string };
  transcript: { turns: Turn[] };
  // Spec-0084/T1: only an actual valid rating has a score; derived scores stay diagnostic.
  feeling: { score: number; reason: string } | null;
  feedback?: {
    schema_version: 1;
    task_assessment: {
      status: "fulfilled" | "unfulfilled" | "unknown";
      source: string;
      evidence_refs: string[];
    };
    experience: {
      status: "rated" | "missing" | "invalid" | "unavailable";
      score: number | null;
      source: string;
      reason: string;
    };
    attribution: { status: "confirmed" | "uncertain" | "unknown"; claims: unknown[] };
    opportunities: unknown[];
  };
  issue_refs: { number: number; url: string; state: string }[];
  sim_trace?: SimTrace | null;
}

export interface Roster {
  user: number;
  triager: number;
  architect: number;
  developer: number;
  divergent?: number; // Spec-0028+: discovery-track generator (defaults to 0)
  owner?: number; // Spec-0029: sole admission authority (0 = purely mechanical)
}

export interface ConfigResponse {
  roster: Roster;
}

// /api/overview: overview metrics + two curves (consumed by Spec-0026/T3 Charts).
// feeling_trend=[[created_at, score]]; issue_curve=[[timestamp, delta, backlog]] (0025/T7 executable backlog definition).
export interface OverviewResponse {
  open_issue_count: number;
  session_count: number;
  feeling_trend: [string, number][];
  feedback_counts?: Record<string, { rated: number; missing: number; invalid: number; unavailable: number }>;
  issue_curve: [string, number, number][];
  // Spec-0029/T9: current counts in the three-plane funnel (absent on older backends → omit the funnel bar).
  funnel?: { report: number; proposal: number; ready: number };
}

// Spec-0032/T7: delivery observations (/api/delivery): open PR + needs-human backlog (vigil's work view, read-only).
export interface Pull {
  number: number;
  title: string;
  state: "open" | "closed" | "merged";
  head_branch: string;
  mergeable: boolean | null;
  labels: string[];
  closes_issues: number[];
  url: string;
  created_at: string;
  updated_at: string;
}

export interface DeliveryResponse {
  connected: boolean;
  pulls: Pull[];
  needs_human: number;
}

// Dashboard selection: the fourth column displays full details for the selected object.
export type Selection =
  | { type: "agent"; agentId: string }
  | { type: "history"; index: number }
  | { type: "issue"; number: number }
  | { type: "commit"; sha: string };
