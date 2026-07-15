#!/usr/bin/env python3
"""探针：有进度 vs 无进度的长跑等待——看真用户 agent 怎么选。

用法（仓根）：
  PYTHONPATH=backend .venv/bin/python backend/scripts/probe_wait_progress.py

凭证：/Users/bytedance/cjh/.env 的 LLM_* → USER_LLM_*。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
HOME_ENV = Path("/Users/bytedance/cjh/.env")


def _load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _setup_llm() -> None:
    home = _load_env(HOME_ENV) if HOME_ENV.is_file() else {}
    backend = _load_env(ROOT / ".env") if (ROOT / ".env").is_file() else {}
    model = home.get("LLM_MODEL") or backend.get("USER_LLM_MODEL")
    base = home.get("LLM_BASE_URL") or backend.get("USER_LLM_BASE_URL")
    key = home.get("LLM_API_KEY") or backend.get("USER_LLM_API_KEY")
    if not (model and base and key):
        raise SystemExit("缺 LLM 凭证")
    for role in ("USER",):
        os.environ[f"{role}_LLM_MODEL"] = model
        os.environ[f"{role}_LLM_BASE_URL"] = base
        os.environ[f"{role}_LLM_API_KEY"] = key
    host = urlparse(base).hostname
    bypass = ["localhost", "127.0.0.1"]
    if host:
        bypass.append(host)
    os.environ["NO_PROXY"] = ",".join(bypass)
    os.environ["no_proxy"] = os.environ["NO_PROXY"]
    print(f"LLM model={model} base={base}")


class SlowProgressHarness:
    """模拟 Codex：多次 pending，每次多一条工具活动，最后才 reply。"""

    def __init__(self, *, with_progress: bool) -> None:
        self.with_progress = with_progress
        self.last_progress: list[dict] = []
        self.last_steps: list[dict] = []
        self.manual = (
            "# Manual\nCoding assistant. While it works you see a short activity strip.\n"
            "You can interrupt a running request.\n"
        )
        self._n = 0
        self._closed = False
        self._t0 = 0.0

    def begin(self, message: str) -> None:  # noqa: ARG002
        self._n = 0
        self.last_progress = []
        self._t0 = time.monotonic()

    def poll(self, timeout: float) -> tuple[str, object]:  # noqa: ARG002
        self._n += 1
        waited = time.monotonic() - self._t0 + self._n * 90.0  # 假装已等 n*90s
        if self.with_progress:
            # 每次心跳多一条新活动（像真人看见它还在干活）
            activities = [
                "🔧 read_file: billing/core.py",
                "🔧 run_shell: python -c 'import billing'",
                "🔧 run_shell: pytest billing/ -q",
                "🔧 run_shell: pytest billing/ -q  (retry after fix)",
            ]
            self.last_progress = [
                {"kind": "tool", "text": t} for t in activities[: min(self._n, len(activities))]
            ]
        # 前 3 次 pending，第 4 次交付
        if self._n < 4:
            return ("pending", waited)
        return ("reply", "Added split_bill and smoke-tested; all green.")

    def control(self, name: str) -> str:
        return f"[interrupted] stopped via {name}; session kept."

    def reset(self) -> None:
        self._n = 0
        self.last_progress = []

    def close(self) -> None:
        self._closed = True


def _run_one(*, label: str, with_progress: bool) -> None:
    from auto_designer.user.sim.dimensions import (
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
    from auto_designer.user.sim.loop import run_session
    from auto_designer.user.sim.persona_client import ApiPersonaClient

    persona = finalize_persona(
        Persona(
            persona_id=f"P-{label}",
            d1=D1Eval.EXPERT,
            d2=D2Domain(stack=("python",), depth=D2Depth.SENIOR, weak=()),
            d41=D41Grain.SPEC_LEVEL,
            d42=D42Supervise.EVERY_STEP,
            d43=D43Correct.FILE_ISSUE,
            d5=D5Autonomy.COLLABORATIVE,
        )
    )
    client = ApiPersonaClient()
    harness = SlowProgressHarness(with_progress=with_progress)
    task = (
        "Please add split_bill(total, n) to billing/core.py and run a quick smoke test. "
        "It's a small change but feel free to take the time you need if you're actually working."
    )
    print(f"\n======== {label} (progress={with_progress}) ========")
    t0 = time.monotonic()
    res = run_session(persona, client, harness, task, manual=harness.manual)
    print(f"elapsed={time.monotonic() - t0:.1f}s end={res.end_reason}")
    if res.feeling:
        print(f"feeling={res.feeling.score}/4 — {res.feeling.reason}")
    for t in res.turns:
        if t.phase == "waiting":
            print(
                f"  WAIT action={t.action} patience={t.patience} "
                f"perceive={t.perceive!r} verdict={t.verdict}"
            )
        else:
            print(
                f"  turn={t.turn} action={t.action} patience={t.patience} "
                f"msg={t.message[:80]!r}"
            )


def main() -> int:
    sys.path.insert(0, str(ROOT))
    _setup_llm()
    _run_one(label="WITH-PROGRESS", with_progress=True)
    _run_one(label="BLACK-BOX", with_progress=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
