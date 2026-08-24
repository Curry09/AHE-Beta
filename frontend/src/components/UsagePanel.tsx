import type { UsageEvent, UsageSummary } from "../types";
import { useMemo } from "react";

function n(value: number): string {
  return new Intl.NumberFormat("zh-CN", { notation: "compact" }).format(value);
}

export function UsagePanel({ usage, events }: { usage: UsageSummary | null; events: UsageEvent[] }) {
  const instances = useMemo(() => {
    const grouped = new Map<string, { user: number; harness: number; unavailable: number }>();
    for (const event of events) {
      if (!event.instance_id) continue;
      const row = grouped.get(event.instance_id) ?? { user: 0, harness: 0, unavailable: 0 };
      if (event.role === "user") row.user += event.total_tokens ?? 0;
      if (event.role === "harness") row.harness += event.total_tokens ?? 0;
      if (event.usage_source === "unavailable") row.unavailable += 1;
      grouped.set(event.instance_id, row);
    }
    return [...grouped.entries()];
  }, [events]);
  if (!usage) return <section className="usage-panel">Token 用量加载中…</section>;
  return (
    <section className="usage-panel" aria-label="LLM Token 用量">
      <div><b>{n(usage.total_tokens)}</b><span>{usage.unavailable_count ? "已报告 Token" : "总 Token"}</span></div>
      <div><b>{n(usage.input_tokens)}</b><span>输入</span></div>
      <div><b>{n(usage.output_tokens)}</b><span>输出</span></div>
      <div><b>{n(usage.reasoning_tokens)}</b><span>推理</span></div>
      <div><b>{n(usage.cached_input_tokens)}</b><span>缓存输入</span></div>
      <div className="usage-roles">
        {Object.entries(usage.by_role).map(([role, totals]) => (
          <span key={role}>
            {role} {n(totals.total_tokens)}
            {totals.unavailable_count > 0 ? `（另 ${totals.unavailable_count} 次不可用）` : ""}
          </span>
        ))}
        {usage.unavailable_count > 0 && <span>{usage.unavailable_count} 次用量不可用</span>}
      </div>
      <details>
        <summary>调用明细（{events.length}）</summary>
        <div className="usage-events">
          {events.slice(-30).reverse().map((event, i) => (
            <span key={`${event.timestamp}-${i}`}>
              {event.role ?? "unknown"} · {event.agent_id ?? event.session_id ?? "未归属"} ·
              {event.interaction_id ?? (event.turn_no === null ? "未关联交互" : `turn-${event.turn_no}`)} ·
              {event.model ?? "未知模型"} · {event.usage_source === "unavailable"
                ? "Token 不可用"
                : `${n(event.total_tokens ?? 0)} Token`}
            </span>
          ))}
        </div>
      </details>
      {instances.length > 0 && (
        <details>
          <summary>按题用量（{instances.length}）</summary>
          <div className="usage-events">
            {instances.map(([instance, row]) => (
              <span key={instance}>
                {instance} · user {n(row.user)} · harness {n(row.harness)} · 已报告合计 {n(row.user + row.harness)}
                {row.unavailable > 0 ? ` · 另 ${row.unavailable} 次不可用` : ""}
              </span>
            ))}
          </div>
        </details>
      )}
    </section>
  );
}
