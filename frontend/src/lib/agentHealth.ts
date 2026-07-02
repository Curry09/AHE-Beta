import type { Agent } from "../types";

// 运行中但超过此时长无更新 → 疑似卡顿（已超过 300s per-call 超时）。
export const STALE_MS = 330_000;

export function fmtDur(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  return m > 0 ? `${m}m${s % 60}s` : `${s}s`;
}

// 健康状态：异常 > 卡顿 > 运行 > 完成/空闲。cls 复用既有 ok/warn/err/idle 色板。
export function health(a: Agent, now: number): { cls: string; text: string } {
  if (/\[harness error\]|error|否决|未过/i.test(a.status)) return { cls: "err", text: "异常" };
  if (a.running) {
    const stale = now - new Date(a.updated_at).getTime();
    if (stale > STALE_MS) return { cls: "warn", text: "卡顿?" };
    return { cls: "ok", text: "运行中" };
  }
  return { cls: "idle", text: "完成" };
}
