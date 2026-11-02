#!/usr/bin/env python3
"""探针：超时 harness × 真用户 agent → SessionStore → 真设计师（看它怎么判）。

用法（仓根）：
  PYTHONPATH=backend .venv/bin/python -m tools.dev.probes.probe_timeout_to_architect

凭证通过 --secrets-file 显式提供，或预先注入环境变量。
harness 是脚本化「一直超时 + 0 步」——不启真 nexau 子进程，专测信号链路。
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
    """脚本化 harness：每轮都超时，且 last_steps=[]（0 步轮）——模拟「预算太紧/内层空转」。"""

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
        self.last_steps = []  # 关键：内层零过程流
        # 轻微墙钟，让用户侧感知到「等了一会儿才失败」（非真 120s，探针要跑得完）
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

    # 专家用户：会核验、会提 issue——超时场景下最可能留下强信号
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

    print("\n=== A｜用户 agent × TimeoutHarness ===")
    t0 = time.monotonic()
    session = run_fn(display, scenario, TimeoutHarness())
    print(f"会话耗时 {time.monotonic() - t0:.1f}s  session_id={session.session_id}")
    print(f"feeling={session.feeling.score}/4 — {session.feeling.reason}")
    print(f"issues={session.issue_refs}  open={len(tracker.list_open_issues())}")
    # 把 sim 侧细节也打出来（若 make_sim 里拿不到 SessionResult，至少看 transcript）
    print("\n--- transcript ---")
    for i, turn in enumerate(session.transcript.turns):
        steps_n = len(turn.steps)
        print(f"  [{i}] {turn.role} steps={steps_n}: {turn.content[:100]!r}")

    print("\n=== 运行时聚合（喂设计师前先看一眼）===")
    agg_text = format_runtime_agg(
        aggregate_runtime(store=store, harness_repo=harness_repo, recent_n=50)
    )
    print(agg_text)

    print("\n=== D｜设计师 agent ===")

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
    print(f"设计师耗时 {time.monotonic() - t1:.1f}s  proposals={outcome.proposal_numbers}")

    print("\n=== 最终 backlog ===")
    for issue in tracker.list_open_issues():
        print(f"\n#{issue.number} [{','.join(issue.labels)}] {issue.title}")
        print(issue.body[:800])
        if len(issue.body) > 800:
            print("…")

    print(f"\n(工件目录保留：{work})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
