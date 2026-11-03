// Spec-0071/T5: historical records retain their status; API mode remains live.
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ExperimentPicker } from "./components/ExperimentPicker";
import { TopBar } from "./components/TopBar";
import type { ExperimentSummary } from "./api";
import type { RunState } from "./types";

vi.mock("./components/ThemeToggle", () => ({ ThemeToggle: () => null }));

const snapshot: ExperimentSummary = {
  id: "harness-mixed16-20260909-r3",
  title: "Harness mixed16 r3",
  status: "RUNNING",
  updated_at: "2026-09-09T13:32:43.525735+00:00",
  source: "static",
};

const controls = {
  state: {
    running: true, round: 3, total_rounds: 5,
    round_shas: [], started_at: null, updated_at: snapshot.updated_at,
  } satisfies RunState,
  openCount: 2,
  view: "dashboard" as const,
  onView: () => {},
  showDone: false,
  onShowDone: () => {},
  round: "all" as const,
  rounds: [3],
  onRound: () => {},
};

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("historical snapshot presentation", () => {
  it("labels the recorded RUNNING state and time without presenting a live run", () => {
    const picker = renderToStaticMarkup(createElement(ExperimentPicker, {
      experiments: [snapshot], selected: snapshot.id, onSelect: () => {},
    }));
    const bar = renderToStaticMarkup(createElement(TopBar, {
      ...controls, historical: true, snapshot,
    }));
    expect(picker).toContain("Historical snapshot");
    expect(picker).toContain("Recorded state RUNNING");
    expect(picker).toContain("2026-09-09 13:32:43 UTC");
    expect(picker).toContain(`dateTime="${snapshot.updated_at}"`);
    expect(bar).toContain("Historical snapshot");
    expect(bar).toContain("Recorded state RUNNING");
    expect(bar).not.toContain("dot on");
    expect(bar).not.toContain("Running ·");
    expect(picker + bar).not.toContain("COMPLETED");
  });

  it("retains live status and hides the historical picker in API mode", () => {
    const bar = renderToStaticMarkup(createElement(TopBar, controls));
    expect(bar).toContain("Running · Round 3/5");
    expect(bar).toContain("dot on");
    expect(bar).not.toContain("Historical snapshot");
    expect(renderToStaticMarkup(createElement(ExperimentPicker, {
      experiments: [], selected: null, onSelect: () => {},
    }))).toBe("");
  });

  it("does not show another record's time for an unknown experiment", () => {
    const picker = renderToStaticMarkup(createElement(ExperimentPicker, {
      experiments: [snapshot], selected: "missing", onSelect: () => {},
    }));
    expect(picker).not.toContain("Recorded time: ");
  });
});

describe("API routing", () => {
  it("reads frozen records and state from the selected static snapshot", async () => {
    vi.stubEnv("VITE_STATIC_SITE", "1");
    vi.stubEnv("BASE_URL", "/ahe-beta/");
    vi.stubGlobal("window", { location: { search: `?experiment=${snapshot.id}`, pathname: "/" } });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ experiments: [snapshot] }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const api = await import("./api");
    expect(await api.getExperiments()).toEqual([snapshot]);
    expect(fetchMock).toHaveBeenLastCalledWith("/ahe-beta/experiments/index.json");
    await api.getState();
    expect(fetchMock).toHaveBeenLastCalledWith(`/ahe-beta/experiments/${snapshot.id}/api/state`);
  });

  it("uses the same selection for path-based snapshot views", async () => {
    vi.stubGlobal("window", { location: { search: "", pathname: `/experiments/${snapshot.id}/` } });
    const api = await import("./api");
    expect(api.getSelectedExperimentId()).toBe(snapshot.id);
  });

  it("continues fetching live state from /api without a static index request", async () => {
    vi.stubEnv("VITE_STATIC_SITE", "0");
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => controls.state });
    vi.stubGlobal("fetch", fetchMock);
    const api = await import("./api");
    expect(await api.getExperiments()).toEqual([]);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(await api.getState()).toEqual(controls.state);
    expect(fetchMock).toHaveBeenLastCalledWith("/api/state");
  });
});
