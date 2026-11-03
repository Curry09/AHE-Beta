"""Spec-0073/T4: unified frozen-task experiment controller. Start through the experiment CLI."""

from __future__ import annotations

import os
import subprocess
import sys
from functools import partial
from pathlib import Path

from ahe_beta.experiment.controllers import runtime
from ahe_beta.models import bound_session_provenance
from ahe_beta.usage import current_usage_context


class _AssessmentReadyLauncher:
    """Gate actual Actors, while allowing sealed-session recovery without a worker."""

    def __init__(self, launcher, assessment):
        self._launcher = launcher
        self._assessment = assessment

    def __getattr__(self, name):
        return getattr(self._launcher, name)

    def launch(self, *args, **kwargs):
        # Recovery resolves authoritative Sessions before reaching launch. Each
        # real launch still checks the current generation's signed readiness;
        # no mutable "already ready" flag is shared by concurrent user slots.
        self._assessment.await_worker()
        return self._launcher.launch(*args, **kwargs)


def _resolve_frozen_session(binding, sim_personas):
    from ahe_beta.experiment.context import frozen_scenario
    from ahe_beta.models import Persona

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
    from ahe_beta.loop.live import archive_agent, update_agent

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
                "score": result.feeling.score
                if result is not None and result.feeling is not None
                else None,
            },
        )


def main() -> int:
    from urllib.parse import urlparse

    from ahe_beta.experiment.context import require_controller_context

    context = require_controller_context()
    runtime.TOTAL_ROUNDS = int(os.environ["TOTAL_ROUNDS"])
    runtime.apply_experiment_context(ctx=context)
    runtime._isolate_git_credentials()
    for _suffix in ("MODEL", "BASE_URL", "API_KEY"):
        _val = os.environ.get(f"HARNESS_LLM_{_suffix}")
        if not _val:
            raise SystemExit(
                f"Runtime configuration is missing HARNESS_LLM_{_suffix} (the harness's independent LLM configuration)"
            )
        os.environ[f"LLM_{_suffix}"] = _val
    _reasoning_effort = os.environ.get("HARNESS_LLM_REASONING_EFFORT", "").strip()
    if _reasoning_effort:
        os.environ["LLM_REASONING_EFFORT"] = _reasoning_effort
    else:
        os.environ.pop("LLM_REASONING_EFFORT", None)
    gitea = runtime._load_env(runtime.GITEA_ENV_FILE)
    from ahe_beta.loop.roster import load_roster

    roster = load_roster()
    print(
        f"⓪.5 Roster: users×{roster['user']} · Architects×{roster['architect']} · delivery concurrency×{roster['developer']} (vigil --parallel; frontend room capacity matches)"
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
    from ahe_beta.distill.library import PersonaLibrary
    from ahe_beta.harness.launcher import HarnessLauncher
    from ahe_beta.loop.metrics import Metrics
    from ahe_beta.loop.orchestrator import Orchestrator
    from ahe_beta.loop.round_gate import RoundDeliveryBlocked
    from ahe_beta.loop.sim_user import result_to_turns
    from ahe_beta.tracker.gitea import GiteaTracker
    from ahe_beta.user.session_store import SessionStore
    from ahe_beta.user.sim.persona_client import AgenticPersonaClient, ApiPersonaClient
    from ahe_beta.user.sim.persona_io import card_to_personas

    print(f"⓪ Input: frozen persona library={os.environ['PERSONA_LIBRARY']}")
    run_mode = runtime.experiment_run_mode()
    role_runs = runtime.install_role_runs(data_root=runtime.DATA)
    recovery = runtime.load_recovery_store(mode=run_mode)
    from ahe_beta.invocation import init_manifest

    if run_mode == "fresh":
        init_manifest(
            roster=roster,
            models={
                "user": os.environ.get("USER_LLM_MODEL", ""),
                "architect": os.environ.get("DEMAND_LLM_MODEL", ""),
                "harness": os.environ.get("HARNESS_LLM_MODEL", ""),
                "delivery": os.environ.get("ANTHROPIC_MODEL", ""),
            },
        )
    print(f"⓪.6 Experiment invocation slice ROLE_RUNS_DIR={role_runs}")
    if run_mode == "fresh":
        print("① fresh: initialize the local harness repository ...")
        repo = runtime._seed_harness_repo()
    else:
        print("① resume: reuse the existing local harness repository ...")
        repo = runtime.existing_harness_repo()
    print("② Connect Gitea + local storage + launcher ...")
    tracker = GiteaTracker(
        base_url=gitea["GITEA_URL"], owner=gitea["OWNER"], repo=gitea["REPO"], token=gitea["TOKEN"]
    )
    tracker.ensure_labels(["bug", "feature"])
    runtime._set_gitea_remote(repo, gitea)
    if run_mode == "fresh":
        print("②.5 fresh: reset Gitea harness, issues, and live projections ...")
        runtime._reset_to_initial(repo, tracker)
    else:
        print("②.5 resume: preserve Gitea, session, harness, and live history ...")
    store = SessionStore(role_runs / "sessions")
    from ahe_beta.loop.round_assessment import RoundAssessment, read_json

    experiment_root = Path(os.environ["AHE_BETA_FROZEN_MANIFEST"]).parent
    store.bind_assessment_root(experiment_root / "assessment")
    round_assessment = RoundAssessment(
        experiment_root, read_json(experiment_root / "manifest.json"), store
    )
    launcher = _AssessmentReadyLauncher(
        HarnessLauncher(harness_repo=str(repo), runs_root=runtime.DATA / "harness_runs"),
        round_assessment,
    )
    print(
        "③ Assemble the simulated user (spec-0005 control loop) and generation/admission roles ..."
    )
    api = ApiPersonaClient()

    def client_factory() -> AgenticPersonaClient:
        return AgenticPersonaClient(api.complete)

    sim_persona_list = card_to_personas(PersonaLibrary(Path(os.environ["PERSONA_LIBRARY"])))
    from ahe_beta.experiment.context import frozen_workload

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

    from ahe_beta.loop.live import (
        append_agent_log,
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
        status = f"In conversation… turn {last.turn} · {last.verdict}" if last else "Starting…"
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

    from ahe_beta.experiment.controllers.feedback import assemble_feedback_roles

    feedback_roles = assemble_feedback_roles(
        tracker=tracker,
        store=store,
        repo=repo,
        definitions_root=runtime.ROOT / "agent_defs",
        roster=roster,
        round_provider=lambda: current["round"] or None,
        artifact_root=role_runs / "architect_grouping",
        status_factory=lambda role, agent_id, label: _role_status(
            role=role,
            agent_id=agent_id,
            label=label,
            data_dir=runtime.DATA,
            round_provider=lambda: current["round"],
        ),
        event_factory=make_event_logger,
    )
    triagers, architects, divergents, owner = (
        feedback_roles[key] for key in ("triagers", "architects", "divergents", "owner")
    )
    raw_parallel = os.environ.get("MAX_PARALLEL_USERS", "").strip()
    max_parallel_users = int(raw_parallel) if raw_parallel.isdigit() else len(plan["rounds"][0])
    max_parallel_users = max(1, max_parallel_users)
    from ahe_beta.guards.repo_guard import snapshot_repo, verify_unchanged

    _repo_baseline = snapshot_repo(repo=str(runtime.ROOT))

    def integrity_guard() -> None:
        verify_unchanged(repo=str(runtime.ROOT), before=_repo_baseline)

    orch = Orchestrator(
        round_assessment=round_assessment,
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
        architects=architects,
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
    from ahe_beta.experiment.config import delivery_required, read_json_document

    frozen_manifest = read_json_document(path=Path(os.environ["AHE_BETA_FROZEN_MANIFEST"]))
    run_root = Path(os.environ["AHE_BETA_FROZEN_MANIFEST"]).parent
    if delivery_required(frozen_manifest["config"]):
        print(f"③.5 Start delivery vigil (OpenAgents, mode={runtime.vigil_mode()})...")
        vigil = runtime.start_vigil(
            repo=repo,
            parallel=roster["developer"],
            gitea=gitea,
            log_path=runtime.DATA / "vigil.log",
        )
    print(
        f"④ Run {runtime.TOTAL_ROUNDS} evolution rounds ({len(plan['rounds'][0])} sessions × {len(triagers)} triager shards ∥ {len(divergents)} divergent → {roster['architect']} architect → owner({('review' if roster['owner'] >= 1 else 'mechanical handoff without LLM')})); delivery vigil --parallel {roster['developer']} (users only in the final round; otherwise seal delivery before advancing), stage a concurrency {max_parallel_users}, backpressure thresholds proposal>{proposal_alarm}/ready>{ready_alarm}, real models)..."
    )
    refs: list[str] = []
    exit_code = 0
    terminal_phase = "failed"
    try:
        if "continuation" in frozen_manifest["config"]:
            from ahe_beta.experiment.controllers.feedback import run_continuation_bootstrap

            print(
                "[continuation-bootstrap] processing parent feedback · "
                f"parent logical round {frozen_manifest['lineage']['base_round']}"
            )
            update_live_run(
                data_dir=runtime.DATA,
                running=True,
                round_no=0,
                total_rounds=runtime.TOTAL_ROUNDS,
                phase="continuation-bootstrap",
            )
            run_continuation_bootstrap(
                run_root=run_root,
                manifest=frozen_manifest,
                tracker=tracker,
                child_store=store,
                repo=repo,
                definitions_root=runtime.ROOT / "agent_defs",
                roster=roster,
                resolve_head=partial(orch._resolve_head, ref="main"),
                assert_descendant=orch._assert_descendant,
                integrity_guard=integrity_guard,
                status_factory=lambda role, agent_id, label: _role_status(
                    role=role,
                    agent_id=agent_id,
                    label=label,
                    data_dir=runtime.DATA,
                    round_provider=lambda: 0,
                ),
                event_factory=make_event_logger,
            )
        refs = orch.run(runtime.TOTAL_ROUNDS)
        from ahe_beta.experiment.collection import export_gitea_snapshot
        from ahe_beta.experiment.continuation.export import export_continuation

        export_gitea_snapshot(
            run_dir=run_root,
            resources={
                "gitea": {"url": gitea["GITEA_URL"], "owner": gitea["OWNER"], "repo": gitea["REPO"]}
            },
            credentials={"GITEA_TOKEN": gitea["TOKEN"]},
            terminal=True,
            controller_nonce=os.environ.get("AHE_BETA_CONTROLLER_NONCE"),
        )
        export_continuation(
            root=run_root,
            harness_repo=repo,
            manifest=frozen_manifest,
            recovery=recovery,
            sessions_root=store.root,
            forge_path=run_root / "runtime/gitea-evidence.json",
        )
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
        print(f"[orchestrator] Delivery blocked this round; experiment stopped: {exc}")
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
    print("\n=== Results ===")
    print("main HEAD SHA by round:", refs)
    m = Metrics(tracker, store)
    print("Current open issue count:", m.open_issue_count())
    print("User experience trend:", m.feeling_trend())
    print("Issue curve (t, opened, net_open):", m.issue_curve())
    print("Local repository branches:", end=" ")
    subprocess.run(["git", "-C", str(repo), "branch", "--format=%(refname:short)"])
    return exit_code


# Spec-0079/T4: phase assembly shares concrete UI callbacks without mutating roles.
def _role_status(*, role, agent_id, label, data_dir, round_provider):
    from ahe_beta.loop.live import archive_agent, update_agent

    def callback(*, running, status, detail=None, proposals=None, **kwargs):
        number = round_provider()
        update_agent(
            data_dir=data_dir,
            agent_id=agent_id,
            role=role,
            label=label,
            running=running,
            status=status,
            detail=detail,
            round_no=number,
        )
        if not running:
            archive_agent(
                data_dir=data_dir,
                agent_id=agent_id,
                round_no=number,
                extra={"kind": role + "_run", "proposals": proposals or []},
            )

    return callback


if __name__ == "__main__":
    sys.exit(main())
