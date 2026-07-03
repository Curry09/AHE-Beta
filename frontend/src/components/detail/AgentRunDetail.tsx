import type { ReactNode } from "react";
import type { AgentRole, Commit, LogEntry, Selection, Turn } from "../../types";
import { ProcessStream, Turns } from "../Stream";

// dev/designer 的一段工作（live 槽位或归档快照），以及 live 用户 agent 的会话中间态：
// 元信息 + 完整对话/过程流 + 最终报告，issue/tag 可交叉跳转。
export function AgentRunDetail(props: {
  role: AgentRole;
  label: string;
  running?: boolean;
  status: string;
  round: number | null;
  turns: Turn[];
  log: LogEntry[];
  detail: string | null;
  issueNumber?: number | null;
  tag?: string | null;
  committed?: boolean;
  proposals?: number[];
  score?: number | null;
  endReason?: string;
  commits: Commit[];
  onSelect: (sel: Selection) => void;
  onBack: () => void;
}) {
  const {
    role,
    label,
    running,
    status,
    round,
    turns,
    log,
    detail,
    issueNumber,
    tag,
    committed,
    proposals,
    score,
    endReason,
    commits,
    onSelect,
    onBack,
  } = props;

  const tagCommit = tag ? commits.find((c) => c.tags.includes(tag)) : undefined;

  const rows: [string, ReactNode][] = [];
  if (round != null && round > 0) rows.push(["轮次", `第 ${round} 轮`]);
  rows.push(["状态", status]);
  if (score != null) rows.push(["体感", <span className={`score s${score}`}>{score} / 4</span>]);
  if (endReason) rows.push(["结束原因", endReason]);
  if (issueNumber != null)
    rows.push([
      "issue",
      <button className="link" onClick={() => onSelect({ type: "issue", number: issueNumber })}>
        #{issueNumber}
      </button>,
    ]);
  if (tag)
    rows.push([
      "tag",
      tagCommit ? (
        <button className="link" onClick={() => onSelect({ type: "commit", sha: tagCommit.sha })}>
          {tag} · {tagCommit.short_sha}
        </button>
      ) : (
        <span className="chip tag">{tag}</span>
      ),
    ]);
  if (committed !== undefined) rows.push(["main", committed ? "已推进" : "未推进"]);
  if (proposals && proposals.length > 0)
    rows.push([
      "提案",
      <span>
        {proposals.map((n) => (
          <button key={n} className="link" onClick={() => onSelect({ type: "issue", number: n })}>
            #{n}
          </button>
        ))}
      </span>,
    ]);

  return (
    <div className="detail">
      <div className="detail-head">
        <button className="back" onClick={onBack}>
          ‹ 返回
        </button>
        {running ? <span className="dot on" /> : <span className={`role-dot ${role}`} />}
        <span className="detail-title">{label}</span>
      </div>
      <div className="detail-body">
        <dl className="kv">
          {rows.map(([k, v], i) => (
            <div key={i} style={{ display: "contents" }}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
        {turns.length > 0 && (
          <div className="block">
            <div className="block-title">对话</div>
            <Turns turns={turns} />
          </div>
        )}
        <div className="block">
          <div className="block-title">工作过程</div>
          <ProcessStream log={log} />
        </div>
        {detail && (
          <div className="block">
            <div className="block-title">最终报告</div>
            <div className="prose">{detail}</div>
          </div>
        )}
      </div>
    </div>
  );
}
