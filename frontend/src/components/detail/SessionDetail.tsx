import { getSession } from "../../api";
import { useFetch } from "../../hooks/useFetch";
import { fmtDate } from "../../lib/format";
import type { HistoryItem, Selection } from "../../types";
import { Turns } from "../Stream";

// 已完成用户会话：优先拉权威全量 session（persona/scenario/体感/transcript/issue 引用），
// 拉不到时回退归档快照的 turns。issue 引用可点跳 issue 详情。
export function SessionDetailView(props: {
  item: HistoryItem;
  onSelect: (sel: Selection) => void;
  onBack: () => void;
}) {
  const { item, onSelect, onBack } = props;
  const sessionId = item.session_id ?? null;
  const session = useFetch(sessionId ? () => getSession(sessionId) : null, [sessionId]);

  const turns = session?.transcript.turns ?? item.turns;
  const score = session?.feeling.score ?? item.score;

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
          <dd>第 {item.round} 轮</dd>
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
              <dt>persona</dt>
              <dd>
                {session.persona.identity} · {session.persona.level} · {session.persona.domain}
              </dd>
              <dt>目标</dt>
              <dd>{session.persona.goal}</dd>
              <dt>说话风格</dt>
              <dd>{session.persona.speaking_style}</dd>
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
            <div className="block-title">场景</div>
            <div className="prose dim">{session.scenario.description}</div>
          </div>
        )}
        {session && (
          <div className="block">
            <div className="block-title">体感评价</div>
            <div className="prose">
              <span className={`score s${session.feeling.score}`}>
                {session.feeling.score} / 4
              </span>
              　{session.feeling.reason}
            </div>
          </div>
        )}
        <div className="block">
          <div className="block-title">完整对话</div>
          <Turns turns={turns} />
        </div>
      </div>
    </div>
  );
}
