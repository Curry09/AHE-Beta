// 镜像后端 DTO（backend/auto_designer/web/api.py）。字段名是契约，须与后端一致。

export interface Overview {
  open_issue_count: number | null;
  session_count: number;
  feeling_trend: [string, number][]; // [created_at, score]
  issue_curve: [string, number, number][]; // [created_at, opened, net_open]
}

export interface SessionSummary {
  session_id: string;
  created_at: string;
  score: number;
  n_issues: number;
  persona_identity: string;
  scenario: string;
}

export interface Turn {
  role: "user" | "harness";
  content: string;
}

export interface Issue {
  number: number;
  title: string;
  labels: string[];
  state: string;
  url: string;
}

export interface IssuesResponse {
  connected: boolean;
  board_url: string | null;
  issues: Issue[];
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

export type AgentRole = "user" | "designer" | "developer";

export interface Agent {
  agent_id: string;
  role: AgentRole;
  label: string;
  running: boolean;
  status: string;
  turns: Turn[];
  detail: string | null;
  started_at: string;
  updated_at: string;
}

export interface AgentsResponse {
  agents: Agent[];
}

// 编制（后端 roster 单一真源，经 /api/config 读）：三个房间的容量。
export interface Roster {
  user: number;
  designer: number;
  developer: number;
}

export interface ConfigResponse {
  roster: Roster;
}

export interface IssueRef {
  number: number;
  url: string;
  state: string;
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
  issue_refs: IssueRef[];
}
