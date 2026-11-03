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
      <div className="block-title">User mental trajectory</div>
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
                <MindCell title="② Intent · Original intent">
                  {intentText}
                </MindCell>
                <MindCell title="③ Act · Chosen action">
                  {`action: ${action}\nmessage: ${message}\ngap: ${gap}`}
                </MindCell>
              </div>
              <div className="mind-meta">
                <span>{turn.executor}/{turn.channel}</span>
                <span>patience {turn.patience}</span>
                <span>trust {turn.trust}</span>
                {steps.length > 0 && <span>Private verification {steps.length} steps</span>}
              </div>
              {steps.length > 0 && (
                <details className="mind-private">
                  <summary>Show private verification ({steps.length} steps)</summary>
                  <ProcessStream log={steps} />
                </details>
              )}
            </details>
          );
        })}
      </div>
      {trace?.signals?.length ? (
        <div className="mind-signals">Signal: {trace.signals.join(" · ")}</div>
      ) : null}
    </div>
  );
}

// Completed user session: prefer the authoritative full session (persona/scenario/user experience/transcript/issue references),
// falling back to archived snapshot turns if unavailable. Issue references link to issue details.
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
          ‹ Back
        </button>
        <span className="role-dot user" />
        <span className="detail-title">{item.label}</span>
        {score != null && <span className={`score s${score}`}>Experience {score}</span>}
      </div>
      <div className="detail-body">
        <dl className="kv">
          <dt>Round</dt>
          <dd>Round {origin?.round_no ?? item.round}</dd>
          {sessionId && <><dt>session</dt><dd>{sessionId}</dd></>}
          {origin && (
            <>
              <dt>Task</dt><dd>{origin.task_id} · {origin.task_kind}</dd>
              <dt>Persona ID</dt><dd>{origin.persona_id}</dd>
              <dt>Interaction method</dt><dd>{origin.interaction}</dd>
              <dt>Slot</dt><dd>{origin.slot}</dd>
              <dt>Harness SHA</dt><dd>{origin.harness_sha}</dd>
              <dt>Task digest</dt><dd>{origin.task_digest}</dd>
            </>
          )}
          <dt>Status</dt>
          <dd>{item.status}</dd>
          {item.end_reason && (
            <>
              <dt>End reason</dt>
              <dd>{item.end_reason}</dd>
            </>
          )}
          {session && (
            <>
              <dt>Time</dt>
              <dd>{fmtDate(session.created_at)}</dd>
            </>
          )}
          {session && session.issue_refs.length > 0 && (
            <>
              <dt>Reported issues</dt>
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
              <dt>Identity</dt>
              <dd>{session.persona.identity}</dd>
              <dt>Proficiency · Domain</dt>
              <dd>
                {session.persona.level} · {session.persona.domain}
              </dd>
              <dt>Goal</dt>
              <dd>{session.persona.goal}</dd>
              <dt>Speaking style</dt>
              <dd>{session.persona.speaking_style}</dd>
            </dl>
          </div>
        )}
        {session && (
          <div className="block">
            <div className="block-title">Scenario</div>
            <div className="prose dim">{session.scenario.description}</div>
          </div>
        )}
        {session && (
          <div className="block">
            <div className="block-title">Experience assessment</div>
            <div className="prose">
              {session.feeling ? (
                <>
                  <span className={`score s${session.feeling.score}`} style={{ marginRight: 8 }}>
                    {session.feeling.score} / 4
                  </span>
                  {session.feeling.reason}
                </>
              ) : (
                <span>Experience data missing ({experience?.status ?? "missing"}): {experience?.reason || "No valid self-assessment recorded"}</span>
              )}
              {experience?.source && <div className="dim">Source: {experience.source}</div>}
            </div>
          </div>
        )}
        <div className="block">
          <div className="block-title">Full conversation</div>
          <Turns turns={turns} />
        </div>
        <MindTrace trace={session?.sim_trace} />
      </div>
    </div>
  );
}
