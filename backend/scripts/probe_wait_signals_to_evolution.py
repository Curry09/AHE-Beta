#!/usr/bin/env python3
"""探针：把 wait 探针里 expert/blind 的体感 + WAIT_GAP 信号喂给设计师 → 开发者。

用法（仓根）：
  PYTHONPATH=backend .venv/bin/python backend/scripts/probe_wait_signals_to_evolution.py

凭证：/Users/bytedance/cjh/.env 的 LLM_* → DESIGNER_LLM_* / DEV_LLM_*。
不重跑用户 sim：按最近探针结果种 SessionStore + FakeTracker bug，再真 LLM 进化一轮。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
HOME_ENV = Path("/Users/bytedance/cjh/.env")
TEMPLATE = ROOT / "harness_template"
DESIGNER_DEF = ROOT / "agent_defs" / "designer"
DEV_DEF = ROOT / "agent_defs" / "developer_agent"


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
    model = home.get("LLM_MODEL") or backend.get("LLM_MODEL")
    base = home.get("LLM_BASE_URL") or backend.get("LLM_BASE_URL")
    key = home.get("LLM_API_KEY") or backend.get("LLM_API_KEY")
    if not (model and base and key):
        raise SystemExit("缺 LLM 凭证")
    for role in ("DESIGNER", "DEV", "USER"):
        os.environ[f"{role}_LLM_MODEL"] = model
        os.environ[f"{role}_LLM_BASE_URL"] = base
        os.environ[f"{role}_LLM_API_KEY"] = key
    os.environ["LLM_MODEL"] = model
    os.environ["LLM_BASE_URL"] = base
    os.environ["LLM_API_KEY"] = key
    host = urlparse(base).hostname
    bypass = ["localhost", "127.0.0.1"]
    if host:
        bypass.append(host)
    os.environ["NO_PROXY"] = ",".join(bypass)
    os.environ["no_proxy"] = os.environ["NO_PROXY"]
    print(f"LLM model={model} base={base}")


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@x", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _seed_harness_repo(work: Path) -> Path:
    """harness 工作仓 + 本地 bare origin（开发者要 push）。"""
    repo = work / "harness"
    shutil.copytree(TEMPLATE, repo)
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "seed: harness v0")
    bare = work / "origin.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-u", "origin", "main")
    return repo


def main() -> int:
    sys.path.insert(0, str(ROOT))
    _setup_llm()

    from auto_designer.designer.designer import DESIGN_LABEL, Designer
    from auto_designer.designer.runtime_agg import aggregate_runtime, format_runtime_agg
    from auto_designer.dev.agentic_developer import AgenticDeveloper
    from auto_designer.models import (
        FeelingScore,
        IssueDraft,
        Persona,
        SeedScenario,
        Session,
        Transcript,
        Turn,
    )
    from auto_designer.tracker.fake import FakeTracker
    from auto_designer.user.session_store import SessionStore

    work = Path(tempfile.mkdtemp(prefix="probe_wait_evo_"))
    store = SessionStore(work / "sessions")
    tracker = FakeTracker()
    harness_repo = _seed_harness_repo(work)
    print(f"work={work}")
    print(f"harness={harness_repo}")

    scenario = SeedScenario(
        description=(
            "add split_bill(total, n) to billing/core.py and run a quick smoke test; "
            "billing-only, no network"
        )
    )

    # —— 按最近探针结果种两局会话（WAIT_GAP 不落盘，写进 feeling.reason + issue body）——
    expert_gaps = (
        "WAIT_GAP: intent=check_status action=keep_waiting (×2); "
        "WAIT_GAP: intent=check_status action=invoke_control:interrupt (×3). "
        "User wanted status/peek while work looked on-track; menu only wait/interrupt."
    )
    blind_gaps = (
        "WAIT_GAP: intent=check_status action=keep_waiting (×7); "
        "later interrupt only after repeated 'done' without stdout. "
        "Blind persona waited through on-track activity; gap still = missing status."
    )

    store.save(
        Session(
            persona=Persona(
                identity="P-expert-ON-TRACK",
                level="senior",
                domain="python",
                goal="split_bill + smoke",
                speaking_style="direct",
            ),
            scenario=scenario,
            transcript=Transcript(
                turns=[
                    Turn(
                        role="user",
                        content="Please add split_bill(total, n) to billing/core.py and smoke test.",
                    ),
                    Turn(
                        role="harness",
                        content=(
                            "[interrupted] You stopped this request via `interrupt`; "
                            "session kept — send a follow-up."
                        ),
                        steps=[
                            {"kind": "tool", "text": "🔧 read_file: billing/core.py"},
                            {
                                "kind": "tool",
                                "text": "🔧 run_shell: python -c 'from billing.core import split_bill'",
                            },
                        ],
                    ),
                    Turn(
                        role="user",
                        content="Continue: implement split_bill and show smoke-test output.",
                    ),
                    Turn(
                        role="harness",
                        content="[interrupted] You stopped this request via `interrupt`; session kept.",
                        steps=[
                            {"kind": "tool", "text": "🔧 read_file: billing/core.py"},
                            {"kind": "tool", "text": "🔧 run_shell: pytest billing/ -q"},
                        ],
                    ),
                ]
            ),
            feeling=FeelingScore(
                score=1,
                reason=(
                    "I just wanted a tiny billing change with a smoke test, and it kept "
                    "stalling so I had to interrupt with nothing useful to show for it. "
                    + expert_gaps
                ),
            ),
        )
    )
    store.save(
        Session(
            persona=Persona(
                identity="P-blind-ON-TRACK",
                level="junior",
                domain="python",
                goal="split_bill + smoke",
                speaking_style="casual",
            ),
            scenario=scenario,
            transcript=Transcript(
                turns=[
                    Turn(
                        role="user",
                        content="Please add split_bill(total, n) and run a quick smoke test.",
                    ),
                    Turn(
                        role="harness",
                        content="done.",
                        steps=[
                            {"kind": "tool", "text": "🔧 read_file: billing/core.py"},
                            {
                                "kind": "tool",
                                "text": "🔧 run_shell: python -c 'from billing.core import split_bill'",
                            },
                            {"kind": "tool", "text": "🔧 run_shell: pytest billing/ -q"},
                        ],
                    ),
                    Turn(
                        role="user",
                        content="Please paste the exact smoke-test stdout/stderr.",
                    ),
                    Turn(
                        role="harness",
                        content="done.",
                        steps=[{"kind": "tool", "text": "🔧 read_file: billing/core.py"}],
                    ),
                    Turn(
                        role="user",
                        content="I need actual output, not just 'done'.",
                    ),
                    Turn(
                        role="harness",
                        content="[interrupted] You stopped this request via `interrupt`; session kept.",
                        steps=[{"kind": "tool", "text": "🔧 read_file: billing/core.py"}],
                    ),
                ]
            ),
            feeling=FeelingScore(
                score=1,
                reason=(
                    "I just wanted a simple billing change and command output, but it kept "
                    "stalling and I had to interrupt. " + blind_gaps
                ),
            ),
        )
    )

    bug_expert = tracker.create_issue(
        IssueDraft(
            title="Waiting: want status but can only interrupt (expert)",
            body=(
                "Task: tiny billing-only split_bill + smoke test.\n"
                "While tools looked on-track (read billing/core.py, import smoke, pytest), "
                "I repeatedly wanted to peek/check status. The menu only offered keep_waiting "
                "or interrupt — so I interrupted and got no final deliverable.\n"
                f"Signals: {expert_gaps}\n"
                "Feeling 1/4: stalling; I had to interrupt myself.\n"
                "Ask: expose a status/partial-progress control (or auto status) so I don't "
                "have to kill an on-track run just to know where it is."
            ),
            labels=["bug"],
        )
    )
    bug_blind = tracker.create_issue(
        IssueDraft(
            title="Waiting: check_status gap; done without stdout (blind)",
            body=(
                "Same small billing task. I waited through on-track activity (kept waiting "
                "when I wanted status). Harness later said 'done' without pasting smoke "
                "stdout; only then did I interrupt.\n"
                f"Signals: {blind_gaps}\n"
                "Feeling 1/4.\n"
                "Ask: (1) status while waiting; (2) when claiming done, show command output."
            ),
            labels=["bug"],
        )
    )
    print(f"seeded bugs: #{bug_expert.number}, #{bug_blind.number}")
    print("\n=== runtime_agg ===")
    print(
        format_runtime_agg(aggregate_runtime(store=store, harness_repo=harness_repo, recent_n=50))
    )

    print("\n=== D｜Designer.propose_once ===")
    t0 = time.monotonic()
    designer = Designer(
        tracker,
        store,
        str(harness_repo),
        str(DESIGNER_DEF),
        on_status=lambda *, running, status, **kw: print(f"  [designer] {status}"),
    )
    d_out = designer.propose_once()
    print(f"designer elapsed={time.monotonic() - t0:.1f}s proposals={d_out.proposal_numbers}")
    open_issues = tracker.list_open_issues()
    for iss in open_issues:
        print(f"  open #{iss.number} labels={iss.labels} title={iss.title!r}")
        print(f"    body[:400]={(iss.body or '')[:400]!r}")

    design_nums = {i.number for i in open_issues if DESIGN_LABEL in i.labels}
    if not design_nums:
        print("无 design 提案，跳过开发者")
        return 1

    # 先领 design 单：跳过用户 bug
    skip = {bug_expert.number, bug_blind.number}
    print(f"\n=== B｜Developer.work_one (skip bugs {skip}) ===")
    t1 = time.monotonic()
    dev = AgenticDeveloper(
        tracker,
        str(harness_repo),
        str(DEV_DEF),
        on_status=lambda *, running, status, **kw: print(f"  [dev] {status}"),
    )
    # 可能多条 design：连做直到没有可领 design 或一轮无提交
    attempted: set[int] = set(skip)
    rounds = 0
    while rounds < 3:
        rounds += 1
        open_design = [
            i
            for i in tracker.list_open_issues()
            if DESIGN_LABEL in i.labels and i.number not in attempted
        ]
        if not open_design:
            break
        out = dev.work_one(skip=attempted)
        print(
            f"  round={rounds} issue=#{out.issue_number} tag={out.tag} "
            f"committed={out.committed} elapsed={time.monotonic() - t1:.1f}s"
        )
        if out.issue_number:
            attempted.add(out.issue_number)
        if not out.committed:
            break

    print("\n=== harness main.md (tail) ===")
    main_md = harness_repo / "agents" / "main.md"
    if main_md.is_file():
        text = main_md.read_text(encoding="utf-8")
        print(text[-1200:] if len(text) > 1200 else text)
    print("\n=== tags ===")
    print(_git(harness_repo, "tag") or "(none)")
    print("\n=== remaining open ===")
    for iss in tracker.list_open_issues():
        print(f"  #{iss.number} {iss.labels} {iss.title!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
