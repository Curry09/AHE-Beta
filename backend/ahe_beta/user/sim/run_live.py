"""
run_live.py
Live test: my orchestrated harness trajectory (scenarios.SplitBillHarness) against *real Nex user agent*
(ApiPersonaClient, uses NexAU gateway from repo .env).

  uv run python -m ahe_beta.user.sim.run_live shallow
  uv run python -m ahe_beta.user.sim.run_live expert

Both personas traverse the same harness trajectory, observing capability fork (purely subjective, no oracle):
  shallow → accepts standard test cases → money-losing bug escapes (low perception fails to surface; high perception accepts)
  expert  → constructs 100/3 boundary, reads sum=99.99 in text → forces evidence to patience exhaustion → files_issue
"""

from __future__ import annotations

import sys

from .demo import print_result
from .dimensions import (
    D1Eval,
    D2Depth,
    D2Domain,
    D5Autonomy,
    D41Grain,
    D42Supervise,
    D43Correct,
    Persona,
    finalize_persona,
)
from .loop import run_session
from .persona_client import ApiPersonaClient
from .scenarios import SplitBillHarness

# NOTE: a REAL coding task on the user's OWN project — deliberately requiring the assistant to
# edit code and actually RUN it (not just chat). A harness with no file/test tools must honestly
# hit its capability gap (it can advise, it cannot act), and surfacing THAT gap as a user issue
# is exactly the structural signal we want (it tells developers "v0 only handles advisory tasks;
# build tool-calling"). Still natural / underspecified: the acceptance criterion (shares must sum
# EXACTLY to total) is NOT stated, so catching the lost cent comes from the PERSONA's capability +
# bar, not from the task leaking the oracle. "Theoretically completable" = a harness that evolves
# real file/test tools could do it; whether v0 can is evolution's problem, not the task's.
TASK = (
    "I've got a small Python billing module (billing/core.py) in my project. Add a "
    "split_bill(total, n) function there that splits a bill total among n people, then "
    "run it and show me it actually works before calling it done."
)


def shallow() -> Persona:
    return finalize_persona(
        Persona(
            persona_id="P-0473",
            d1=D1Eval.SHALLOW,
            d2=D2Domain(stack=("python",), depth=D2Depth.PROFICIENT, weak=("money/rounding",)),
            d41=D41Grain.HALF_CONTEXT,
            d42=D42Supervise.PHASE_CHECK,
            d43=D43Correct.FEEDBACK,
            d5=D5Autonomy.COLLABORATIVE,
        )
    )


def expert() -> Persona:
    return finalize_persona(
        Persona(
            persona_id="P-0991",
            d1=D1Eval.EXPERT,
            d2=D2Domain(stack=("python",), depth=D2Depth.SENIOR, weak=()),
            d41=D41Grain.SPEC_LEVEL,
            d42=D42Supervise.EVERY_STEP,
            d43=D43Correct.FILE_ISSUE,
            d5=D5Autonomy.COLLABORATIVE,
        )
    )


PERSONAS = {"shallow": shallow, "expert": expert}


def main() -> None:
    who = sys.argv[1] if len(sys.argv) > 1 else "shallow"
    persona = PERSONAS[who]()
    client = ApiPersonaClient()
    print(f"(live NexAU user-agent: model={client.model})\n")
    res = run_session(persona, client, SplitBillHarness(), TASK)
    print_result(res)


if __name__ == "__main__":
    main()
