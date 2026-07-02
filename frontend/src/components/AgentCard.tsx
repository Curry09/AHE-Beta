import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { Agent } from "../types";
import { getSessions } from "../api";
import { health, fmtDur } from "../lib/agentHealth";
import { avatarFor } from "../lib/avatar";
import { TranscriptThread } from "./TranscriptThread";

const ROLE_CN: Record<string, string> = { user: "用户 Agent", developer: "开发者 Agent" };

// 单个 agent 的卡通卡：emoji 头像 + 身份 + status + 按健康态驱动的动画；点击按 role 分派。
export function AgentCard({ a, now }: { a: Agent; now: number }) {
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const h = health(a, now);
  const { face, badge } = avatarFor(a.label, a.role);

  const updated = new Date(a.updated_at).getTime();
  const started = a.started_at ? new Date(a.started_at).getTime() : updated; // 容旧数据缺 started_at
  const timing = a.running
    ? `运行 ${fmtDur(now - started)}`
    : `用时 ${fmtDur(updated - started)}`;

  // 用户卡：按 persona_identity===label 找最新会话跳转；无匹配则降级为就地展开，不报错。
  // 开发者卡：无会话可跳，就地展开 status/detail。
  async function onClick() {
    if (a.role !== "user") {
      setOpen((v) => !v);
      return;
    }
    try {
      const sessions = await getSessions();
      const mine = sessions
        .filter((s) => s.persona_identity === a.label)
        .sort((x, y) => (x.created_at < y.created_at ? 1 : -1));
      if (mine.length > 0) {
        nav(`/sessions/${mine[0].session_id}`);
        return;
      }
    } catch {
      // 拉取失败 → 降级展开
    }
    setOpen((v) => !v);
  }

  return (
    <div className="agent-card">
      <button className="agent-card-face" onClick={onClick} title={a.status}>
        <span className={`avatar anim-${h.cls}`}>
          <span className="avatar-face">{face}</span>
          <span className="avatar-badge">{h.cls === "idle" ? "😴" : badge}</span>
        </span>
        <b className="agent-card-label">{a.label}</b>
        <span className="agent-card-role">{ROLE_CN[a.role] ?? a.role}</span>
        <span className={`badge ${h.cls}`}>{h.text}</span>
        <span className="agent-card-status muted">{a.status}</span>
        <span className="agent-card-timing">{timing}</span>
      </button>
      {open && (
        <div className="agent-card-body">
          {a.turns.length > 0 && <TranscriptThread turns={a.turns} />}
          {a.detail && <pre className="detail">{a.detail}</pre>}
          {a.turns.length === 0 && !a.detail && <p className="muted">（暂无展开内容）</p>}
        </div>
      )}
    </div>
  );
}
