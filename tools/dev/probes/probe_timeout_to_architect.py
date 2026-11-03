#!/usr/bin/env python3
"""Probe: timeout harness × real user agent → SessionStore → real architect (watch how it judges).

Usage (repo root):
  PYTHONPATH=backend .venv/bin/python -m tools.dev.probes.probe_timeout_to_architect

Credentials provided explicitly via --secrets-file or pre-injected in environment.
harness is scripted "always timeout + 0 steps"—does not spawn real nexau subprocess, tests signal chain only.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

from tools.dev import add_inputs, load_secrets, role_environment

ROOT = Path(__file__).resolve().parents[3] / "backend"  # backend/
TEMPLATE = ROOT / "harness_template"
ARCHITECT_DEF = ROOT / "agent_defs" / "architect"


class TimeoutHarness:
    """Scripted harness: every round times out, last_steps=[] (zero-step round)—simulate "budget too tight / inner empty loop"."""

    def __init__(self) -> None:
        self._n = 0
        self._closed = False
        self.last_steps: list = []
        self.manual = (
            "# Harness MANUAL (probe)\n"
            "Coding assistant. One reply per turn. May timeout on long tasks.\n"
        )

    def send(self, message: str) -> str:
        if self._closed:
            raise RuntimeError("closed")
        self._n += 1
        self.last_steps = []  # Key: zero process flow in inner layer
        # Mild wall-clock delay, let user side perceive "waited a while before failing" (not truly 120s, probe must finish running)
        time.sleep(1.2)
        return (
            f"[harness error] call timeout after 120s "
            f"(attempt {self._n}); no partial result delivered. "
            f"Your last message started with: {message[:60]!r}"
        )

    def reset(self) -> None:
        self._n = 0
        self.last_steps = []

    def close(self) -> None:
        self._closed = True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_inputs(parser)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    load_secrets(args.secrets_file)
    role_environment("USER", "DEMAND")

    from ahe_beta.demand.architect import Architect
    from ahe_beta.demand.runtime_agg import aggregate_runtime, format_runtime_agg
    from ahe_beta.loop.sim_user import make_sim_run_session_fn
    from ahe_beta.models import Persona, SeedScenario
    from ahe_beta.tracker.fake import FakeTracker
    from ahe_beta.user.session_store import SessionStore
    from ahe_beta.user.sim.dimensions import (
        D1Eval,
        D2Depth,
        D2Domain,
        D5Autonomy,
        D41Grain,
        D42Supervise,
        D43Correct,
        finalize_persona,
    )
    from ahe_beta.user.sim.dimensions import (
        Persona as SimPersona,
    )
    from ahe_beta.user.sim.persona_client import AgenticPersonaClient, ApiPersonaClient

    work = Path(tempfile.mkdtemp(prefix="probe_timeout_"))
    sessions_dir = work / "sessions"
    harness_repo = work / "harness_repo"
    shutil.copytree(TEMPLATE, harness_repo)
    print(f"work dir: {work}")

    # Expert users: will validate and file issues—timeout scenario most likely to leave strong signals
    sim_p = finalize_persona(
        SimPersona(
            persona_id="P-PROBE-TIMEOUT",
            d1=D1Eval.EXPERT,
            d2=D2Domain(stack=("python",), depth=D2Depth.SENIOR, weak=()),
            d41=D41Grain.SPEC_LEVEL,
            d42=D42Supervise.EVERY_STEP,
            d43=D43Correct.FILE_ISSUE,
            d5=D5Autonomy.COLLABORATIVE,
        )
    )
    display = Persona(
        identity=sim_p.persona_id,
        level="senior",
        domain="python",
        goal="get a working split_bill helper",
        speaking_style="direct",
    )
    scenario = SeedScenario(
        description=(
            "I've got billing/core.py in my project. Please add split_bill(total, n) "
            "that splits a bill among n people, run it, and show me it works. "
            "This should be a small change — don't take forever."
        )
    )

    tracker = FakeTracker()
    store = SessionStore(sessions_dir)
    api = ApiPersonaClient()

    def client_factory() -> AgenticPersonaClient:
        return AgenticPersonaClient(api.complete)

    def on_turn(identity, sim_persona, partial, running, *, session_id=None) -> None:
        n = len(partial.turns)
        last = partial.turns[-1] if partial.turns else None
        if running and last is not None:
            print(
                f"  [user turn {n}] action={last.action} verdict={last.verdict} "
                f"patience={last.patience} "
                f"ho={last.harness_output[:70]!r}…"
            )
        if not running:
            print(f"  [user done] end={partial.end_reason} session={session_id}")

    run_fn = make_sim_run_session_fn(
        client_factory=client_factory,
        tracker=tracker,
        store=store,
        sim_personas={display.identity: sim_p},
        on_turn=on_turn,
    )

    print("\n=== A｜User agent × TimeoutHarness ===")
    t0 = time.monotonic()
    session = run_fn(display, scenario, TimeoutHarness())
    print(f"Session duration {time.monotonic() - t0:.1f}s  session_id={session.session_id}")
    print(f"feeling={session.feeling.score}/4 — {session.feeling.reason}")
    print(f"issues={session.issue_refs}  open={len(tracker.list_open_issues())}")
    # Print sim side details too (if SessionResult unavailable from make_sim, at least see transcript)
    print("\n--- transcript ---")
    for i, turn in enumerate(session.transcript.turns):
        steps_n = len(turn.steps)
        print(f"  [{i}] {turn.role} steps={steps_n}: {turn.content[:100]!r}")

    print("\n=== Runtime aggregate (inspect before providing it to Architect)===")
    agg_text = format_runtime_agg(
        aggregate_runtime(store=store, harness_repo=harness_repo, recent_n=50)
    )
    print(agg_text)

    print("\n=== D｜Architect agent ===")

    def on_status(*, running: bool, status: str, **kw) -> None:
        detail = kw.get("detail")
        proposals = kw.get("proposals")
        print(f"  [architect] running={running} status={status} proposals={proposals}")
        if detail and not running:
            print("--- architect detail (truncated) ---")
            text = str(detail)
            print(text[:3000] + ("…" if len(text) > 3000 else ""))

    architect = Architect(
        tracker=tracker,
        store=store,
        harness_repo=str(harness_repo),
        agent_def_dir=str(ARCHITECT_DEF),
        on_status=on_status,
        on_event=lambda kind, text: print(f"    · {kind}: {text[:120]}"),
    )
    t1 = time.monotonic()
    outcome = architect.propose_once()
    print(f"Architect duration {time.monotonic() - t1:.1f}s  proposals={outcome.proposal_numbers}")

    print("\n=== Final backlog ===")
    for issue in tracker.list_open_issues():
        print(f"\n#{issue.number} [{','.join(issue.labels)}] {issue.title}")
        print(issue.body[:800])
        if len(issue.body) > 800:
            print("…")

    print(f"\n(Artifact directory retained：{work})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
