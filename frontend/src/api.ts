// fetch 客户端：本地/后端托管模式走 /api；GitHub Pages 模式走历史实验的静态 API 快照。

import type {
  AgentsResponse,
  CommitDetailResponse,
  CommitsResponse,
  ConfigResponse,
  DeliveryResponse,
  HistoryResponse,
  IssueDetailResponse,
  IssuesResponse,
  OverviewResponse,
  RunState,
  SessionDetail,
  UsageSummary,
  UsageEventsResponse,
} from "./types";

export interface ExperimentSummary {
  id: string;
  title: string;
  status: string;
  updated_at: string;
  source: "static" | "api";
  description?: string;
}

const staticSite = import.meta.env.VITE_STATIC_SITE === "1";
const baseUrl = import.meta.env.BASE_URL;

export function getSelectedExperimentId(): string | null {
  const query = new URLSearchParams(window.location.search).get("experiment");
  if (query) return query;
  const match = window.location.pathname.match(/\/experiments\/([^/]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

// Spec-0071/T5: index.updated_at is the snapshot record time, not a live heartbeat.
export function formatSnapshotTime(recordedAt: string): string {
  const time = new Date(recordedAt);
  return Number.isNaN(time.getTime())
    ? "记录时间未知"
    : `${time.toISOString().slice(0, 19).replace("T", " ")} UTC`;
}

function apiRoot(): string {
  if (!staticSite) return "/api";
  const id = getSelectedExperimentId() || "_default";
  return `${baseUrl}experiments/${encodeURIComponent(id)}/api`;
}

async function get<T>(path: string): Promise<T> {
  const root = apiRoot();
  const resp = await fetch(`${root}${path}`);
  if (!resp.ok) throw new Error(`GET ${root}${path} -> ${resp.status}`);
  return (await resp.json()) as T;
}

export async function getExperiments(): Promise<ExperimentSummary[]> {
  if (!staticSite) return [];
  const resp = await fetch(`${baseUrl}experiments/index.json`);
  if (!resp.ok) throw new Error(`GET experiments/index.json -> ${resp.status}`);
  const data = (await resp.json()) as { experiments: ExperimentSummary[] };
  return data.experiments;
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
export const getDelivery = () => get<DeliveryResponse>("/delivery"); // Spec-0032/T7：交付面观测
export const getUsageSummary = (round?: number) =>
  get<UsageSummary>(`/usage/summary${round ? `?round_no=${round}` : ""}`);
export const getUsageEvents = (round?: number) =>
  get<UsageEventsResponse>(`/usage/events${round ? `?round_no=${round}` : ""}`);
