import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Agent, HistoryItem } from "../../types";
import { AgentColumn } from "../AgentColumn";
import { FloorWorkspace } from "./FloorWorkspace";
import { buildFloorModels, historyLabel } from "./buildingModel";

describe("Spec-0068/T4 Synthesizer presentation", () => {
  const agent: Agent = {
    agent_id: "synthesizer-0", role: "synthesizer", label: "自定义结构组",
    running: true, status: "综合中", round: 2, turns: [], detail: null, log: [],
    started_at: "", updated_at: "",
  };
  const item: HistoryItem = {
    ...agent, kind: "synthesizer_run", round: 1, archived_at: "", proposals: [7, 9],
  };
  const history = [{ item, index: 0 }];

  it("retains Synthesizer occupants, archive proposals, roster capacity and custom labels", () => {
    const [floor] = buildFloorModels({
      roles: [{ role: "synthesizer", name: "结构综合" }], agents: [agent], history,
      roster: { user: 1, triager: 1, synthesizer: 3, developer: 0 }, mode: "live",
    });
    expect(floor.liveAgents).toEqual([agent]);
    expect(floor.history).toEqual(history);
    expect(floor.capacity).toBe(3);
    expect(floor.emptySeats).toBe(2);
    expect(historyLabel(item)).toBe("2 RFC");
    const html = renderToStaticMarkup(<FloorWorkspace floor={floor} mode="live" round="all" onSelect={() => {}} />);
    expect(html).toContain("role-synthesizer");
    expect(html).toContain("SYNTHESIZER");
    expect(html).toContain("自定义结构组");
  });

  it("shows live and archived Synthesizer cards on the dashboard", () => {
    const html = renderToStaticMarkup(<AgentColumn role="synthesizer" name="结构综合" agents={[agent]}
      history={history} showDone selection={null} onSelect={() => {}} />);
    expect(html).toContain("结构综合");
    expect(html.match(/card role-synthesizer/g)).toHaveLength(2);
    expect(html).toContain("2 条提案");
    expect(html).toContain("自定义结构组");
  });
});
