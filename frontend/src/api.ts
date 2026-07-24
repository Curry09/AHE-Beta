// 薄 fetch 客户端：/api 相对路径——dev 由 vite 代理到 :8000，生产同源（FastAPI 托管 dist）。

import type {
  AgentsResponse,
  CommitDetailResponse,
  CommitsResponse,
  ConfigResponse,
  HistoryResponse,
  IssueDetailResponse,
  IssuesResponse,
  OverviewResponse,
  RunState,
  SessionDetail,
} from "./types";

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(`/api${path}`);
  if (!resp.ok) throw new Error(`GET /api${path} -> ${resp.status}`);
  return (await resp.json()) as T;
}

export const getAgents = () => get<AgentsResponse>("/agents");
export const getState = () => get<RunState>("/state");
export const getHistory = () => get<HistoryResponse>("/history");
export const getIssues = () => get<IssuesResponse>("/issues");
export const getIssue = (number: number) => get<IssueDetailResponse>(`/issues/${number}`);
export const getCommits = () => get<CommitsResponse>("/commits");
export const getCommit = (sha: string) => get<CommitDetailResponse>(`/commits/${sha}`);
export const getConfig = () => get<ConfigResponse>("/config");
export const getSession = (id: string) => get<SessionDetail>(`/sessions/${id}`);
export const getOverview = () => get<OverviewResponse>("/overview");
