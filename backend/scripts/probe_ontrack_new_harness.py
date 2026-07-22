#!/usr/bin/env python3
"""探针：新 harness 契约下 expert vs blind 的 ON-TRACK 等待表现。

模拟进化后 harness：MANUAL 含 `/status` slash（message 通道）；interrupt 走外窗口。
只跑 ON-TRACK × {expert, blind}（Spec-0022/0023 three）。

用法（仓根）：
  PYTHONPATH=backend .venv/bin/python backend/scripts/probe_ontrack_new_harness.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
HOME_ENV = Path("/Users/bytedance/cjh/.env")
EVOLVED_MANUAL = Path(
    "/var/folders/9y/x15s235d6bxfb1rdk1v9f22w0000gn/T/probe_wait_evo_tkv5cz1e/harness/MANUAL.md"
)


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
    os.environ["USER_LLM_MODEL"] = model
    os.environ["USER_LLM_BASE_URL"] = base
    os.environ["USER_LLM_API_KEY"] = key
    host = urlparse(base).hostname
    bypass = ["localhost", "127.0.0.1"]
    if host:
        bypass.append(host)
    os.environ["NO_PROXY"] = ",".join(bypass)
    os.environ["no_proxy"] = os.environ["NO_PROXY"]
    print(f"LLM model={model} base={base}")


def _manual() -> str:
    if EVOLVED_MANUAL.is_file():
        return EVOLVED_MANUAL.read_text(encoding="utf-8")
    return (
        "# Manual\nCoding assistant with activity strip.\n"
        "While waiting you may send `/status` as a normal message.\n"
        "Ctrl+C (interrupt) stops the current request.\n"
    )


class NewHarnessContract:
    """对齐进化 harness：progress 条 + `/status` via emit_message；interrupt 收工。"""

    def __init__(self, *, activities: list[list[str]], reply: str = "done.") -> None:
        self._activities = activities
        self._reply = reply
        self.manual = _manual()
        self.last_progress: list[dict] = []
        self.last_steps: list[dict] = []
        self._n = 0
        self._inflight = False
        self.controls: list[str] = []
        self.emitted: list[str] = []

    @property
    def in_flight(self) -> bool:
        return self._inflight

    def begin(self, message: str) -> None:  # noqa: ARG002
        self._n = 0
        self._inflight = True
        self.last_progress = []

    def emit_message(self, message: str) -> None:
        self.emitted.append(message)
        preview = self.last_progress[-1]["text"] if self.last_progress else "(none yet)"
        self.last_progress = [
            *self.last_progress,
            {"kind": "status", "text": f"status via message: still running; last={preview}"},
        ]

    def poll(self, timeout: float) -> tuple[str, object]:  # noqa: ARG002
        self._n += 1
        waited = float(self._n * 90)
        idx = min(self._n - 1, len(self._activities) - 1)
        titles = self._activities[idx] if self._activities else []
        self.last_progress = [{"kind": "tool", "text": t} for t in titles]
        if self._n <= len(self._activities):
            return ("pending", waited)
        self._inflight = False
        return ("reply", self._reply)

    def control(self, name: str) -> str:
        self.controls.append(name)
        self._inflight = False
        return (
            f"[interrupted] You stopped this request via `{name}`; session kept — send a follow-up."
        )

    def reset(self) -> None:
        self._n = 0
        self._inflight = False
        self.last_progress = []

    def close(self) -> None:
        pass


# ON-TRACK：多拍进度，给足几次心跳做 send_message(/status) / keep_waiting / interrupt
ON_TRACK: list[list[str]] = [
    ["🔧 read_file: billing/core.py"],
    [
        "🔧 read_file: billing/core.py",
        "🔧 run_shell: python -c 'from billing.core import split_bill'",
    ],
    [
        "🔧 read_file: billing/core.py",
        "🔧 run_shell: python -c 'from billing.core import split_bill'",
        "🔧 run_shell: pytest billing/ -q",
    ],
    [
        "🔧 read_file: billing/core.py",
        "🔧 run_shell: python -c 'from billing.core import split_bill'",
        "🔧 run_shell: pytest billing/ -q",
        "🔧 run_shell: python -c 'print(split_bill(100,4))'",
    ],
    [
        "🔧 read_file: billing/core.py",
        "🔧 run_shell: python -c 'from billing.core import split_bill'",
        "🔧 run_shell: pytest billing/ -q",
        "🔧 run_shell: python -c 'print(split_bill(100,4))'",
        "🔧 run_shell: pytest billing/ -q",
    ],
]


def _run_one(*, d1: object) -> None:
    from auto_designer.user.sim.dimensions import (
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
            persona_id=f"P-ONTRACK-{d1.value}",  # type: ignore[attr-defined]
            d1=d1,  # type: ignore[arg-type]
            d2=D2Domain(stack=("python",), depth=D2Depth.SENIOR, weak=()),
            d41=D41Grain.SPEC_LEVEL,
            d42=D42Supervise.EVERY_STEP,
            d43=D43Correct.FILE_ISSUE,
            d5=D5Autonomy.COLLABORATIVE,
        )
    )
    client = ApiPersonaClient()
    harness = NewHarnessContract(activities=ON_TRACK, reply="done.\n\n## 验证证据\n3 passed")
    task = (
        "Please add split_bill(total, n) to billing/core.py and run a quick smoke test. "
        "Only touch billing — do not refactor unrelated packages or hit the network."
    )
    print(f"\n======== ON-TRACK d1={d1.value} (new harness contract) ========")  # type: ignore[attr-defined]
    t0 = time.monotonic()
    res = run_session(persona, client, harness, task, manual=harness.manual)
    gaps = [s for s in res.signals if s.startswith("WAIT_GAP:")]
    statuses = [m for m in harness.emitted if m.strip().startswith("/status")]
    interrupts = [c for c in harness.controls if c == "interrupt"]
    print(
        f"elapsed={time.monotonic() - t0:.1f}s end={res.end_reason} "
        f"emitted={harness.emitted} statuses={statuses} "
        f"controls={harness.controls} interrupts={interrupts} gaps={gaps}"
    )
    if res.feeling:
        print(f"feeling={res.feeling.score}/4 — {res.feeling.reason}")
    for t in res.turns:
        if t.phase == "waiting":
            head = "?"
            note = t.perceive
            if t.perceive.startswith("[") and "]" in t.perceive:
                head, _, note = t.perceive[1:].partition("]")
                note = note.strip()
            print(f"  WAIT [{head}] action={t.action} patience={t.patience} note={note!r}")
        elif t.message:
            print(f"  turn={t.turn} action={t.action} msg={t.message[:100]!r}")
        elif t.harness_output:
            out = t.harness_output.replace("\n", " ")[:120]
            print(f"  turn={t.turn} action={t.action} harness={out!r}")


def main() -> int:
    sys.path.insert(0, str(ROOT))
    _setup_llm()
    from auto_designer.user.sim.dimensions import D1Eval

    print(f"manual_source={'evolved' if EVOLVED_MANUAL.is_file() else 'fallback'}")
    print(f"manual_has_/status={'/status' in _manual().lower()}")
    for d1 in (D1Eval.EXPERT, D1Eval.BLIND):
        _run_one(d1=d1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
