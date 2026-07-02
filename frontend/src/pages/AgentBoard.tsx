import { getAgents } from "../api";
import { useLiveData } from "../hooks/useLiveData";
import type { Agent } from "../types";
import { AgentCard } from "../components/AgentCard";
import { LiveIndicator } from "../components/LiveIndicator";

function Wall({ title, agents, now }: { title: string; agents: Agent[]; now: number }) {
  const running = agents.filter((a) => a.running).length;
  return (
    <div className="agent-wall">
      <h3>
        {title}（{agents.length}）
        {running > 0 && <span className="live"> · {running} 运行中</span>}
      </h3>
      {agents.length === 0 ? (
        <p className="muted">暂无</p>
      ) : (
        <div className="agent-cards">
          {agents.map((a) => (
            <AgentCard key={a.agent_id} a={a} now={now} />
          ))}
        </div>
      )}
    </div>
  );
}

// AgentBoard：卡通形式实时展示活动 agent，按 role 分两组卡片墙，2s 轮询。
export default function AgentBoard() {
  const { data, error, updatedAt } = useLiveData(getAgents, 2000);

  if (error) return <p className="muted">加载失败：{error}</p>;
  if (!data) return <p className="muted">加载中…</p>;

  const agents = data.agents;
  const now = Date.now();
  const users = agents.filter((a) => a.role === "user");
  const devs = agents.filter((a) => a.role === "developer");

  return (
    <div>
      <div className="head">
        <h2>AgentBoard</h2>
        <LiveIndicator updatedAt={updatedAt} />
      </div>
      {agents.length === 0 ? (
        <p className="muted">暂无活动 agent（跑闭环后实时出现）</p>
      ) : (
        <>
          <Wall title="用户 Agent" agents={users} now={now} />
          <Wall title="开发者 Agent" agents={devs} now={now} />
        </>
      )}
    </div>
  );
}
