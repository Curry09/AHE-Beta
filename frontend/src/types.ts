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

export interface LiveSession {
  active: boolean;
  persona_identity?: string;
  scenario?: string;
  turns?: Turn[];
  updated_at?: string;
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
