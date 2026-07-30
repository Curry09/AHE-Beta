import { useEffect, useMemo, useState } from "react";
import {
  getAgents,
  getCommits,
  getDelivery,
  getHistory,
  getIssues,
  getOverview,
  getState,
} from "./api";
import { AgentColumn } from "./components/AgentColumn";
import { Charts } from "./components/Charts";
import { SidePanel } from "./components/SidePanel";
import { TopBar } from "./components/TopBar";
import { usePolling } from "./hooks/usePolling";
import type { AgentRole, Selection } from "./types";

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
  { role: "developer", name: "开发者" },
];
const OPTIONAL_ROLES: AgentRole[] = ["divergent", "developer"];

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

export default function App() {
  const agents = usePolling(getAgents, POLL_MS);
  const state = usePolling(getState, POLL_MS);
  const history = usePolling(getHistory, POLL_MS);
  const issues = usePolling(getIssues, POLL_MS);
  const commits = usePolling(getCommits, POLL_MS);
  const overview = usePolling(getOverview, POLL_MS);
  const delivery = usePolling(getDelivery, POLL_MS); // Spec-0032/T7：交付面（PR + needs-human）

  const [showDone, setShowDone] = useState(
    () => new URLSearchParams(location.search).get("done") === "1",
  );
  const [round, setRound] = useState<"all" | number>(() => {
    const raw = new URLSearchParams(location.search).get("round");
    return raw && /^\d+$/.test(raw) ? Number(raw) : "all";
  });
  const [selection, setSelection] = useState<Selection | null>(() =>
    parseSelection(new URLSearchParams(location.search).get("sel")),
  );

  useEffect(() => {
    const params = new URLSearchParams();
    if (showDone) params.set("done", "1");
    if (round !== "all") params.set("round", String(round));
    if (selection) params.set("sel", selectionToParam(selection));
    const qs = params.toString();
    window.history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
  }, [showDone, round, selection]);

  const items = useMemo(() => history?.items ?? [], [history]);
  // 可选轮次 = 归档里出现过的轮 ∪ 当前轮（运行中还没归档也能选）。
  const rounds = useMemo(() => {
    const set = new Set<number>(items.map((it) => it.round));
    if (state && state.round > 0) set.add(state.round);
    return [...set].sort((a, b) => b - a);
  }, [items, state]);

  const openCount = issues ? issues.issues.filter((i) => i.state === "open").length : null;

  return (
    <div className="app">
      <TopBar
        state={state}
        openCount={openCount}
        showDone={showDone}
        onShowDone={(v) => setShowDone(v)}
        round={round}
        rounds={rounds}
        onRound={(r) => setRound(r)}
      />
      <Charts overview={overview} />
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
            history={items
              .map((item, index) => ({ item, index }))
              .filter(({ item }) => item.role === role)
              .filter(({ item }) => round === "all" || item.round === round)}
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
    </div>
  );
}
