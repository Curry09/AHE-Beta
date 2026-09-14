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
  SWEBENCH_ALL_ONCE    真值时每轮覆盖题池各一次，persona 轮转；忽略 SESSIONS_PER_ROUND
  TOTAL_ROUNDS         闭环轮数（默认 5）
  MAX_PARALLEL_USERS   a 段并发（默认 = SESSIONS_PER_ROUND）
  SWEBENCH_INSTANCE_FILE  JSON 题池 manifest（instances[].instance_id）
  SWEBENCH_INSTANCE    只跑指定题（须在内置题池中；省流量冒烟测试用）
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
PERSONA_IDS = [
    "sr-01-willison",
    "sr-02-ronacher",
    "sr-03-hashimoto",
    "sr-04-dhh",
    "sr-05-klabnik",
]


def _load_persona_ids(*, path: Path | None, fallback: list[str]) -> list[str]:
    """Load the frozen persona roster used by an auditable experiment."""
    if path is None:
        return list(fallback)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        records = document["personas"]
        persona_ids = [str(item["id"]) for item in records]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f"persona roster 非法：{path}: {exc}") from exc
    if not persona_ids or len(persona_ids) != len(set(persona_ids)):
        raise SystemExit(f"persona roster 必须非空且 ID 唯一：{path}")
    return persona_ids


def _load_interaction_plan(
    *, path: Path | None, total_rounds: int, persona_ids: list[str], instance_ids: list[str]
) -> list[list[tuple[str, str]]] | None:
    """Validate and freeze every round's persona/task assignment."""
    if path is None:
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"interaction plan 非法：{path}: {exc}") from exc
    if not isinstance(document, list) or len(document) != total_rounds:
        raise SystemExit(
            f"interaction plan 轮数必须为 {total_rounds}：{path}（实际 "
            f"{len(document) if isinstance(document, list) else '非列表'}）"
        )
    allowed_personas = set(persona_ids)
    allowed_instances = set(instance_ids)
    rounds: list[list[tuple[str, str]]] = []
    expected_size: int | None = None
    for round_index, raw_round in enumerate(document, start=1):
        if not isinstance(raw_round, list) or not raw_round:
            raise SystemExit(f"interaction plan 第 {round_index} 轮必须为非空列表")
        pairs: list[tuple[str, str]] = []
        for raw_pair in raw_round:
            if not isinstance(raw_pair, list) or len(raw_pair) != 2:
                raise SystemExit(f"interaction plan 第 {round_index} 轮含非法 pair")
            persona_id, instance_id = map(str, raw_pair)
            if persona_id not in allowed_personas:
                raise SystemExit(
                    f"interaction plan 第 {round_index} 轮引用 roster 外 persona：{persona_id}"
                )
            if instance_id not in allowed_instances:
                raise SystemExit(
                    f"interaction plan 第 {round_index} 轮引用题池外 instance：{instance_id}"
                )
            pairs.append((persona_id, instance_id))
        if len({persona for persona, _instance in pairs}) != len(pairs):
            raise SystemExit(f"interaction plan 第 {round_index} 轮 persona 必须唯一")
        if len({instance for _persona, instance in pairs}) != len(pairs):
            raise SystemExit(f"interaction plan 第 {round_index} 轮 instance 必须唯一")
        expected_size = expected_size or len(pairs)
        if len(pairs) != expected_size:
            raise SystemExit("interaction plan 每轮 session 数必须一致")
        rounds.append(pairs)
    return rounds


# 难度 4×<15min + 4×15m-1h + 2×1-4h；10 个不同仓，避开 django 过密。
_DEFAULT_INSTANCE_IDS = [
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
_instance_file_raw = os.environ.get("SWEBENCH_INSTANCE_FILE", "").strip()
if _instance_file_raw:
    _instance_file = Path(_instance_file_raw).expanduser().resolve()
    _instance_doc = json.loads(_instance_file.read_text(encoding="utf-8"))
    _pool_instance_ids = [str(item["instance_id"]) for item in _instance_doc["instances"]]
    if not _pool_instance_ids or len(_pool_instance_ids) != len(set(_pool_instance_ids)):
        raise SystemExit(f"SWEBENCH_INSTANCE_FILE 题目须非空且唯一：{_instance_file}")
else:
    _pool_instance_ids = _DEFAULT_INSTANCE_IDS


def _select_instance_ids(pool: list[str], selected: str) -> list[str]:
    if selected and selected not in pool:
        raise SystemExit(f"SWEBENCH_INSTANCE 不在当前题池：{selected!r}；可选：{pool}")
    return [selected] if selected else list(pool)


_selected_instance = os.environ.get("SWEBENCH_INSTANCE", "").strip()
INSTANCE_IDS = _select_instance_ids(_pool_instance_ids, _selected_instance)
ALL_ONCE = os.environ.get("SWEBENCH_ALL_ONCE", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SESSIONS_PER_ROUND = (
    len(INSTANCE_IDS) if ALL_ONCE else int(os.environ.get("SESSIONS_PER_ROUND", "10") or "10")
)
SESSION_SEED = int(os.environ.get("SESSION_SEED", "20260725") or "20260725")

os.environ.setdefault("TOTAL_ROUNDS", "5")
os.environ.setdefault("N_USERS", str(SESSIONS_PER_ROUND))
run_mod.TOTAL_ROUNDS = int(os.environ.get("TOTAL_ROUNDS", "5") or "5")

_persona_roster_raw = os.environ.get("PERSONA_ROSTER", "").strip()
PERSONA_IDS = _load_persona_ids(
    path=Path(_persona_roster_raw).expanduser().resolve() if _persona_roster_raw else None,
    fallback=PERSONA_IDS,
)
_interaction_plan_raw = os.environ.get("SWEBENCH_INTERACTION_PLAN", "").strip()
FROZEN_INTERACTION_PLAN = _load_interaction_plan(
    path=(Path(_interaction_plan_raw).expanduser().resolve() if _interaction_plan_raw else None),
    total_rounds=run_mod.TOTAL_ROUNDS,
    persona_ids=PERSONA_IDS,
    instance_ids=INSTANCE_IDS,
)
if FROZEN_INTERACTION_PLAN is not None:
    SESSIONS_PER_ROUND = len(FROZEN_INTERACTION_PLAN[0])
    os.environ["N_USERS"] = str(SESSIONS_PER_ROUND)


def _setup_cmd() -> list[str]:
    return [
        "python -m venv .venv",
        ".venv/bin/python -m pip install -U pip 'setuptools<81' wheel",
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

    seed_root_raw = os.environ.get("SWEBENCH_SEED_ROOT", "").strip()
    if seed_root_raw:
        prepared = (
            Path(seed_root_raw).expanduser().resolve() / "workspace" / meta["instance_id"] / "repo"
        )
        if prepared.is_dir() and (prepared / ".venv" / "bin" / "python").is_file():
            return SeedScenario(
                description=meta["problem_statement"],
                workspace=WorkspaceSpec(
                    kind="prebuilt",
                    params={"source": str(prepared), "instance_id": meta["instance_id"]},
                ),
            )
    seed_image = os.environ.get("SWEBENCH_SEED_IMAGE", "").strip()
    if seed_image:
        return SeedScenario(
            description=meta["problem_statement"],
            workspace=WorkspaceSpec(
                kind="docker-seed",
                params={
                    "image": seed_image,
                    "instance_id": meta["instance_id"],
                    # The harness needs the configured GLM gateway.  Isolation here is
                    # filesystem/process isolation; deployments may replace bridge with
                    # a dedicated egress network.
                    "network": os.environ.get("SWEBENCH_SESSION_NETWORK", "bridge"),
                },
            ),
        )
    return SeedScenario(
        description=meta["problem_statement"],
        workspace=WorkspaceSpec(
            kind="git",
            params={
                "repo": f"https://github.com/{meta['repo']}.git",
                "commit": meta["base_commit"],
                "instance_id": meta["instance_id"],
            },
            setup=_setup_cmd(),
        ),
    )


def _session_picks(rng: random.Random, *, round_index: int) -> list[tuple[str, str]]:
    if FROZEN_INTERACTION_PLAN is not None:
        try:
            return list(FROZEN_INTERACTION_PLAN[round_index])
        except IndexError as exc:
            raise RuntimeError(f"interaction plan 缺第 {round_index + 1} 轮") from exc
    if ALL_ONCE:
        instance_order = list(INSTANCE_IDS)
        rng.shuffle(instance_order)
        persona_offset = round_index % len(PERSONA_IDS)
        return [
            (PERSONA_IDS[(persona_offset + index) % len(PERSONA_IDS)], instance_id)
            for index, instance_id in enumerate(instance_order)
        ]
    return [(rng.choice(PERSONA_IDS), rng.choice(INSTANCE_IDS)) for _ in range(SESSIONS_PER_ROUND)]


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
    from auto_designer.loop.round_gate import RoundDeliveryBlocked
    from auto_designer.loop.sim_user import make_sim_run_session_fn, result_to_turns
    from auto_designer.models import Persona
    from auto_designer.tracker.gitea import GiteaTracker
    from auto_designer.user.session_store import SessionStore
    from auto_designer.user.sim.persona_client import AgenticPersonaClient, ApiPersonaClient
    from auto_designer.user.sim.persona_io import card_to_persona

    context_path = os.environ.get("AUTO_DESIGNER_EXPERIMENT_CONTEXT", "").strip()
    if context_path:
        from auto_designer.experiment.runtime import ExperimentContext

        context = ExperimentContext.load(path=Path(context_path))
        run_mod.apply_experiment_context(ctx=context)
    run_mod._isolate_git_credentials()
    llm_env = run_mod._load_env(ROOT / ".env")
    # 启动命令显式注入的配置优先于仓内 .env，便于临时切换网关/模型且不把密钥写盘。
    run_mod._apply_env_defaults(llm_env)
    for suffix in ("MODEL", "BASE_URL", "API_KEY"):
        val = os.environ.get(f"HARNESS_LLM_{suffix}")
        if not val:
            raise SystemExit(f"backend/.env 缺 HARNESS_LLM_{suffix}")
        os.environ[f"LLM_{suffix}"] = val
    gitea_path = Path(
        os.environ.get("AUTO_DESIGNER_GITEA_ENV_FILE", "").strip()
        or str(ROOT / "deploy" / "gitea" / ".env")
    )
    gitea = run_mod._load_env(gitea_path)

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
    pair_log: dict[int, list[tuple[str, str]]] = {}

    def session_plan():
        round_no = current["round"]
        picks = _session_picks(rng, round_index=round_no - 1)
        pair_log[round_no] = list(picks)
        print(f"  session plan ({len(picks)}): {picks}")
        return [(display[pid], scenarios[iid]) for pid, iid in picks]

    print(
        f"⓪ SWE-bench 闭环：persona×{len(PERSONA_IDS)} · instance×{len(INSTANCE_IDS)} · "
        f"每轮{'无放回全覆盖' if ALL_ONCE else '有放回'} {SESSIONS_PER_ROUND} 对 · "
        f"共 {run_mod.TOTAL_ROUNDS} 轮 · seed={SESSION_SEED}"
    )
    for iid, meta in instances.items():
        print(f"   - {meta['difficulty']:16}  {meta['repo']:28}  {iid}")
    print(
        f"⓪.5 roster：user×{roster['user']} · triager×{roster['triager']} · "
        f"designer×{roster['designer']} · divergent×{roster.get('divergent', 0)} · "
        f"developer×{roster['developer']}"
    )

    from auto_designer.invocation import append_round, init_manifest  # noqa: PLC0415

    run_mode = run_mod.experiment_run_mode()
    role_runs = run_mod.install_role_runs(data_root=run_mod.DATA)
    recovery = run_mod.load_recovery_store(mode=run_mode)
    if run_mode == "fresh":
        init_manifest(
            roster=roster,
            models={
                "user": os.environ.get("USER_LLM_MODEL", ""),
                "designer": os.environ.get("DESIGNER_LLM_MODEL", ""),
                "harness": os.environ.get("HARNESS_LLM_MODEL", ""),
                "delivery": os.environ.get("ANTHROPIC_MODEL", ""),
            },
        )
    print(f"⓪.6 实验切片 ROLE_RUNS_DIR={role_runs}")
    if run_mode == "fresh":
        print("① fresh：种 harness 本地仓 ...")
        repo = run_mod._seed_harness_repo()
    else:
        print("① resume：复用现有 harness 本地仓 ...")
        repo = run_mod.existing_harness_repo()
    print("② 接 Gitea ...")
    tracker = GiteaTracker(
        base_url=gitea["GITEA_URL"], owner=gitea["OWNER"], repo=gitea["REPO"], token=gitea["TOKEN"]
    )
    tracker.ensure_labels(["bug", "feature", "needs-triage", "RFC", "triaged"])
    run_mod._set_gitea_remote(repo, gitea)
    if run_mode == "fresh":
        run_mod._reset_to_initial(repo, tracker)
    if run_mode == "resume" and recovery is not None:
        from auto_designer.loop.live import prepare_live_resume

        prepare_live_resume(data_dir=run_mod.DATA, phase="reconcile")
    store = SessionStore(role_runs / "sessions")
    launcher = HarnessLauncher(harness_repo=str(repo), runs_root=run_mod.DATA / "harness_runs")

    api = ApiPersonaClient()

    def client_factory() -> AgenticPersonaClient:
        return AgenticPersonaClient(api.complete)

    current = {"round": 0}
    round_shas: dict[str, str] = {}

    def on_round_start(k: int) -> None:
        current["round"] = k
        update_live_run(
            data_dir=run_mod.DATA,
            running=True,
            round_no=k,
            total_rounds=run_mod.TOTAL_ROUNDS,
            phase=orch.recovery_phase(round_no=k) if recovery is not None else "users",
        )
        print(f"\n==== round {k}/{run_mod.TOTAL_ROUNDS} ====")

    def on_round_end(k: int, sha: str) -> None:
        round_shas[str(k)] = sha
        append_round(round_no=k, user_sha=None, sealed_sha=sha)
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
            round_provider=lambda: current["round"] or None,
        )
        for i in range(roster["designer"])
    ]
    from auto_designer.designer.grouped_designer import group_designer_stage

    designers = group_designer_stage(designers, artifact_root=role_runs / "designer_grouping")

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

    def make_owner_status(agent_id: str, label: str):
        def cb(*, running, status, detail=None, proposals=None):
            update_agent(
                data_dir=run_mod.DATA,
                agent_id=agent_id,
                role="owner",
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
                    extra={"kind": "owner_run", "proposals": proposals or []},
                )

        return cb

    from auto_designer.designer.owner import Owner  # noqa: PLC0415

    owner = Owner(
        tracker,
        store,
        str(repo),
        str(ROOT / "agent_defs" / "owner"),
        on_status=make_owner_status("owner-0", "owner"),
        on_event=make_event_logger("owner-0"),
        review=roster["owner"] >= 1,
    )

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
        owner=owner,
        on_round_start=on_round_start,
        on_round_end=on_round_end,
        max_parallel_users=max_parallel_users,
        integrity_guard=integrity_guard,
        fetch_issue=lambda number: tracker.get_issue(number=number),
        recovery=recovery,
    )

    vigil = None
    if run_mod.TOTAL_ROUNDS > 1:
        vigil = run_mod.start_vigil(
            repo=repo,
            parallel=roster["developer"],
            gitea=gitea,
            log_path=run_mod.DATA / "vigil.log",
        )

    print(
        f"④ 跑 {run_mod.TOTAL_ROUNDS} 轮闭环（每轮 {SESSIONS_PER_ROUND} session · "
        f"{len(triagers)} triager × {roster['designer']} synthesize × {len(divergents)} divergent；"
        f"owner({'评审' if roster['owner'] >= 1 else '纯机械'}) · "
        f"交付面 vigil --parallel {roster['developer']}（末轮只用户），"
        f"a 段并发 {max_parallel_users}）..."
    )
    refs: list[str] = []
    try:
        refs = orch.run(run_mod.TOTAL_ROUNDS)
    except RoundDeliveryBlocked as exc:
        if vigil is not None:
            vigil.keep_alive = True
        update_live_run(
            data_dir=run_mod.DATA,
            running=False,
            round_no=current["round"],
            total_rounds=run_mod.TOTAL_ROUNDS,
            round_shas=round_shas,
            phase="blocked",
            blocked_issues=list(exc.numbers),
        )
        print(f"[orchestrator] 本轮交付卡死，实验停止：{exc}")
        raise
    finally:
        if vigil is not None:
            run_mod.stop_vigil(vigil)
        update_live_run(
            data_dir=run_mod.DATA,
            running=False,
            round_no=current["round"],
            total_rounds=run_mod.TOTAL_ROUNDS,
            round_shas=round_shas,
        )

    plan_path = run_mod.DATA / "swebench_session_plans.json"
    if recovery is not None:
        saved_rounds = recovery.snapshot().get("rounds") or {}
        recovered_log = []
        for round_no in range(1, run_mod.TOTAL_ROUNDS + 1):
            saved = saved_rounds.get(str(round_no), {}).get("plan") or []
            recovered_log.append(
                [
                    [
                        item["persona"]["identity"],
                        ((item["scenario"].get("workspace") or {}).get("params") or {}).get(
                            "instance_id", ""
                        ),
                    ]
                    for item in saved
                ]
            )
        plan_payload = recovered_log
    else:
        plan_payload = [pair_log[key] for key in sorted(pair_log)]
    plan_path.write_text(
        json.dumps(plan_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
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
