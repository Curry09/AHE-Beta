import { useEffect, useMemo, useState } from "react";
import PhaserGame from "@/components/game/PhaserGame";
import { gameEvents } from "@/lib/events";
import type { SeatDef } from "@/components/game/utils/MapHelpers";
import { getAgents, getIssues, getCommits, getOverview } from "./api";
import type { Agent, IssuesResponse, CommitsResponse, Overview } from "./types";
import { agentsToSeats, seatAgentMap, pushSeats } from "./townBridge";
import ConversationPanel from "./panels/ConversationPanel";
import IssuesPanel from "./panels/IssuesPanel";
import CommitsPanel from "./panels/CommitsPanel";

const POLL_MS = 4000;

export default function App() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [issues, setIssues] = useState<IssuesResponse | null>(null);
  const [commits, setCommits] = useState<CommitsResponse | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [seatDefs, setSeatDefs] = useState<SeatDef[]>([]);
  const [selectedSeatId, setSelectedSeatId] = useState<string | null>(null);
  const [live, setLive] = useState(false);

  // 场景发现工位 / 点击小人 —— 两个事件桥接到 React 状态。
  useEffect(() => {
    const offSeats = gameEvents.on("seats-discovered", (defs) => setSeatDefs(defs));
    const offClick = gameEvents.on("worker-clicked", (seatId) => setSelectedSeatId(seatId));
    return () => {
      offSeats();
      offClick();
    };
  }, []);

  // 轮询 backend。
  useEffect(() => {
    let alive = true;
    async function tick() {
      const results = await Promise.allSettled([
        getAgents(),
        getIssues(),
        getCommits(),
        getOverview(),
      ]);
      if (!alive) return;
      const [a, i, c, o] = results;
      setLive(results.some((r) => r.status === "fulfilled"));
      if (a.status === "fulfilled") setAgents(a.value.agents);
      if (i.status === "fulfilled") setIssues(i.value);
      if (c.status === "fulfilled") setCommits(c.value);
      if (o.status === "fulfilled") setOverview(o.value);
    }
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  // agents / 工位变化 → 重推给场景。
  useEffect(() => {
    if (seatDefs.length === 0) return;
    pushSeats(agentsToSeats(agents, seatDefs));
  }, [agents, seatDefs]);

  const agentBySeat = useMemo(() => seatAgentMap(agents, seatDefs), [agents, seatDefs]);
  const selectedAgent = selectedSeatId ? agentBySeat.get(selectedSeatId) ?? null : null;

  const openIssues = overview?.open_issue_count ?? issues?.issues.length ?? null;

  return (
    <div className="app">
      {/* 左：像素小镇 */}
      <div className="town">
        <PhaserGame />
      </div>

      {/* 右：抬头 + Issue/main（或被完整对话覆盖） */}
      <aside className="side">
        <header className="brand">
          <div className="brand-logo">AD</div>
          <div className="brand-txt">
            <div className="brand-name">auto-designer Inc.</div>
            <div className="brand-sub">体感驱动的 harness 自进化</div>
          </div>
          <div className="brand-metrics">
            <div className="metric">
              <em>Open Issue</em>
              <b>{openIssues ?? "—"}</b>
            </div>
            <div className="metric">
              <em>会话</em>
              <b>{overview?.session_count ?? "—"}</b>
            </div>
            <div className="metric">
              <em>在岗</em>
              <b>{agents.filter((a) => a.running).length}</b>
            </div>
          </div>
          <span className={`live ${live ? "on" : "off"}`}>
            <span className="dot" />
            {live ? "LIVE" : "离线"}
          </span>
        </header>

        <div className="side-body">
          {selectedAgent ? (
            <ConversationPanel agent={selectedAgent} onClose={() => setSelectedSeatId(null)} />
          ) : (
            <div className="boards">
              <IssuesPanel data={issues} />
              <CommitsPanel data={commits} />
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
