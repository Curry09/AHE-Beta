import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { getSession } from "../api";
import type { SessionDetail as Detail } from "../types";
import { TranscriptThread } from "../components/TranscriptThread";

export default function SessionDetail() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    getSession(id)
      .then(setData)
      .catch((e) => setError(String(e)));
  }, [id]);

  if (error) return <p className="muted">加载失败：{error}</p>;
  if (!data) return <p className="muted">加载中…</p>;

  return (
    <div>
      <p>
        <Link to="/sessions">← 返回会话列表</Link>
      </p>
      <h2>会话 {data.session_id.slice(0, 8)}</h2>
      <div className="panel">
        <div className="muted">
          {data.persona.identity} · {data.persona.level} · {data.persona.domain} · 目标：
          {data.persona.goal}
        </div>
        <p>{data.scenario.description}</p>
      </div>

      <div className="panel">
        <h3>对话</h3>
        <TranscriptThread turns={data.transcript.turns} />
      </div>

      <div className="panel">
        <h3>体感：{data.feeling.score} / 4</h3>
        <div className="reason">{data.feeling.reason}</div>
      </div>

      <div className="panel">
        <h3>产出 issue（{data.issue_refs.length}）</h3>
        {data.issue_refs.length === 0 ? (
          <p className="muted">无</p>
        ) : (
          <ul>
            {data.issue_refs.map((ref) => (
              <li key={ref.number}>
                <a href={ref.url} target="_blank" rel="noreferrer">
                  #{ref.number}
                </a>{" "}
                <span className="muted">({ref.state})</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
