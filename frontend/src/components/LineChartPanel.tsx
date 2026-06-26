import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

export interface SeriesSpec {
  key: string;
  name: string;
  color: string;
}

export function LineChartPanel({
  title,
  data,
  series,
  yDomain,
}: {
  title: string;
  data: Record<string, number | string>[];
  series: SeriesSpec[];
  yDomain?: [number, number];
}) {
  return (
    <div className="panel">
      <h3>{title}</h3>
      {data.length === 0 ? (
        <p className="muted">暂无数据</p>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: -16 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="t" tick={{ fontSize: 11 }} />
            <YAxis
              domain={yDomain ?? ["auto", "auto"]}
              allowDecimals={false}
              tick={{ fontSize: 11 }}
            />
            <Tooltip />
            <Legend />
            {series.map((s) => (
              <Line key={s.key} type="monotone" dataKey={s.key} name={s.name} stroke={s.color} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
