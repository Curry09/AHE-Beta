import { getAgents } from "../api";
import { useLiveData } from "../hooks/useLiveData";
import type { Agent } from "../types";
import { TranscriptThread } from "./TranscriptThread";

const STALE_MS = 330_000; // 运行中但超过此时长无更新 → 疑似卡顿（已超过 300s per-call 超时）

function fmtDur(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  return m > 0 ? `${m}m${s % 60}s` : `${s}s`;
}

// 健康状态：异常 > 卡顿 > 运行 > 完成/空闲。
function health(a: Agent, now: number): { cls: string; text: string } {
  if (/\[harness error\]|error|否决|未过/i.test(a.status)) return { cls: "err", text: "异常" };
  if (a.running) {
    const stale = now - new Date(a.updated_at).getTime();
    if (stale > STALE_MS) return { cls: "warn", text: "卡顿?" };
    return { cls: "ok", text: "运行中" };
  }
  return { cls: "idle", text: "完成" };
}

function AgentRow({ a, now }: { a: Agent; now: number }) {
  const updated = new Date(a.updated_at).getTime();
  const started = a.started_at ? new Date(a.started_at).getTime() : updated; // 容旧数据缺 started_at
  const h = health(a, now);
  const timing = a.running
    ? `运行 ${fmtDur(now - started)} · 更新 ${fmtDur(now - updated)}前`
    : `用时 ${fmtDur(updated - started)}`;
  return (
    <details className="agent-row">
      <summary>
        <span className={`dot ${h.cls}`} title={h.text} />
        <b className="agent-label">{a.label}</b>
        <span className={`badge ${h.cls}`}>{h.text}</span>
        <span className="muted agent-status">{a.status}</span>
        <span className="agent-timing">{timing}</span>
      </summary>
      <div className="agent-body">
        {a.turns.length > 0 && <TranscriptThread turns={a.turns} />}
        {a.detail && <pre className="detail">{a.detail}</pre>}
        {a.turns.length === 0 && !a.detail && <p className="muted">（暂无展开内容）</p>}
      </div>
    </details>
  );
}

function Group({ title, agents, now }: { title: string; agents: Agent[]; now: number }) {
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
        agents.map((a) => <AgentRow key={a.agent_id} a={a} now={now} />)
      )}
    </div>
  );
}

// 全 agent 活动面板：按用户/开发者分两组，2s 轮询，显示健康状态 + 运行时长，折叠可展开。
export function AgentsPanel() {
  const { data } = useLiveData(getAgents, 2000);
  const agents = data?.agents ?? [];
  if (agents.length === 0) return null;

  const now = Date.now();
  const users = agents.filter((a) => a.role === "user");
  const devs = agents.filter((a) => a.role === "developer");
  return (
    <div className="panel agents-panel">
      <div className="head">
        <h2 className="panel-title">Agent 活动</h2>
        <span className="live">● 实时</span>
      </div>
      <Group title="用户 Agent" agents={users} now={now} />
      <Group title="开发者 Agent" agents={devs} now={now} />
    </div>
  );
}
