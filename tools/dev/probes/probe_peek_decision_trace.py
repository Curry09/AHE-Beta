#!/usr/bin/env python3
"""Diagnostics: original judge/intent/act text on next hop after send_message(/status).

Usage (repo root):
  PYTHONPATH=backend .venv/bin/python -m tools.dev.probes.probe_peek_decision_trace
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from tools.dev import add_inputs, load_secrets, role_environment
from tools.dev.probes import add_persona_inputs, load_persona_cards, selected_personas

ROOT = Path(__file__).resolve().parents[3] / "backend"


class TraceHarness:
    def __init__(self) -> None:
        self.manual = (
            "# Manual\nCoding assistant with activity strip.\n"
            "While waiting you may send `/status` as a normal message.\n"
            "Ctrl+C (interrupt) stops the current request.\n"
        )
        self._activities = [
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
        ]
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
        preview = self.last_progress[-1]["text"] if self.last_progress else "(none)"
        self.last_progress = [
            *self.last_progress,
            {"kind": "status", "text": f"status via message: last={preview}"},
        ]

    def poll(self, timeout: float) -> tuple[str, object]:  # noqa: ARG002
        self._n += 1
        waited = float(self._n * 90)
        idx = min(self._n - 1, len(self._activities) - 1)
        titles = self._activities[idx]
        self.last_progress = [{"kind": "tool", "text": t} for t in titles]
        if self._n <= len(self._activities):
            return ("pending", waited)
        self._inflight = False
        return ("reply", "done.\n\n## Verification evidence\n3 passed")

    def control(self, name: str) -> str:
        self.controls.append(name)
        self._inflight = False
        return f"[interrupted] stopped via {name}"

    def reset(self) -> None:
        pass

    def close(self) -> None:
        pass


class TracingClient:
    """Wrap ApiPersonaClient, print only key fields of the three waiting hops."""

    def __init__(self) -> None:
        from ahe_beta.user.sim.persona_client import ApiPersonaClient

        self._inner = ApiPersonaClient()
        self.n = 0
        self.after_status_logs: list[dict] = []

    def respond(self, system: str, user: str) -> dict:
        kind = (
            "judge"
            if "<waiting_judge>" in user
            else (
                "intent"
                if "<waiting_intent>" in user
                else ("act" if "<waiting_act>" in user else "other")
            )
        )
        ret = self._inner.respond(system, user)
        if kind == "other":
            return ret
        self.n += 1
        ts = _extract_block(user, "time_sense")
        hist_tail = _history_tail(user, n=3)
        prog_tail = _extract_block(user, "progress")
        row = {
            "i": self.n,
            "kind": kind,
            "time_sense": ts,
            "history_tail": hist_tail,
            "progress_tail": (prog_tail or "")[-400:],
            "ret": {
                k: ret.get(k)
                for k in ("perceive", "judgment", "intent", "intent_detail", "action", "control")
                if k in ret
            },
        }
        self.after_status_logs.append(row)
        # Detailed logging only: history just after send_message /status
        interesting = "send_message" in (hist_tail or "") and "/status" in (hist_tail or "")
        mark = " <<AFTER_STATUS" if interesting else ""
        print(f"\n--- waiting #{self.n} {kind}{mark} ---")
        print(f"time_sense:\n{ts or '(missing)'}")
        if interesting:
            print(f"history_tail:\n{hist_tail or '(empty)'}")
            print(f"progress_tail:\n{(prog_tail or '')[-300:] or '(empty)'}")
        print(f"model_out: {json.dumps(row['ret'], ensure_ascii=False)}")
        return ret


def _extract_block(user: str, name: str) -> str | None:
    m = re.search(rf"<{name}>\n?(.*?)\n?</{name}>", user, flags=re.S)
    return m.group(1).strip() if m else None


def _history_tail(user: str, n: int) -> str:
    block = _extract_block(user, "history") or ""
    lines = [ln for ln in block.splitlines() if ln.strip()]
    return "\n".join(lines[-n:])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--persona", default="sr-05-klabnik")
    add_persona_inputs(parser)
    add_inputs(parser)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    from ahe_beta.user.sim.loop import run_session
    from ahe_beta.user.sim.persona_io import card_to_persona

    cards = load_persona_cards(args.persona_library)
    card = selected_personas(cards, [args.persona])[0]
    persona = card_to_persona(card)
    if args.check_inputs:
        print(
            json.dumps(
                {
                    "status": "inputs-valid",
                    "persona_library": str(args.persona_library),
                    "personas": [persona.persona_id],
                }
            )
        )
        return 0
    load_secrets(args.secrets_file)
    role_environment("USER")
    client = TracingClient()
    harness = TraceHarness()
    task = (
        "Please add split_bill(total, n) to billing/core.py and run a quick smoke test. "
        "Only touch billing — do not refactor unrelated packages or hit the network."
    )
    print(f"persona={persona.persona_id} d42={persona.d42.value} trust={persona.trust.value}")
    res = run_session(persona, client, harness, task, manual=harness.manual)
    print(
        f"\n=== end={res.end_reason} emitted={harness.emitted} controls={harness.controls} "
        f"feeling={(res.feeling.score if res.feeling else None)} ==="
    )
    after = [
        r
        for r in client.after_status_logs
        if "send_message" in (r["history_tail"] or "") and "/status" in (r["history_tail"] or "")
    ]
    print(f"\nAFTER_STATUS hops: {len(after)}")
    for r in after:
        print(f"  #{r['i']} {r['kind']}: {r['ret']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
