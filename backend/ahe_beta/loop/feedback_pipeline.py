"""Spec-0079/T3: one recoverable feedback and delivery cycle.

The caller freezes the round and completes its explicit prerequisite. This
component owns demand, admission, delivery reconciliation and the original
round seal contract, independently of any archive or execution provider.
"""

from __future__ import annotations

import dataclasses
import traceback
from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext
from typing import Any

from ahe_beta.demand.source import bind_harness_source
from ahe_beta.loop.recovery import RecoveryConflictError, RecoveryStore, operation_key
from ahe_beta.loop.round_gate import RoundDeliveryBlocked, classify_issue, wait_round_delivery
from ahe_beta.models import OpenIssue
from ahe_beta.usage import bind_usage_context


def _result_payload(value: Any) -> Any:
    """Convert role/session returns into deterministic JSON receipts."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _result_payload(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _result_payload(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_result_payload(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    for method_name in ("model_dump", "to_dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            return _result_payload(method())
    return {"type": f"{type(value).__module__}.{type(value).__qualname__}"}


def _issue_labels(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        str(item.get("name") or "") if isinstance(item, Mapping) else str(item) for item in value
    ]


class FeedbackPipeline:
    """Execute the concrete feedback stages using an explicitly scoped ledger."""

    def __init__(
        self,
        *,
        recovery: RecoveryStore,
        resolve_head: Callable[[], str],
        assert_descendant: Callable[..., None],
        triagers: Sequence[Any] = (),
        architects: Sequence[Any] = (),
        divergents: Sequence[Any] = (),
        owner: Any = None,
        integrity_guard: Callable[[], None] | None = None,
        fetch_issue: Callable[[int], Mapping[str, Any]] | None = None,
        wait_delivery: Callable[..., None] | None = None,
        prerequisite: str = "users",
        operation_namespace: str | None = None,
        grounding_repo: str | None = None,
    ) -> None:
        if prerequisite not in {"users", "feedback_imported", "objective_grading"}:
            raise ValueError("unsupported feedback prerequisite")
        if prerequisite == "feedback_imported" and not operation_namespace:
            raise ValueError("imported feedback requires an operation namespace")
        if operation_namespace is not None and not operation_namespace.strip():
            raise ValueError("operation namespace must be nonempty")
        self._recovery = recovery
        self._resolve_head = resolve_head
        self._assert_descendant = assert_descendant
        self._triagers = list(triagers)
        self._architects = list(architects)
        self._divergents = list(divergents)
        self._owner = owner
        self._integrity_guard = integrity_guard
        self._fetch_issue = fetch_issue
        self._wait_delivery = wait_delivery
        self._prerequisite = prerequisite
        self._operation_namespace = operation_namespace
        self._grounding_repo = grounding_repo
        self.bind_roles()

    def bind_roles(self) -> None:
        """Activate this ledger for roles reused sequentially across feedback cycles."""
        for role in [*self._triagers, *self._divergents]:
            bind_dependency = getattr(role, "bind_feedback_dependency", None)
            if callable(bind_dependency):
                bind_dependency(self._prerequisite)
        for role in [*self._triagers, *self._divergents, *self._architects, self._owner]:
            bind_recovery = getattr(role, "bind_recovery", None)
            if callable(bind_recovery):
                bind_recovery(self._recovery)

    def operation_key(self, *parts: object) -> str:
        """Preserve ordinary keys; isolate bootstrap's external side effects."""
        if self._operation_namespace is not None:
            return operation_key(self._operation_namespace, *parts)
        return operation_key(*parts)

    def run(self, *, round_no: int, user_sha: str) -> str:
        """Process frozen feedback, await admitted tickets and return sealed SHA."""
        saved = self._recovery.round_state(round_no=round_no)
        if saved is None or saved.get("user_sha") != user_sha:
            raise RecoveryConflictError("feedback round has no matching frozen input SHA")
        if saved.get("status") == "completed":
            sealed = str(saved.get("sealed_sha") or "")
            if not sealed:
                raise RecoveryConflictError("completed feedback round has no sealed SHA")
            return sealed
        self.bind_roles()
        with (
            bind_harness_source(self._grounding_repo, user_sha),
            bind_usage_context(round_no=round_no, harness_sha=user_sha),
        ):
            self._run_recovery_demand(round_no=round_no)
            admitted = self._run_recovery_owner(round_no=round_no)
            self._run_recovery_delivery(round_no=round_no, admitted=admitted)
            return self.seal(round_no=round_no, user_sha=user_sha, dependencies=("delivery_wait",))

    def seal(
        self, *, round_no: int, user_sha: str, dependencies: Sequence[str] = ("users",)
    ) -> str:
        """Keep the ordinary round_sealed key, input and guard ordering intact."""
        if self._integrity_guard is not None:
            self._integrity_guard()
        sealed_sha = self._resolve_head()
        self._assert_descendant(ancestor=user_sha, descendant=sealed_sha)
        self.mark_stage(
            round_no=round_no,
            stage="round_sealed",
            input_value={"user_sha": user_sha, "sealed_sha": sealed_sha},
            dependencies=dependencies,
        )
        self._recovery.seal_round(round_no=round_no, sealed_sha=sealed_sha)
        return sealed_sha

    def mark_stage(
        self, *, round_no: int, stage: str, input_value: Any, dependencies: Sequence[str] = ()
    ) -> None:
        """Persist a concrete stage marker using the selected operation scope."""
        self._mark_recovery_stage(
            round_no=round_no, stage=stage, input_value=input_value, dependencies=dependencies
        )

    def _require_recovery(self) -> RecoveryStore:
        return self._recovery

    def _run_recovery_demand(self, *, round_no: int) -> None:
        recovery = self._require_recovery()
        triage_jobs: list[tuple[str, str, Any, Callable[[], object]]] = []
        n_triagers = len(self._triagers)
        pending_shards: list[list[OpenIssue]] | None = None
        if n_triagers and recovery.stage_status(round_no=round_no, stage="triage") == "pending":
            if hasattr(self._triagers[0], "snapshot_pending"):
                pending = self._triagers[0].snapshot_pending()
                pending_shards = [pending[index::n_triagers] for index in range(n_triagers)]
        for index, triager in enumerate(self._triagers):
            key = self.operation_key(round_no, "triage", index)
            existing = recovery.unit(round_no=round_no, stage="triage", key=key)
            if existing is not None:
                triage_input = existing["input"]
            elif pending_shards is not None:
                triage_input = {
                    "worker": index,
                    "mode": "snapshot",
                    "pending": [issue.to_dict() for issue in pending_shards[index]],
                }
            else:
                triage_input = {
                    "worker": index,
                    "mode": "shard",
                    "shard": [index, n_triagers],
                }
            if triage_input["mode"] == "snapshot":
                frozen_pending = [OpenIssue.from_dict(item) for item in triage_input["pending"]]

                def call(t=triager, p=frozen_pending):
                    return t.triage_once(pending=p)

            else:
                shard = tuple(triage_input["shard"])

                def call(t=triager, s=shard):
                    return t.triage_once(shard=s)

            triage_jobs.append((f"triage[{index}]", key, triage_input, call))
        self._run_recovery_jobs(
            round_no=round_no,
            stage="triage",
            jobs=triage_jobs,
            dependencies=(self._prerequisite,),
        )

        divergent_jobs = [
            (
                f"divergent[{index}]",
                self.operation_key(round_no, "divergent", index),
                {"worker": index},
                divergent.propose_once,
            )
            for index, divergent in enumerate(self._divergents)
        ]
        self._run_recovery_jobs(
            round_no=round_no,
            stage="divergent",
            jobs=divergent_jobs,
            dependencies=(self._prerequisite,),
        )

        architect_jobs = [
            (
                f"architect[{index}]",
                self.operation_key(round_no, "architect", index),
                {"worker": index},
                architect.propose_once,
            )
            for index, architect in enumerate(self._architects)
        ]
        self._run_recovery_jobs(
            round_no=round_no,
            stage="architect",
            jobs=architect_jobs,
            dependencies=("triage",),
        )

    def _run_recovery_owner(self, *, round_no: int) -> list[int]:
        recovery = self._require_recovery()
        round_state = recovery.round_state(round_no=round_no) or {}
        if recovery.stage_status(round_no=round_no, stage="owner") == "completed":
            return [int(number) for number in round_state.get("admitted_issue_ids") or []]
        if self._owner is None:
            recovery.set_admitted_issue_ids(round_no=round_no, issue_ids=[])
            self._mark_recovery_stage(
                round_no=round_no,
                stage="owner",
                input_value={"owner": None},
                dependencies=("divergent", "architect"),
            )
            return []
        key = self.operation_key(round_no, "owner")
        unit = recovery.begin_unit(
            round_no=round_no,
            stage="owner",
            key=key,
            input_value={"round": round_no},
            expected_postconditions={"completed": True},
            dependencies=("divergent", "architect"),
        )
        if unit.get("status") == "completed":
            return [int(number) for number in round_state.get("admitted_issue_ids") or []]
        try:
            # Ordinary Owner historically runs without an outer operation key.
            # Bootstrap must scope its own nested model/forge operations too.
            context = (
                bind_usage_context(operation=key, role="owner", round_no=round_no)
                if self._operation_namespace is not None
                else nullcontext()
            )
            with context:
                outcome = self._owner.admit_once()
            admitted = sorted(set(int(n) for n in (getattr(outcome, "admitted", None) or [])))
            recovery.save_output(
                round_no=round_no,
                stage="owner",
                key=key,
                output=_result_payload(outcome),
            )
            recovery.set_admitted_issue_ids(round_no=round_no, issue_ids=admitted)
            recovery.complete_unit(
                round_no=round_no,
                stage="owner",
                key=key,
                observed_postconditions={"completed": True},
            )
            recovery.complete_stage(round_no=round_no, stage="owner")
            return admitted
        except Exception as exc:  # noqa: BLE001
            recovery.fail_unit(
                round_no=round_no,
                stage="owner",
                key=key,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise RoundDeliveryBlocked(
                numbers=[], reason="owner-failed:admission did not complete"
            ) from exc

    def _run_recovery_delivery(self, *, round_no: int, admitted: Sequence[int]) -> None:
        recovery = self._require_recovery()
        if recovery.stage_status(round_no=round_no, stage="delivery_wait") == "completed":
            return
        if not admitted:
            self._mark_recovery_stage(
                round_no=round_no,
                stage="delivery_wait",
                input_value={"issues": []},
                dependencies=("owner",),
            )
            return
        inflight: list[tuple[int, str]] = []
        blocked_numbers: list[int] = []
        for number in admitted:
            key = self.operation_key(round_no, "delivery", int(number))
            unit = recovery.begin_unit(
                round_no=round_no,
                stage="delivery_wait",
                key=key,
                input_value={"issue": int(number)},
                expected_postconditions={"classification": "done"},
                dependencies=("owner",),
            )
            if unit.get("status") == "completed":
                continue
            if self._fetch_issue is not None:
                snapshot = self._fetch_issue(int(number))
                classification = classify_issue(
                    state=str(snapshot.get("state") or ""),
                    labels=_issue_labels(snapshot.get("labels")),
                )
                if classification == "done":
                    recovery.complete_unit(
                        round_no=round_no,
                        stage="delivery_wait",
                        key=key,
                        observed_postconditions={"classification": "done", "issue": snapshot},
                    )
                    continue
                if classification == "blocked":
                    recovery.fail_unit(
                        round_no=round_no,
                        stage="delivery_wait",
                        key=key,
                        error="delivery terminal failure",
                        blocked=True,
                    )
                    blocked_numbers.append(int(number))
                    continue
            inflight.append((int(number), key))
        # Reconcile the complete admitted set before failing closed.  Raising
        # on the first terminal failure left later merged issues stale in the
        # durable ledger and made every subsequent resume stop at the same
        # ticket without projecting forge truth for the rest of the round.
        if blocked_numbers:
            raise RoundDeliveryBlocked(numbers=blocked_numbers, reason="delivery-failed")
        if inflight:
            try:
                self._await_round_delivery(numbers=[number for number, _ in inflight])
            except RoundDeliveryBlocked as exc:
                affected = set(int(number) for number in exc.numbers)
                for number, key in inflight:
                    if self._fetch_issue is not None:
                        snapshot = self._fetch_issue(number)
                        classification = classify_issue(
                            state=str(snapshot.get("state") or ""),
                            labels=_issue_labels(snapshot.get("labels")),
                        )
                        if classification == "done":
                            recovery.complete_unit(
                                round_no=round_no,
                                stage="delivery_wait",
                                key=key,
                                observed_postconditions={
                                    "classification": "done",
                                    "issue": snapshot,
                                },
                            )
                            continue
                        if classification == "blocked":
                            recovery.fail_unit(
                                round_no=round_no,
                                stage="delivery_wait",
                                key=key,
                                error=f"delivery terminal failure for issue #{number}",
                                blocked=True,
                            )
                            affected.add(number)
                            continue
                    # The gate reports only the tickets responsible for the
                    # stop.  Leave unrelated in-flight units retryable instead
                    # of falsely stamping the whole original wait set failed.
                    if number in affected:
                        recovery.fail_unit(
                            round_no=round_no,
                            stage="delivery_wait",
                            key=key,
                            error=f"delivery {exc.reason} for issue #{number}",
                            blocked=exc.reason != "timeout",
                        )
                raise
            for number, key in inflight:
                observed: dict[str, Any] = {"classification": "done"}
                if self._fetch_issue is not None:
                    snapshot = self._fetch_issue(number)
                    classification = classify_issue(
                        state=str(snapshot.get("state") or ""),
                        labels=_issue_labels(snapshot.get("labels")),
                    )
                    if classification != "done":
                        recovery.fail_unit(
                            round_no=round_no,
                            stage="delivery_wait",
                            key=key,
                            error=f"delivery wait returned before issue #{number} was done",
                            blocked=True,
                        )
                        raise RoundDeliveryBlocked(
                            numbers=[number], reason="postcondition-mismatch"
                        )
                    observed["issue"] = snapshot
                recovery.complete_unit(
                    round_no=round_no,
                    stage="delivery_wait",
                    key=key,
                    observed_postconditions=observed,
                )
        recovery.complete_stage(round_no=round_no, stage="delivery_wait")

    def _run_recovery_jobs(
        self,
        *,
        round_no: int,
        stage: str,
        jobs: Sequence[tuple[str, str, Any, Callable[[], object]]],
        dependencies: Sequence[str],
    ) -> None:
        recovery = self._require_recovery()
        if recovery.stage_status(round_no=round_no, stage=stage) == "completed":
            return
        if not jobs:
            self._mark_recovery_stage(
                round_no=round_no,
                stage=stage,
                input_value={"jobs": []},
                dependencies=dependencies,
            )
            return
        failures: list[str] = []
        for name, key, input_value, call in jobs:
            unit = recovery.begin_unit(
                round_no=round_no,
                stage=stage,
                key=key,
                input_value=input_value,
                expected_postconditions={"completed": True},
                dependencies=dependencies,
            )
            if unit.get("status") == "completed":
                continue
            try:
                with bind_usage_context(operation=key, role=stage, round_no=round_no):
                    result = call()
                # A role can persist a failed inner unit and return its failure
                # outcome. Keep its outer worker retryable so resume re-enters
                # the role and reconciles saved model output / side effects.
                failed = getattr(result, "failed", None)
                if isinstance(failed, Mapping) and failed:
                    raise RoundDeliveryBlocked(numbers=[], reason=f"{stage}-incomplete")
                recovery.save_output(
                    round_no=round_no,
                    stage=stage,
                    key=key,
                    output=_result_payload(result),
                )
                recovery.complete_unit(
                    round_no=round_no,
                    stage=stage,
                    key=key,
                    observed_postconditions={"completed": True},
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[orchestrator] {name} 异常，恢复账本保留该工作项：")
                traceback.print_exc()
                recovery.fail_unit(
                    round_no=round_no,
                    stage=stage,
                    key=key,
                    error=f"{type(exc).__name__}: {exc}",
                )
                failures.append(key)
        if failures:
            raise RoundDeliveryBlocked(numbers=[], reason=f"{stage}-incomplete")
        recovery.complete_stage(round_no=round_no, stage=stage)

    def _mark_recovery_stage(
        self,
        *,
        round_no: int,
        stage: str,
        input_value: Any,
        dependencies: Sequence[str] = (),
    ) -> None:
        recovery = self._require_recovery()
        key = self.operation_key(round_no, stage, "stage-marker")
        unit = recovery.begin_unit(
            round_no=round_no,
            stage=stage,
            key=key,
            input_value=input_value,
            expected_postconditions={"completed": True},
            dependencies=dependencies,
        )
        if unit.get("status") != "completed":
            recovery.complete_unit(
                round_no=round_no,
                stage=stage,
                key=key,
                observed_postconditions={"completed": True},
            )
        recovery.complete_stage(round_no=round_no, stage=stage)

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
