import type {
  Overview,
  SessionSummary,
  SessionDetail,
  IssuesResponse,
  CommitsResponse,
  AgentsResponse,
  ConfigResponse,
} from "./types";

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(path);
  if (!resp.ok) throw new Error(`${path} → ${resp.status}`);
  return (await resp.json()) as T;
}

export const getOverview = () => get<Overview>("/api/overview");
export const getSessions = () => get<SessionSummary[]>("/api/sessions");
export const getSession = (id: string) => get<SessionDetail>(`/api/sessions/${id}`);
export const getIssues = () => get<IssuesResponse>("/api/issues");
export const getCommits = () => get<CommitsResponse>("/api/commits");
export const getAgents = () => get<AgentsResponse>("/api/agents");
export const getConfig = () => get<ConfigResponse>("/api/config");
