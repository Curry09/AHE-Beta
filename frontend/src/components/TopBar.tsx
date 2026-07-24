import type { RunState } from "../types";
import { ThemeToggle } from "./ThemeToggle";

export function TopBar(props: {
  state: RunState | null;
  openCount: number | null;
  showDone: boolean;
  onShowDone: (v: boolean) => void;
  round: "all" | number;
  rounds: number[];
  onRound: (r: "all" | number) => void;
}) {
  const { state, openCount, showDone, onShowDone, round, rounds, onRound } = props;
  const running = state?.running ?? false;
  const chip = state
    ? state.round > 0
      ? `第 ${state.round}/${state.total_rounds} 轮`
      : "未运行"
    : "连接中…";

  return (
    <header className="topbar">
      <div className="title">
        auto-designer <span>观测看板</span>
      </div>
      <div className="run-chip">
        <span className={running ? "dot on" : "dot"} />
        {running ? `运行中 · ${chip}` : chip}
      </div>
      <div className="spacer" />
      <div className="seg" role="group" aria-label="状态筛选">
        <button className={showDone ? "" : "active"} onClick={() => onShowDone(false)}>
          运行中
        </button>
        <button className={showDone ? "active" : ""} onClick={() => onShowDone(true)}>
          + 已完成
        </button>
      </div>
      {showDone && (
        <select
          aria-label="轮次筛选"
          value={round === "all" ? "all" : String(round)}
          onChange={(e) => onRound(e.target.value === "all" ? "all" : Number(e.target.value))}
        >
          <option value="all">全部轮次</option>
          {rounds.map((r) => (
            <option key={r} value={r}>
              第 {r} 轮
            </option>
          ))}
        </select>
      )}
      <div className="meta">{openCount === null ? "issues —" : `issues ${openCount} open`}</div>
      <ThemeToggle />
    </header>
  );
}
