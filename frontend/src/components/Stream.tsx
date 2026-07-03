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

// 用户会话 transcript：user / harness 双方对话。
export function Turns({ turns }: { turns: Turn[] }) {
  if (turns.length === 0) return <div className="empty">暂无对话</div>;
  return (
    <div className="turns">
      {turns.map((t, i) => (
        <div key={i} className={`turn ${t.role}`}>
          <div className="who">{t.role === "user" ? "用户" : "harness"}</div>
          <div className="prose">{t.content}</div>
        </div>
      ))}
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
