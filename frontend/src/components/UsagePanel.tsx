import type { UsageEvent, UsageSummary } from "../types";
import { useMemo } from "react";

function n(value: number): string {
  return new Intl.NumberFormat("en-US", { notation: "compact" }).format(value);
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
  if (!usage) return <section className="usage-panel">Loading token usage…</section>;
  return (
    <section className="usage-panel" aria-label="LLM Token Usage">
      <div><b>{n(usage.total_tokens)}</b><span>{usage.unavailable_count ? "Reported tokens" : "Total tokens"}</span></div>
      <div><b>{n(usage.input_tokens)}</b><span>Input</span></div>
      <div><b>{n(usage.output_tokens)}</b><span>Output</span></div>
      <div><b>{n(usage.reasoning_tokens)}</b><span>Reasoning</span></div>
      <div><b>{n(usage.cached_input_tokens)}</b><span>Cached input</span></div>
      <div className="usage-roles">
        {Object.entries(usage.by_role).map(([role, totals]) => (
          <span key={role}>
            {role} {n(totals.total_tokens)}
            {totals.unavailable_count > 0 ? ` (${totals.unavailable_count} calls without usage data)` : ""}
          </span>
        ))}
        {usage.unavailable_count > 0 && <span>{usage.unavailable_count} Call usage unavailable</span>}
      </div>
      <details>
        <summary>Call details ({events.length})</summary>
        <div className="usage-events">
          {events.slice(-30).reverse().map((event, i) => (
            <span key={`${event.timestamp}-${i}`}>
              {event.role ?? "unknown"} · {event.agent_id ?? event.session_id ?? "Unassigned"} ·
              {event.interaction_id ?? (event.turn_no === null ? "Unlinked interaction" : `turn-${event.turn_no}`)} ·
              {event.model ?? "Unknown model"} · {event.usage_source === "unavailable"
                ? "Tokens unavailable"
                : `${n(event.total_tokens ?? 0)} tokens`}
            </span>
          ))}
        </div>
      </details>
      {instances.length > 0 && (
        <details>
          <summary>Usage by task ({instances.length})</summary>
          <div className="usage-events">
            {instances.map(([instance, row]) => (
              <span key={instance}>
                {instance} · user {n(row.user)} · harness {n(row.harness)} · Reported total {n(row.user + row.harness)}
                {row.unavailable > 0 ? ` · ${row.unavailable} calls without usage data` : ""}
              </span>
            ))}
          </div>
        </details>
      )}
    </section>
  );
}
