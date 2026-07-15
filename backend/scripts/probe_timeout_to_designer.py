#!/usr/bin/env python3
"""探针：超时 harness × 真用户 agent → SessionStore → 真设计师（看它怎么判）。

用法（仓根）：
  PYTHONPATH=backend .venv/bin/python backend/scripts/probe_timeout_to_designer.py

凭证默认读 /Users/bytedance/cjh/.env 的 LLM_*，映射到 USER_LLM_* / DESIGNER_LLM_*。
harness 是脚本化「一直超时 + 0 步」——不启真 nexau 子进程，专测信号链路。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]  # backend/
HOME_ENV = Path("/Users/bytedance/cjh/.env")
TEMPLATE = ROOT / "harness_template"
DESIGNER_DEF = ROOT / "agent_defs" / "designer"


def _load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _setup_llm_env() -> None:
    """用户指定的家目录 .env → 角色变量；缺字段再回落 backend/.env。"""
    home = _load_env(HOME_ENV) if HOME_ENV.is_file() else {}
    backend = _load_env(ROOT / ".env") if (ROOT / ".env").is_file() else {}
    model = home.get("LLM_MODEL") or backend.get("USER_LLM_MODEL") or backend.get("LLM_MODEL")
    base = (
        home.get("LLM_BASE_URL") or backend.get("USER_LLM_BASE_URL") or backend.get("LLM_BASE_URL")
    )
    key = home.get("LLM_API_KEY") or backend.get("USER_LLM_API_KEY") or backend.get("LLM_API_KEY")
    if not (model and base and key):
        raise SystemExit(f"缺 LLM 凭证：请检查 {HOME_ENV} 或 {ROOT / '.env'}")
    for role in ("USER", "DESIGNER"):
        os.environ[f"{role}_LLM_MODEL"] = model
        os.environ[f"{role}_LLM_BASE_URL"] = base
        os.environ[f"{role}_LLM_API_KEY"] = key
    # harness 仓 agent.yaml 若被 designer 误触 plain LLM_*，一并填上
    os.environ["LLM_MODEL"] = model
    os.environ["LLM_BASE_URL"] = base
    os.environ["LLM_API_KEY"] = key
    host = urlparse(base).hostname
    bypass = ["localhost", "127.0.0.1"]
    if host:
        bypass.append(host)
    os.environ["NO_PROXY"] = ",".join(bypass)
    os.environ["no_proxy"] = os.environ["NO_PROXY"]
    print(f"LLM model={model} base={base} (key=***)")


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
    sys.path.insert(0, str(ROOT))
    _setup_llm_env()

    from auto_designer.designer.designer import Designer
    from auto_designer.designer.runtime_agg import aggregate_runtime, format_runtime_agg
    from auto_designer.loop.sim_user import make_sim_run_session_fn
    from auto_designer.models import Persona, SeedScenario
    from auto_designer.tracker.fake import FakeTracker
    from auto_designer.user.session_store import SessionStore
    from auto_designer.user.sim.dimensions import (
        D1Eval,
        D2Depth,
        D2Domain,
        D5Autonomy,
        D41Grain,
        D42Supervise,
        D43Correct,
        finalize_persona,
    )
    from auto_designer.user.sim.dimensions import (
        Persona as SimPersona,
    )
    from auto_designer.user.sim.persona_client import AgenticPersonaClient, ApiPersonaClient

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
        print(f"  [designer] running={running} status={status} proposals={proposals}")
        if detail and not running:
            print("--- designer detail (truncated) ---")
            text = str(detail)
            print(text[:3000] + ("…" if len(text) > 3000 else ""))

    designer = Designer(
        tracker=tracker,
        store=store,
        harness_repo=str(harness_repo),
        agent_def_dir=str(DESIGNER_DEF),
        on_status=on_status,
        on_event=lambda kind, text: print(f"    · {kind}: {text[:120]}"),
    )
    t1 = time.monotonic()
    outcome = designer.propose_once()
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
