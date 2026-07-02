import { useMemo, useState } from "react";
import { getAgents, getOverview, getIssues, getCommits } from "../api";
import { useLiveData } from "../hooks/useLiveData";
import { Header } from "./Header";
import { DepartmentRail } from "./DepartmentRail";
import { IssueBoard } from "./IssueBoard";
import { CommitBoard } from "./CommitBoard";
import { AgentDrawer } from "./AgentDrawer";

// 公司办公室组织看板：顶部抬头栏 + 左侧部门（员工工位）+ 中央公告墙（Issue 公告 / main 分支更新）。
// 点击员工卡打开详情抽屉；点击公告条目跳 Gitea。轮询驱动，暂停即冻结。
export default function Office() {
  const [paused, setPaused] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data: agentsData, error, updatedAt } = useLiveData(getAgents, 2000, !paused);
  const { data: overview } = useLiveData(getOverview, 5000, !paused);
  const { data: issues } = useLiveData(getIssues, 8000, !paused);
  const { data: commits } = useLiveData(getCommits, 8000, !paused);

  const agents = useMemo(() => agentsData?.agents ?? [], [agentsData]);
  const now = Date.now();
  const running = agents.filter((a) => a.running).length;
  const selected = agents.find((a) => a.agent_id === selectedId) ?? null;

  const feeling = overview?.feeling_trend.length
    ? overview.feeling_trend[overview.feeling_trend.length - 1][1]
    : "—";

  const toggle = (id: string) => setSelectedId((cur) => (cur === id ? null : id));

  return (
    <div className="office">
      <Header
        openIssues={overview?.open_issue_count ?? "—"}
        sessions={overview?.session_count ?? "—"}
        feeling={feeling}
        running={running}
        updatedAt={updatedAt}
        paused={paused}
        onTogglePause={() => setPaused((v) => !v)}
      />

      <div className="office-body">
        <DepartmentRail
          agents={agents}
          now={now}
          selectedId={selectedId}
          onSelect={toggle}
        />
        <main className="wall">
          {error && <div className="wall-err">加载失败：{error}</div>}
          <IssueBoard data={issues} />
          <CommitBoard data={commits} now={now} />
        </main>
      </div>

      {selected && <AgentDrawer agent={selected} now={now} onClose={() => setSelectedId(null)} />}
    </div>
  );
}
