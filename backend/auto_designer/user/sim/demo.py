"""
demo.py
跑两个 persona 走同一条 harness 轨迹, 并排看信号如何随能力分叉。
  P-0473  SHALLOW + FEEDBACK(耗尽则放弃)   -> 预期: 漏掉 DST 逃逸 bug, accept
  P-0991  EXPERT  + FILE_ISSUE             -> 预期: 识破, 耐心耗尽 -> file_issue

运行(无需 API key, 用离线脚本后端):
  python3 -m auto_designer.user.sim.demo
有 LLM 网关 (USER_LLM_BASE_URL+USER_LLM_API_KEY) 或 OPENAI_API_KEY 时自动改用真实 LLM。
"""

from __future__ import annotations

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
from .harness_adapter import ScriptedHarness
from .loop import run_session
from .persona_client import make_client

TASK = (
    "Write to_user_tz(dt, tz_name) in the timeutils lib: convert a naive datetime "
    "to the given timezone, must not break on DST boundaries. We mainly use "
    "Asia/Shanghai and America/New_York."
)


def make_personas():
    p0473 = finalize_persona(
        Persona(
            persona_id="P-0473",
            d1=D1Eval.SHALLOW,
            d2=D2Domain(stack=("python",), depth=D2Depth.PROFICIENT, weak=("timezone", "pytz")),
            d41=D41Grain.HALF_CONTEXT,
            d42=D42Supervise.PHASE_CHECK,
            d43=D43Correct.FEEDBACK,
            d5=D5Autonomy.COLLABORATIVE,
        )
    )
    p0991 = finalize_persona(
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
    return [p0473, p0991]


def print_result(res):
    print("=" * 72)
    print(f"PERSONA {res.persona_id}   ->   END: {res.end_reason}")
    print("=" * 72)
    for t in res.turns:
        print(f"\n  TURN {t.turn} [{t.phase}] patience={t.patience} trust={t.trust}")
        print(f"    action_space : {t.action_space}")
        print(f"    perceive     : {t.perceive[:110]}")
        print(f"    verdict      : {t.verdict}")
        print(f"    action       : {t.action}  ({t.executor}/{t.channel})")
        if t.message:
            print(f"    message      : {t.message[:110]}")
    if res.feeling or res.feeling_derived:
        print("\n  --- FEELING SCORE (training signal) ---")
        if res.feeling:
            print(f"    llm-rated : {res.feeling.score}/4  — {res.feeling.reason}")
        if res.feeling_derived:
            print(f"    derived   : {res.feeling_derived.score}/4  — {res.feeling_derived.reason}")
    print("\n  --- FEEDBACK SIGNALS (to developers) ---")
    for s in res.signals:
        print(f"    * {s}")
    if res.issue_artifact:
        print("\n  --- ISSUE ARTIFACT ---")
        for line in res.issue_artifact.splitlines():
            print("    " + line)
    print()


def main():
    client = make_client()
    for persona in make_personas():
        harness = ScriptedHarness()  # 每个 persona 用全新 harness 轨迹
        res = run_session(persona, client, harness, TASK)
        print_result(res)


if __name__ == "__main__":
    main()
