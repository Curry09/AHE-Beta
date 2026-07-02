import { useEffect, useState } from "react";
import type { Agent, SessionDetail } from "../types";
import { getSession, getSessions } from "../api";
import { health, fmtDur } from "../lib/agentHealth";
import { ROLE_META } from "./pixel";
import { Sprite } from "./Character";
import { TranscriptThread } from "../components/TranscriptThread";

// 右侧详情抽屉：选中居民的实时信息（角色/健康/status/detail/turns），
// 用户居民额外可载入其最新完整会话（场景 + 体感 + 产出 issue）。
export function DetailDrawer({
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

  // 切换居民时清掉旧会话。用户居民自动尝试拉最新会话（按 persona_identity===label 匹配）。
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

  const h = health(agent, now);
  const meta = ROLE_META[agent.role] ?? { cn: agent.role, plate: "#eee", ink: "#555" };
  const updated = new Date(agent.updated_at).getTime();
  const started = agent.started_at ? new Date(agent.started_at).getTime() : updated;
  const timing = agent.running ? `运行 ${fmtDur(now - started)}` : `用时 ${fmtDur(updated - started)}`;

  return (
    <aside className="drawer">
      <button className="drawer-close" onClick={onClose} aria-label="关闭">
        ✕
      </button>
      <div className="drawer-hero">
        <Sprite label={agent.label} role={agent.role} size={64} />
        <div>
          <div className="drawer-name">{agent.label}</div>
          <div className="drawer-role" style={{ background: meta.plate, color: meta.ink }}>
            {meta.cn}
          </div>
          <div className="drawer-meta">
            <span className={`badge ${h.cls}`}>{h.text}</span> · {timing}
          </div>
        </div>
      </div>

      <div className="drawer-status">{agent.status}</div>

      {agent.turns.length > 0 && (
        <section>
          <h4>实时对话</h4>
          <TranscriptThread turns={agent.turns} />
        </section>
      )}

      {agent.detail && (
        <section>
          <h4>细节</h4>
          <pre className="detail">{agent.detail}</pre>
        </section>
      )}

      {sessionErr && <p className="err">会话载入失败：{sessionErr}</p>}
      {session && (
        <section>
          <h4>最新完整会话</h4>
          <p className="muted">{session.scenario.description}</p>
          <div className="reason">体感 {session.feeling.score}/4 · {session.feeling.reason}</div>
          {session.issue_refs.length > 0 && (
            <p className="muted">
              产出 issue：
              {session.issue_refs.map((r) => (
                <a key={r.number} href={r.url} target="_blank" rel="noreferrer" className="chip">
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
