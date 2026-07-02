import type { CommitsResponse } from "../types";

export default function CommitsPanel(props: { data: CommitsResponse | null }) {
  const { data } = props;
  return (
    <section className="board">
      <div className="board-head">
        <span className="board-title">main 分支</span>
        {data && <span className="board-count">{data.commits.length}</span>}
        {data?.commits_url && (
          <a className="board-link" href={data.commits_url} target="_blank" rel="noreferrer">
            Gitea ↗
          </a>
        )}
      </div>
      <div className="board-body">
        {!data && <div className="empty">加载中…</div>}
        {data && !data.connected && <div className="empty">未连接仓库</div>}
        {data?.connected && data.commits.length === 0 && <div className="empty">暂无 commit</div>}
        <ul className="feed">
          {data?.commits.map((c) => (
            <li key={c.sha}>
              <a className="feed-row" href={c.url} target="_blank" rel="noreferrer">
                <span className="feed-num">{c.short_sha}</span>
                <span className="feed-title">{c.message}</span>
                <span className="feed-meta">
                  {c.author} · {c.date}
                  {c.tags.map((t) => (
                    <span key={t} className="tag ver">
                      {t}
                    </span>
                  ))}
                </span>
              </a>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
