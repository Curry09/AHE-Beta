import { useMemo, useState } from "react";
import { getAgents, getOverview, getIssues } from "../api";
import { useLiveData } from "../hooks/useLiveData";
import type { IssuesResponse } from "../types";
import { ControlBar } from "./ControlBar";
import { Building } from "./Building";
import { Character } from "./Character";
import { DialogueLog } from "./DialogueLog";
import { Roster } from "./Roster";
import { DetailDrawer } from "./DetailDrawer";
import { ZONES, placeAgents } from "./layout";

// 顶右角像素告示牌：概览三指标（open issue / 会话数 / 最新体感）。
function StatsSign({
  openIssues,
  sessions,
  feeling,
}: {
  openIssues: number | string;
  sessions: number | string;
  feeling: number | string;
}) {
  return (
    <div className="stats-sign">
      <span>📋 open issue <b>{openIssues}</b></span>
      <span>💬 会话 <b>{sessions}</b></span>
      <span>😊 体感 <b>{feeling}</b></span>
    </div>
  );
}

// Issue 公告板面板：点公告板建筑后拉 open issues。
function IssuesPanel({ data, onClose }: { data: IssuesResponse | null; onClose: () => void }) {
  return (
    <aside className="drawer issues-panel">
      <button className="drawer-close" onClick={onClose} aria-label="关闭">
        ✕
      </button>
      <div className="drawer-name">📋 Issue 公告板</div>
      {data?.board_url && (
        <p>
          <a href={data.board_url} target="_blank" rel="noreferrer">
            ↗ 在 Gitea 打开看板
          </a>
        </p>
      )}
      {!data ? (
        <p className="muted">载入中…</p>
      ) : !data.connected ? (
        <p className="muted">未连接 Gitea（设 GITEA_URL/OWNER/REPO/TOKEN 后显示）。</p>
      ) : data.issues.length === 0 ? (
        <p className="muted">暂无 open issue。</p>
      ) : (
        <ul className="issue-list">
          {data.issues.map((i) => (
            <li key={i.number}>
              <a href={i.url} target="_blank" rel="noreferrer">
                #{i.number} {i.title}
              </a>
              {i.labels.map((l) => (
                <span key={l} className="chip">
                  {l}
                </span>
              ))}
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}

export default function Town() {
  const [paused, setPaused] = useState(false);
  const [showDialogue, setShowDialogue] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [boardOpen, setBoardOpen] = useState(false);

  const { data: agentsData, error, updatedAt } = useLiveData(getAgents, 2000, !paused);
  const { data: overview } = useLiveData(getOverview, 5000, !paused);
  const { data: issues } = useLiveData(getIssues, 8000, boardOpen && !paused);

  const agents = useMemo(() => agentsData?.agents ?? [], [agentsData]);
  const placed = useMemo(() => placeAgents(agents), [agents]);
  const now = Date.now();
  const running = agents.filter((a) => a.running).length;
  const selected = agents.find((a) => a.agent_id === selectedId) ?? null;

  const feeling = overview?.feeling_trend.length
    ? overview.feeling_trend[overview.feeling_trend.length - 1][1]
    : "—";

  const toggle = (id: string) => setSelectedId((cur) => (cur === id ? null : id));

  return (
    <div className="town">
      <ControlBar
        paused={paused}
        onTogglePause={() => setPaused((v) => !v)}
        showDialogue={showDialogue}
        onToggleDialogue={() => setShowDialogue((v) => !v)}
        updatedAt={updatedAt}
        running={running}
      />

      <div className="world-wrap">
        <div className="world">
          {ZONES.map((z) => (
            <Building
              key={z.key}
              zone={z}
              count={z.key === "board" ? overview?.open_issue_count ?? undefined : undefined}
              onClick={z.key === "board" ? () => setBoardOpen(true) : undefined}
            />
          ))}

          {placed.map((p) => (
            <Character
              key={p.agent.agent_id}
              agent={p.agent}
              now={now}
              x={p.x}
              y={p.y}
              selected={p.agent.agent_id === selectedId}
              showBubble={showDialogue}
              onSelect={toggle}
            />
          ))}

          {error && <div className="world-hint err">加载失败：{error}</div>}
          {!error && agents.length === 0 && (
            <div className="world-hint">小镇尚无活动居民 —— 跑闭环后居民会陆续入住。</div>
          )}

          {showDialogue && <DialogueLog agents={agents} selected={selected} />}
          <StatsSign
            openIssues={overview?.open_issue_count ?? "—"}
            sessions={overview?.session_count ?? "—"}
            feeling={feeling}
          />
        </div>
      </div>

      <Roster agents={agents} now={now} selectedId={selectedId} onSelect={toggle} />

      {selected && <DetailDrawer agent={selected} now={now} onClose={() => setSelectedId(null)} />}
      {boardOpen && <IssuesPanel data={issues} onClose={() => setBoardOpen(false)} />}
    </div>
  );
}
