import { getIssues } from "../api";
import { useLiveData } from "../hooks/useLiveData";
import { LiveIndicator } from "../components/LiveIndicator";

export default function Issues() {
  const { data, error, updatedAt } = useLiveData(getIssues);

  if (error) return <p className="muted">加载失败：{error}</p>;
  if (!data) return <p className="muted">加载中…</p>;

  return (
    <div>
      <div className="head">
        <h2>Gitea 看板</h2>
        <LiveIndicator updatedAt={updatedAt} />
      </div>

      {data.board_url && (
        <p>
          <a href={data.board_url} target="_blank" rel="noreferrer">
            ↗ 在 Gitea 打开项目看板
          </a>
        </p>
      )}

      {!data.connected ? (
        <p className="muted">未连接 Gitea（设 GITEA_URL/OWNER/REPO/TOKEN 环境变量后显示 issue）。</p>
      ) : data.issues.length === 0 ? (
        <p className="muted">暂无 open issue。</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>标题</th>
              <th>标签</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {data.issues.map((issue) => (
              <tr key={issue.number}>
                <td>{issue.number}</td>
                <td>
                  {issue.url ? (
                    <a href={issue.url} target="_blank" rel="noreferrer">
                      {issue.title}
                    </a>
                  ) : (
                    issue.title
                  )}
                </td>
                <td>
                  {issue.labels.map((label) => (
                    <span key={label} className="chip">
                      {label}
                    </span>
                  ))}
                </td>
                <td>{issue.state}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
