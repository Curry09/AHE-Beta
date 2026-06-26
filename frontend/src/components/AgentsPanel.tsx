import { getAgents } from "../api";
import { useLiveData } from "../hooks/useLiveData";
import type { Agent } from "../types";
import { TranscriptThread } from "./TranscriptThread";

// 单个 agent 行：默认折叠（原生 <details>），点击展开看对话/开发详情。绿点=运行中。
function AgentRow({ a }: { a: Agent }) {
  return (
    <details className="agent-row">
      <summary>
        <span className={a.running ? "dot run" : "dot"} />
        <b className="agent-label">{a.label}</b>
        <span className="muted agent-status">{a.status}</span>
      </summary>
      <div className="agent-body">
        {a.turns.length > 0 && <TranscriptThread turns={a.turns} />}
        {a.detail && <pre className="detail">{a.detail}</pre>}
        {a.turns.length === 0 && !a.detail && <p className="muted">（暂无展开内容）</p>}
      </div>
    </details>
  );
}

function Group({ title, agents }: { title: string; agents: Agent[] }) {
  const runningCount = agents.filter((a) => a.running).length;
  return (
    <div className="agent-group">
      <h3>
        {title}（{agents.length}）
        {runningCount > 0 && <span className="live"> · {runningCount} 运行中</span>}
      </h3>
      {agents.length === 0 ? (
        <p className="muted">暂无</p>
      ) : (
        agents.map((a) => <AgentRow key={a.agent_id} a={a} />)
      )}
    </div>
  );
}

// 全 agent 活动面板：按用户/开发者分两组，2s 轮询，置于 shell 顶部全页可见。
export function AgentsPanel() {
  const { data } = useLiveData(getAgents, 2000);
  const agents = data?.agents ?? [];
  if (agents.length === 0) return null;

  const users = agents.filter((a) => a.role === "user");
  const devs = agents.filter((a) => a.role === "developer");
  return (
    <div className="panel agents-panel">
      <div className="head">
        <h2 className="panel-title">Agent 活动</h2>
        <span className="live">● 实时</span>
      </div>
      <Group title="用户 Agent" agents={users} />
      <Group title="开发者 Agent" agents={devs} />
    </div>
  );
}
