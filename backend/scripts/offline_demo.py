#!/usr/bin/env python3
"""Run synthetic persona sessions with scripted clients; never select an LLM."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ahe_beta.user.sim.demo import TASK, make_personas, print_result  # noqa: E402
from ahe_beta.user.sim.harness_adapter import ScriptedHarness  # noqa: E402
from ahe_beta.user.sim.loop import run_session  # noqa: E402
from ahe_beta.user.sim.persona_client import ScriptedPersonaClient  # noqa: E402


def main() -> None:
    for persona in make_personas():
        result = run_session(persona, ScriptedPersonaClient(), ScriptedHarness(), TASK)
        print_result(result)
    print("Offline demo complete: scripted sessions only; no model, forge or delivery invoked.")


if __name__ == "__main__":
    main()
