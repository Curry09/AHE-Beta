import type { Turn } from "../types";

export function TranscriptThread({ turns }: { turns: Turn[] }) {
  return (
    <div>
      {turns.map((turn, i) => {
        const blank = !turn.content || !turn.content.trim();
        const isError = turn.content.startsWith("[harness error]");
        return (
          <div key={i} className={`bubble ${turn.role}`}>
            <strong>{turn.role === "user" ? "用户" : "harness"}</strong>
            <div>
              {blank ? (
                <span className="muted">（harness 未返回内容——空回复，见根因修复）</span>
              ) : isError ? (
                <span className="err">{turn.content}</span>
              ) : (
                turn.content
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
