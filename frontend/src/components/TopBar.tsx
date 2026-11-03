import type { RunState, ViewMode } from "../types";
import type { ExperimentSummary } from "../api";
import { ThemeToggle } from "./ThemeToggle";

export function TopBar(props: {
  state: RunState | null;
  openCount: number | null;
  view: ViewMode;
  onView: (v: ViewMode) => void;
  showDone: boolean;
  onShowDone: (v: boolean) => void;
  round: "all" | number;
  rounds: number[];
  onRound: (r: "all" | number) => void;
  historical?: boolean;
  snapshot?: ExperimentSummary;
}) {
  const { state, openCount, view, onView, showDone, onShowDone, round, rounds, onRound } = props;
  const running = state?.running ?? false;
  const chip = state
    ? state.round > 0
      ? `Round ${state.round}/${state.total_rounds}`
      : "Not running"
    : "Connecting…";

  return (
    <header className="topbar">
      <div className="title">
        AHE-Beta <span>{props.historical ? "Historical snapshot" : "Dashboard"}</span>
      </div>
      <div className="run-chip">
        {/* Spec-0071/T5: preserve the observed state without suggesting a live run. */}
        <span className={!props.historical && running ? "dot on" : "dot"} />
        {props.historical
          ? `Recorded state ${props.snapshot?.status ?? (state ? (running ? "RUNNING" : "Not running") : "Loading…")} · ${chip}`
          : running ? `Running · ${chip}` : chip}
      </div>
      <div className="spacer" />
      <div className="seg" role="group" aria-label="View switcher">
        <button
          className={view === "dashboard" ? "active" : ""}
          aria-pressed={view === "dashboard"}
          onClick={() => onView("dashboard")}
        >
          Dashboard
        </button>
        <button
          className={view === "building" ? "active" : ""}
          aria-pressed={view === "building"}
          onClick={() => onView("building")}
        >
          Building
        </button>
        <button
          className={view === "openagents" ? "active" : ""}
          aria-pressed={view === "openagents"}
          onClick={() => onView("openagents")}
        >
          OpenAgents
        </button>
      </div>
      {view === "openagents" ? (
        <select
          aria-label="OpenAgents Round filter"
          value={round === "all" ? "all" : String(round)}
          onChange={(e) => onRound(e.target.value === "all" ? "all" : Number(e.target.value))}
        >
          <option value="all">All rounds</option>
          {rounds.map((r) => (
            <option key={r} value={r}>
              Round {r}
            </option>
          ))}
        </select>
      ) : (
        <>
          <div className="seg" role="group" aria-label="Status filter">
            <button className={showDone ? "" : "active"} onClick={() => onShowDone(false)}>
              Running
            </button>
            <button className={showDone ? "active" : ""} onClick={() => onShowDone(true)}>
              + Completed
            </button>
          </div>
          {showDone && (
            <select
              aria-label="Round filter"
              value={round === "all" ? "all" : String(round)}
              onChange={(e) => onRound(e.target.value === "all" ? "all" : Number(e.target.value))}
            >
              <option value="all">All rounds</option>
              {rounds.map((r) => (
                <option key={r} value={r}>
                  Round {r}
                </option>
              ))}
            </select>
          )}
        </>
      )}
      <div className="meta">{openCount === null ? "issues —" : `issues ${openCount} open`}</div>
      <ThemeToggle />
    </header>
  );
}
