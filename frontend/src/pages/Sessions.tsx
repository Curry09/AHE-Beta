import { Link } from "react-router-dom";
import { getSessions } from "../api";
import { useLiveData } from "../hooks/useLiveData";
import { LiveIndicator } from "../components/LiveIndicator";

export default function Sessions() {
  const { data: rows, error, updatedAt } = useLiveData(getSessions);

  if (error) return <p className="muted">加载失败：{error}</p>;
  if (!rows) return <p className="muted">加载中…</p>;

  return (
    <div>
      <div className="head">
        <h2>会话（{rows.length}）</h2>
        <LiveIndicator updatedAt={updatedAt} />
      </div>
      {rows.length === 0 ? (
        <p className="muted">暂无会话</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>用户画像</th>
              <th>场景</th>
              <th>体感</th>
              <th>issue 数</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.session_id}>
                <td>{r.created_at.slice(0, 16).replace("T", " ")}</td>
                <td>{r.persona_identity}</td>
                <td>
                  <Link to={`/sessions/${r.session_id}`}>{r.scenario}</Link>
                </td>
                <td>{r.score}</td>
                <td>{r.n_issues}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
