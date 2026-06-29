"""
run_live.py
实测: 我编排的 harness 轨迹(scenarios.SplitBillHarness)对阵 *真实 Nex 用户 agent*
(ApiPersonaClient, 走 repo .env 的 NexAU 网关)。

  uv run python -m auto_designer.user.sim.run_live shallow
  uv run python -m auto_designer.user.sim.run_live expert

两个 persona 走同一条 harness 轨迹, 看能力分叉(纯主观, 无 oracle):
  shallow -> 跑常规用例就接受 -> 丢分钱的 bug 逃逸(低体感才暴露不出, 高体感接受)
  expert  -> 构造 100/3 边界, 文本里读到 sum=99.99 -> 逼证据到耐心耗尽 -> file_issue
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

# NOTE: natural / underspecified on purpose. The acceptance criterion (shares must
# sum exactly to total) is NOT stated — whether the user catches the lost cent must come
# from the PERSONA's capability + acceptance bar, not from the task leaking the oracle.
TASK = (
    "We have a billing library. Add a split_bill(total, n) function that splits a bill "
    "total among n people. Put it in the repo and show me it works."
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
