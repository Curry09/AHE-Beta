import { useEffect, useMemo, useState } from "react";
import PhaserGame from "@/components/game/PhaserGame";
import { gameEvents } from "@/lib/events";
import { getAgents, getIssues, getCommits, getOverview, getConfig } from "./api";
import type { Agent, IssuesResponse, CommitsResponse, Overview, Roster } from "./types";
import { buildLayout, pushLayout } from "./townBridge";
import ConversationPanel from "./panels/ConversationPanel";
import IssuesPanel from "./panels/IssuesPanel";
import CommitsPanel from "./panels/CommitsPanel";

const POLL_MS = 4000;
// roster 未拉到前的默认编制（与后端 DEFAULT_ROSTER 一致），保证房间在离线时也能渲染。
const DEFAULT_ROSTER: Roster = { user: 3, designer: 1, developer: 3 };

export default function App() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [roster, setRoster] = useState<Roster>(DEFAULT_ROSTER);
  const [issues, setIssues] = useState<IssuesResponse | null>(null);
  const [commits, setCommits] = useState<CommitsResponse | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [selectedSeatId, setSelectedSeatId] = useState<string | null>(null);
  const [sceneReady, setSceneReady] = useState(false);
  const [loaded, setLoaded] = useState(false); // 首个 tick 完成后为 true，用于区分「加载中 vs 离线」
  const [live, setLive] = useState(false);

  // 场景就绪 / 点击小人 —— 两个事件桥接到 React 状态。
  useEffect(() => {
    const offReady = gameEvents.on("scene-ready", () => setSceneReady(true));
    const offClick = gameEvents.on("worker-clicked", (seatId) => setSelectedSeatId(seatId));
    return () => {
      offReady();
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
        getConfig(),
      ]);
      if (!alive) return;
      const [a, i, c, o, cfg] = results;
      setLive(results.some((r) => r.status === "fulfilled"));
      if (a.status === "fulfilled") setAgents(a.value.agents);
      if (i.status === "fulfilled") setIssues(i.value);
      if (c.status === "fulfilled") setCommits(c.value);
      if (o.status === "fulfilled") setOverview(o.value);
      if (cfg.status === "fulfilled") setRoster(cfg.value.roster);
      setLoaded(true);
    }
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  // roster / agents 变化 → 重算三房间布局并推给场景（需场景就绪）。
  const layout = useMemo(() => buildLayout(roster, agents), [roster, agents]);
  useEffect(() => {
    if (!sceneReady) return;
    pushLayout(layout);
  }, [layout, sceneReady]);

  const selectedAgent = selectedSeatId ? layout.seatAgents.get(selectedSeatId) ?? null : null;

  const openIssues = overview?.open_issue_count ?? issues?.issues.length ?? null;
  const activeCount = agents.filter((a) => a.running).length;

  return (
    <div className="app">
      {/* 左：像素小镇（三房间：用户 / 设计师 / 开发者） */}
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
              <b>{activeCount}</b>
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
              <IssuesPanel data={issues} offline={loaded && !issues} />
              <CommitsPanel data={commits} offline={loaded && !commits} />
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
