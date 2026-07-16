import { getIssue } from "../../api";
import { useFetch } from "../../hooks/useFetch";
import { fmtDate } from "../../lib/format";
import type { IssueComment } from "../../types";

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
            <dl className="kv">
              {issue.labels.length > 0 && (
                <>
                  <dt>labels</dt>
                  <dd>
                    {issue.labels.map((l) => (
                      <span key={l} className="chip" style={{ marginRight: 4 }}>
                        {l}
                      </span>
                    ))}
                  </dd>
                </>
              )}
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
              <div className="prose">{issue.body || "（无正文）"}</div>
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
                    <div className="prose dim">{c.body}</div>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
