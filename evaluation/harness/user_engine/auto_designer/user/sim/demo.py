"""
demo.py
对照两组正交轴：
  1) 能力分叉（浅层 vs 专家）——体感/验收差异
  2) 时间气质分叉（同失败策略下 impatient vs patient）——等待耐心差异

Spec-0037/T2: demo 打印 tempo / patience0 / stuck_extra，展示正交。

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
    TimeTemperament,
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
    # 能力分叉：浅层易浅接受；专家易识破并 file_issue
    shallow = finalize_persona(
        Persona(
            persona_id="P-shallow-steady",
            d1=D1Eval.SHALLOW,
            d2=D2Domain(stack=("python",), depth=D2Depth.PROFICIENT, weak=("timezone", "pytz")),
            d41=D41Grain.HALF_CONTEXT,
            d42=D42Supervise.PHASE_CHECK,
            d43=D43Correct.FEEDBACK,
            d5=D5Autonomy.COLLABORATIVE,
            tempo=TimeTemperament.STEADY,
        )
    )
    expert = finalize_persona(
        Persona(
            persona_id="P-expert-steady",
            d1=D1Eval.EXPERT,
            d2=D2Domain(stack=("python",), depth=D2Depth.SENIOR, weak=()),
            d41=D41Grain.SPEC_LEVEL,
            d42=D42Supervise.EVERY_STEP,
            d43=D43Correct.FILE_ISSUE,
            d5=D5Autonomy.COLLABORATIVE,
            tempo=TimeTemperament.STEADY,
        )
    )
    # 正交证明：同为 FEEDBACK，仅 tempo 不同（脚本后端不会走长等待，但 state 初值可见）
    impatient = finalize_persona(
        Persona(
            persona_id="P-feedback-impatient",
            d1=D1Eval.SHALLOW,
            d2=D2Domain(stack=("python",), depth=D2Depth.PROFICIENT),
            d41=D41Grain.HALF_CONTEXT,
            d42=D42Supervise.FIRE_FORGET,
            d43=D43Correct.FEEDBACK,
            d5=D5Autonomy.COLLABORATIVE,
            tempo=TimeTemperament.IMPATIENT,
        )
    )
    patient_giver = finalize_persona(
        Persona(
            persona_id="P-giveup-patient",
            d1=D1Eval.SHALLOW,
            d2=D2Domain(stack=("python",), depth=D2Depth.PROFICIENT),
            d41=D41Grain.HALF_CONTEXT,
            d42=D42Supervise.FIRE_FORGET,
            d43=D43Correct.GIVE_UP,
            d5=D5Autonomy.COLLABORATIVE,
            tempo=TimeTemperament.PATIENT,
        )
    )
    return [shallow, expert, impatient, patient_giver]


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
    from .state import init_state, make_coef

    client = make_client()
    for persona in make_personas():
        st = init_state(persona)
        coef = make_coef(persona)
        print(
            f"[init] {persona.persona_id}: tempo={persona.tempo.value} "
            f"d43={persona.d43.value} patience0={st.patience} "
            f"decay={coef.patience_decay} stuck_extra={coef.stuck_extra}"
        )
        print(f"  process involvement clause id: {persona.d42.value}")
        harness = ScriptedHarness()
        res = run_session(persona, client, harness, TASK)
        print_result(res)


if __name__ == "__main__":
    main()
