import { useEffect, useMemo, useState } from "react";
import {
  getExperiments,
  getSelectedExperimentId,
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

// Order follows the demand flow: a → first beat (triage∥divergent) → second beat (architect) → Owner admission (Spec-0029/0032).
// Divergent defaults to zero agents; show its room only when active or archived work exists to avoid a persistent empty column.
// Spec-0032/T7: the developer column is retired (delivery runs in the external vigil process); keep it for historical dev_run archives.
// New delivery progress appears in the sidebar's delivery / PR panel.
const ROLES: { role: AgentRole; name: string }[] = [
  { role: "user", name: "User" },
  { role: "triager", name: "Triage" },
  { role: "divergent", name: "Divergent PM" },
  { role: "architect", name: "Architect" },
  { role: "owner", name: "Owner" },
  { role: "developer", name: "Delivery" },
];
const OPTIONAL_ROLES: AgentRole[] = ["divergent", "developer"];
const ROLE_KEYS = ROLES.map(({ role }) => role);

// Dashboard state ↔ URL query string (?done=1&round=2&sel=issue:7): preserve context across refreshes and sharing.
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
  const selectedExperiment = getSelectedExperimentId();
  const snapshot = experiments.find((item) => item.id === selectedExperiment)
    ?? (selectedExperiment ? undefined : experiments[0]);

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
  const delivery = usePolling(getDelivery, POLL_MS); // Spec-0032/T7: delivery view (PR + needs-human)

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
    const experiment = new URLSearchParams(location.search).get("experiment");
    if (experiment) params.set("experiment", experiment);
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
  // Selectable rounds = archived rounds ∪ current round (selectable while running, even before archiving).
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
        historical={staticSite}
        snapshot={snapshot}
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
