import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getSessions } from "../api";
import type { SessionSummary } from "../types";

export default function Sessions() {
  const [rows, setRows] = useState<SessionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSessions()
      .then(setRows)
      .catch((e) => setError(String(e)));
  }, []);

  if (error) return <p className="muted">加载失败：{error}</p>;
  if (!rows) return <p className="muted">加载中…</p>;
  if (rows.length === 0) return <p className="muted">暂无会话</p>;

  return (
    <div>
      <h2>会话（{rows.length}）</h2>
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
    </div>
  );
}
