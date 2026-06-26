import { getLive } from "../api";
import { useLiveData } from "../hooks/useLiveData";

// 进行中会话：每 2s 轮询 /api/live，逐轮流式渲染；末轮为 user 即 harness 回复中。
export function LiveSessionCard() {
  const { data } = useLiveData(getLive, 2000);
  if (!data || !data.active || !data.turns || data.turns.length === 0) return null;

  const turns = data.turns;
  const awaiting = turns[turns.length - 1].role === "user";

  return (
    <div className="panel live-card">
      <div className="head">
        <h3>● 进行中会话（流式）</h3>
        <span className="live">{data.persona_identity} · 实时</span>
      </div>
      {data.scenario && <p className="muted">{data.scenario}</p>}
      <div>
        {turns.map((t, i) => (
          <div key={i} className={`bubble ${t.role}`}>
            <strong>{t.role === "user" ? "用户" : "harness"}</strong>
            <div>
              {t.content?.trim() ? (
                t.content
              ) : (
                <span className="muted">（空回复）</span>
              )}
            </div>
          </div>
        ))}
        {awaiting && (
          <div className="bubble harness">
            <strong>harness</strong>
            <div className="muted typing">回复中…</div>
          </div>
        )}
      </div>
    </div>
  );
}
