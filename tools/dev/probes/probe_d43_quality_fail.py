#!/usr/bin/env python3
"""质量失败策略（d43）对照：真 LLM 用户 × ScriptedHarness（会反复交错/半吊子实现）。

Spec-0037/T6: d43 路径可观测；与 tempo 正交（本探针固定/同 tempo）。

同题同 tempo，只改 d43，看收场是 feedback 循环 / give_up / file_issue / handover / resend。

用法（仓根）：
  PYTHONPATH=backend PYTHONUNBUFFERED=1 .venv/bin/python -u \\
    -m tools.dev.probes.probe_d43_quality_fail [--d43 feedback] ...
  不传 --d43 则五档全跑（可并行多进程，本脚本串行；外层并行用多次调用）。
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from tools.dev import add_inputs, load_secrets, role_environment

ROOT = Path(__file__).resolve().parents[3] / "backend"


TASK = (
    "Write to_user_tz(dt, tz_name) in the timeutils lib: convert a naive datetime "
    "to the given timezone, must not break on DST boundaries. We mainly use "
    "Asia/Shanghai and America/New_York."
)


def _persona(d43_value: str):
    from ahe_beta.user.sim.dimensions import (
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

    return finalize_persona(
        Persona(
            persona_id=f"d43-{d43_value}",
            d1=D1Eval.EXPERT,  # 能识破 DST 错实现
            d2=D2Domain(stack=("python",), depth=D2Depth.SENIOR, weak=()),
            d41=D41Grain.SPEC_LEVEL,
            d42=D42Supervise.PHASE_CHECK,
            d43=D43Correct(d43_value),
            d5=D5Autonomy.COLLABORATIVE,
            tempo=TimeTemperament.STEADY,  # 失败策略对照，气质固定
        )
    )


def _run_one(d43_value: str) -> int:
    from ahe_beta.user.sim.harness_adapter import ScriptedHarness
    from ahe_beta.user.sim.loop import run_session
    from ahe_beta.user.sim.persona_client import AgenticPersonaClient, ApiPersonaClient
    from ahe_beta.user.sim.state import init_state, make_coef

    persona = _persona(d43_value)
    st0 = init_state(persona)
    coef = make_coef(persona)
    print(
        f"\n### d43={persona.d43.value} tempo={persona.tempo.value} "
        f"patience0={st0.patience} decay={coef.patience_decay}",
        flush=True,
    )

    api = ApiPersonaClient()
    client = AgenticPersonaClient(api.complete)
    # 无真实工作区：内层工具会受限，但仍可走 judge/intent/act + d43 文案
    harness = ScriptedHarness()

    turns_seen = 0

    def on_progress(partial) -> None:
        nonlocal turns_seen
        n = len(partial.turns)
        if n <= turns_seen:
            return
        turns_seen = n
        t = partial.turns[-1]
        print(
            f"  [turn {n} {getattr(t, 'phase', '')}] "
            f"action={getattr(t, 'action', '')} "
            f"patience={getattr(t, 'patience', '')} "
            f"verdict={getattr(t, 'verdict', '')} "
            f"msg={(getattr(t, 'message', '') or '')[:90]!r}",
            flush=True,
        )

    t0 = time.monotonic()
    res = run_session(persona, client, harness, TASK, on_progress=on_progress)
    elapsed = time.monotonic() - t0
    feel = res.feeling or res.feeling_derived
    actions = [getattr(t, "action", "") for t in res.turns]
    print("=== RESULT ===", flush=True)
    print(
        f"d43={d43_value} end={res.end_reason} feeling={feel.score if feel else None} "
        f"reason={(feel.reason if feel else '')[:200]!r}",
        flush=True,
    )
    print(f"turns={len(res.turns)} elapsed_s={elapsed:.1f} actions={actions}", flush=True)
    if res.issue_artifact:
        print(f"issue[:200]={res.issue_artifact[:200]!r}", flush=True)
    return 0 if res.end_reason else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--d43",
        action="append",
        dest="d43s",
        choices=["feedback", "handover", "resend", "give_up", "file_issue"],
        help="不传则五档全跑",
    )
    add_inputs(parser)
    args = parser.parse_args()
    load_secrets(args.secrets_file)
    role_environment("USER")
    d43s = args.d43s or ["feedback", "handover", "resend", "give_up", "file_issue"]
    rc = 0
    for d in d43s:
        rc = _run_one(d) or rc
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
