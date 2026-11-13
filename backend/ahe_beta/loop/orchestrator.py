# Spec-0032/T4: requirement-plane orchestration — two phases of generation (triage partitioning ∥ divergent → architect) → owner admission.
# Spec-0050/T3: after non-final-round admission, wait for this round's admitted tickets to reach terminal state; final round runs user sessions only, no generation/delivery gates.
"""Orchestrate demand generation and delivery across evolution rounds.

Non-final rounds: users test current main, proposals are generated in two stages, Owner admits
issues, and the round waits for those issues to reach terminal states before returning the
sealed SHA as feedback. The final round runs user sessions only, without generation, Owner,
or delivery gates. A blocked delivery raises RoundDeliveryBlocked and prevents the next
round's user sessions from starting.
"""

from __future__ import annotations

import contextvars
import json
import subprocess
import threading
import traceback
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from types import MappingProxyType
from typing import Any, Protocol

from ahe_beta.demand.architect import Architect
from ahe_beta.demand.divergent import Divergent
from ahe_beta.demand.source import bind_harness_source
from ahe_beta.harness.interface import HarnessInterface
from ahe_beta.harness.launcher import HarnessLauncher
from ahe_beta.loop.feedback_pipeline import FeedbackPipeline, _result_payload
from ahe_beta.loop.recovery import (
    RecoveryConflictError,
    RecoveryIdentity,
    RecoveryStore,
    operation_key,
)
from ahe_beta.loop.round_gate import RoundDeliveryBlocked, wait_round_delivery
from ahe_beta.models import (
    Persona,
    SeedScenario,
    Session,
    bound_session_provenance,
    validate_session_provenance,
)
from ahe_beta.usage import bind_usage_context, current_usage_context
from ahe_beta.user.sim.deps import ensure_deps
from ahe_beta.user.sim.runtime import (
    WorkspaceRuntime,
    as_runtime,
    cleanup_workspace,
    make_empty_runtime,
)
from ahe_beta.user.sim.workspace import materialize as materialize_workspace

type SessionPair = tuple[Persona, SeedScenario]
type SessionPlan = Sequence[SessionPair] | Callable[[], Sequence[SessionPair]]


class SessionRunner(Protocol):
    """Run a session for (persona, scenario, harness); the return value is unrestricted.

    The implementation persists or submits outputs; orchestration does not consume the return value.
    Spec-0008/T1 v2: optional keyword `workspace_dir` is the shared workspace materialized by the
    orchestrator before each session. The launcher supplies it to the harness, and the session
    implementation uses it to bind the inner client. None preserves the legacy behavior.
    """

    def __call__(
        self,
        persona: Persona,
        scenario: SeedScenario,
        harness: HarnessInterface,
        *,
        workspace_dir: WorkspaceRuntime | None = None,
    ) -> object: ...


class Orchestrator:
    """Chain a→b→c into repeatable evolution rounds. Each component uses dependency injection."""

    def __init__(
        self,
        launcher: HarnessLauncher,
        harness_repo: str,
        fixed_set: SessionPlan,
        run_session_fn: SessionRunner,
        initial_ref: str,
        triagers: list | None = None,
        architects: list[Architect] | None = None,
        divergents: list[Divergent] | None = None,
        owner: object | None = None,
        on_round_start: Callable[[int], None] | None = None,
        on_round_end: Callable[[int, str], None] | None = None,
        max_parallel_users: int = 1,
        integrity_guard: Callable[[], None] | None = None,
        fetch_issue: Callable[[int], Mapping[str, Any]] | None = None,
        wait_delivery: Callable[..., None] | None = None,
        recovery: RecoveryStore | None = None,
        frozen_session_plan: Callable[[int], Sequence[Mapping[str, Any]]] | None = None,
        resolve_session: Callable[[Mapping[str, Any]], SessionPair] | None = None,
        task_kinds: Mapping[str, str] | None = None,
        round_assessment: Callable[..., None] | None = None,
        on_session_event: Callable[[str, Persona, SeedScenario, Session | None], None]
        | None = None,
    ) -> None:
        self._round_assessment = round_assessment
        self._launcher = launcher
        # Spec-0007/T2: harness repository used to parse main HEAD SHA
        self._harness_repo = harness_repo
        # Fixed list = same set per round; callable = re-drawn per round (e.g., random sampling with replacement over persona×task).
        self._fixed_set = fixed_set
        # Two phases of generation: first phase triage partitioning ∥ divergent; second phase architect; then owner does the single admission.
        self._triagers = triagers or []
        self._architects = architects or []
        self._divergents = divergents or []
        # Owner (Spec-0029/T6, always 1): None = skip admission phase (proposal backlog accumulates, backward compatible with old tests/scenarios without owner).
        self._owner = owner
        self._run_session = run_session_fn
        self._initial_ref = initial_ref  # Tracked trunk branch name (trunk = "main"), parse its HEAD SHA per session
        # Round observability callback (optional): round starts from 1; end carries this round's latest main SHA. Dashboard run state is determined from this.
        self._on_round_start = on_round_start
        self._on_round_end = on_round_end
        # Spec-0017/T3: concurrency level for phase-a user sessions (concurrency unit = entire session). Defaults to 1 = equivalent to old serial behavior.
        # Note: generation phase parallelizes within the same round using thread pool (read-only harness + write tracker), no git push.
        self._max_parallel_users = max(1, max_parallel_users)
        # Spec-0021/T1: orchestration repo integrity tripwire (optional). Invoked once per round end — agents within this process (generators/owner)
        # or delivery-plane agents on same machine escape and modify orchestration repo → raise error and abort this round (fail-closed). None = skip.
        self._integrity_guard = integrity_guard
        # Spec-0050/T3: read single ticket state for delivery gate; tests can inject wait_delivery to avoid real polling.
        self._fetch_issue = fetch_issue
        self._wait_delivery = wait_delivery
        # Spec-0064/T2: when present, run_round delegates to the durable stage
        # machine.  None preserves the established in-process behavior.
        self._recovery = recovery
        if (frozen_session_plan is None) != (resolve_session is None):
            raise ValueError("logical session plan and resolver must be supplied together")
        if frozen_session_plan is not None and recovery is None:
            raise ValueError("logical frozen sessions require a recovery store")
        # Spec-0073/T4: logical identity is frozen independently of provider coordinates.
        self._frozen_session_plan = frozen_session_plan
        self._resolve_session = resolve_session
        self._task_kinds = dict(task_kinds or {})
        self._on_session_event = on_session_event
        self._feedback_pipeline = self._make_feedback_pipeline() if recovery is not None else None

    def _make_feedback_pipeline(self) -> FeedbackPipeline:
        return FeedbackPipeline(
            recovery=self._require_recovery(),
            triagers=self._triagers,
            architects=self._architects,
            divergents=self._divergents,
            owner=self._owner,
            resolve_head=lambda: self._resolve_head(ref=self._initial_ref),
            assert_descendant=self._assert_descendant,
            integrity_guard=self._integrity_guard,
            fetch_issue=self._fetch_issue,
            wait_delivery=self._wait_delivery,
            grounding_repo=self._harness_repo,
            prerequisite="objective_grading" if self._round_assessment is not None else "users",
        )

    @property
    def recovery_enabled(self) -> bool:
        return self._recovery is not None

    @property
    def recovery_revision(self) -> int:
        return self._recovery.revision if self._recovery is not None else 0

    def refresh_recovery(self) -> None:
        """Reopen the ledger after Harbor restored its containing checkpoint."""
        if self._recovery is None:
            return
        identity = RecoveryIdentity(**self._recovery.snapshot()["identity"])
        self._recovery = RecoveryStore.open(root=self._recovery.root, identity=identity)
        self._feedback_pipeline = self._make_feedback_pipeline()

    def recovery_phase(self, *, round_no: int) -> str:
        """Return the first incomplete durable stage for the legacy RunState projection."""
        if self._recovery is None:
            return "a"
        round_state = self._recovery.round_state(round_no=round_no)
        if round_state is None:
            return "round_started"
        order = (
            "round_started",
            "users",
            *(("objective_grading",) if self._round_assessment else ()),
            "triage",
            "divergent",
            "architect",
            "owner",
            "delivery_wait",
            "round_sealed",
        )
        return next(
            (
                stage
                for stage in order
                if (round_state.get("stages") or {}).get(stage, {}).get("status") != "completed"
            ),
            "completed",
        )

    def run_round(self, ref: str, *, deliver: bool = True, round_no: int | None = None) -> str:
        if self._recovery is not None:
            number = round_no or current_usage_context().round_no
            if number is None:
                raise ValueError("recoverable run_round requires round_no or a bound round context")
            return self._run_recoverable_round(ref=ref, deliver=deliver, round_no=number)
        # Spec-0007/T2: passed ref is merely last round's observation cursor (forwarded for harbor runner's checkpoint resumption chain),
        # trunk always follows live main, not pinned by this — this round parses current main HEAD SHA as session-level snapshot anchor point.
        sha = self._resolve_head(ref=self._initial_ref)

        # Phase a: each fixed-set (persona, scenario) launches one session against that main SHA, produces issues (→tracker) + subjective experience (→store).
        #    launcher checkouts by SHA → multiple send calls within same session run the same SHA snapshot, harness does not change under foot.
        #    Spec-0008/T1 v2: prepare one **shared workspace** per session, same directory is both injected via launcher into harness
        #    (SANDBOX_WORK_DIR) and passed to session implementation binding inner client — harness changes, user agent validates in same directory.
        #    git/fixture-type seeds materialize + ensure_deps; plain-text cards (workspace=None) also open one empty
        #    scratch (fresh per session, isolated), ensuring user agent validates in same directory as harness, not just "mouth-verified"
        #    harness replies (else when environment missing, confabulates "test passed" polluting subjective experience).
        #    Spec-0017/T3: split into two phases — phase one serially prepares workspace (materialize/ensure_deps uses git clone cache
        #    shared resources, moved forward to avoid concurrent contention); Phase 2 uses thread pool to run sessions in parallel (launch + run_session as a complete unit,
        #    concurrency unit = entire session, envelope-internal sequencing unchanged). When max_parallel_users=1, behavior is equivalent to the old serial mode.
        prepared: list[tuple[Persona, SeedScenario, WorkspaceRuntime]] = []
        planned = list(self._session_plan())
        for persona, scenario in planned:
            try:
                if scenario.workspace is not None:
                    workspace_dir = as_runtime(
                        materialize_workspace(scenario.workspace), owns_tmp=True
                    )
                    # Spec-0009/T3: After materialize and before launch, prepare dependencies per scenario.workspace.setup
                    # (convention: create per-workspace .venv) -- this shared directory is ready before launch.
                    ensure_deps(workspace_dir, scenario.workspace)
                else:
                    workspace_dir = make_empty_runtime()
            except Exception:  # noqa: BLE001
                # Single session clone/setup failure (e.g., pip install fails on old repo) is logged and skipped; if the entire round fails,
                # the all-user-sessions-failed gate below will prevent this round from continuing.
                print(
                    f"[orchestrator] Workspace preparation failed (persona={persona.identity}); "
                    "skipping this session; other sessions in the round continue: "
                )
                traceback.print_exc()
                continue
            prepared.append((persona, scenario, workspace_dir))

        successful_sessions = 0
        session_lock = threading.Lock()

        def _one_session(
            persona: Persona, scenario: SeedScenario, workspace_dir: WorkspaceRuntime
        ) -> None:
            nonlocal successful_sessions
            try:
                harness = self._launcher.launch(sha, workspace_dir=workspace_dir)
                self._run_session(persona, scenario, harness, workspace_dir=workspace_dir)
                with session_lock:
                    successful_sessions += 1
            finally:
                cleanup_workspace(workspace_dir.close, stage="close", identity=persona.identity)

        if prepared:
            with ThreadPoolExecutor(
                max_workers=min(len(prepared), self._max_parallel_users)
            ) as pool:
                futures = {pool.submit(_one_session, p, s, ws): p for p, s, ws in prepared}
                for fut in as_completed(futures):
                    try:
                        fut.result()
                    except Exception:  # noqa: BLE001
                        # After 0012, harness failures are converted to [harness error] signals within the session (not re-raised); only
                        # launch/persistence-related exceptions remain -- single session failure is logged and skipped, does not fail the round or block other sessions.
                        print(
                            f"[orchestrator] User session failed (persona="
                            f"{futures[fut].identity}); skipping this session; other sessions in the round continue: "
                        )
                        traceback.print_exc()

        if planned and successful_sessions == 0:
            raise RoundDeliveryBlocked(numbers=[], reason="all-user-sessions-failed")

        # Spec-0050/T3: In the final round, only test users; skip proposal/admission/delivery gates.
        if not deliver:
            if self._integrity_guard is not None:
                self._integrity_guard()
            return self._resolve_head(ref=self._initial_ref)

        with bind_harness_source(self._harness_repo, sha):
            return self._run_legacy_feedback()

    def _run_legacy_feedback(self) -> str:
        # Generation phase, first wave (Spec-0029/T8): triage sharding ∥ divergent, running in parallel in the same thread pool.
        # Both only depend on phase a artifacts (triage consumes reports, divergent consumes session evidence), no interdependency; all outputs are unclaimed
        # proposals (PM independently handed to Owner, Architect only absorbs non-PM sources) → sharding is unrestricted.
        # Individual generator crash is logged and skipped, does not fail the round.
        beat1: list[tuple[str, Callable[[], object]]] = []
        n_triagers = len(self._triagers)
        triage_shards: list[list] | None = None
        if n_triagers and hasattr(self._triagers[0], "snapshot_pending"):
            # Snapshot once before any triager can mutate report labels.  Passing
            # explicit subsets makes ownership stable for the whole parallel beat.
            pending = self._triagers[0].snapshot_pending()
            triage_shards = [pending[idx::n_triagers] for idx in range(n_triagers)]
        for idx, triager in enumerate(self._triagers):
            if triage_shards is None:
                beat1.append(
                    (
                        f"triage[{idx}]",
                        (lambda t=triager, k=idx: t.triage_once(shard=(k, n_triagers))),
                    )
                )
            else:
                beat1.append(
                    (
                        f"triage[{idx}]",
                        (lambda t=triager, p=triage_shards[idx]: t.triage_once(pending=p)),
                    )
                )
        for divergent in self._divergents:
            beat1.append(("divergent", divergent.propose_once))
        self._run_parallel(beat1)

        # Generation phase, second wave: architect (runs after all triage completes -- must see this round's newly promoted from-triage proposals,
        # structural synthesis does not lag a round). When grouping is enabled, the entry point provides a coordinator: the entire pool classifies once,
        # then existing Architect workers pick up mutually exclusive groups, avoiding multiple workers each processing the entire pool.
        beat2: list[tuple[str, Callable[[], object]]] = [
            ("architect", architect.propose_once) for architect in self._architects
        ]
        self._run_parallel(beat2)

        # Owner consolidates independent PM and delivery routes, marks delivery overlap but preserves independent acceptance; Architect handles only non-PM coverage.
        # Owner is the sole admission authority; its failure must block this round, cannot be masked as success with an empty wait set.
        admitted: list[int] = []
        if self._owner is not None:
            try:
                outcome = self._owner.admit_once()
                admitted = [int(n) for n in (getattr(outcome, "admitted", None) or [])]
            except Exception as exc:  # noqa: BLE001
                print(
                    "[orchestrator] Owner admission failed; skipping it and continuing this round: "
                )
                traceback.print_exc()
                # Owner is the sole admission authority.  Continuing with an
                # empty wait set would incorrectly mark the round successful
                # and start the next user round with proposals still blocked.
                raise RoundDeliveryBlocked(
                    numbers=[], reason="owner-failed:admission did not complete"
                ) from exc

        # Spec-0050/T3: Wait for this round's admission ticket to reach final state. Empty list succeeds immediately. Deadlock is re-raised, does not start the next user round.
        self._await_round_delivery(numbers=admitted)

        # Orchestration repo integrity tripwire (Spec-0021, fail-closed).
        if self._integrity_guard is not None:
            self._integrity_guard()

        # After gate succeeds, origin/main = this round's sealed SHA (may still be user SHA if wait set was empty).
        return self._resolve_head(ref=self._initial_ref)

    def run(self, n_rounds: int, *, start_round: int = 1) -> list[str]:
        if n_rounds <= 0:
            raise ValueError(f"n_rounds must be positive: {n_rounds}")
        if not 1 <= start_round <= n_rounds:
            raise ValueError(f"start_round must be within 1..{n_rounds}: {start_round}")
        refs: list[str] = []
        # Starting cursor = main branch name; first run_round immediately resolves its HEAD SHA
        ref = self._initial_ref
        for i in range(start_round - 1, n_rounds):
            is_last = i == n_rounds - 1
            with bind_usage_context(round_no=i + 1):
                if self._on_round_start is not None:
                    self._on_round_start(i + 1)
                # Spec-0050/T3: In the final round, deliver=False. If the gate raises an error, this loop does not enter the next round.
                if getattr(self, "_recovery", None) is not None:
                    ref = self.run_round(ref, deliver=not is_last, round_no=i + 1)
                else:
                    ref = self.run_round(ref, deliver=not is_last)
                refs.append(ref)
                if self._on_round_end is not None:
                    self._on_round_end(i + 1, ref)
        return refs

    def _run_recoverable_round(self, *, ref: str, deliver: bool, round_no: int) -> str:
        """Spec-0064/T2: execute one round as a resumable stage DAG."""
        recovery = self._recovery
        assert recovery is not None
        saved_round = recovery.round_state(round_no=round_no)
        if saved_round is not None and saved_round.get("status") == "completed":
            sealed = str(saved_round.get("sealed_sha") or "")
            if not sealed:
                raise RecoveryConflictError(f"completed round {round_no} has no sealed SHA")
            return sealed

        if self._frozen_session_plan is not None:
            plan_payload = self._logical_plan(round_no=round_no)
            if saved_round is None:
                user_sha = self._resolve_head(ref=self._initial_ref)
                saved_round = recovery.freeze_round(
                    round_no=round_no, user_sha=user_sha, plan=plan_payload
                )
            else:
                user_sha = str(saved_round.get("user_sha") or "")
                if not user_sha or saved_round.get("plan") != plan_payload:
                    raise RecoveryConflictError("saved round differs from the frozen logical plan")
            planned = []
        elif saved_round is None:
            user_sha = self._resolve_head(ref=self._initial_ref)
            planned = list(self._session_plan())
            plan_payload = [
                {"persona": persona.to_dict(), "scenario": scenario.to_dict()}
                for persona, scenario in planned
            ]
            saved_round = recovery.freeze_round(
                round_no=round_no, user_sha=user_sha, plan=plan_payload
            )
        else:
            user_sha = str(saved_round.get("user_sha") or "")
            if not user_sha:
                raise RecoveryConflictError(f"round {round_no} has no frozen user SHA")
            planned = [
                (Persona.from_dict(item["persona"]), SeedScenario.from_dict(item["scenario"]))
                for item in saved_round.get("plan") or []
            ]
            plan_payload = None
        self._assert_commit_available(user_sha)
        self._mark_recovery_stage(
            round_no=round_no,
            stage="round_started",
            input_value={"user_sha": user_sha, "plan": saved_round.get("plan") or []},
        )
        self._run_recovery_users(
            round_no=round_no,
            user_sha=user_sha,
            planned=planned,
            bindings=plan_payload if self._frozen_session_plan is not None else None,
        )

        if self._round_assessment is not None:
            self._round_assessment(
                round_no=round_no, user_sha=user_sha, bindings=plan_payload, recovery=recovery
            )
        assert self._feedback_pipeline is not None
        if deliver:
            return self._feedback_pipeline.run(round_no=round_no, user_sha=user_sha)
        return self._feedback_pipeline.seal(
            round_no=round_no,
            user_sha=user_sha,
            dependencies=("objective_grading",)
            if self._round_assessment is not None
            else ("users",),
        )

    def _logical_plan(self, *, round_no: int) -> list[dict[str, Any]]:
        """Spec-0073/T4: use the same immutable binding for round, key and input."""
        assert self._frozen_session_plan is not None
        plan = json.loads(json.dumps(list(self._frozen_session_plan(round_no))))
        keys = {"round_no", "slot", "persona_id", "task_id", "task_digest", "interaction"}
        # Spec-0080/T2: slot distinguishes sessions even for identical persona/task pairs.
        for index, binding in enumerate(plan):
            if (
                not isinstance(binding, dict)
                or set(binding) != keys
                or type(binding["round_no"]) is not int
                or type(binding["slot"]) is not int
                or binding["round_no"] != round_no
                or binding["slot"] != index
                or not all(
                    isinstance(binding[key], str) and binding[key]
                    for key in ("persona_id", "task_id", "task_digest", "interaction")
                )
                or binding["interaction"] not in {"direct", "simulated_user"}
                or self._task_kinds.get(binding["task_id"])
                not in {"ordinary", "swebench", "benchmark"}
            ):
                raise RecoveryConflictError("invalid frozen logical session binding")
        return plan

    def _resolve_logical_session(self, binding: Mapping[str, Any]) -> SessionPair:
        assert self._resolve_session is not None
        persona, scenario = self._resolve_session(MappingProxyType(dict(binding)))
        params = scenario.workspace.params if scenario.workspace is not None else {}
        if (
            persona.identity != binding["persona_id"]
            or any(
                params.get(key) != binding[key] for key in ("task_id", "task_digest", "interaction")
            )
            or params.get("task_kind") != self._task_kinds[binding["task_id"]]
        ):
            raise RecoveryConflictError("resolved session does not match its frozen binding")
        return persona, scenario

    def _run_recovery_users(
        self,
        *,
        round_no: int,
        user_sha: str,
        planned: Sequence[SessionPair],
        bindings: Sequence[Mapping[str, Any]] | None,
    ) -> None:
        recovery = self._require_recovery()
        if (
            recovery.stage_status(round_no=round_no, stage="users") == "completed"
            and bindings is None
        ):
            return
        if not planned and not bindings:
            self._mark_recovery_stage(
                round_no=round_no,
                stage="users",
                input_value={"sessions": []},
                dependencies=("round_started",),
            )
            return
        failures: list[str] = []
        recovery_lock = threading.RLock()
        pending = []
        run_id = str(recovery.snapshot()["identity"]["run_id"])
        pairs = [(None, None)] * len(bindings) if bindings is not None else planned
        for index, (persona, scenario) in enumerate(pairs):
            binding = dict(bindings[index]) if bindings is not None else None
            if binding is not None:
                key = operation_key(run_id, "users", binding)
                input_value = {"binding": binding, "user_sha": user_sha}
            else:
                key = operation_key(round_no, "users", index, persona.to_dict(), scenario.to_dict())
                input_value = {
                    "index": index,
                    "persona": persona.to_dict(),
                    "scenario": scenario.to_dict(),
                    "user_sha": user_sha,
                }
            # The frozen round already fixes every slot/key. A queued future is
            # not running until it acquires a worker (Spec-0073/T4 live validation).
            pending.append((key, persona, scenario, binding, input_value))

        def run_one(item) -> None:
            key, persona, scenario, binding, input_value = item
            with recovery_lock:
                unit = recovery.begin_unit(
                    round_no=round_no,
                    stage="users",
                    key=key,
                    input_value=input_value,
                    expected_postconditions={"completed": True},
                    dependencies=("round_started",),
                )
            if unit.get("status") == "completed" and binding is None:
                return
            workspace_dir: WorkspaceRuntime | None = None
            context = {"session_id": key, "round_no": round_no, "run_id": run_id}
            if binding is not None:
                context.update(
                    persona_id=binding["persona_id"],
                    task_id=binding["task_id"],
                    task_digest=binding["task_digest"],
                    task_kind=self._task_kinds[binding["task_id"]],
                    interaction_mode=binding["interaction"],
                    slot=binding["slot"],
                    instance_id=binding["task_id"],
                    harness_sha=user_sha,
                    attempt=int(unit["attempt"]),
                )
            with bind_usage_context(**context):
                try:
                    expected = bound_session_provenance()
                    load_completed = getattr(self._run_session, "load_completed_session", None)
                    existing = load_completed(key) if callable(load_completed) else None
                    if existing is not None:
                        if binding is not None:
                            if not isinstance(existing, Session) or existing.session_id != key:
                                raise RecoveryConflictError(
                                    "cached result is not the bound session"
                                )
                            validate_session_provenance(existing, expected)
                        result = existing
                        if binding is not None:
                            persona, scenario = existing.persona, existing.scenario
                    else:
                        if binding is not None and unit.get("status") == "completed":
                            raise RecoveryConflictError(
                                "completed unit has no authoritative session"
                            )
                        if binding is not None:
                            persona, scenario = self._resolve_logical_session(binding)
                        if self._on_session_event is not None:
                            self._on_session_event("running", persona, scenario, None)
                        if scenario.workspace is not None:
                            workspace_dir = as_runtime(
                                materialize_workspace(scenario.workspace), owns_tmp=True
                            )
                            ensure_deps(workspace_dir, scenario.workspace)
                        else:
                            workspace_dir = make_empty_runtime()
                        harness = self._launcher.launch(user_sha, workspace_dir=workspace_dir)
                        result = self._run_session(
                            persona, scenario, harness, workspace_dir=workspace_dir
                        )
                        if binding is not None:
                            if not isinstance(result, Session) or result.session_id != key:
                                raise RecoveryConflictError(
                                    "runner returned a different session identity"
                                )
                            validate_session_provenance(result, expected)
                    with recovery_lock:
                        if unit.get("status") != "completed":
                            recovery.save_output(
                                round_no=round_no,
                                stage="users",
                                key=key,
                                output=_result_payload(result),
                            )
                            recovery.complete_unit(
                                round_no=round_no,
                                stage="users",
                                key=key,
                                observed_postconditions={"completed": True, "session_id": key},
                            )
                    if self._on_session_event is not None:
                        self._on_session_event("completed", persona, scenario, result)
                except Exception as exc:  # noqa: BLE001
                    with recovery_lock:
                        if unit.get("status") != "completed":
                            recovery.fail_unit(
                                round_no=round_no,
                                stage="users",
                                key=key,
                                error=f"{type(exc).__name__}: {exc}",
                            )
                        failures.append(key)
                    if self._on_session_event is not None:
                        if persona is None:
                            persona = Persona(binding["persona_id"], "", "", "", "")
                            scenario = SeedScenario("")
                        self._on_session_event("failed", persona, scenario, None)
                    traceback.print_exc()
                finally:
                    if workspace_dir is not None:
                        cleanup_workspace(workspace_dir.close, stage="close", identity=key)

        if pending:
            with ThreadPoolExecutor(
                max_workers=min(len(pending), self._max_parallel_users)
            ) as pool:
                futures = [pool.submit(run_one, item) for item in pending]
                for future in futures:
                    future.result()
        if failures:
            raise RoundDeliveryBlocked(numbers=[], reason="user-sessions-incomplete")
        recovery.complete_stage(round_no=round_no, stage="users")

    def _mark_recovery_stage(
        self,
        *,
        round_no: int,
        stage: str,
        input_value: Any,
        dependencies: Sequence[str] = (),
    ) -> None:
        assert self._feedback_pipeline is not None
        self._feedback_pipeline.mark_stage(
            round_no=round_no, stage=stage, input_value=input_value, dependencies=dependencies
        )

    def _require_recovery(self) -> RecoveryStore:
        if self._recovery is None:
            raise RuntimeError("recovery store is not configured")
        return self._recovery

    def _assert_commit_available(self, sha: str) -> None:
        result = subprocess.run(
            ["git", "-C", self._harness_repo, "cat-file", "-e", f"{sha}^{{commit}}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RecoveryConflictError(f"frozen user SHA is unavailable: {sha}")

    def _assert_descendant(self, *, ancestor: str, descendant: str) -> None:
        result = subprocess.run(
            ["git", "-C", self._harness_repo, "merge-base", "--is-ancestor", ancestor, descendant],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RecoveryConflictError(
                f"remote main {descendant} does not descend from frozen user SHA {ancestor}"
            )

    def _await_round_delivery(self, *, numbers: list[int]) -> None:
        """Wait for this round's admitted issues; no-op when the wait set is empty."""
        if self._wait_delivery is not None:
            self._wait_delivery(numbers=numbers)
            return
        fetch = self._fetch_issue
        if fetch is None:
            if numbers:
                raise RuntimeError(
                    "round delivery wait needs fetch_issue when Owner admitted tickets"
                )
            return
        wait_round_delivery(numbers=numbers, fetch_issue=fetch)

    def _session_plan(self) -> Sequence[SessionPair]:
        """List of (persona, scenario) pairs to run this round; when fixed_set is callable, re-sample each round."""
        plan = self._fixed_set
        return plan() if callable(plan) else plan

    @staticmethod
    def _run_parallel(jobs: list[tuple[str, Callable[[], object]]]) -> None:
        """Run one generation stage in a thread pool; log and skip individual failures.

        The outputs are non-binding proposals, so losing one generator does not invalidate the round.
        """
        if not jobs:
            return
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = {pool.submit(contextvars.copy_context().run, fn): name for name, fn in jobs}
            for fut in as_completed(futures):
                name = futures[fut]
                try:
                    fut.result()
                except Exception:  # noqa: BLE001
                    print(f"[orchestrator] {name} failed; skipping it and continuing this round: ")
                    traceback.print_exc()

    def _resolve_head(self, *, ref: str) -> str:
        """Resolve a harness repo ref to its current HEAD commit SHA; trunk always uses main.

        An invalid ref raises RuntimeError. Spec-0033/T3: fetch origin first and **prefer origin/<ref>**.
        Since spec-0032, Gitea performs server-side merges into main while local main remains at the seed.
        Fetching also retrieves the commit objects required for the launcher's checkout by SHA.
        Fall back to local <ref> when there is no origin or usable remote-tracking ref. If origin/<ref>
        already exists but fetch fails, reject that potentially stale cursor to avoid silently repeating
        an earlier round.
        """
        remotes = subprocess.run(
            ["git", "-C", self._harness_repo, "remote"], capture_output=True, text=True
        ).stdout.split()
        fetch_failed = False
        if "origin" in remotes:
            fetched = subprocess.run(
                ["git", "-C", self._harness_repo, "fetch", "origin", ref],
                capture_output=True,
                text=True,
            )
            if fetched.returncode != 0:
                fetch_failed = True
                print(
                    f"[orchestrator] fetch origin {ref} failed (the cursor may be stale): "
                    f"{fetched.stderr.strip()[:200]}"
                )
        for candidate in (f"refs/remotes/origin/{ref}", ref):
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    self._harness_repo,
                    "rev-parse",
                    "--verify",
                    f"{candidate}^{{commit}}",
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                if fetch_failed and candidate.startswith("refs/remotes/origin/"):
                    raise RuntimeError(
                        f"origin/{ref} fetch failed; refusing to use a potentially stale remote cursor"
                    )
                return result.stdout.strip()
        raise RuntimeError(f"Failed to resolve main ref {ref!r}: {result.stderr[:200]}")
