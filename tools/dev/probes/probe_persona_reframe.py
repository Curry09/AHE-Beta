#!/usr/bin/env python3
"""手动对照模拟：tempo ⊥ d43、过程卷入影响 stuck、卡注入缺省/显式 D7。

Spec-0037/T6: 脚本态正交探针（非 CI 门禁）。

不依赖 LLM、不绑 v0 harness 协议细节——只跑状态机 + 脚本会话 + 卡注入。

  PYTHONPATH=backend python -m tools.dev.probes.probe_persona_reframe
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_designer.user.sim.clauses import compile_block_p  # noqa: E402
from auto_designer.user.sim.dimensions import (  # noqa: E402
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
from auto_designer.user.sim.harness_adapter import ScriptedHarness  # noqa: E402
from auto_designer.user.sim.loop import run_session  # noqa: E402
from auto_designer.user.sim.persona_client import ScriptedPersonaClient  # noqa: E402
from auto_designer.user.sim.persona_io import card_to_persona  # noqa: E402
from auto_designer.user.sim.state import apply_verdict, init_state, make_coef  # noqa: E402


def _p(
    *,
    pid: str,
    tempo: TimeTemperament,
    d43: D43Correct = D43Correct.FEEDBACK,
    d42: D42Supervise = D42Supervise.PHASE_CHECK,
    d1: D1Eval = D1Eval.SHALLOW,
) -> Persona:
    return finalize_persona(
        Persona(
            persona_id=pid,
            d1=d1,
            d2=D2Domain(stack=("python",), depth=D2Depth.PROFICIENT),
            d41=D41Grain.HALF_CONTEXT,
            d42=d42,
            d43=d43,
            d5=D5Autonomy.COLLABORATIVE,
            tempo=tempo,
        )
    )


def section(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def probe_orthogonality() -> list[str]:
    """期望：patience 跟 tempo，不跟 d43。"""
    bugs: list[str] = []
    cases = [
        ("feedback+impatient", D43Correct.FEEDBACK, TimeTemperament.IMPATIENT, 3, 2),
        ("feedback+patient", D43Correct.FEEDBACK, TimeTemperament.PATIENT, 7, 1),
        ("give_up+patient", D43Correct.GIVE_UP, TimeTemperament.PATIENT, 7, 1),
        ("give_up+impatient", D43Correct.GIVE_UP, TimeTemperament.IMPATIENT, 3, 2),
    ]
    section("1) tempo ⊥ d43（耐心基线/衰减）")
    for name, d43, tempo, want_p0, want_decay in cases:
        p = _p(pid=name, tempo=tempo, d43=d43)
        st = init_state(p)
        coef = make_coef(p)
        ok = st.patience == want_p0 and coef.patience_decay == want_decay
        mark = "OK" if ok else "BUG"
        print(
            f"  [{mark}] {name}: patience0={st.patience} (want {want_p0}), "
            f"decay={coef.patience_decay} (want {want_decay})"
        )
        if not ok:
            bugs.append(f"orthogonality:{name}")
    return bugs


def probe_stuck_involvement() -> list[str]:
    bugs: list[str] = []
    section("2) 过程卷入抬高 stuck 扣减")
    low = _p(pid="low", tempo=TimeTemperament.STEADY, d42=D42Supervise.FIRE_FORGET)
    high = _p(pid="high", tempo=TimeTemperament.STEADY, d42=D42Supervise.EVERY_STEP)
    s_low, s_high = init_state(low), init_state(high)
    apply_verdict(s_low, "stuck", make_coef(low))
    apply_verdict(s_high, "stuck", make_coef(high))
    print(f"  low involvement after stuck: patience={s_low.patience}")
    print(f"  high involvement after stuck: patience={s_high.patience}")
    if not (s_high.patience < s_low.patience):
        bugs.append("stuck_involvement: high should drop faster")
        print("  [BUG] high involvement should have lower patience after stuck")
    else:
        print("  [OK] high involvement drops faster on stuck")
    return bugs


def probe_prompt_language() -> list[str]:
    bugs: list[str] = []
    section("3) BLOCK-P 是人话，不焊产品 UX")
    p = _p(
        pid="prompt",
        tempo=TimeTemperament.IMPATIENT,
        d42=D42Supervise.EVERY_STEP,
        d43=D43Correct.FILE_ISSUE,
    )
    block = compile_block_p(p)
    print(block)
    forbidden = ["interrupt", "queued", "/help", "keep_waiting", "ctrl+c"]
    hits = [w for w in forbidden if w in block.lower()]
    if hits:
        bugs.append(f"prompt_language:{hits}")
        print(f"  [BUG] product words leaked into persona block: {hits}")
    else:
        print("  [OK] no product UX words in persona block")
    for needle in ("Process involvement", "Time temperament", "SESSION POLICY", "opaque"):
        if needle.lower() not in block.lower() and needle not in block:
            # SESSION POLICY and Process involvement are exact; opaque is in clause
            if needle == "opaque" and "opaque" not in block:
                bugs.append("prompt_missing:opaque")
                print("  [BUG] missing opaque-process language")
            elif needle != "opaque" and needle not in block:
                bugs.append(f"prompt_missing:{needle}")
                print(f"  [BUG] missing section/marker: {needle}")
    if not bugs:
        print("  [OK] reframed sections present")
    return bugs


def probe_card_injection() -> list[str]:
    bugs: list[str] = []
    section("4) 卡注入：显式 D7 + 旧卡缺省 steady")
    base = {
        "id": "probe-card",
        "authenticity": "authentic",
        "dimensions": {
            "D1_evaluation_capability": {"value": "competent", "source": "grounded"},
            "D2_acceptance_bar": {
                "primary": "functional",
                "flags": [],
                "source": "grounded",
            },
            "D3_interaction_style": {
                "delegation": {"value": "loose", "source": "grounded"},
                "supervision": {"value": "reviews", "source": "grounded"},
                "on_offtrack": {"value": "correct", "source": "grounded"},
            },
            "D4_trust_model": {"value": "balanced", "source": "grounded"},
            "D5_domain": {
                "area": "web-backend",
                "depth": "working",
                "stack": ["python"],
                "weak": [],
                "source": "grounded",
            },
            "D6_autonomy_expectation": {"value": "collaborative", "source": "grounded"},
        },
    }
    old = card_to_persona(base)
    if old.tempo is not TimeTemperament.STEADY:
        bugs.append("card_default_tempo")
        print(f"  [BUG] missing D7 should be steady, got {old.tempo}")
    else:
        print("  [OK] missing D7 → steady")

    import copy

    card2 = copy.deepcopy(base)
    card2["dimensions"]["D7_time_temperament"] = {
        "value": "impatient",
        "source": "injected",
        "confidence": "low",
    }
    p2 = card_to_persona(card2)
    if p2.tempo is not TimeTemperament.IMPATIENT:
        bugs.append("card_explicit_tempo")
        print(f"  [BUG] explicit impatient, got {p2.tempo}")
    else:
        print("  [OK] explicit D7 → impatient")
    return bugs


def probe_scripted_session() -> list[str]:
    bugs: list[str] = []
    section("5) 脚本会话冒烟（能力分叉仍可跑通）")
    client = ScriptedPersonaClient()
    for p in (
        _p(pid="sess-shallow", tempo=TimeTemperament.STEADY, d1=D1Eval.SHALLOW),
        _p(
            pid="sess-expert",
            tempo=TimeTemperament.STEADY,
            d1=D1Eval.EXPERT,
            d43=D43Correct.FILE_ISSUE,
            d42=D42Supervise.EVERY_STEP,
        ),
    ):
        res = run_session(p, client, ScriptedHarness(), "Add to_user_tz; handle DST.")
        print(
            f"  {p.persona_id}: end={res.end_reason} turns={len(res.turns)} "
            f"feeling={res.feeling_derived.score if res.feeling_derived else None}"
        )
        if not res.turns:
            bugs.append(f"empty_session:{p.persona_id}")
    if not bugs:
        print("  [OK] scripted sessions completed")
    return bugs


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    bugs: list[str] = []
    bugs.extend(probe_orthogonality())
    bugs.extend(probe_stuck_involvement())
    bugs.extend(probe_prompt_language())
    bugs.extend(probe_card_injection())
    bugs.extend(probe_scripted_session())
    section("SUMMARY")
    if bugs:
        print(f"BUGS ({len(bugs)}):")
        for b in bugs:
            print(f"  - {b}")
        return 1
    print("All probes passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
