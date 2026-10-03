"""Spec-0073/T4: unified frozen-task experiment controller. Start through the experiment CLI."""

from __future__ import annotations

import os
import subprocess
import sys
from functools import partial
from pathlib import Path

from auto_designer.experiment.controllers import runtime
from auto_designer.models import bound_session_provenance
from auto_designer.usage import current_usage_context


def _resolve_frozen_session(binding, sim_personas):
    from auto_designer.experiment.context import frozen_scenario
    from auto_designer.models import Persona

    sp = sim_personas[binding["persona_id"]]
    scenario = frozen_scenario(task_id=binding["task_id"])
    return Persona(
        identity=sp.persona_id,
        level=sp.d1.value,
        domain="/".join(sp.d2.stack) or "general",
        goal=scenario.description[:120],
        speaking_style=f"delegation={sp.d41.value}; autonomy={sp.d5.value}",
    ), scenario


def _observe_session(status, persona, scenario, result, *, data_dir, persona_meta):
    from auto_designer.loop.live import archive_agent, update_agent

    ctx = current_usage_context()
    provenance = bound_session_provenance()
    meta = dict(persona_meta.get(persona.identity) or {})
    meta.update(
        session_provenance=provenance,
        session_id=ctx.session_id,
        **{
            key: provenance[key]
            for key in (
                "persona_id",
                "task_id",
                "task_digest",
                "task_kind",
                "interaction",
                "slot",
                "harness_sha",
            )
        },
    )
    update_agent(
        data_dir=data_dir,
        agent_id=f"user-{ctx.session_id}",
        role="user",
        label=persona.identity,
        running=status == "running",
        status=status,
        round_no=ctx.round_no,
        meta=meta,
        turns=[turn.to_dict() for turn in result.transcript.turns] if result is not None else None,
    )
    if status != "running":
        archive_agent(
            data_dir=data_dir,
            agent_id=f"user-{ctx.session_id}",
            round_no=ctx.round_no,
            extra={
                "kind": "user_session",
                **meta,
                "score": result.feeling.score if result is not None else None,
            },
        )


def main() -> int:
    from urllib.parse import urlparse

    from auto_designer.experiment.context import require_controller_context

    context = require_controller_context()
    runtime.TOTAL_ROUNDS = int(os.environ["TOTAL_ROUNDS"])
    runtime.apply_experiment_context(ctx=context)
    runtime._isolate_git_credentials()
    for _suffix in ("MODEL", "BASE_URL", "API_KEY"):
        _val = os.environ.get(f"HARNESS_LLM_{_suffix}")
        if not _val:
            raise SystemExit(f"运行配置缺 HARNESS_LLM_{_suffix}（harness 本体的独立 LLM 配置）")
        os.environ[f"LLM_{_suffix}"] = _val
    _reasoning_effort = os.environ.get("HARNESS_LLM_REASONING_EFFORT", "").strip()
    if _reasoning_effort:
        os.environ["LLM_REASONING_EFFORT"] = _reasoning_effort
    else:
        os.environ.pop("LLM_REASONING_EFFORT", None)
    gitea = runtime._load_env(runtime.GITEA_ENV_FILE)
    from auto_designer.loop.roster import load_roster

    roster = load_roster()
    print(
        f"⓪.5 编制 roster：用户×{roster['user']} · Synthesizer×{roster['synthesizer']} · 交付面并发×{roster['developer']}（vigil --parallel；前端房间容量与此一致）"
    )
    bypass = ["localhost", "127.0.0.1"]
    for url in (
        os.environ.get("USER_LLM_BASE_URL"),
        os.environ.get("DEMAND_LLM_BASE_URL"),
        gitea.get("GITEA_URL"),
    ):
        host = urlparse(url).hostname if url else None
        if host and host not in bypass:
            bypass.append(host)
    no_proxy = ",".join(bypass)
    os.environ["NO_PROXY"] = no_proxy
    os.environ["no_proxy"] = no_proxy
    from auto_designer.demand.synthesizer import Synthesizer
    from auto_designer.demand.triage import Triager
    from auto_designer.distill.library import PersonaLibrary
    from auto_designer.harness.launcher import HarnessLauncher
    from auto_designer.loop.metrics import Metrics
    from auto_designer.loop.orchestrator import Orchestrator
    from auto_designer.loop.round_gate import RoundDeliveryBlocked
    from auto_designer.loop.sim_user import result_to_turns
    from auto_designer.tracker.gitea import GiteaTracker
    from auto_designer.user.session_store import SessionStore
    from auto_designer.user.sim.persona_client import AgenticPersonaClient, ApiPersonaClient
    from auto_designer.user.sim.persona_io import card_to_personas

    print(f"⓪ 输入：冻结 persona 卡库={os.environ['PERSONA_LIBRARY']}")
    run_mode = runtime.experiment_run_mode()
    role_runs = runtime.install_role_runs(data_root=runtime.DATA)
    recovery = runtime.load_recovery_store(mode=run_mode)
    from auto_designer.invocation import init_manifest

    if run_mode == "fresh":
        init_manifest(
            roster=roster,
            models={
                "user": os.environ.get("USER_LLM_MODEL", ""),
                "synthesizer": os.environ.get("DEMAND_LLM_MODEL", ""),
                "harness": os.environ.get("HARNESS_LLM_MODEL", ""),
                "delivery": os.environ.get("ANTHROPIC_MODEL", ""),
            },
        )
    print(f"⓪.6 实验切片 ROLE_RUNS_DIR={role_runs}")
    if run_mode == "fresh":
        print("① fresh：种 harness 本地仓 ...")
        repo = runtime._seed_harness_repo()
    else:
        print("① resume：复用现有 harness 本地仓 ...")
        repo = runtime.existing_harness_repo()
    print("② 接 Gitea + 本地存储 + launcher ...")
    tracker = GiteaTracker(
        base_url=gitea["GITEA_URL"], owner=gitea["OWNER"], repo=gitea["REPO"], token=gitea["TOKEN"]
    )
    tracker.ensure_labels(["bug", "feature"])
    runtime._set_gitea_remote(repo, gitea)
    if run_mode == "fresh":
        print("②.5 fresh：复位 Gitea harness、issue 与 live 投影 ...")
        runtime._reset_to_initial(repo, tracker)
    else:
        print("②.5 resume：保留 Gitea、session、harness 与 live 历史 ...")
    store = SessionStore(role_runs / "sessions")
    launcher = HarnessLauncher(harness_repo=str(repo), runs_root=runtime.DATA / "harness_runs")
    print("③ 装配 sim 用户 agent（spec-0005 控制信封）+ 生成/准入角色 ...")
    synthesizer_agent_def = str(runtime.ROOT / "agent_defs" / "synthesizer")
    triager_agent_def = str(runtime.ROOT / "agent_defs" / "triage_agent")
    divergent_agent_def = str(runtime.ROOT / "agent_defs" / "divergent_pm")
    owner_agent_def = str(runtime.ROOT / "agent_defs" / "owner")
    api = ApiPersonaClient()

    def client_factory() -> AgenticPersonaClient:
        return AgenticPersonaClient(api.complete)

    sim_persona_list = card_to_personas(PersonaLibrary(Path(os.environ["PERSONA_LIBRARY"])))
    from auto_designer.experiment.context import frozen_workload

    catalog, plan, _workspaces = frozen_workload()
    if len(plan["rounds"]) != runtime.TOTAL_ROUNDS:
        raise SystemExit("Frozen session plan does not match TOTAL_ROUNDS")
    sim_personas = {sp.persona_id: sp for sp in sim_persona_list}
    persona_meta = {
        sp.persona_id: {
            "identity": sp.persona_id,
            "level": sp.d1.value,
            "domain": "/".join(sp.d2.stack) or "general",
        }
        for sp in sim_persona_list
    }

    def frozen_session_plan(round_no):
        return plan["rounds"][round_no - 1]

    def resolve_session(binding):
        return _resolve_frozen_session(binding, sim_personas)

    from auto_designer.loop.live import (
        append_agent_log,
        archive_agent,
        clear_live,
        prepare_live_resume,
        update_agent,
        update_live_run,
    )

    if run_mode == "fresh":
        clear_live(data_dir=runtime.DATA)
    elif recovery is not None:
        prepare_live_resume(data_dir=runtime.DATA, phase="reconcile")
    current = {"round": 0}
    round_shas: list[str] = []

    def on_round_start(k):
        current["round"] = k
        update_live_run(
            data_dir=runtime.DATA,
            running=True,
            round_no=k,
            total_rounds=runtime.TOTAL_ROUNDS,
            phase=orch.recovery_phase(round_no=k) if recovery is not None else "users",
        )

    proposal_alarm = runtime._alarm_threshold("PROPOSAL_DEPTH_ALARM")
    ready_alarm = runtime._alarm_threshold("READY_DEPTH_ALARM")
    on_round_end = partial(runtime._on_round_end, tracker=tracker, round_shas=round_shas)

    def make_event_logger(agent_id):
        return lambda kind, text: append_agent_log(
            data_dir=runtime.DATA, agent_id=agent_id, text=text, kind=kind
        )

    on_session_event = partial(_observe_session, data_dir=runtime.DATA, persona_meta=persona_meta)

    def on_sim_turn(identity, sim_persona, res, running, *, session_id=None):
        ctx = current_usage_context()
        turns = [t.to_dict() for t in result_to_turns(res)]
        last = res.turns[-1] if res.turns else None
        status = f"对话中… 第 {last.turn} 轮 · {last.verdict}" if last else "启动中…"
        update_agent(
            data_dir=runtime.DATA,
            agent_id=f"user-{ctx.session_id}",
            role="user",
            label=identity,
            running=running,
            status=status,
            turns=turns,
            round_no=ctx.round_no,
        )

    user_run_session_fn = runtime._make_user_run_session_fn(
        client_factory=client_factory,
        tracker=tracker,
        store=store,
        sim_personas=sim_personas,
        on_turn=on_sim_turn,
        round_provider=lambda: current["round"] or None,
    )

    def make_triager_status(agent_id, label):

        def cb(*, running, status, detail=None, **kw):
            update_agent(
                data_dir=runtime.DATA,
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
                    data_dir=runtime.DATA,
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
            triager_agent_def,
            on_status=make_triager_status(
                f"triager-{i}", "triager" if roster["triager"] == 1 else f"triager#{i + 1}"
            ),
            on_event=make_event_logger(f"triager-{i}"),
        )
        for i in range(roster["triager"])
    ]

    def make_synthesizer_status(agent_id, label):

        def cb(*, running, status, detail=None, proposals=None):
            update_agent(
                data_dir=runtime.DATA,
                agent_id=agent_id,
                role="synthesizer",
                label=label,
                running=running,
                status=status,
                detail=detail,
                round_no=current["round"],
            )
            if not running:
                archive_agent(
                    data_dir=runtime.DATA,
                    agent_id=agent_id,
                    round_no=current["round"],
                    extra={"kind": "synthesizer_run", "proposals": proposals or []},
                )

        return cb

    synthesizers = [
        Synthesizer(
            tracker,
            store,
            str(repo),
            synthesizer_agent_def,
            on_status=make_synthesizer_status(
                f"synthesizer-{i}",
                "synthesizer" if roster["synthesizer"] == 1 else f"synthesizer#{i + 1}",
            ),
            on_event=make_event_logger(f"synthesizer-{i}"),
            round_provider=lambda: current["round"] or None,
        )
        for i in range(roster["synthesizer"])
    ]
    from auto_designer.demand.grouped_synthesizer import group_synthesizer_stage

    synthesizers = group_synthesizer_stage(
        synthesizers, artifact_root=role_runs / "synthesizer_grouping"
    )

    def make_divergent_status(agent_id, label):

        def cb(*, running, status, detail=None, proposals=None):
            update_agent(
                data_dir=runtime.DATA,
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
                    data_dir=runtime.DATA,
                    agent_id=agent_id,
                    round_no=current["round"],
                    extra={"kind": "divergent_run", "proposals": proposals or []},
                )

        return cb

    from auto_designer.demand.divergent import Divergent

    divergents = [
        Divergent(
            tracker,
            store,
            str(repo),
            divergent_agent_def,
            on_status=make_divergent_status(
                f"divergent-{i}", "divergent" if roster["divergent"] == 1 else f"divergent#{i + 1}"
            ),
            on_event=make_event_logger(f"divergent-{i}"),
            round_provider=lambda: current["round"] or None,
        )
        for i in range(roster["divergent"])
    ]

    def make_owner_status(agent_id, label):

        def cb(*, running, status, detail=None, proposals=None):
            update_agent(
                data_dir=runtime.DATA,
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
                    data_dir=runtime.DATA,
                    agent_id=agent_id,
                    round_no=current["round"],
                    extra={"kind": "owner_run", "proposals": proposals or []},
                )

        return cb

    from auto_designer.demand.owner import Owner

    owner = Owner(
        tracker,
        store,
        str(repo),
        owner_agent_def,
        on_status=make_owner_status("owner-0", "owner"),
        on_event=make_event_logger("owner-0"),
        review=roster["owner"] >= 1,
    )
    raw_parallel = os.environ.get("MAX_PARALLEL_USERS", "").strip()
    max_parallel_users = int(raw_parallel) if raw_parallel.isdigit() else len(plan["rounds"][0])
    max_parallel_users = max(1, max_parallel_users)
    from auto_designer.guards.repo_guard import snapshot_repo, verify_unchanged

    _repo_baseline = snapshot_repo(repo=str(runtime.ROOT))

    def integrity_guard() -> None:
        verify_unchanged(repo=str(runtime.ROOT), before=_repo_baseline)

    orch = Orchestrator(
        launcher=launcher,
        harness_repo=str(repo),
        fixed_set=[],
        frozen_session_plan=frozen_session_plan,
        resolve_session=resolve_session,
        task_kinds={task["id"]: task["kind"] for task in catalog["tasks"]},
        on_session_event=on_session_event,
        run_session_fn=user_run_session_fn,
        initial_ref="main",
        triagers=triagers,
        synthesizers=synthesizers,
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
    if runtime.TOTAL_ROUNDS > 1:
        print(f"③.5 起交付面 vigil（OpenAgents，mode={runtime.vigil_mode()}）...")
        vigil = runtime.start_vigil(
            repo=repo,
            parallel=roster["developer"],
            gitea=gitea,
            log_path=runtime.DATA / "vigil.log",
        )
    print(
        f"④ 跑 {runtime.TOTAL_ROUNDS} 轮闭环（{len(plan['rounds'][0])} 个 session × {len(triagers)} triager 分片 ∥ {len(divergents)} divergent → {roster['synthesizer']} synthesize → owner({('评审' if roster['owner'] >= 1 else '零 LLM 机械交接')})；交付面 vigil --parallel {roster['developer']}（末轮只用户；非末轮封口后切轮），a 段并发 {max_parallel_users}，背压阈值 proposal>{proposal_alarm}/ready>{ready_alarm}，真模型）..."
    )
    refs: list[str] = []
    exit_code = 0
    terminal_phase = "failed"
    try:
        refs = orch.run(runtime.TOTAL_ROUNDS)
        terminal_phase = "done"
    except KeyboardInterrupt:
        exit_code = 130
        terminal_phase = "stopped"
        if vigil is not None:
            vigil.keep_alive = False
    except RoundDeliveryBlocked as exc:
        exit_code = 1
        terminal_phase = "blocked"
        if vigil is not None:
            vigil.keep_alive = recovery is None
        update_live_run(
            data_dir=runtime.DATA,
            running=False,
            round_no=current["round"],
            total_rounds=runtime.TOTAL_ROUNDS,
            round_shas=round_shas,
            phase="blocked",
            blocked_issues=list(exc.numbers),
        )
        print(f"[orchestrator] 本轮交付卡死，实验停止：{exc}")
    finally:
        if vigil is not None:
            runtime.stop_vigil(vigil)
        update_live_run(
            data_dir=runtime.DATA,
            running=False,
            round_no=current["round"],
            total_rounds=runtime.TOTAL_ROUNDS,
            round_shas=round_shas,
            phase=terminal_phase,
        )
    if terminal_phase == "stopped":
        return exit_code
    print("\n=== 结果 ===")
    print("各轮 main HEAD SHA:", refs)
    m = Metrics(tracker, store)
    print("当前 open issue 数:", m.open_issue_count())
    print("体感趋势:", m.feeling_trend())
    print("issue 曲线 (t, opened, net_open):", m.issue_curve())
    print("本地仓分支:", end=" ")
    subprocess.run(["git", "-C", str(repo), "branch", "--format=%(refname:short)"])
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
