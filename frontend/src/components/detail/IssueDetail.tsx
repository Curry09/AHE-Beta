import { getIssue } from "../../api";
import { useFetch } from "../../hooks/useFetch";
import { fmtDate } from "../../lib/format";
import {
  issueKind,
  planeOf,
  priorityOf,
  provenanceOf,
  roundOf,
  terminalOf,
  triageStatus,
} from "../../lib/issueMeta";
import type { IssueComment } from "../../types";
import { Markdown } from "../Markdown";
import { buildIssueTimelineView } from "./issueTimelineModel";

// triage 状态 → 中文标签（展示用）。
const STATUS_LABEL: Record<string, string> = {
  "needs-triage": "待 triage",
  triaged: "已 triage（可执行）",
  rejected: "已驳回",
  "needs-info": "信息不足",
  superseded: "被 RFC 取代",
};

// Spec-0020/T5：详情页覆盖关系直接从已有数据推导（零新端点）——
// covers 解析 body 的机器行（T1 产出，最后一条为准）；covered_by 解析 T1 挂的 covered-by 评论。
function parseCovers(body: string): number[] {
  const lines = [...(body ?? "").matchAll(/^covers:((?:\s*#\d+)+)\s*$/gm)];
  if (lines.length === 0) return [];
  const last = lines[lines.length - 1][1];
  return [...last.matchAll(/#(\d+)/g)].map((m) => Number(m[1]));
}

function coveredByFrom(comments: IssueComment[]): number | null {
  for (let i = comments.length - 1; i >= 0; i--) {
    const m = /^covered-by:\s*#(\d+)\s*$/.exec((comments[i].body ?? "").trim());
    if (m) return Number(m[1]);
  }
  return null;
}

// issue 全量：标题/labels/状态/正文 + 评论时间线（含 dev 关闭时留的推进说明）。
export function IssueDetailView(props: { number: number; onBack: () => void }) {
  const { number, onBack } = props;
  const data = useFetch(() => getIssue(number), [number]);
  const issue = data?.issue ?? null;
  const covers = issue ? parseCovers(issue.body) : [];
  const coveredBy = coveredByFrom(data?.comments ?? []);
  // 详情端点不附平台层派生字段（那是 /api/issues 列表口径）——这里按 labels 客户端推导。
  const kind = issue ? issueKind(issue) : "";
  const status = issue ? triageStatus(issue) : null;
  const prio = issue ? priorityOf(issue) : null;
  const round = issue ? roundOf(issue) : null;
  // Spec-0029/T10：三平面/来源/终态。
  const pl = issue ? planeOf(issue) : null;
  const prov = issue ? provenanceOf(issue) : null;
  const terminal = issue ? terminalOf(issue) : null;
  const timelineView = issue ? buildIssueTimelineView(issue, data?.timeline) : null;
  const delivery = issue?.labels.includes("needs-human")
    ? "阻塞 · needs-human"
    : issue?.labels.includes("ready")
      ? "执行中 · ready"
      : issue?.labels.includes("openagents")
        ? "待 intake · openagents"
        : "—";
  const planeLabel: Record<string, string> = {
    report: "报告（待分诊）",
    proposal: "提案（待准入）",
    ready: "Ready（可领）",
  };

  return (
    <div className="detail">
      <div className="detail-head">
        <button className="back" onClick={onBack}>
          ‹ 返回
        </button>
        <span className="detail-title">
          #{number} {issue?.title ?? ""}
        </span>
        {issue && <span className={`chip ${issue.state}`}>{issue.state}</span>}
      </div>
      <div className="detail-body">
        {!data && <div className="empty">加载中…</div>}
        {data && !data.connected && (
          <div className="disconnected">未连接 Gitea，看不到 issue 详情。</div>
        )}
        {data && issue && (
          <>
            <div className="issue-dimensions" aria-label="issue 当前状态维度">
              <div className="issue-dimension">
                <span>平面</span>
                <strong>{pl ? (planeLabel[pl] ?? pl) : terminal ? `终态 · ${terminal}` : "—"}</strong>
              </div>
              <div className="issue-dimension">
                <span>来源</span>
                <strong>{prov ?? "—"}</strong>
              </div>
              <div className="issue-dimension">
                <span>优先级</span>
                <strong>{prio ?? "—"}</strong>
              </div>
              <div className="issue-dimension">
                <span>产生轮次</span>
                <strong>{round == null ? "—" : `round-${round}`}</strong>
              </div>
              <div className="issue-dimension">
                <span>交付</span>
                <strong>{delivery}</strong>
              </div>
              <div className="issue-dimension">
                <span>类型 / 分诊</span>
                <strong>{status ? `${kind} · ${STATUS_LABEL[status] ?? status}` : kind}</strong>
              </div>
            </div>

            {timelineView && timelineView.anomalies.length > 0 && (
              <div className="timeline-alerts" role="alert">
                <div className="block-title">状态完整性告警 · {timelineView.anomalies.length}</div>
                {timelineView.anomalies.map((anomaly) => (
                  <div key={anomaly.id} className={`timeline-alert ${anomaly.severity}`}>
                    <strong>{anomaly.code}</strong>
                    <span>{anomaly.message}</span>
                  </div>
                ))}
                {Object.values(timelineView.lastKnown).some((value) => value != null) && (
                  <div className="timeline-compare">
                    <span>
                      历史最后已知：{timelineView.lastKnown.plane ?? "—"} ·{" "}
                      {timelineView.lastKnown.provenance ?? "—"} ·{" "}
                      {timelineView.lastKnown.priority ?? "—"} ·{" "}
                      {timelineView.lastKnown.round == null
                        ? "—"
                        : `round-${timelineView.lastKnown.round}`}
                    </span>
                    <span>
                      当前 Gitea：{pl ?? terminal ?? "无平面"} · {prov ?? "无来源"} ·{" "}
                      {prio ?? "无优先级"} · {round == null ? "无轮次" : `round-${round}`}
                    </span>
                  </div>
                )}
              </div>
            )}

            <div className="block issue-timeline-block">
              <div className="block-title">
                状态演进
                {timelineView?.available && !timelineView.complete && (
                  <span className="timeline-confidence">历史不完整</span>
                )}
              </div>
              {!timelineView?.available && (
                <div className="timeline-unavailable">
                  标签时间线不可用：{timelineView?.unavailableReason ?? "未知原因"}
                </div>
              )}
              {timelineView?.available && timelineView.transitions.length === 0 && (
                <div className="empty">尚未观测到标签迁移</div>
              )}
              {timelineView?.available && timelineView.transitions.length > 0 && (
                <div className="issue-timeline">
                  {timelineView.transitions.map((transition) => {
                    const raw = data.timeline?.transitions.find((item) => item.id === transition.id);
                    return (
                      <div key={transition.id} className={`timeline-step ${transition.severity}`}>
                        <div className="timeline-marker" />
                        <div className="timeline-step-body">
                          <div className="timeline-step-head">
                            <strong>{transition.title}</strong>
                            <span>{fmtDate(transition.createdAt)}</span>
                            <span>{transition.actor || "未知操作者"}</span>
                          </div>
                          <div className="timeline-state-change">
                            <span>{transition.from}</span>
                            <b>→</b>
                            <span>{transition.to}</span>
                          </div>
                          <div className="timeline-label-change">
                            {transition.added.map((label) => (
                              <code key={`add-${label}`} className="label-add">
                                +{label}
                              </code>
                            ))}
                            {transition.removed.map((label) => (
                              <code key={`remove-${label}`} className="label-remove">
                                -{label}
                              </code>
                            ))}
                          </div>
                          {raw && (
                            <details className="timeline-debug">
                              <summary>状态快照</summary>
                              <pre>{JSON.stringify({ before: raw.before, after: raw.after }, null, 2)}</pre>
                            </details>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            <dl className="kv issue-secondary-meta">
              {coveredBy != null && (
                <>
                  <dt>覆盖于</dt>
                  <dd>
                    <span className="chip" title={`已被设计票 #${coveredBy} 覆盖`}>
                      ⊂ #{coveredBy}
                    </span>
                  </dd>
                </>
              )}
              {covers.length > 0 && (
                <>
                  <dt>覆盖</dt>
                  <dd>
                    {covers.map((n) => (
                      <span key={n} className="chip" style={{ marginRight: 4 }}>
                        #{n}
                      </span>
                    ))}
                  </dd>
                </>
              )}
              <dt>创建</dt>
              <dd>{fmtDate(issue.created_at)}</dd>
              {issue.closed_at && (
                <>
                  <dt>关闭</dt>
                  <dd>{fmtDate(issue.closed_at)}</dd>
                </>
              )}
              {issue.url && (
                <>
                  <dt>Gitea</dt>
                  <dd>
                    <a className="link" href={issue.url} target="_blank" rel="noreferrer">
                      打开 ↗
                    </a>
                  </dd>
                </>
              )}
            </dl>
            <div className="block">
              <div className="block-title">正文</div>
              {issue.body ? <Markdown>{issue.body}</Markdown> : <div className="prose">（无正文）</div>}
            </div>
            <div className="block">
              <div className="block-title">评论 · {data.comments.length}</div>
              {data.comments.length === 0 && <div className="empty">暂无评论</div>}
              <div className="turns">
                {data.comments.map((c, i) => (
                  <div key={i} className="comment">
                    <div className="who">
                      {c.author}
                      <span className="when">{fmtDate(c.created_at)}</span>
                    </div>
                    <Markdown dim>{c.body}</Markdown>
                  </div>
                ))}
              </div>
            </div>
            <details className="block issue-debug">
              <summary>Debug · 原始标签与事件</summary>
              <div className="debug-label-groups">
                {(timelineView?.groups ?? []).map((group) => (
                  <div key={group.key}>
                    <span>{group.label}</span>
                    <div>
                      {group.labels.map((label) => (
                        <code key={label}>{label}</code>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              {(data.timeline?.events.length ?? 0) > 0 && (
                <div className="raw-events">
                  {data.timeline?.events.map((event, index) => (
                    <div key={`${event.id ?? "event"}-${index}`}>
                      <span>{fmtDate(event.created_at)}</span>
                      <span>{event.actor || "—"}</span>
                      <code>
                        {event.operation === "unknown"
                          ? event.type
                          : `${event.operation === "add" ? "+" : "-"}${event.label}`}
                      </code>
                    </div>
                  ))}
                </div>
              )}
            </details>
          </>
        )}
      </div>
    </div>
  );
}
