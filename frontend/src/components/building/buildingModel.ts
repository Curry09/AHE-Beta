import type { Agent, AgentRole, HistoryItem, LogEntry, Roster } from "../../types";

export type RoundFilter = "all" | number;
export type BuildingMode = "live" | "replay" | "summary";
export type HistoryEntry = { item: HistoryItem; index: number };

export interface FloorLogItem extends LogEntry {
  source: string;
}

export interface FloorModel {
  role: AgentRole;
  name: string;
  floorNo: number;
  subtitle: string;
  icon: string;
  liveAgents: Agent[];
  history: HistoryEntry[];
  capacity: number;
  activeCount: number;
  emptySeats: number;
  recentLogs: FloorLogItem[];
}

export const ROLE_COPY: Record<AgentRole, { icon: string; subtitle: string }> = {
  user: { icon: "🧑‍💻", subtitle: "用户实验室 · 真实体感采样" },
  triager: { icon: "🧭", subtitle: "分诊台 · 归类定位与去重" },
  designer: { icon: "🎨", subtitle: "设计工区 · 结构综合与 RFC" },
  divergent: { icon: "💡", subtitle: "发散 PM · 产品候选孵化" },
  owner: { icon: "🚪", subtitle: "准入门 · proposal → ready 裁决" },
  developer: { icon: "🚚", subtitle: "交付面 · OpenAgents PR / main 推进" },
};

function latestRound(history: HistoryEntry[]): number | null {
  let out: number | null = null;
  for (const { item } of history) {
    if (out == null || item.round > out) out = item.round;
  }
  return out;
}

export function resolveBuildingMode(
  showDone: boolean,
  round: RoundFilter,
  agents: Agent[],
  filteredHistory: HistoryEntry[],
  allHistory: HistoryEntry[],
): { mode: BuildingMode; effectiveHistory: HistoryEntry[]; fallbackRound: number | null } {
  if (!showDone) {
    const hasRunning = agents.some((agent) => agent.running);
    const last = hasRunning ? null : latestRound(allHistory);
    if (last != null) {
      return {
        mode: "replay",
        effectiveHistory: allHistory.filter(({ item }) => item.round === last),
        fallbackRound: last,
      };
    }
    return { mode: "live", effectiveHistory: filteredHistory, fallbackRound: null };
  }
  if (round === "all") return { mode: "summary", effectiveHistory: filteredHistory, fallbackRound: null };
  return { mode: "replay", effectiveHistory: filteredHistory, fallbackRound: null };
}

export function historyLabel(item: HistoryItem): string {
  if (item.kind === "user_session") return item.score != null ? `体感 ${item.score}` : "用户会话";
  if (item.kind === "triager_run") return "分诊完成";
  if (item.kind === "divergent_run") return `${(item.proposals ?? []).length} 候选`;
  if (item.kind === "designer_run") return `${(item.proposals ?? []).length} RFC`;
  if (item.kind === "dev_run") return item.tag ? `${item.tag}` : item.committed ? "已推进" : "未推进";
  return "已完成";
}

export function shortStatus(text: string): string {
  return text.length > 52 ? `${text.slice(0, 52)}…` : text;
}

function seatCount(
  role: AgentRole,
  liveAgents: Agent[],
  floorHistory: HistoryEntry[],
  roster: Roster | null,
  mode: BuildingMode,
): number {
  const occupants = mode === "replay" ? floorHistory.length : liveAgents.length;
  const rosterCount = roster?.[role] ?? Math.max(occupants, 1);
  return Math.max(rosterCount, occupants);
}

function floorLogs(
  mode: BuildingMode,
  liveAgents: Agent[],
  history: HistoryEntry[],
): FloorLogItem[] {
  if (mode === "live") {
    return liveAgents
      .flatMap((agent) =>
        (agent.log ?? []).slice(-3).map((log) => ({ ...log, source: agent.label })),
      )
      .slice(-8)
      .reverse();
  }
  return [...history]
    .reverse()
    .flatMap(({ item }) => {
      const logs = (item.log ?? []).slice(-2).map((log) => ({ ...log, source: item.label }));
      if (logs.length > 0) return logs;
      return [{ kind: "status", text: item.status || historyLabel(item), source: item.label }];
    })
    .slice(0, 8);
}

export function buildFloorModels(params: {
  roles: { role: AgentRole; name: string }[];
  agents: Agent[];
  history: HistoryEntry[];
  roster: Roster | null;
  mode: BuildingMode;
}): FloorModel[] {
  const visualRoles = [...params.roles].reverse();
  return visualRoles.map(({ role, name }, index) => {
    const liveAgents = params.agents.filter((agent) => agent.role === role);
    const floorHistory = params.history.filter(({ item }) => item.role === role);
    const capacity = seatCount(role, liveAgents, floorHistory, params.roster, params.mode);
    const activeCount = params.mode === "replay" ? floorHistory.length : liveAgents.length;
    const copy = ROLE_COPY[role];
    return {
      role,
      name,
      floorNo: visualRoles.length - index,
      subtitle: copy.subtitle,
      icon: copy.icon,
      liveAgents,
      history: floorHistory,
      capacity,
      activeCount,
      emptySeats: params.mode === "summary" ? 0 : Math.max(0, capacity - activeCount),
      recentLogs: floorLogs(params.mode, liveAgents, floorHistory),
    };
  });
}

export function titleCopy(mode: BuildingMode, round: RoundFilter, fallbackRound: number | null): string {
  if (fallbackRound != null) {
    return `当前没有 live agent，自动展示最近归档的第 ${fallbackRound} 轮复盘。`;
  }
  if (mode === "live") return "Live 模式：每层显示当前 agent 的办公状态。";
  if (mode === "replay" && round !== "all") return `第 ${round} 轮复盘：大厦展示该轮各楼层归档。`;
  return "全部轮次汇总：大厦展示各楼层累计产出。";
}
