import { useEffect, useState } from "react";
import { getOverview } from "../api";
import type { Overview as OverviewData } from "../types";
import { KpiCard } from "../components/KpiCard";
import { LineChartPanel } from "../components/LineChartPanel";

export default function Overview() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getOverview()
      .then(setData)
      .catch((e) => setError(String(e)));
  }, []);

  if (error) return <p className="muted">加载失败：{error}</p>;
  if (!data) return <p className="muted">加载中…</p>;

  const feeling = data.feeling_trend.map(([t, score]) => ({ t: t.slice(5, 16), score }));
  const issues = data.issue_curve.map(([t, opened, net]) => ({ t: t.slice(5, 16), opened, net }));

  return (
    <div>
      <h2>概览</h2>
      <div className="cards">
        <KpiCard label="当前 open issue" value={data.open_issue_count ?? "—"} />
        <KpiCard label="会话总数" value={data.session_count} />
        <KpiCard
          label="最新体感"
          value={
            data.feeling_trend.length
              ? data.feeling_trend[data.feeling_trend.length - 1][1]
              : "—"
          }
        />
      </div>
      <LineChartPanel
        title="体感趋势（1–4）"
        data={feeling}
        series={[{ key: "score", name: "体感", color: "#0969da" }]}
        yDomain={[1, 4]}
      />
      <LineChartPanel
        title="issue 曲线"
        data={issues}
        series={[
          { key: "opened", name: "新产", color: "#cf222e" },
          { key: "net", name: "累计", color: "#1a7f37" },
        ]}
      />
    </div>
  );
}
