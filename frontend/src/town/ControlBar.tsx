import { useEffect, useState } from "react";

const WEEK = ["日", "一", "二", "三", "四", "五", "六"];

// 模拟时钟：真实墙钟，每秒跳动，斯坦福小镇顶栏那种「2024年2月13日星期二 10:41:50」格式。
function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  const p = (n: number) => String(n).padStart(2, "0");
  return (
    <span className="clock">
      {now.getFullYear()}年{now.getMonth() + 1}月{now.getDate()}日 星期{WEEK[now.getDay()]}{" "}
      {p(now.getHours())}:{p(now.getMinutes())}:{p(now.getSeconds())}
    </span>
  );
}

// 顶部控制条：运行/暂停（冻结轮询）、显示/隐藏对话、模拟时钟、实时更新指示。
export function ControlBar({
  paused,
  onTogglePause,
  showDialogue,
  onToggleDialogue,
  updatedAt,
  running,
}: {
  paused: boolean;
  onTogglePause: () => void;
  showDialogue: boolean;
  onToggleDialogue: () => void;
  updatedAt: number | null;
  running: number;
}) {
  return (
    <div className="controlbar">
      <span className="brand">🏙️ auto-designer 小镇</span>
      <button className={`ctrl ${paused ? "" : "on"}`} onClick={onTogglePause}>
        {paused ? "▶ 运行" : "⏸ 暂停"}
      </button>
      <button className={`ctrl ${showDialogue ? "on" : ""}`} onClick={onToggleDialogue}>
        {showDialogue ? "隐藏对话" : "显示对话"}
      </button>
      <Clock />
      <span className="spacer" />
      <span className="live-dot">
        {paused ? "⏸ 已暂停" : `● 实时 · ${running} 居民活动中`}
      </span>
      <span className="upd">更新于 {updatedAt ? new Date(updatedAt).toLocaleTimeString() : "…"}</span>
    </div>
  );
}
