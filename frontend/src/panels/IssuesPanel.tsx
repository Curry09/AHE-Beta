import type { IssuesResponse } from "../types";

export default function IssuesPanel(props: { data: IssuesResponse | null }) {
  const { data } = props;
  return (
    <section className="board">
      <div className="board-head">
        <span className="board-title">Issues</span>
        {data && <span className="board-count">{data.issues.length}</span>}
        {data?.board_url && (
          <a className="board-link" href={data.board_url} target="_blank" rel="noreferrer">
            Gitea ↗
          </a>
        )}
      </div>
      <div className="board-body">
        {!data && <div className="empty">加载中…</div>}
        {data && !data.connected && <div className="empty">未连接 issue tracker</div>}
        {data?.connected && data.issues.length === 0 && <div className="empty">暂无 open issue</div>}
        <ul className="feed">
          {data?.issues.map((it) => (
            <li key={it.number}>
              <a className="feed-row" href={it.url} target="_blank" rel="noreferrer">
                <span className="feed-num">#{it.number}</span>
                <span className="feed-title">{it.title}</span>
                <span className="feed-meta">
                  {it.labels.map((l) => (
                    <span key={l} className="tag">
                      {l}
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
