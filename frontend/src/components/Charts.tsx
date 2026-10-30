import { useId } from "react";
import type { OverviewResponse } from "../types";

// 概览曲线（Spec-0026/T3）：内联 SVG，消费 /api/overview。preserveAspectRatio=none 撑满宽度、
// vector-effect=non-scaling-stroke 保线宽恒定，双主题走 token（stroke=currentColor via CSS var）。
const VW = 300;
const VH = 44;
const PAD = 5;

function LineChart(props: { values: number[]; min: number; max: number; color: string }) {
  const { values, min, max, color } = props;
  const gid = useId();
  const span = Math.max(1e-9, max - min);
  const n = values.length;
  const x = (i: number) => (n <= 1 ? VW / 2 : PAD + (i / (n - 1)) * (VW - PAD * 2));
  const y = (v: number) => VH - PAD - ((v - min) / span) * (VH - PAD * 2);
  const pts = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
  const line = pts.join(" ");
  const area = `${PAD},${VH} ${line} ${x(n - 1).toFixed(1)},${VH}`;
  const lastX = x(n - 1);
  const lastY = y(values[n - 1]);
  return (
    <svg viewBox={`0 0 ${VW} ${VH}`} preserveAspectRatio="none" role="img">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.22" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={area} fill={`url(#${gid})`} />
      <polyline
        points={line}
        fill="none"
        stroke={color}
        strokeWidth="1.6"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
      <circle cx={lastX} cy={lastY} r="2.4" fill={color} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function Panel(props: {
  title: string;
  now: string;
  values: number[];
  min: number;
  max: number;
  color: string;
}) {
  const { title, now, values, min, max, color } = props;
  return (
    <div className="chart">
      <div className="chart-head">
        {title}
        <span className="now">{now}</span>
      </div>
      {values.length > 0 ? (
        <LineChart values={values} min={min} max={max} color={color} />
      ) : (
        <div className="empty-line">暂无数据</div>
      )}
    </div>
  );
}

export function Charts({ overview }: { overview: OverviewResponse | null }) {
  const feeling = (overview?.feeling_trend ?? []).map(([, s]) => s).filter((s) => Number.isInteger(s) && s >= 1 && s <= 4);
  const backlog = (overview?.issue_curve ?? []).map(([, , b]) => b);
  const feelNow = feeling.length ? `${feeling[feeling.length - 1]}/4` : "—";
  const backlogMax = backlog.length ? Math.max(...backlog, 1) : 1;
  const backlogNow = backlog.length ? String(backlog[backlog.length - 1]) : "—";
  return (
    <div className="overview">
      <Panel
        title="体感"
        now={feelNow}
        values={feeling}
        min={1}
        max={4}
        color="var(--role-user)"
      />
      <Panel
        title="可执行 backlog"
        now={backlogNow}
        values={backlog}
        min={0}
        max={backlogMax}
        color="var(--role-developer)"
      />
      {Object.entries(overview?.feedback_counts ?? {}).map(([condition, count]) => (
        <div className="chart" key={condition}>
          <div className="chart-head">体感样本 · {{ unavailable: "无后续输入", possible: "可后续输入", unknown: "输入条件未知" }[condition] ?? condition}</div>
          <div className="dim">有效 {count.rated} · 未提供 {count.missing} · 无效 {count.invalid} · 不可用 {count.unavailable}</div>
        </div>
      ))}
    </div>
  );
}
