import type { Turn } from "../types";

export function TranscriptThread({ turns }: { turns: Turn[] }) {
  return (
    <div>
      {turns.map((turn, i) => (
        <div key={i} className={`bubble ${turn.role}`}>
          <strong>{turn.role === "user" ? "用户" : "harness"}</strong>
          <div>{turn.content}</div>
        </div>
      ))}
    </div>
  );
}
