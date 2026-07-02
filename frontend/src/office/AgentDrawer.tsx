import { useEffect, useState } from "react";
import type { Agent, SessionDetail } from "../types";
import { getSession, getSessions } from "../api";
import { health, fmtDur } from "../lib/agentHealth";
import { TranscriptThread } from "../components/TranscriptThread";
import { roleMeta } from "./roles";

// 右侧员工详情抽屉：选中员工的实时信息（部门/健康/status/detail/turns）；
// 用户部员工额外尝试载入其最新完整会话（场景 + 体感 + 产出 issue）。
export function AgentDrawer({
  agent,
  now,
  onClose,
}: {
  agent: Agent;
  now: number;
  onClose: () => void;
}) {
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [sessionErr, setSessionErr] = useState<string | null>(null);

  useEffect(() => {
    setSession(null);
    setSessionErr(null);
    if (agent.role !== "user") return;
    let alive = true;
    getSessions()
      .then((rows) => {
        const mine = rows
          .filter((s) => s.persona_identity === agent.label)
          .sort((x, y) => (x.created_at < y.created_at ? 1 : -1));
        if (!mine.length) return;
        return getSession(mine[0].session_id).then((d) => {
          if (alive) setSession(d);
        });
      })
      .catch((e) => alive && setSessionErr(String(e)));
    return () => {
      alive = false;
    };
  }, [agent.agent_id, agent.role, agent.label]);

  const meta = roleMeta(agent.role);
  const h = health(agent, now);
  const fullTurns = session?.transcript.turns ?? null;
  const updated = new Date(agent.updated_at).getTime();
  const started = agent.started_at ? new Date(agent.started_at).getTime() : updated;
  const timing = agent.running ? `运行 ${fmtDur(now - started)}` : `用时 ${fmtDur(updated - started)}`;

  return (
    <aside className="drawer">
      <button className="drawer-close" onClick={onClose} aria-label="关闭">
        ✕
      </button>
      <div className="drawer-hero">
        <span
          className="drawer-avatar"
          style={{ background: `${meta.accent}1a`, color: meta.accent }}
        >
          {meta.emoji}
        </span>
        <div>
          <div className="drawer-name">{agent.label}</div>
          <div className="drawer-dept" style={{ color: meta.accent }}>
            {meta.dept} · {meta.role}
          </div>
          <div className="drawer-meta">
            <span className={`badge ${h.cls}`}>{h.text}</span> · {timing}
          </div>
        </div>
      </div>

      <div className="drawer-status">{agent.status}</div>

      {session && (
        <details className="persona" open>
          <summary>
            <span className="persona-title">用户 Persona</span>
            <span className="persona-sub">{session.persona.identity}</span>
          </summary>
          <dl className="persona-grid">
            <dt>身份</dt>
            <dd>{session.persona.identity}</dd>
            <dt>水平</dt>
            <dd>{session.persona.level}</dd>
            <dt>领域</dt>
            <dd>{session.persona.domain}</dd>
            <dt>目标</dt>
            <dd>{session.persona.goal}</dd>
            <dt>说话风格</dt>
            <dd>{session.persona.speaking_style}</dd>
          </dl>
        </details>
      )}

      {fullTurns && fullTurns.length > 0 ? (
        <section>
          <h4>完整对话记录（{fullTurns.length} 轮）</h4>
          <TranscriptThread turns={fullTurns} />
        </section>
      ) : agent.turns.length > 0 ? (
        <section>
          <h4>实时对话（进行中 · {agent.turns.length} 轮）</h4>
          <TranscriptThread turns={agent.turns} />
        </section>
      ) : null}

      {agent.detail && (
        <section>
          <h4>细节</h4>
          <pre className="detail">{agent.detail}</pre>
        </section>
      )}

      {sessionErr && <p className="err">会话载入失败：{sessionErr}</p>}
      {session && (
        <section>
          <h4>会话信息</h4>
          <p className="muted">{session.scenario.description}</p>
          <div className="reason">
            体感 {session.feeling.score}/4 · {session.feeling.reason}
          </div>
          {session.issue_refs.length > 0 && (
            <p className="muted">
              产出 issue：
              {session.issue_refs.map((r) => (
                <a key={r.number} href={r.url} target="_blank" rel="noreferrer" className="tag">
                  #{r.number}
                </a>
              ))}
            </p>
          )}
        </section>
      )}
    </aside>
  );
}
