import { getSession } from "../../api";
import { useFetch } from "../../hooks/useFetch";
import { fmtDate } from "../../lib/format";
import type { HistoryItem, Selection, SimTrace, SimTurn } from "../../types";
import { ProcessStream, Turns } from "../Stream";

function traceFor(turn: SimTurn, role: string) {
  return (turn.persona_trace ?? []).find((call) => call.role === role)?.parsed ?? {};
}

function textValue(value: unknown, fallback = "—"): string {
  if (value == null) return fallback;
  if (typeof value === "string") return value.trim() || fallback;
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return String(value);
  return JSON.stringify(value);
}

function privateSteps(turn: SimTurn) {
  return (turn.persona_trace ?? []).flatMap((call) => call.steps ?? []);
}

function shortText(text: string, limit = 86): string {
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > limit ? `${clean.slice(0, limit)}…` : clean;
}

function MindCell(props: { title: string; children: string; defaultOpen?: boolean }) {
  return (
    <details className="mind-cell" open={props.defaultOpen}>
      <summary>{props.title}</summary>
      <div className="mind-cell-body">{props.children || "—"}</div>
    </details>
  );
}

function MindTrace({ trace }: { trace: SimTrace | null | undefined }) {
  const turns = trace?.turns ?? [];
  if (turns.length === 0) return null;
  return (
    <div className="block">
      <div className="block-title">用户心智轨迹</div>
      <div className="mind-trace">
        {turns.map((turn) => {
          const prefix = turn.phase === "waiting" ? "waiting" : "main";
          const judge = traceFor(turn, `${prefix}_judge`);
          const intent = traceFor(turn, `${prefix}_intent`);
          const act = traceFor(turn, `${prefix}_act`);
          const judgeLabel = prefix === "waiting" ? "Judgment" : "Verdict";
          const judgeText = textValue(judge.perceive, textValue(turn.perceive.replace(/^\[[^\]]+\]\s*/, "")));
          const verdict = textValue(judge.verdict ?? judge.judgment, turn.verdict || "—");
          const intentText = textValue(intent.intent);
          const action = textValue(act.action, turn.action || "—");
          const message = textValue(act.message, turn.message ? turn.message : "(empty)");
          const gap = textValue(act.gap);
          const steps = privateSteps(turn);
          return (
            <details key={`${turn.phase}-${turn.turn}-${turn.action}`} className="mind-turn">
              <summary className="mind-summary">
                <span>#{turn.turn}</span>
                <b>{turn.phase}</b>
                <em>{verdict}</em>
                <i>intent {shortText(intentText)}</i>
                <strong>act {action}</strong>
              </summary>
              <div className="mind-grid">
                <MindCell title={`① Judge · ${judgeLabel} ${verdict}`} defaultOpen>
                  {judgeText}
                </MindCell>
                <MindCell title="② Intent · 原始愿望">
                  {intentText}
                </MindCell>
                <MindCell title="③ Act · 动作收敛">
                  {`action: ${action}\nmessage: ${message}\ngap: ${gap}`}
                </MindCell>
              </div>
              <div className="mind-meta">
                <span>{turn.executor}/{turn.channel}</span>
                <span>patience {turn.patience}</span>
                <span>trust {turn.trust}</span>
                {steps.length > 0 && <span>私有核实 {steps.length} 步</span>}
              </div>
              {steps.length > 0 && (
                <details className="mind-private">
                  <summary>展开私有核实过程（{steps.length} 步）</summary>
                  <ProcessStream log={steps} />
                </details>
              )}
            </details>
          );
        })}
      </div>
      {trace?.signals?.length ? (
        <div className="mind-signals">信号：{trace.signals.join(" · ")}</div>
      ) : null}
    </div>
  );
}

// 已完成用户会话：优先拉权威全量 session（persona/scenario/体感/transcript/issue 引用），
// 拉不到时回退归档快照的 turns。issue 引用可点跳 issue 详情。
export function SessionDetailView(props: {
  item: HistoryItem;
  onSelect: (sel: Selection) => void;
  onBack: () => void;
}) {
  const { item, onSelect, onBack } = props;
  const sessionId = item.session_id ?? null;
  const loaded = useFetch(sessionId ? () => getSession(sessionId) : null, [sessionId]);
  const session = loaded?.session_id === sessionId ? loaded : null;

  const turns = session?.transcript.turns ?? item.turns;
  // Spec-0084/T1: a loaded missing rating is authoritative, even if history has a stale score.
  const score = session ? session.feeling?.score : item.score;
  const experience = session?.feedback?.experience;
  const origin = session?.session_provenance ?? item.session_provenance;

  return (
    <div className="detail">
      <div className="detail-head">
        <button className="back" onClick={onBack}>
          ‹ 返回
        </button>
        <span className="role-dot user" />
        <span className="detail-title">{item.label}</span>
        {score != null && <span className={`score s${score}`}>体感 {score}</span>}
      </div>
      <div className="detail-body">
        <dl className="kv">
          <dt>轮次</dt>
          <dd>第 {origin?.round_no ?? item.round} 轮</dd>
          {sessionId && <><dt>会话</dt><dd>{sessionId}</dd></>}
          {origin && (
            <>
              <dt>任务</dt><dd>{origin.task_id} · {origin.task_kind}</dd>
              <dt>Persona ID</dt><dd>{origin.persona_id}</dd>
              <dt>交互方式</dt><dd>{origin.interaction}</dd>
              <dt>槽位</dt><dd>{origin.slot}</dd>
              <dt>Harness SHA</dt><dd>{origin.harness_sha}</dd>
              <dt>任务摘要</dt><dd>{origin.task_digest}</dd>
            </>
          )}
          <dt>状态</dt>
          <dd>{item.status}</dd>
          {item.end_reason && (
            <>
              <dt>结束原因</dt>
              <dd>{item.end_reason}</dd>
            </>
          )}
          {session && (
            <>
              <dt>时间</dt>
              <dd>{fmtDate(session.created_at)}</dd>
            </>
          )}
          {session && session.issue_refs.length > 0 && (
            <>
              <dt>提的 issue</dt>
              <dd>
                {session.issue_refs.map((ref) => (
                  <button
                    key={ref.number}
                    className="link"
                    onClick={() => onSelect({ type: "issue", number: ref.number })}
                  >
                    #{ref.number}
                  </button>
                ))}
              </dd>
            </>
          )}
        </dl>
        {session && (
          <div className="block">
            <div className="block-title">Persona</div>
            <dl className="kv">
              <dt>身份</dt>
              <dd>{session.persona.identity}</dd>
              <dt>水平 · 领域</dt>
              <dd>
                {session.persona.level} · {session.persona.domain}
              </dd>
              <dt>目标</dt>
              <dd>{session.persona.goal}</dd>
              <dt>说话风格</dt>
              <dd>{session.persona.speaking_style}</dd>
            </dl>
          </div>
        )}
        {session && (
          <div className="block">
            <div className="block-title">场景</div>
            <div className="prose dim">{session.scenario.description}</div>
          </div>
        )}
        {session && (
          <div className="block">
            <div className="block-title">体感评价</div>
            <div className="prose">
              {session.feeling ? (
                <>
                  <span className={`score s${session.feeling.score}`} style={{ marginRight: 8 }}>
                    {session.feeling.score} / 4
                  </span>
                  {session.feeling.reason}
                </>
              ) : (
                <span>体感缺测（{experience?.status ?? "missing"}）：{experience?.reason || "未记录有效自评"}</span>
              )}
              {experience?.source && <div className="dim">来源：{experience.source}</div>}
            </div>
          </div>
        )}
        <div className="block">
          <div className="block-title">完整对话</div>
          <Turns turns={turns} />
        </div>
        <MindTrace trace={session?.sim_trace} />
      </div>
    </div>
  );
}
