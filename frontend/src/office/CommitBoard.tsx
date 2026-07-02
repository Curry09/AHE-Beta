import type { CommitsResponse } from "../types";

// 相对时间：把 ISO 时间转成「2m前 / 3h前 / 5d前」。非法/缺失显示占位。
function ago(iso: string, now: number): string {
  const t = new Date(iso).getTime();
  if (!iso || Number.isNaN(t)) return "";
  const s = Math.max(0, Math.floor((now - t) / 1000));
  if (s < 60) return `${s}s前`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h前`;
  return `${Math.floor(h / 24)}d前`;
}

// 中央公告墙右栏：main 分支更新（最近 commit + vK tag）。每条可点击 → 跳 Gitea commit 详情。
export function CommitBoard({ data, now }: { data: CommitsResponse | null; now: number }) {
  return (
    <section className="board">
      <div className="board-head">
        <span className="board-title">🌿 main 分支更新</span>
        {data?.connected && <span className="board-count">{data.commits.length}</span>}
        {data?.commits_url && (
          <a className="board-link" href={data.commits_url} target="_blank" rel="noreferrer">
            提交历史 ↗
          </a>
        )}
      </div>
      <div className="board-body">
        {!data ? (
          <p className="empty">载入中…</p>
        ) : !data.connected ? (
          <p className="empty">未连接 Gitea（设 GITEA_URL/OWNER/REPO 后显示 harness 仓提交）。</p>
        ) : data.commits.length === 0 ? (
          <p className="empty">main 暂无提交。</p>
        ) : (
          <ul className="feed">
            {data.commits.map((c) => (
              <li key={c.sha}>
                <a className="feed-row" href={c.url} target="_blank" rel="noreferrer">
                  {c.tags.map((t) => (
                    <span key={t} className="tag ver">
                      {t}
                    </span>
                  ))}
                  <span className="feed-title">{c.message || "(无提交信息)"}</span>
                  <span className="feed-meta">
                    <code>{c.short_sha}</code>
                    {c.author && <span> · {c.author}</span>}
                    {c.date && <span> · {ago(c.date, now)}</span>}
                  </span>
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
