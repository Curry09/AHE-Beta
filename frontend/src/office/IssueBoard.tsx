import type { IssuesResponse } from "../types";

// 中央公告墙左栏：Issue 公告。每条 issue 可点击 → 跳 Gitea 详情页；表头可点击 → 跳看板。
export function IssueBoard({ data }: { data: IssuesResponse | null }) {
  return (
    <section className="board">
      <div className="board-head">
        <span className="board-title">📋 Issue 公告</span>
        {data?.connected && (
          <span className="board-count">{data.issues.length}</span>
        )}
        {data?.board_url && (
          <a className="board-link" href={data.board_url} target="_blank" rel="noreferrer">
            看板 ↗
          </a>
        )}
      </div>
      <div className="board-body">
        {!data ? (
          <p className="empty">载入中…</p>
        ) : !data.connected ? (
          <p className="empty">未连接 Gitea（设 GITEA_URL/OWNER/REPO/TOKEN 后显示）。</p>
        ) : data.issues.length === 0 ? (
          <p className="empty">暂无 open issue。</p>
        ) : (
          <ul className="feed">
            {data.issues.map((i) => (
              <li key={i.number}>
                <a className="feed-row" href={i.url} target="_blank" rel="noreferrer">
                  <span className="feed-num">#{i.number}</span>
                  <span className="feed-title">{i.title}</span>
                  {i.labels.map((l) => (
                    <span key={l} className="tag">
                      {l}
                    </span>
                  ))}
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
