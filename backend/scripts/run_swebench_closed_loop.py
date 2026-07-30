#!/usr/bin/env python3
"""SWE-bench_Verified × persona 闭环：5 persona 池 + 10 均衡题池，每轮有放回抽 10 对，跑 5 轮。

相对 run.py：
  - 种子不进 seeds.json（benchmark held-out 契约禁 not_in_benchmark=false），直接物化为
    SeedScenario（题面只用 problem_statement；FAIL_TO_PASS 等不进训练侧）。
  - 每轮 session 计划可重抽（Orchestrator.fixed_set=callable）。

用法（仓根）：
  TOTAL_ROUNDS=5 N_USERS=10 \\
  PYTHONPATH=backend .venv/bin/python backend/scripts/run_swebench_closed_loop.py

环境变量（可选）：
  SWEBENCH_PARQUET     默认 ~/cjh/SWE-bench_Verified/data/test-00000-of-00001.parquet
  PERSONA_LIBRARY      默认 backend/persona_library.json
  SESSION_SEED         随机种子（默认 20260725），保证可复现
  SESSIONS_PER_ROUND   每轮会话数（默认 10）
  TOTAL_ROUNDS         闭环轮数（默认 5）
  MAX_PARALLEL_USERS   a 段并发（默认 = SESSIONS_PER_ROUND）
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]  # backend/
REPO = ROOT.parent  # auto-designer 编排仓根（绊线盯这里）
sys.path.insert(0, str(ROOT))

import run as run_mod  # noqa: E402  — 复用 run.py 的种子/复位/凭证隔离

SWEBENCH_PARQUET = Path(
    os.environ.get(
        "SWEBENCH_PARQUET",
        str(Path.home() / "cjh/SWE-bench_Verified/data/test-00000-of-00001.parquet"),
    )
)
PERSONA_LIB = Path(os.environ.get("PERSONA_LIBRARY", str(ROOT / "persona_library.json")))
PERSONA_IDS = ["SR-001", "SR-002", "SR-003", "SR-004", "SR-005"]
# 难度 4×<15min + 4×15m-1h + 2×1-4h；10 个不同仓，避开 django 过密。
INSTANCE_IDS = [
    "pallets__flask-5014",
    "psf__requests-1142",
    "pytest-dev__pytest-7982",
    "pylint-dev__pylint-4970",
    "mwaskom__seaborn-3069",
    "matplotlib__matplotlib-24627",
    "scikit-learn__scikit-learn-12682",
    "astropy__astropy-8707",
    "pydata__xarray-3993",
    "sphinx-doc__sphinx-8548",
]
SESSIONS_PER_ROUND = int(os.environ.get("SESSIONS_PER_ROUND", "10") or "10")
SESSION_SEED = int(os.environ.get("SESSION_SEED", "20260725") or "20260725")

os.environ.setdefault("TOTAL_ROUNDS", "5")
os.environ.setdefault("N_USERS", str(SESSIONS_PER_ROUND))
run_mod.TOTAL_ROUNDS = int(os.environ.get("TOTAL_ROUNDS", "5") or "5")


def _setup_cmd() -> list[str]:
    return [
        "python -m venv .venv",
        ".venv/bin/python -m pip install -U pip setuptools wheel",
        ".venv/bin/python -m pip install -e .",
    ]


def _load_instances() -> dict[str, dict]:
    import pyarrow.parquet as pq

    if not SWEBENCH_PARQUET.is_file():
        raise SystemExit(f"缺 SWE-bench_Verified parquet: {SWEBENCH_PARQUET}")
    table = pq.read_table(
        SWEBENCH_PARQUET,
        columns=["instance_id", "repo", "base_commit", "problem_statement", "difficulty"],
    )
    by_id: dict[str, dict] = {}
    for iid, repo, commit, prompt, difficulty in zip(
        table.column("instance_id").to_pylist(),
        table.column("repo").to_pylist(),
        table.column("base_commit").to_pylist(),
        table.column("problem_statement").to_pylist(),
        table.column("difficulty").to_pylist(),
        strict=True,
    ):
        by_id[str(iid)] = {
            "instance_id": str(iid),
            "repo": str(repo),
            "base_commit": str(commit),
            "problem_statement": str(prompt),
            "difficulty": str(difficulty),
        }
    missing = [i for i in INSTANCE_IDS if i not in by_id]
    if missing:
        raise SystemExit(f"parquet 缺 instance: {missing}")
    return {i: by_id[i] for i in INSTANCE_IDS}


def _to_scenario(meta: dict):
    from auto_designer.models import SeedScenario, WorkspaceSpec

    return SeedScenario(
        description=meta["problem_statement"],
        workspace=WorkspaceSpec(
            kind="git",
            params={
                "repo": f"https://github.com/{meta['repo']}.git",
                "commit": meta["base_commit"],
            },
            setup=_setup_cmd(),
        ),
    )


def main() -> int:
    from auto_designer.designer.designer import Designer
    from auto_designer.designer.triage import Triager
    from auto_designer.dev.repo_guard import snapshot_repo, verify_unchanged
    from auto_designer.harness.launcher import HarnessLauncher
    from auto_designer.loop.live import (
        append_agent_log,
        archive_agent,
        update_agent,
        update_live_run,
    )
    from auto_designer.loop.metrics import Metrics
    from auto_designer.loop.orchestrator import Orchestrator
    from auto_designer.loop.roster import load_roster
    from auto_designer.loop.sim_user import make_sim_run_session_fn, result_to_turns
    from auto_designer.models import Persona
    from auto_designer.tracker.gitea import GiteaTracker
    from auto_designer.user.session_store import SessionStore
    from auto_designer.user.sim.persona_client import AgenticPersonaClient, ApiPersonaClient
    from auto_designer.user.sim.persona_io import card_to_persona

    run_mod._isolate_git_credentials()
    llm_env = run_mod._load_env(ROOT / ".env")
    os.environ.update(llm_env)
    for suffix in ("MODEL", "BASE_URL", "API_KEY"):
        val = os.environ.get(f"HARNESS_LLM_{suffix}")
        if not val:
            raise SystemExit(f"backend/.env 缺 HARNESS_LLM_{suffix}")
        os.environ[f"LLM_{suffix}"] = val
    gitea = run_mod._load_env(ROOT / "deploy" / "gitea" / ".env")

    roster = load_roster()
    bypass = ["localhost", "127.0.0.1"]
    for url in (
        os.environ.get("USER_LLM_BASE_URL"),
        os.environ.get("DEV_LLM_BASE_URL"),
        os.environ.get("DESIGNER_LLM_BASE_URL"),
        gitea.get("GITEA_URL"),
    ):
        host = urlparse(url).hostname if url else None
        if host and host not in bypass:
            bypass.append(host)
    os.environ["NO_PROXY"] = ",".join(bypass)
    os.environ["no_proxy"] = os.environ["NO_PROXY"]

    instances = _load_instances()
    scenarios = {iid: _to_scenario(meta) for iid, meta in instances.items()}
    cards = {c["id"]: c for c in json.loads(PERSONA_LIB.read_text(encoding="utf-8"))}
    missing_p = [p for p in PERSONA_IDS if p not in cards]
    if missing_p:
        raise SystemExit(f"persona 库缺: {missing_p}")

    sim_personas = {pid: card_to_persona(cards[pid]) for pid in PERSONA_IDS}
    display: dict[str, Persona] = {}
    persona_meta: dict[str, dict[str, str]] = {}
    for pid, sp in sim_personas.items():
        domain = "/".join(sp.d2.stack) or "general"
        display[pid] = Persona(
            identity=sp.persona_id,
            level=sp.d1.value,
            domain=domain,
            goal="use harness on SWE-bench task",
            speaking_style=f"delegation={sp.d41.value}; autonomy={sp.d5.value}",
        )
        persona_meta[pid] = {
            "identity": sp.persona_id,
            "level": sp.d1.value,
            "domain": domain,
            "goal": "use harness on SWE-bench task",
        }

    rng = random.Random(SESSION_SEED)
    pair_log: list[list[tuple[str, str]]] = []

    def session_plan():
        picks = [
            (rng.choice(PERSONA_IDS), rng.choice(INSTANCE_IDS)) for _ in range(SESSIONS_PER_ROUND)
        ]
        pair_log.append(list(picks))
        print(f"  session plan ({len(picks)}): {picks}")
        return [(display[pid], scenarios[iid]) for pid, iid in picks]

    print(
        f"⓪ SWE-bench 闭环：persona×{len(PERSONA_IDS)} · instance×{len(INSTANCE_IDS)} · "
        f"每轮有放回 {SESSIONS_PER_ROUND} 对 · 共 {run_mod.TOTAL_ROUNDS} 轮 · seed={SESSION_SEED}"
    )
    for iid, meta in instances.items():
        print(f"   - {meta['difficulty']:16}  {meta['repo']:28}  {iid}")
    print(
        f"⓪.5 roster：user×{roster['user']} · triager×{roster['triager']} · "
        f"designer×{roster['designer']} · divergent×{roster.get('divergent', 0)} · "
        f"developer×{roster['developer']}"
    )

    print("① 种 harness 本地仓 ...")
    repo = run_mod._seed_harness_repo()
    print("② 接 Gitea + 复位 ...")
    tracker = GiteaTracker(
        base_url=gitea["GITEA_URL"], owner=gitea["OWNER"], repo=gitea["REPO"], token=gitea["TOKEN"]
    )
    tracker.ensure_labels(["bug", "feature", "needs-triage", "RFC", "triaged"])
    run_mod._set_gitea_remote(repo, gitea)
    run_mod._reset_to_initial(repo, tracker)
    store = SessionStore(run_mod.DATA / "sessions")
    launcher = HarnessLauncher(harness_repo=str(repo), runs_root=run_mod.DATA / "harness_runs")

    api = ApiPersonaClient()

    def client_factory() -> AgenticPersonaClient:
        return AgenticPersonaClient(api.complete)

    current = {"round": 0}
    round_shas: dict[str, str] = {}

    def on_round_start(k: int) -> None:
        current["round"] = k
        update_live_run(
            data_dir=run_mod.DATA, running=True, round_no=k, total_rounds=run_mod.TOTAL_ROUNDS
        )
        print(f"\n==== round {k}/{run_mod.TOTAL_ROUNDS} ====")

    def on_round_end(k: int, sha: str) -> None:
        round_shas[str(k)] = sha
        update_live_run(
            data_dir=run_mod.DATA,
            running=True,
            round_no=k,
            total_rounds=run_mod.TOTAL_ROUNDS,
            round_shas=round_shas,
        )
        print(f"==== round {k} done · main={sha[:12]} ====")

    def make_event_logger(agent_id: str):
        return lambda kind, text: append_agent_log(
            data_dir=run_mod.DATA, agent_id=agent_id, text=text, kind=kind
        )

    def on_sim_turn(identity, sim_persona, res, running, *, session_id=None):
        turns = [t.to_dict() for t in result_to_turns(res)]
        last = res.turns[-1] if res.turns else None
        feel = res.feeling or res.feeling_derived
        if running:
            status = f"对话中… 第 {last.turn} 轮 · {last.verdict}" if last else "启动中…"
        else:
            score = feel.score if feel else "?"
            status = f"已完成 · {res.end_reason} · 体感 {score}"
        update_agent(
            data_dir=run_mod.DATA,
            agent_id=f"user-{identity}",
            role="user",
            label=identity,
            running=running,
            status=status,
            turns=turns,
            round_no=current["round"],
            meta=persona_meta.get(identity),
        )
        if not running:
            archive_agent(
                data_dir=run_mod.DATA,
                agent_id=f"user-{identity}",
                round_no=current["round"],
                extra={
                    "kind": "user_session",
                    "session_id": session_id,
                    "score": feel.score if feel else None,
                    "end_reason": res.end_reason,
                },
            )

    user_run_session_fn = make_sim_run_session_fn(
        client_factory=client_factory,
        tracker=tracker,
        store=store,
        sim_personas=sim_personas,
        on_turn=on_sim_turn,
        round_provider=lambda: current["round"] or None,
    )

    def make_triager_status(agent_id: str, label: str):
        def cb(*, running, status, detail=None, **kw):
            update_agent(
                data_dir=run_mod.DATA,
                agent_id=agent_id,
                role="triager",
                label=label,
                running=running,
                status=status,
                detail=detail,
                round_no=current["round"],
            )
            if not running:
                archive_agent(
                    data_dir=run_mod.DATA,
                    agent_id=agent_id,
                    round_no=current["round"],
                    extra={"kind": "triager_run"},
                )

        return cb

    triagers = [
        Triager(
            tracker,
            store,
            str(repo),
            str(ROOT / "agent_defs" / "triage_agent"),
            on_status=make_triager_status(
                f"triager-{i}", "triager" if roster["triager"] == 1 else f"triager#{i + 1}"
            ),
            on_event=make_event_logger(f"triager-{i}"),
        )
        for i in range(roster["triager"])
    ]

    def make_designer_status(agent_id: str, label: str):
        def cb(*, running, status, detail=None, proposals=None):
            update_agent(
                data_dir=run_mod.DATA,
                agent_id=agent_id,
                role="designer",
                label=label,
                running=running,
                status=status,
                detail=detail,
                round_no=current["round"],
            )
            if not running:
                archive_agent(
                    data_dir=run_mod.DATA,
                    agent_id=agent_id,
                    round_no=current["round"],
                    extra={"kind": "designer_run", "proposals": proposals or []},
                )

        return cb

    designers = [
        Designer(
            tracker,
            store,
            str(repo),
            str(ROOT / "agent_defs" / "designer"),
            on_status=make_designer_status(
                f"designer-{i}", "designer" if roster["designer"] == 1 else f"designer#{i + 1}"
            ),
            on_event=make_event_logger(f"designer-{i}"),
        )
        for i in range(roster["designer"])
    ]

    def make_divergent_status(agent_id: str, label: str):
        def cb(*, running, status, detail=None, proposals=None):
            update_agent(
                data_dir=run_mod.DATA,
                agent_id=agent_id,
                role="divergent",
                label=label,
                running=running,
                status=status,
                detail=detail,
                round_no=current["round"],
            )
            if not running:
                archive_agent(
                    data_dir=run_mod.DATA,
                    agent_id=agent_id,
                    round_no=current["round"],
                    extra={"kind": "divergent_run", "proposals": proposals or []},
                )

        return cb

    from auto_designer.designer.divergent import Divergent  # noqa: PLC0415

    divergents = [
        Divergent(
            tracker,
            store,
            str(repo),
            str(ROOT / "agent_defs" / "divergent_pm"),
            on_status=make_divergent_status(
                f"divergent-{i}",
                "divergent" if roster["divergent"] == 1 else f"divergent#{i + 1}",
            ),
            on_event=make_event_logger(f"divergent-{i}"),
            round_provider=lambda: current["round"] or None,
        )
        for i in range(roster.get("divergent", 0))
    ]

    raw_parallel = os.environ.get("MAX_PARALLEL_USERS", "").strip()
    max_parallel_users = int(raw_parallel) if raw_parallel.isdigit() else SESSIONS_PER_ROUND
    max_parallel_users = max(1, max_parallel_users)

    _repo_baseline = snapshot_repo(repo=str(REPO))

    def integrity_guard() -> None:
        verify_unchanged(repo=str(REPO), before=_repo_baseline)

    orch = Orchestrator(
        launcher=launcher,
        harness_repo=str(repo),
        fixed_set=session_plan,
        run_session_fn=user_run_session_fn,
        initial_ref="main",
        triagers=triagers,
        designers=designers,
        divergents=divergents,
        on_round_start=on_round_start,
        on_round_end=on_round_end,
        max_parallel_users=max_parallel_users,
        integrity_guard=integrity_guard,
    )

    # Spec-0032/T5 + 0033/T2：交付面接线与 run.py 同源——start_vigil 按 VIGIL_MODE 自带预检/
    # 配置落盘/生命周期（finally 收尾停）。
    vigil = run_mod.start_vigil(
        repo=repo,
        parallel=roster["developer"],
        gitea=gitea,
        log_path=run_mod.DATA / "vigil.log",
    )

    print(
        f"④ 跑 {run_mod.TOTAL_ROUNDS} 轮闭环（每轮 {SESSIONS_PER_ROUND} session · "
        f"{len(triagers)} triager × {len(designers)} synthesize × {len(divergents)} divergent；"
        f"交付面 vigil --parallel {roster['developer']} 常驻，"
        f"a 段并发 {max_parallel_users}）..."
    )
    try:
        refs = orch.run(run_mod.TOTAL_ROUNDS)
    finally:
        run_mod.stop_vigil(vigil)
        update_live_run(
            data_dir=run_mod.DATA,
            running=False,
            round_no=current["round"],
            total_rounds=run_mod.TOTAL_ROUNDS,
            round_shas=round_shas,
        )

    plan_path = run_mod.DATA / "swebench_session_plans.json"
    plan_path.write_text(
        json.dumps(pair_log, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("\n=== 结果 ===")
    print("各轮 main HEAD SHA:", refs)
    print("session plans →", plan_path)
    m = Metrics(tracker, store)
    print("当前 open issue 数:", m.open_issue_count())
    print("体感趋势:", m.feeling_trend())
    print("issue 曲线 (t, opened, net_open):", m.issue_curve())
    print("本地仓分支:", end=" ")
    subprocess.run(["git", "-C", str(repo), "branch", "--format=%(refname:short)"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
