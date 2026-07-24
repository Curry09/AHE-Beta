// 数据契约：字段名与 backend/auto_designer/web/api.py 的响应一一对应，两侧须同步修改。

export type AgentRole = "user" | "triager" | "designer" | "developer";

// Spec-0026/T1：用户 agent 活动槽可带的 persona 摘要（只读展示，缺省 null）。
export interface PersonaMeta {
  identity: string;
  level: string;
  domain: string;
  goal: string;
}

export interface Turn {
  role: "user" | "harness";
  content: string;
  // 仅 harness 轮：该轮内层迭代过程流（模型发言/工具调用/结果）。content 是给用户看的最终答案，
  // steps 是观测层展开时才看的完整内层过程。缺省即无（老数据/无过程）。
  steps?: LogEntry[];
}

// 过程流条目：status(状态变化) / assistant(模型发言) / tool(工具调用) / tool_result / tool_error
// t 可选：dev/designer 的 live log 带时间戳；harness 内层 steps 无时间戳。
export interface LogEntry {
  t?: string;
  kind: string;
  text: string;
}

export interface Agent {
  agent_id: string;
  role: AgentRole;
  label: string;
  running: boolean;
  status: string;
  round: number | null;
  meta?: PersonaMeta | null; // Spec-0026：用户 agent 带 persona 摘要；其余角色/老后端为 null
  turns: Turn[];
  detail: string | null;
  log: LogEntry[];
  started_at: string;
  updated_at: string;
}

export interface AgentsResponse {
  agents: Agent[];
}

// 整条 run 的运行态（data/live/run.json）
export interface RunState {
  running: boolean;
  round: number;
  total_rounds: number;
  round_shas: string[];
  started_at: string | null;
  updated_at: string | null;
}

// 按轮归档的已完成工作项（data/live/history.json）
export type HistoryKind = "user_session" | "designer_run" | "dev_run";

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
  score?: number | null;
  end_reason?: string;
  // dev_run
  issue_number?: number | null;
  tag?: string | null;
  committed?: boolean;
  // designer_run
  proposals?: number[];
}

export interface HistoryResponse {
  items: HistoryItem[];
}

// triage 状态（Spec-0025/T7 后端标签投影；老后端缺省 → 由 labels 客户端兜底推导）。
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
  // Spec-0025/T7 平台层标签投影（老后端缺省 → 前端按 labels 兜底推导，见 lib/issueMeta）：
  kind?: string; // bug/feature/chore/document 或 rfc（RFC 凌驾 type）
  round?: number | null; // round-N 的 N
  triage_status?: TriageStatus | null;
  priority?: string | null; // P0-P3
  reject_reason?: string | null; // 驳回/needs-info 原因（权威原因见详情评论）
  // 覆盖关系：covers = RFC 声明覆盖的 triaged 票号；covered_by = 被哪张 open RFC 覆盖。
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

export interface IssueDetailResponse {
  connected: boolean;
  issue: Issue | null;
  comments: IssueComment[];
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

export interface SessionDetail {
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
  feeling: { score: number; reason: string };
  issue_refs: { number: number; url: string; state: string }[];
}

export interface Roster {
  user: number;
  triager: number;
  designer: number;
  developer: number;
}

export interface ConfigResponse {
  roster: Roster;
}

// /api/overview：概览数字 + 两条曲线（Spec-0026/T3 Charts 消费）。
// feeling_trend=[[created_at, score]]；issue_curve=[[timestamp, delta, backlog]]（0025/T7 可执行 backlog 口径）。
export interface OverviewResponse {
  open_issue_count: number;
  session_count: number;
  feeling_trend: [string, number][];
  issue_curve: [string, number, number][];
}

// 看板选中态：点谁，第四栏就展示谁的完整信息。
export type Selection =
  | { type: "agent"; agentId: string }
  | { type: "history"; index: number }
  | { type: "issue"; number: number }
  | { type: "commit"; sha: string };
