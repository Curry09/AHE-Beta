import { useMemo, useState } from "react";
import { getAgents, getCommits, getHistory, getIssues, getState } from "./api";
import { AgentColumn } from "./components/AgentColumn";
import { SidePanel } from "./components/SidePanel";
import { TopBar } from "./components/TopBar";
import { usePolling } from "./hooks/usePolling";
import type { AgentRole, Selection } from "./types";

const POLL_MS = 3000;

const ROLES: { role: AgentRole; name: string }[] = [
  { role: "user", name: "用户" },
  { role: "designer", name: "设计师" },
  { role: "developer", name: "开发者" },
];

export default function App() {
  const agents = usePolling(getAgents, POLL_MS);
  const state = usePolling(getState, POLL_MS);
  const history = usePolling(getHistory, POLL_MS);
  const issues = usePolling(getIssues, POLL_MS);
  const commits = usePolling(getCommits, POLL_MS);

  const [showDone, setShowDone] = useState(false);
  const [round, setRound] = useState<"all" | number>("all");
  const [selection, setSelection] = useState<Selection | null>(null);

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
      <div className="board">
        {ROLES.map(({ role, name }) => (
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
        />
      </div>
    </div>
  );
}
