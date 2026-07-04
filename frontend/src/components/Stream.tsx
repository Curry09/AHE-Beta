import { useState } from "react";
import type { LogEntry, Turn } from "../types";
import { fmtTime } from "../lib/format";

// 过程流：status/assistant/tool/tool_result/tool_error 分型渲染，
// 重建「assistant 发言 → 工具调用 → 结果」的完整工作过程。
export function ProcessStream({ log }: { log: LogEntry[] }) {
  if (log.length === 0) return <div className="empty">暂无过程记录</div>;
  return (
    <div className="stream">
      {log.map((e, i) => {
        const kind = ["status", "assistant", "tool", "tool_result", "tool_error"].includes(e.kind)
          ? e.kind
          : "tool";
        return (
          <div key={i} className={`ev ${kind}`}>
            {kind !== "assistant" && <span className="t">{fmtTime(e.t)}</span>}
            {e.text}
          </div>
        );
      })}
    </div>
  );
}

// 折叠预览：取首个非空行，截断到 ~100 字。
function previewLine(text: string): string {
  const line = text.split("\n").find((l) => l.trim()) ?? text;
  return line.length > 100 ? `${line.slice(0, 100)}…` : line;
}

// 用户会话 transcript：user 消息全展开；harness 回复默认只展开最后一轮，
// 更早的折叠成预览、点一下展开。overrides 记录用户手动切换，未手动的跟随「是否最后一轮」
// —— live 流式新回复进来时，最新一轮自动成为展开项、旧的自动收起（除非用户已钉住）。
export function Turns({ turns }: { turns: Turn[] }) {
  const [overrides, setOverrides] = useState<Record<number, boolean>>({});
  if (turns.length === 0) return <div className="empty">暂无对话</div>;

  let lastHarness = -1;
  turns.forEach((t, i) => {
    if (t.role === "harness") lastHarness = i;
  });
  const isOpen = (i: number) => overrides[i] ?? i === lastHarness;
  const toggle = (i: number) => setOverrides((prev) => ({ ...prev, [i]: !isOpen(i) }));

  return (
    <div className="turns">
      {turns.map((t, i) => {
        if (t.role === "user") {
          return (
            <div key={i} className="turn user">
              <div className="who">用户</div>
              <div className="prose">{t.content}</div>
            </div>
          );
        }
        const open = isOpen(i);
        return (
          <div key={i} className={`turn harness${open ? "" : " collapsed"}`}>
            <button className="who toggle" onClick={() => toggle(i)}>
              <span className="caret">{open ? "▾" : "▸"}</span>
              harness
              {i === lastHarness && <span className="latest">最新</span>}
            </button>
            {open ? (
              <div className="prose">{t.content}</div>
            ) : (
              <button className="prose preview" onClick={() => toggle(i)}>
                {previewLine(t.content)}
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

// commit diff：行级着色（+ 绿 / - 红 / @@ 蓝 / 文件头灰）。
export function Diff({ diff }: { diff: string }) {
  if (!diff) return <div className="empty">无 diff 内容</div>;
  const cls = (line: string) => {
    if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("diff ") || line.startsWith("index "))
      return "meta-line";
    if (line.startsWith("@@")) return "hunk";
    if (line.startsWith("+")) return "add";
    if (line.startsWith("-")) return "del";
    return "";
  };
  return (
    <div className="diff">
      {diff.split("\n").map((line, i) => (
        <div key={i} className={`line ${cls(line)}`}>
          {line || " "}
        </div>
      ))}
    </div>
  );
}
