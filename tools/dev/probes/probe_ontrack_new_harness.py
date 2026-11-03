#!/usr/bin/env python3
"""Probe: ON-TRACK wait behavior under new harness contract, expert vs blind.

Simulate evolved harness: MANUAL includes `/status` slash (message channel); interrupt uses external window.
Run only ON-TRACK × {expert, blind} (Spec-0022/0023 three).

Usage (repo root):
  PYTHONPATH=backend .venv/bin/python -m tools.dev.probes.probe_ontrack_new_harness
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from tools.dev import add_inputs, load_secrets, role_environment

ROOT = Path(__file__).resolve().parents[3] / "backend"
EVOLVED_MANUAL: Path | None = None


def _manual() -> str:
    if EVOLVED_MANUAL is not None:
        return EVOLVED_MANUAL.read_text(encoding="utf-8")
    return (
        "# Manual\nCoding assistant with activity strip.\n"
        "While waiting you may send `/status` as a normal message.\n"
        "Ctrl+C (interrupt) stops the current request.\n"
    )


class NewHarnessContract:
    """Align evolved harness: progress bar + `/status` via emit_message; interrupt wraps up."""

    def __init__(self, *, activities: list[list[str]], reply: str = "done.") -> None:
        self._activities = activities
        self._reply = reply
        self.manual = _manual()
        self.last_progress: list[dict] = []
        self.last_steps: list[dict] = []
        self._n = 0
        self._inflight = False
        self.controls: list[str] = []
        self.emitted: list[str] = []

    @property
    def in_flight(self) -> bool:
        return self._inflight

    def begin(self, message: str) -> None:  # noqa: ARG002
        self._n = 0
        self._inflight = True
        self.last_progress = []

    def emit_message(self, message: str) -> None:
        self.emitted.append(message)
        preview = self.last_progress[-1]["text"] if self.last_progress else "(none yet)"
        self.last_progress = [
            *self.last_progress,
            {"kind": "status", "text": f"status via message: still running; last={preview}"},
        ]

    def poll(self, timeout: float) -> tuple[str, object]:  # noqa: ARG002
        self._n += 1
        waited = float(self._n * 90)
        idx = min(self._n - 1, len(self._activities) - 1)
        titles = self._activities[idx] if self._activities else []
        self.last_progress = [{"kind": "tool", "text": t} for t in titles]
        if self._n <= len(self._activities):
            return ("pending", waited)
        self._inflight = False
        return ("reply", self._reply)

    def control(self, name: str) -> str:
        self.controls.append(name)
        self._inflight = False
        return (
            f"[interrupted] You stopped this request via `{name}`; session kept — send a follow-up."
        )

    def reset(self) -> None:
        self._n = 0
        self._inflight = False
        self.last_progress = []

    def close(self) -> None:
        pass


# ON-TRACK: multi-shot progress, sufficient heartbeats to send_message(/status) / keep_waiting / interrupt
ON_TRACK: list[list[str]] = [
    ["🔧 read_file: billing/core.py"],
    [
        "🔧 read_file: billing/core.py",
        "🔧 run_shell: python -c 'from billing.core import split_bill'",
    ],
    [
        "🔧 read_file: billing/core.py",
        "🔧 run_shell: python -c 'from billing.core import split_bill'",
        "🔧 run_shell: pytest billing/ -q",
    ],
    [
        "🔧 read_file: billing/core.py",
        "🔧 run_shell: python -c 'from billing.core import split_bill'",
        "🔧 run_shell: pytest billing/ -q",
        "🔧 run_shell: python -c 'print(split_bill(100,4))'",
    ],
    [
        "🔧 read_file: billing/core.py",
        "🔧 run_shell: python -c 'from billing.core import split_bill'",
        "🔧 run_shell: pytest billing/ -q",
        "🔧 run_shell: python -c 'print(split_bill(100,4))'",
        "🔧 run_shell: pytest billing/ -q",
    ],
]


def _run_one(*, d1: object) -> None:
    from ahe_beta.user.sim.dimensions import (
        D2Depth,
        D2Domain,
        D5Autonomy,
        D41Grain,
        D42Supervise,
        D43Correct,
        Persona,
        finalize_persona,
    )
    from ahe_beta.user.sim.loop import run_session
    from ahe_beta.user.sim.persona_client import ApiPersonaClient

    persona = finalize_persona(
        Persona(
            persona_id=f"P-ONTRACK-{d1.value}",  # type: ignore[attr-defined]
            d1=d1,  # type: ignore[arg-type]
            d2=D2Domain(stack=("python",), depth=D2Depth.SENIOR, weak=()),
            d41=D41Grain.SPEC_LEVEL,
            d42=D42Supervise.EVERY_STEP,
            d43=D43Correct.FILE_ISSUE,
            d5=D5Autonomy.COLLABORATIVE,
        )
    )
    client = ApiPersonaClient()
    harness = NewHarnessContract(
        activities=ON_TRACK, reply="done.\n\n## Verification evidence\n3 passed"
    )
    task = (
        "Please add split_bill(total, n) to billing/core.py and run a quick smoke test. "
        "Only touch billing — do not refactor unrelated packages or hit the network."
    )
    print(f"\n======== ON-TRACK d1={d1.value} (new harness contract) ========")  # type: ignore[attr-defined]
    t0 = time.monotonic()
    res = run_session(persona, client, harness, task, manual=harness.manual)
    gaps = [s for s in res.signals if s.startswith("WAIT_GAP:")]
    statuses = [m for m in harness.emitted if m.strip().startswith("/status")]
    interrupts = [c for c in harness.controls if c == "interrupt"]
    print(
        f"elapsed={time.monotonic() - t0:.1f}s end={res.end_reason} "
        f"emitted={harness.emitted} statuses={statuses} "
        f"controls={harness.controls} interrupts={interrupts} gaps={gaps}"
    )
    if res.feeling:
        print(f"feeling={res.feeling.score}/4 — {res.feeling.reason}")
    for t in res.turns:
        if t.phase == "waiting":
            head = "?"
            note = t.perceive
            if t.perceive.startswith("[") and "]" in t.perceive:
                head, _, note = t.perceive[1:].partition("]")
                note = note.strip()
            print(f"  WAIT [{head}] action={t.action} patience={t.patience} note={note!r}")
        elif t.message:
            print(f"  turn={t.turn} action={t.action} msg={t.message[:100]!r}")
        elif t.harness_output:
            out = t.harness_output.replace("\n", " ")[:120]
            print(f"  turn={t.turn} action={t.action} harness={out!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manual", type=Path, help="Optional explicit evolved Harness manual")
    add_inputs(parser)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    global EVOLVED_MANUAL
    EVOLVED_MANUAL = args.manual
    load_secrets(args.secrets_file)
    role_environment("USER")
    from ahe_beta.user.sim.dimensions import D1Eval

    print(f"manual_source={'evolved' if EVOLVED_MANUAL is not None else 'fallback'}")
    print(f"manual_has_/status={'/status' in _manual().lower()}")
    for d1 in (D1Eval.EXPERT, D1Eval.BLIND):
        _run_one(d1=d1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
