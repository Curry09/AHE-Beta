import { useEffect, useMemo, useState } from "react";
import {
  getExperiments,
  getAgents,
  getCommits,
  getConfig,
  getDelivery,
  getHistory,
  getIssues,
  getOverview,
  getState,
  getUsageSummary,
  getUsageEvents,
} from "./api";
import { ExperimentPicker } from "./components/ExperimentPicker";
import { AgentColumn } from "./components/AgentColumn";
import { BuildingView } from "./components/BuildingView";
import { Charts } from "./components/Charts";
import { SidePanel } from "./components/SidePanel";
import { TopBar } from "./components/TopBar";
import { UsagePanel } from "./components/UsagePanel";
import { OpenAgentsView } from "./components/openagents/OpenAgentsView";
import { usePolling } from "./hooks/usePolling";
import { roundOf } from "./lib/issueMeta";
import type { AgentRole, Selection, ViewMode } from "./types";

const POLL_MS = 3000;

// 顺序对齐需求面 a → 第一拍(triage∥divergent) → 第二拍(synthesize) → Owner 准入（Spec-0029/0032）。
// divergent 默认编制 0 → 该房间仅在有活动/归档时显示，避免常驻空列。
// Spec-0032/T7：开发者列退役（交付面在进程外 vigil）——列位保留给历史归档回看（旧 run 的 dev_run），
// 新交付进度看侧栏「交付面 · PR」面板。
const ROLES: { role: AgentRole; name: string }[] = [
  { role: "user", name: "用户" },
  { role: "triager", name: "分诊" },
  { role: "divergent", name: "发散" },
  { role: "designer", name: "设计师" },
  { role: "owner", name: "准入" },
  { role: "developer", name: "交付面" },
];
const OPTIONAL_ROLES: AgentRole[] = ["divergent", "developer"];
const ROLE_KEYS = ROLES.map(({ role }) => role);

// 看板状态 ↔ URL 查询串（?done=1&round=2&sel=issue:7）：刷新/分享不丢上下文。
function parseSelection(raw: string | null): Selection | null {
  if (!raw) return null;
  const [type, ...rest] = raw.split(":");
  const value = rest.join(":");
  if (type === "agent" && value) return { type: "agent", agentId: value };
  if (type === "history" && /^\d+$/.test(value)) return { type: "history", index: Number(value) };
  if (type === "issue" && /^\d+$/.test(value)) return { type: "issue", number: Number(value) };
  if (type === "commit" && value) return { type: "commit", sha: value };
  return null;
}

function selectionToParam(sel: Selection): string {
  if (sel.type === "agent") return `agent:${sel.agentId}`;
  if (sel.type === "history") return `history:${sel.index}`;
  if (sel.type === "issue") return `issue:${sel.number}`;
  return `commit:${sel.sha}`;
}

function parseView(raw: string | null): ViewMode {
  if (raw === "building" || raw === "openagents") return raw;
  return "dashboard";
}

function parseFloor(raw: string | null): AgentRole {
  return ROLE_KEYS.includes(raw as AgentRole) ? (raw as AgentRole) : "developer";
}

export default function App() {
  const [experiments, setExperiments] = useState<Awaited<ReturnType<typeof getExperiments>>>([]);
  const staticSite = import.meta.env.VITE_STATIC_SITE === "1";
  const selectedExperiment = new URLSearchParams(location.search).get("experiment");

  useEffect(() => {
    if (!staticSite) return;
    getExperiments().then((items) => {
      setExperiments(items);
      if (!selectedExperiment && items[0]) {
        const url = new URL(location.href);
        url.searchParams.set("experiment", items[0].id);
        window.history.replaceState(null, "", url.pathname + url.search);
      }
    }).catch(() => setExperiments([]));
  }, [staticSite, selectedExperiment]);

  const agents = usePolling(getAgents, POLL_MS);
  const state = usePolling(getState, POLL_MS);
  const history = usePolling(getHistory, POLL_MS);
  const issues = usePolling(getIssues, POLL_MS);
  const commits = usePolling(getCommits, POLL_MS);
  const config = usePolling(getConfig, POLL_MS);
  const overview = usePolling(getOverview, POLL_MS);
  const delivery = usePolling(getDelivery, POLL_MS); // Spec-0032/T7：交付面（PR + needs-human）

  const [view, setView] = useState<ViewMode>(() =>
    parseView(new URLSearchParams(location.search).get("view")),
  );
  const [selectedFloor, setSelectedFloor] = useState<AgentRole>(() =>
    parseFloor(new URLSearchParams(location.search).get("floor")),
  );
  const [showDone, setShowDone] = useState(
    () => new URLSearchParams(location.search).get("done") === "1",
  );
  const [round, setRound] = useState<"all" | number>(() => {
    const raw = new URLSearchParams(location.search).get("round");
    return raw && /^\d+$/.test(raw) ? Number(raw) : "all";
  });
  const usageRound = round === "all" ? undefined : round;
  const usage = usePolling(() => getUsageSummary(usageRound), POLL_MS);
  const usageEvents = usePolling(() => getUsageEvents(usageRound), POLL_MS);
  const [selection, setSelection] = useState<Selection | null>(() =>
    parseSelection(new URLSearchParams(location.search).get("sel")),
  );

  useEffect(() => {
    const params = new URLSearchParams();
    if (view === "building") {
      params.set("view", "building");
      params.set("floor", selectedFloor);
    } else if (view === "openagents") {
      params.set("view", "openagents");
    }
    if (view !== "openagents" && showDone) params.set("done", "1");
    if (round !== "all") params.set("round", String(round));
    if (selection) params.set("sel", selectionToParam(selection));
    const qs = params.toString();
    window.history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
  }, [view, selectedFloor, showDone, round, selection]);

  const items = useMemo(() => history?.items ?? [], [history]);
  // 可选轮次 = 归档里出现过的轮 ∪ 当前轮（运行中还没归档也能选）。
  const rounds = useMemo(() => {
    const set = new Set<number>(items.map((it) => it.round));
    for (const issue of issues?.issues ?? []) {
      const issueRound = roundOf(issue);
      if (issueRound !== null) set.add(issueRound);
    }
    if (state && state.round > 0) set.add(state.round);
    return [...set].sort((a, b) => b - a);
  }, [items, issues, state]);
  const historyEntries = useMemo(
    () =>
      items
        .map((item, index) => ({ item, index }))
        .filter(({ item }) => round === "all" || item.round === round),
    [items, round],
  );

  const openCount = issues ? issues.issues.filter((i) => i.state === "open").length : null;

  return (
    <div className="app">
      <ExperimentPicker
        experiments={experiments}
        selected={selectedExperiment}
        onSelect={(id) => {
          const url = new URL(location.href);
          url.searchParams.set("experiment", id);
          window.location.assign(url.pathname + url.search);
        }}
      />
      <TopBar
        state={state}
        openCount={openCount}
        view={view}
        onView={(v) => setView(v)}
        showDone={showDone}
        onShowDone={(v) => setShowDone(v)}
        round={round}
        rounds={rounds}
        onRound={(r) => setRound(r)}
      />
      <Charts overview={overview} />
      <UsagePanel usage={usage} events={usageEvents?.events ?? []} />
      {view === "openagents" ? (
        <div className="openagents-layout">
          <OpenAgentsView
            issues={issues}
            delivery={delivery}
            commits={commits}
            state={state}
            overview={overview}
            round={round}
            onSelect={(sel) => setSelection(sel)}
          />
          <SidePanel
            selection={selection}
            onSelect={(sel) => setSelection(sel)}
            agents={agents?.agents ?? []}
            history={items}
            issues={issues}
            commits={commits}
            funnel={overview?.funnel ?? null}
            delivery={delivery}
          />
        </div>
      ) : view === "building" ? (
        <div className="building-layout">
          <BuildingView
            roles={ROLES}
            agents={agents?.agents ?? []}
            history={historyEntries}
            allHistory={items.map((item, index) => ({ item, index }))}
            roster={config?.roster ?? null}
            showDone={showDone}
            round={round}
            issues={issues}
            delivery={delivery}
            selectedFloor={selectedFloor}
            onSelectFloor={(role) => setSelectedFloor(role)}
            onSelect={(sel) => setSelection(sel)}
            onOpenAgents={() => setView("openagents")}
          />
          <SidePanel
            selection={selection}
            onSelect={(sel) => setSelection(sel)}
            agents={agents?.agents ?? []}
            history={items}
            issues={issues}
            commits={commits}
            funnel={overview?.funnel ?? null}
            delivery={delivery}
          />
        </div>
      ) : (
        <div className="board">
          {ROLES.filter(
            ({ role }) =>
              !OPTIONAL_ROLES.includes(role) ||
              (agents?.agents ?? []).some((a) => a.role === role) ||
              items.some((it) => it.role === role),
          ).map(({ role, name }) => (
            <AgentColumn
              key={role}
              role={role}
              name={name}
              agents={(agents?.agents ?? []).filter((a) => a.role === role)}
              history={historyEntries.filter(({ item }) => item.role === role)}
              showDone={showDone}
              selection={selection}
              onSelect={(sel) => setSelection(sel)}
            />
          ))}
          <SidePanel
            selection={selection}
            onSelect={(sel) => setSelection(sel)}
            agents={agents?.agents ?? []}
            history={items}
            issues={issues}
            commits={commits}
            funnel={overview?.funnel ?? null}
            delivery={delivery}
          />
        </div>
      )}
    </div>
  );
}
