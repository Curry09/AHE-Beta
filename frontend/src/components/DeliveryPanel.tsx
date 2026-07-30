// Spec-0032/T7：交付面面板——open PR 列表 + needs-human 积压告警（vigil 的工作切面，只读观测）。
// 开发者列随 dev 退役撤下：交付进度以 PR 为粒度呈现（票 → PR → 状态），merge 后落 Main 列表。

import type { DeliveryResponse, Pull } from "../types";

const STATE_BADGE: Record<Pull["state"], string> = {
  open: "进行中",
  merged: "已合并",
  closed: "已关闭",
};

export function DeliveryPanel({ delivery }: { delivery: DeliveryResponse | null }) {
  if (!delivery) return null;
  return (
    <>
      <div className="side-section-head">
        交付面 · PR
        {/* needs-human 是无人值守环里唯一要人清的死票队列——非零即高亮告警。 */}
        {delivery.needs_human > 0 && (
          <span
            className="chip"
            style={{ color: "var(--red)", fontWeight: 600 }}
            title="交付面 agent 干不动、主动交人的票/PR 数（去 Gitea 处理后摘 needs-human 标签复活）"
          >
            needs-human {delivery.needs_human}
          </span>
        )}
      </div>
      {!delivery.connected && (
        <div className="disconnected">未连接 Gitea（交付面 PR 列表不可用）。</div>
      )}
      {delivery.connected && delivery.pulls.length === 0 && (
        <div className="empty">暂无进行中的 PR</div>
      )}
      {delivery.pulls.map((p) => (
        <a
          key={p.number}
          className="row"
          href={p.url || undefined}
          target="_blank"
          rel="noreferrer"
          title={`head: ${p.head_branch}`}
        >
          <span className="num">PR#{p.number}</span>
          <span className="row-title">{p.title}</span>
          <span className="chip" title={`状态：${p.state}`}>
            {STATE_BADGE[p.state] ?? p.state}
          </span>
          {p.closes_issues.map((n) => (
            <span key={n} className="chip tag" title="合并后自动关闭的票（closing 关键字）">
              →#{n}
            </span>
          ))}
          {p.mergeable === false && (
            <span className="chip" style={{ color: "var(--amber)" }} title="有冲突，等交付面 rebase">
              冲突
            </span>
          )}
          {p.labels.includes("needs-human") && (
            <span className="chip" style={{ color: "var(--red)" }} title="交付面交人，待处理">
              needs-human
            </span>
          )}
        </a>
      ))}
    </>
  );
}
