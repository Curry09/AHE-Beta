"""Connect the spec-0005 simulated user to the spec-0003/0007 evolution loop.

Orchestrator calls run_session_fn(persona, scenario, harness), passing through its return value;
the implementation owns persistence and submission. This module builds that function around
sim.loop.run_session, using a real persona LLM and harness. Its on_turn callback supplies live
turn updates to the dashboard. At session end, it submits issue_artifact to the tracker,
converts SessionResult to models.Session, and saves it to the store.
The simulation uses a 9-dimensional persona. The caller derives the display-side models.Persona
and matches the two representations by identity before invoking the session.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import uuid
from collections.abc import Callable
from pathlib import Path

from ahe_beta.demand.issue_schema import NEEDS_TRIAGE, round_label
from ahe_beta.harness.connector import HarnessConnector
from ahe_beta.harness.interface import HarnessInterface
from ahe_beta.loop.recovery import operation_key
from ahe_beta.models import (
    FeelingScore,
    IssueDraft,
    IssueRef,
    Persona,
    PersonaCallTrace,
    SeedScenario,
    Session,
    SimTrace,
    SimTurn,
    Transcript,
    Turn,
    bound_session_provenance,
    validate_session_provenance,
)
from ahe_beta.tracker.base import IssueTracker
from ahe_beta.usage import bind_usage_context, current_usage_context
from ahe_beta.user.patches import preserve_prediction
from ahe_beta.user.session_store import SessionStore
from ahe_beta.user.sim.deps import ensure_deps
from ahe_beta.user.sim.dimensions import Persona as SimPersona
from ahe_beta.user.sim.feeling import experience_feedback
from ahe_beta.user.sim.loop import SessionResult
from ahe_beta.user.sim.loop import run_session as sim_run_session
from ahe_beta.user.sim.persona_client import PersonaClient
from ahe_beta.user.sim.runtime import (
    CollectionSourceLost,
    InvalidWorkspaceArtifact,
    ReviewSnapshot,
    Workspace,
    as_runtime,
    capture_review_snapshot,
    cleanup_workspace,
    utc_now,
)
from ahe_beta.user.sim.workspace import materialize as materialize_workspace

# Observation callback: (identity, sim_persona, in-progress/final SessionResult, running, *, session_id) -> None.
# session_id is only included when wrapping up (running=False) after the session is persisted to store, for dashboard archival to correlate full session context.
SimTurnHook = Callable[..., None]


class EnvironmentInfrastructureError(RuntimeError):
    """A completed Actor awaits infrastructure capture; no feedback may be published."""


def _observation_binding(harness) -> dict | None:
    source = getattr(harness, "observation_source", None)
    if source is None:
        return None
    return {
        "directory": source.directory,
        "container_id": source.container_id,
        "version": dict(source.version),
        "expected": source.expected,
        "run_id": source.run_id,
    }


def _actor_checkpoint_payload(
    *, mode, persona, scenario, execution_contract, workspace, actor, observation
):
    binding = getattr(workspace, "collection_binding", None)
    return {
        "mode": mode,
        "persona": persona.to_dict(),
        "scenario": scenario.to_dict(),
        "execution_contract": execution_contract,
        "actor": actor,
        "collection_binding": binding() if callable(binding) else None,
        "workspace_present": workspace is not None,
        "workspace_evidence": dict(getattr(workspace, "evidence", {}) or {}),
        "observation": observation,
    }


def _capture_completed_actor(*, packet, store, session_id, provenance, observation_root, workspace):
    """Reuse the original attempt or committed frozen bytes, never instantiate an Actor."""
    payload = packet["payload"]
    scenario = SeedScenario.from_dict(payload["scenario"])
    if provenance and (
        payload["mode"] != provenance["interaction"]
        or payload["persona"]["identity"] != provenance["persona_id"]
        or scenario.workspace is None
        or any(
            scenario.workspace.params.get(key) != provenance[key]
            for key in ("task_id", "task_digest", "task_kind", "interaction")
        )
    ):
        raise EnvironmentInfrastructureError("Actor checkpoint logical task binding differs")
    evidence = dict(payload["workspace_evidence"])
    binding = payload.get("collection_binding")
    captured = store.load_actor_capture(session_id, expected_provenance=provenance)
    if captured is not None:
        value = captured["payload"]
        snapshot = ReviewSnapshot(
            {name: base64.b64decode(body, validate=True) for name, body in value["files"].items()},
            patch=value["patch"],
            omissions=value["omissions"],
        )
        evidence.update(value["evidence"])
    else:

        def save_capture(snapshot):
            store.stage_actor_capture(
                session_id,
                provenance=provenance,
                payload={
                    "files": {
                        name: base64.b64encode(body).decode("ascii")
                        for name, body in snapshot._files.items()
                    },
                    "patch": snapshot._patch,
                    "omissions": snapshot.evidence["omissions"],
                    "evidence": dict(evidence),
                },
            )

        try:
            if workspace is None and payload["workspace_present"]:
                if binding is None:
                    raise EnvironmentInfrastructureError(
                        "Completed Actor has no recoverable task environment"
                    )
                from ahe_beta.user.sim.seed_source import resume_collection

                workspace = resume_collection(
                    binding=binding,
                    expected_provenance={**provenance, "session_id": session_id},
                    spec=scenario.workspace,
                )
                workspace.evidence.update(evidence)
            if workspace is not None:
                workspace.evidence["collection_pending"] = True
            snapshot = _freeze_actor_outputs(
                workspace=workspace,
                scenario=scenario,
                store=store,
                session_id=session_id,
                provenance=provenance,
                evidence=evidence,
                capture_complete=save_capture,
            )
        except Exception as error:
            store.record_actor_capture_failure(
                session_id, provenance=provenance, evidence=evidence, error=type(error).__name__
            )
            raise
    descriptor = payload.get("observation")
    if descriptor is not None:
        from ahe_beta.observations.publication import ObservationSource, verify_published

        source = ObservationSource(
            **{key: descriptor[key] for key in ("directory", "container_id", "version", "expected")}
        )
        source.run_id = descriptor["run_id"]
        previous = (
            verify_published(
                root=observation_root,
                session_id=session_id,
                run_id=source.run_id,
                version=source.version,
            )
            if source.expected
            else None
        )
        evidence["observation"] = previous or source.collect(
            root=observation_root, session_id=session_id
        )
        if evidence["observation"].get("status") == "unavailable":
            raise EnvironmentInfrastructureError(
                "Completed Actor observation transport is unavailable"
            )
        if source.expected:
            verified = verify_published(
                root=observation_root,
                session_id=session_id,
                run_id=source.run_id,
                version=source.version,
            )
            if verified is None:
                raise EnvironmentInfrastructureError("Published Actor observation is missing")
            evidence["observation"] = verified
    # These flags describe evidence collection, not the later resource release.
    evidence.pop("collection_pending", None)
    evidence.pop("retained_for_observations", None)
    return snapshot, evidence


def _audit_events(
    *,
    workspace_evidence: dict,
    request_outcomes: list[dict],
) -> list[dict]:
    """Build the minimal ordered evidence timeline retained with a session."""
    events: list[dict] = []

    def append(event: str, at: str, data: dict) -> None:
        events.append({"seq": len(events) + 1, "event": event, "at": at, "data": data})

    if workspace_evidence.get("kind") == "docker" and workspace_evidence.get("started_at"):
        append(
            "container_started",
            str(workspace_evidence["started_at"]),
            {
                "container_id": workspace_evidence.get("container_id"),
                "container_name": workspace_evidence.get("container_name"),
                "image_digest": workspace_evidence.get("image_digest"),
            },
        )
    for row in request_outcomes:
        append(
            "harness_request_terminal",
            str(row.get("finished_at") or row.get("started_at") or ""),
            {key: row.get(key) for key in ("request_id", "status", "started_at")},
        )
    if workspace_evidence.get("diff_sha256"):
        append(
            "patch_exported",
            str(workspace_evidence.get("patch_exported_at") or ""),
            {
                "diff_sha256": workspace_evidence.get("diff_sha256"),
                "diff_bytes": workspace_evidence.get("diff_bytes"),
            },
        )
    if workspace_evidence.get("kind") == "docker" and workspace_evidence.get("closed_at"):
        append(
            "container_stopped",
            str(workspace_evidence["closed_at"]),
            {"container_id": workspace_evidence.get("container_id")},
        )
    return events


def _freeze_prediction_base(workspace: Workspace) -> None:
    """Freeze before any Harness tools, without extending legacy runtime protocols."""
    freeze = getattr(workspace, "freeze_patch_base", None)
    if not callable(freeze):
        return
    try:
        freeze()
    except Exception as exc:  # noqa: BLE001 - still retain user interaction and failure evidence
        workspace.evidence["diff_base_error"] = type(exc).__name__


def _collect_evaluation_artifacts(*, workspace, scenario, store, session_id, provenance, evidence):
    """Spec-0084/T2: finalize once even when no declared output files exist."""
    declarations = (scenario.workspace.params if scenario.workspace else {}).get(
        "evaluation_artifacts", []
    )
    from ahe_beta.evaluation.artifacts import collect_session_artifacts

    class CaptureBoundary:
        def __getattr__(self, name):
            return getattr(workspace, name)

        def quiesce(self):
            evidence["actor_freeze"] = {"status": "pending"}
            stop = getattr(workspace, "quiesce", None)
            if callable(stop):
                stop()

        def finalize_task(self):
            finalize = getattr(workspace, "finalize_task", None)
            if callable(finalize):
                finalize()
            evidence["actor_freeze"] = {"status": "frozen", "at": utc_now()}

    receipt = collect_session_artifacts(
        workspace=CaptureBoundary(),
        sessions_root=store.root,
        session_id=session_id,
        provenance=provenance or {},
        declarations=declarations,
    )
    if evidence.get("actor_freeze", {}).get("status") != "frozen":
        evidence["actor_freeze"] = {"status": "failed", "reason": "quiesce_or_finalize_failed"}
        receipt["complete"] = False
    evidence["evaluation_artifacts"] = receipt


def _freeze_actor_outputs(
    *, workspace, scenario, store, session_id, provenance, evidence, capture_complete
) -> ReviewSnapshot:
    """One actor output boundary for both modes; review never re-exports its own modifications."""
    if workspace is None:
        evidence["prediction_error"] = {"status": "unavailable", "reason": "no_workspace"}
        snapshot = ReviewSnapshot({}, omissions=["no_workspace"])
        capture_complete(snapshot)
        return snapshot
    workspace = as_runtime(workspace)
    try:
        _collect_evaluation_artifacts(
            workspace=workspace,
            scenario=scenario,
            store=store,
            session_id=session_id,
            provenance=provenance,
            evidence=evidence,
        )
        if evidence["actor_freeze"]["status"] != "frozen":
            evidence["prediction_error"] = {
                "status": "unavailable",
                "reason": "actor_not_quiescent",
            }
            raise EnvironmentInfrastructureError("Actor quiesce or service finalization failed")
        if any(
            row["status"] == "collection_failed"
            for row in evidence["evaluation_artifacts"]["entries"]
        ):
            raise EnvironmentInfrastructureError("Completed Actor artifact transport failed")
        patch, _ = _export_prediction(
            workspace=workspace, store=store, session_id=session_id, evidence=evidence
        )
        invalid_git = evidence.get("prediction_error", {}).get("status") == "invalid_task_artifact"
        if evidence.get("prediction_error") and not invalid_git:
            raise EnvironmentInfrastructureError("Completed Actor patch preservation failed")
        files = {}
        for row in evidence["evaluation_artifacts"]["entries"]:
            if row["status"] == "collected":
                data = (store.root.parent / row["path"]).read_bytes()
                if hashlib.sha256(data).hexdigest() != row["sha256"]:
                    raise ValueError("frozen artifact digest changed")
                files[f"artifacts/{row['id']}"] = data
        snapshot = (
            ReviewSnapshot(files, omissions=["invalid_git_artifact"])
            if invalid_git
            else capture_review_snapshot(workspace, patch=patch, files=files)
        )
        if any(str(reason).startswith("files:") for reason in snapshot.evidence["omissions"]):
            raise EnvironmentInfrastructureError("Completed Actor review listing transport failed")
        evidence["review_snapshot"] = dict(snapshot.evidence)
        capture_complete(snapshot)
        if not callable(getattr(workspace, "collection_binding", None)):
            workspace.evidence["collection_pending"] = False
        return snapshot
    finally:
        if not callable(getattr(workspace, "collection_binding", None)):
            cleanup_workspace(workspace.close, stage="close", identity=session_id)
        for key, value in dict(getattr(workspace, "evidence", {}) or {}).items():
            if key not in {"prediction", "diff_sha256", "diff_bytes"}:
                evidence[key] = value


def _execution_contract(*, session_id, scenario, provenance, harness, direct):
    from ahe_beta.execution_contract import canonical_sha256, make_execution_contract

    params = (scenario.workspace.params if scenario.workspace else {}) or {}
    execution = params.get("execution") or {}
    seconds = execution.get(
        "task_budget_seconds",
        execution.get("budget_seconds", getattr(harness, "request_budget_seconds", None)),
    )
    contract = make_execution_contract(
        session_id=session_id,
        task_id=str(
            provenance.get("task_id") or params.get("task_id") or params.get("task_key") or "task"
        ),
        task_digest=str(provenance.get("task_digest") or canonical_sha256(scenario.to_dict())),
        followup_input="unavailable" if direct else "possible",
        task_budget_seconds=seconds,
        budget_source=execution.get("budget_source")
        or ("operator_quota" if seconds else "undeclared"),
        public_refs=[
            {
                "kind": "task",
                "path": f"{session_id}/execution/task.json",
                "sha256": canonical_sha256(scenario.to_dict()),
            }
        ],
    )
    bind = getattr(harness, "bind_execution_contract", None)
    if callable(bind):
        bind(contract)
    return contract


def _report_plan(drafts: list[IssueDraft], session_id: str) -> list[dict]:
    from ahe_beta.execution_contract import canonical_sha256

    return [
        {
            "operation_key": operation_key("session-issue", session_id, index),
            "draft": draft.to_dict(),
            "draft_sha256": canonical_sha256(draft.to_dict()),
        }
        for index, draft in enumerate(drafts)
    ]


def _publish_reports(session: Session, *, tracker, store) -> Session:
    """Spec-0084/T2: immutable complete plan + per-report receipts, then one handoff enrichment."""
    from ahe_beta.demand.evidence_contract import build_evidence_envelope
    from ahe_beta.execution_contract import canonical_sha256
    from ahe_beta.user.session_store import _atomic_json

    if session.report_plan is None:
        return session
    directory = store.root / "reports"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{session.session_id}.json"
    with (directory / f"{session.session_id}.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        digest = canonical_sha256(session.report_plan)
        receipt = (
            json.loads(path.read_text())
            if path.exists()
            else {"plan_sha256": digest, "refs": {}, "completed": False}
        )
        if receipt["plan_sha256"] != digest:
            raise ValueError("report plan digest changed")
        for item in session.report_plan:
            if canonical_sha256(item["draft"]) != item["draft_sha256"]:
                raise ValueError("report draft digest changed")
            key = item["operation_key"]
            if key not in receipt["refs"]:
                create_once = getattr(tracker, "create_issue_once", None)
                if not callable(create_once):
                    raise RuntimeError("report publication requires create_issue_once")
                ref = create_once(IssueDraft.from_dict(item["draft"]), operation_key=key)
                receipt["refs"][key] = ref.to_dict()
                _atomic_json(path, receipt)
        refs = [
            IssueRef.from_dict(receipt["refs"][item["operation_key"]])
            for item in session.report_plan
        ]
        if not session.issue_refs and refs:
            session.issue_refs = refs
            session.user_feedback_envelope = build_evidence_envelope(session).to_dict()
            store.save(session)
        elif [ref.to_dict() for ref in session.issue_refs] != [ref.to_dict() for ref in refs]:
            raise ValueError("session issue handoff conflicts with publication receipts")
        receipt["completed"] = True
        _atomic_json(path, receipt)
        return session


def _release_saved_workspace(session: Session, *, store, packet=None) -> None:
    from ahe_beta.user.sim.seed_source import release_collection

    packet = packet or store.load_actor_checkpoint(
        session.session_id, expected_provenance=session.session_provenance or {}
    )
    if packet is None or (binding := packet["payload"].get("collection_binding")) is None:
        return
    if (
        store.load_actor_capture(
            session.session_id, expected_provenance=session.session_provenance or {}
        )
        is None
    ):
        raise EnvironmentInfrastructureError("Saved session has no bound Actor capture")
    cleanup_workspace(
        lambda: release_collection(
            binding=binding,
            expected_provenance={**session.session_provenance, "session_id": session.session_id},
            spec=session.scenario.workspace,
        ),
        stage="release",
        identity=session.session_id,
    )


def _save_and_publish(session: Session, *, tracker, store, packet) -> Session:
    from ahe_beta.demand.evidence_contract import build_evidence_envelope

    session.user_feedback_envelope = build_evidence_envelope(session).to_dict()
    store.save(session)
    _release_saved_workspace(session, store=store, packet=packet)
    return _publish_reports(session, tracker=tracker, store=store)


def _reconcile_saved_session(session: Session, *, tracker, store) -> Session:
    _release_saved_workspace(session, store=store)
    return _publish_reports(session, tracker=tracker, store=store)


def _recover_pending_actor(*, packet, store, complete) -> Session | None:
    try:
        return complete()
    except CollectionSourceLost:
        # Only the durable orchestrator can launch a replacement with a new attempt identity.
        binding = packet["payload"].get("collection_binding")
        attempt = (binding or {}).get("identity", {}).get("attempt")
        current = current_usage_context()
        if (
            current.session_id != packet["session_id"]
            or type(current.attempt) is not int
            or type(attempt) is not int
            or current.attempt <= attempt
        ):
            raise
        store.retire_lost_actor(
            packet["session_id"], provenance=packet["provenance"], attempt=attempt
        )
        return None


def _export_prediction(
    *, workspace: Workspace, store: SessionStore, session_id: str, evidence: dict
) -> tuple[str, str]:
    """Spec-0075/T1: export and preserve full bytes before session save/cleanup."""
    evidence.update(dict(getattr(workspace, "evidence", {}) or {}))
    evidence.pop("prediction", None)
    if evidence.get("patch_capability") == "not_applicable":
        # Spec-0081/T3: a file/service task has no synthetic empty Git prediction.
        evidence["prediction_status"] = "not_applicable"
        evidence.pop("prediction_error", None)
        evidence.pop("patch_export_error", None)
        return "", ""
    try:
        if evidence.get("diff_base_error"):
            raise RuntimeError("original patch base could not be captured")
        patch, patch_sha = workspace.export_patch()
    except InvalidWorkspaceArtifact:
        evidence["prediction_error"] = {
            "status": "invalid_task_artifact",
            "reason": "invalid_git_artifact",
        }
        for key in (
            "diff_sha256",
            "diff_bytes",
            "patch_sha256",
            "patch_bytes",
            "patch_exported_at",
        ):
            evidence.pop(key, None)
        return "", ""
    except Exception as exc:  # noqa: BLE001 - retain the session without a fake prediction
        evidence["patch_export_error"] = str(exc)
        evidence["prediction_error"] = {"status": "export_failed", "error_type": type(exc).__name__}
        for key in (
            "diff_sha256",
            "diff_bytes",
            "patch_sha256",
            "patch_bytes",
            "patch_exported_at",
        ):
            evidence.pop(key, None)
        return "", ""
    try:
        receipt = preserve_prediction(
            sessions_root=store.root, session_id=session_id, patch=patch, patch_sha256=patch_sha
        )
    except Exception as exc:  # noqa: BLE001 - write/digest failure must not claim persistence
        evidence["prediction_error"] = {
            "status": "preservation_failed",
            "error_type": type(exc).__name__,
        }
    else:
        evidence["prediction"] = receipt
        evidence.pop("prediction_error", None)
    evidence.pop("patch_export_error", None)
    evidence.update(
        {
            "diff_sha256": patch_sha,
            "diff_bytes": len(patch.encode("utf-8")),
            "patch_exported_at": utc_now(),
        }
    )
    return patch, patch_sha


def result_to_turns(res: SessionResult) -> list[Turn]:
    """SessionResult → sequence of models.Turn: each round contains harness text first, then user message (skipped if empty).

    `TurnLog.harness_output` is a snapshot of "the *previous* harness reply seen by this round's persona", which may repeat
    across empty-turn forwarding. Thus using "adjacent deduplication": we only record one harness turn when the harness
    reply actually changes (= a new round of replies arrives); otherwise the same completion would expand into multiple turns,
    misaligning with user messages (previously caused persisted transcripts to show false patterns like `user, harness×N, user`).
    """
    turns: list[Turn] = []
    prev_ho: str | None = None
    for t in res.turns:
        ho = t.harness_output.strip()
        # Record only when a new round of harness replies arrives; treat consecutive identical snapshots as one record
        if ho and ho != prev_ho:
            # steps = internal iteration trace of this reply (visible only at observation layer expansion; persona only consumes content)
            turns.append(Turn(role="harness", content=ho, steps=list(t.harness_steps or [])))
        if ho:
            prev_ho = ho
        if t.message.strip() and t.action not in {
            "accept",
            "accept_with_reservations",
            "file_issue",
            "give_up",
        }:
            turns.append(Turn(role="user", content=t.message.strip()))
    # Pending harness reply (received but not yet logged with the next TurnLog): inject this real-time snapshot to complete the picture
    pending = (res.pending_harness_output or "").strip()
    if pending and pending != prev_ho:
        turns.append(
            Turn(role="harness", content=pending, steps=list(res.pending_harness_steps or []))
        )
    return turns


def result_to_sim_trace(res: SessionResult) -> SimTrace:
    """Persist the complete TurnLog decision timeline from SessionResult, keeping reasoning and conversation snippets together."""
    derived = None
    if res.feeling_derived is not None:
        derived = FeelingScore(score=res.feeling_derived.score, reason=res.feeling_derived.reason)
    return SimTrace(
        persona_id=res.persona_id,
        end_reason=res.end_reason,
        turns=[
            SimTurn(
                turn=t.turn,
                phase=t.phase,
                action_space=list(t.action_space),
                perceive=t.perceive,
                verdict=t.verdict,
                action=t.action,
                message=t.message,
                executor=t.executor,
                channel=t.channel,
                patience=t.patience,
                trust=t.trust,
                harness_output=t.harness_output,
                harness_steps=list(t.harness_steps or []),
                harness_events=list(getattr(t, "harness_events", []) or []),
                persona_trace=[
                    PersonaCallTrace.from_dict(c) if isinstance(c, dict) else c
                    for c in (t.persona_trace or [])
                ],
                utterance_id=getattr(t, "utterance_id", "") or "",
                delivery=getattr(t, "delivery", "") or "",
                queued_behind=getattr(t, "queued_behind", "") or "",
                answers_utterance_id=getattr(t, "answers_utterance_id", "") or "",
                answers_said=getattr(t, "answers_said", "") or "",
                goal_before=dict(getattr(t, "goal_before", {}) or {}),
                goal_reading=[dict(item) for item in (getattr(t, "goal_reading", []) or [])],
                target_goal_ids=[str(item) for item in (getattr(t, "target_goal_ids", []) or [])],
                expected_progress=str(getattr(t, "expected_progress", "") or ""),
                goal_updates=[dict(item) for item in (getattr(t, "goal_updates", []) or [])],
                goal_after=dict(getattr(t, "goal_after", {}) or {}),
                goal_effect=dict(getattr(t, "goal_effect", {}) or {}),
                goal_field_audit=dict(getattr(t, "goal_field_audit", {}) or {}),
                acceptance_basis=dict(getattr(t, "acceptance_basis", {}) or {}),
            )
            for t in res.turns
        ],
        signals=list(res.signals),
        feeling_derived=derived,
        persona_tail=[
            PersonaCallTrace.from_dict(c) if isinstance(c, dict) else c
            for c in (res.persona_tail or [])
        ],
        evaluation_status=res.evaluation_status,
        evaluation_error=(dict(res.evaluation_error) if res.evaluation_error is not None else None),
        interaction_status=getattr(res, "interaction_status", "completed"),
        protocol_events=[dict(event) for event in (getattr(res, "protocol_events", []) or [])],
        goal_ledger=dict(getattr(res, "goal_ledger", {}) or {}),
        goal_acceptance=(
            dict(res.goal_acceptance) if getattr(res, "goal_acceptance", None) is not None else None
        ),
        goal_audit=dict(getattr(res, "goal_audit", {}) or {}),
        terminal_audit=dict(getattr(res, "terminal_audit", {}) or {}),
    )


def _infer_kind(body: str) -> str:
    """Spec-0025/T2: coarse-grained issue kind classification (type label). Most sim issues stem from failure/dissatisfaction → bug;
    when explicit request keywords like "hope/can we/add/support..." appear, infer feature. **Tentative only**—the triage agent will confirm/correct.
    """
    text = (body or "").lower()
    feature_hints = (
        "hope",
        "can you",
        "add ",
        "support ",
        "feature",
        "would be nice",
        "add a",
        "wish",
    )
    return "feature" if any(h in text for h in feature_hints) else "bug"


def _issue_draft_from_body(body: str, *, round_no: int | None = None) -> IssueDraft:
    """Raw user issue → parameters for creating issue in Gitea (Spec-0025/T2).

    body = user-visible issue report in original text (persona in first person; user cannot see code → only symptoms from user perspective). Label triplet:
    tentative type (bug/feature; triage will confirm) + `needs-triage` (awaiting triage; not to be picked by dev) + optional `round-N`.
    Title taken from first line of body. TRIAGE section fields (root cause/boundary/acceptance) left empty for triage agent to populate after reading code + trace.
    """
    text = body or ""
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "simulated user issue")
    labels = [_infer_kind(text), NEEDS_TRIAGE]
    if round_no is not None:
        labels.append(round_label(round_no))
    return IssueDraft(title=first[:80], body=text, labels=labels)


def make_sim_run_session_fn(
    *,
    client_factory: Callable[[], PersonaClient],
    tracker: IssueTracker,
    store: SessionStore,
    sim_personas: dict[str, SimPersona],
    on_turn: SimTurnHook | None = None,
    round_provider: Callable[[], int | None] | None = None,
) -> Callable[..., Session]:
    """Return run_session_fn for Orchestrator use.

    client_factory: creates a fresh persona client per session (Spec-0017/T2). AgenticPersonaClient is stateful at session scope
    (bind_session writes _persona/_workspace_dir); reusing a single instance across multiple concurrent user sessions in one stage
    must serialize (later bind overwrites earlier bind); the underlying ApiPersonaClient.complete is stateless and can be globally shared,
    factory only creates the wrapper.
    sim_personas: models.Persona.identity → 9-dimensional sim persona mapping (authoritative profiles) for display.
    on_turn: fires once per round (including terminal round) + once at wrap-up, for caller to emit agent activity to dashboard.
    round_provider: Spec-0025/T6—called once at session wrap-up before creating issue, returns current round number to tag raw issue with `round-N`
    label (for incremental triage and observation curves). None (or returns None) skips round tagging, compatible with legacy callers.
    """

    observation_root = Path(
        os.environ.get("AHE_BETA_OBSERVATION_ROOT", str(store.root.parent / "observations"))
    )
    # Spec-0070/T3: preserve the old framework contract while freezing checked transport.
    from ahe_beta.observations.preflight import prepare_observations

    prepare_observations(tracker=tracker, root=observation_root)

    def save_result(packet, res, workspace_evidence):
        payload = packet["payload"]
        persona = Persona.from_dict(payload["persona"])
        scenario = SeedScenario.from_dict(payload["scenario"])
        sim_persona = sim_personas[persona.identity]
        session_id, provenance = packet["session_id"], packet["provenance"]
        request_outcomes = payload["actor"]["request_outcomes"]
        # Spec-0083/T3: grading is private and happens only after collection.
        terminal_note = next(
            (
                t.message.strip()
                for t in reversed(res.turns)
                if t.action in {"accept", "accept_with_reservations", "file_issue", "give_up"}
                and t.message.strip()
            ),
            "",
        )

        round_no = (
            round_provider() if round_provider is not None else current_usage_context().round_no
        )
        bodies = list(res.issue_notes) + ([res.issue_artifact] if res.issue_artifact else [])
        drafts = [_issue_draft_from_body(body, round_no=round_no) for body in bodies]
        opportunities = [
            {"kind": "feature" if "feature" in draft.labels else "diagnostic", "body": draft.body}
            for draft in drafts
        ]
        for draft, opportunity in zip(drafts, opportunities, strict=True):
            if opportunity["kind"] == "diagnostic":
                draft.body += (
                    "\n\nAttribution: user-reported observation; root cause is unconfirmed."
                )
        feedback = {
            "schema_version": 1,
            "task_assessment": {
                "status": "fulfilled"
                if res.end_reason == "accepted"
                else "unfulfilled"
                if res.end_reason in {"abandoned", "issue_filed", "max_turns"}
                else "unknown",
                "source": "simulated_user_terminal_action",
                "evidence_refs": ["sim_trace"],
            },
            "experience": res.experience
            or experience_feedback(
                res.feeling.to_dict() if res.feeling else None, source="simulated_user"
            ),
            "attribution": {"status": "uncertain" if bodies else "unknown", "claims": []},
            "opportunities": opportunities,
        }
        session = Session(
            persona=persona,
            scenario=scenario,
            transcript=Transcript(turns=result_to_turns(res)),
            feeling=None,
            feedback=feedback,
            execution_contract=payload["execution_contract"],
            execution_receipt={
                "interaction_mode": "simulated_user",
                "harness_messages": sum(t.role == "user" for t in result_to_turns(res)),
                "user_assistance": "recorded_in_sim_trace",
            },
            report_plan=_report_plan(drafts, session_id),
            issue_refs=[],
            session_provenance=provenance,
            sim_trace=result_to_sim_trace(res),
            session_id=session_id,
            user_outcome={"end_reason": res.end_reason, "terminal_note": terminal_note},
            request_outcomes=request_outcomes,
            workspace_evidence=workspace_evidence,
            audit_events=_audit_events(
                workspace_evidence=workspace_evidence,
                request_outcomes=request_outcomes,
            ),
        )
        validate_session_provenance(session, provenance)
        _save_and_publish(session, tracker=tracker, store=store, packet=packet)
        if on_turn is not None:
            # Wrap-up: mark running=False, include session_id for dashboard archival to correlate full session.
            on_turn(persona.identity, sim_persona, res, False, session_id=session.session_id)
        return session

    def complete_actor(packet):
        from ahe_beta.user.sim.loop import resume_terminal_review

        payload = packet["payload"]
        persona = Persona.from_dict(payload["persona"])
        sim_persona = sim_personas[persona.identity]
        snapshot, workspace_evidence = _capture_completed_actor(
            packet=packet,
            store=store,
            session_id=packet["session_id"],
            provenance=packet["provenance"],
            observation_root=observation_root,
            workspace=None,
        )
        client = client_factory()
        if hasattr(client, "bind_session"):
            client.bind_session(persona=sim_persona, workspace_dir=snapshot)
        with bind_usage_context(
            session_id=packet["session_id"], role="user", operation="terminal_review"
        ):
            res = resume_terminal_review(
                persona=sim_persona, client=client, checkpoint=payload["actor"]["terminal"]
            )
        return save_result(packet, res, workspace_evidence)

    def run(
        persona: Persona,
        scenario: SeedScenario,
        harness: HarnessInterface,
        *,
        workspace_dir: Workspace | None = None,
    ) -> Session:
        sim_persona = sim_personas[persona.identity]
        # Spec-0064/T3: the staged orchestrator binds a stable operation id.
        # Direct/legacy callers retain a random per-session identity.
        bound_session_id = current_usage_context().session_id
        session_id = bound_session_id or uuid.uuid4().hex
        provenance = bound_session_provenance()
        recovered = store.reconcile(session_id, expected_provenance=provenance)
        if recovered is not None:
            return _reconcile_saved_session(recovered, tracker=tracker, store=store)
        pending = store.load_actor_checkpoint(session_id, expected_provenance=provenance)
        if pending is not None:
            return complete_actor(pending)
        # Spec-0017/T2: independent instance per session; bind calls do not overwrite each other
        client = client_factory()

        # spec-0008/T1 v2: shared workspace. Orchestrator materializes one workspace per session, injects it via launcher as harness
        # (SANDBOX_WORK_DIR) and passes the same directory as workspace_dir here—both sides' cwd point to the same place; harness
        # modifications and user agent verification happen in the same directory. Reuse the passed directory to bind the inner client; no separate materialization.
        # Backward compatibility with direct calls (not via orchestrator): if workspace_dir is not passed but scenario includes workspace, fall back to self-
        # materialization (equivalent to v1). Guarded bind_session: only AgenticPersonaClient exposes it; Scripted/Api skip.
        ws = as_runtime(workspace_dir) if workspace_dir is not None else None
        if ws is None and scenario.workspace is not None:
            ws = as_runtime(materialize_workspace(scenario.workspace), owns_tmp=True)
            # Spec-0009/T3: the fallback calls ensure_deps after materialization, matching the orchestrator path,
            # so workspace setup includes dependency preparation rather than silently skipping it. The orchestrator's main
            # path already provisions dependencies where workspace_dir is passed, so ensure is called only in this fallback branch to avoid duplication.
            ensure_deps(ws, scenario.workspace)
        if ws is not None:
            _freeze_prediction_base(ws)
        if ws is not None and hasattr(client, "bind_session"):
            client.bind_session(persona=sim_persona, workspace_dir=ws)

        def progress(partial: SessionResult) -> None:
            if on_turn is not None:
                on_turn(
                    persona.identity,
                    sim_persona,
                    partial,
                    True,
                    session_id=session_id if provenance else None,
                )

        connector = HarnessConnector(harness)
        instance_id = None
        if scenario.workspace is not None:
            instance_id = scenario.workspace.params.get("instance_id")
        round_no = (
            round_provider() if round_provider is not None else current_usage_context().round_no
        )
        workspace_evidence: dict = {}
        actor_closed = False
        packet = None

        def stage_actor(terminal):
            nonlocal packet
            packet = store.stage_actor(
                session_id,
                provenance=provenance,
                payload=_actor_checkpoint_payload(
                    mode="simulated_user",
                    persona=persona,
                    scenario=scenario,
                    execution_contract=execution_contract,
                    workspace=ws,
                    actor={
                        "terminal": terminal,
                        "request_outcomes": [
                            dict(row) for row in (getattr(harness, "request_outcomes", None) or [])
                        ],
                    },
                    observation=_observation_binding(harness),
                ),
            )
            if ws is not None and packet["payload"]["collection_binding"] is not None:
                ws.evidence["collection_pending"] = True

        def freeze_before_review() -> None:
            nonlocal actor_closed, workspace_evidence
            if actor_closed:
                return
            actor_closed = True
            connector.close()
            if packet is None:
                if ws is not None:
                    cleanup_workspace(ws.close, stage="close", identity=session_id)
                return
            snapshot, workspace_evidence = _capture_completed_actor(
                packet=packet,
                store=store,
                session_id=session_id,
                provenance=provenance,
                observation_root=observation_root,
                workspace=ws,
            )
            if hasattr(client, "bind_session"):
                client.bind_session(persona=sim_persona, workspace_dir=snapshot)

        with bind_usage_context(
            session_id=session_id,
            instance_id=instance_id,
            role="user",
            agent_id=f"user-{session_id}" if provenance else f"user-{persona.identity}",
            round_no=round_no,
            operation="persona",
        ):
            try:
                connector.reset()
                execution_contract = _execution_contract(
                    session_id=session_id,
                    scenario=scenario,
                    provenance=provenance,
                    harness=harness,
                    direct=False,
                )
                res = sim_run_session(
                    sim_persona,
                    client,
                    connector,
                    scenario.description,
                    help_text=connector.help_text,
                    on_progress=progress,
                    before_terminal_review=freeze_before_review,
                    on_actor_complete=stage_actor,
                )
            finally:
                freeze_before_review()
        return save_result(packet, res, workspace_evidence)

    # The orchestrator uses this read path to reconcile a crash after SessionStore
    # committed but before the recovery completion marker was published.
    def load_completed_session(session_id):
        provenance = bound_session_provenance()
        session = store.reconcile(session_id, expected_provenance=provenance)
        if session is not None:
            return _reconcile_saved_session(session, tracker=tracker, store=store)
        pending = store.load_actor_checkpoint(session_id, expected_provenance=provenance)
        if pending is None:
            return None
        if pending["payload"]["mode"] != "simulated_user":
            raise EnvironmentInfrastructureError("Actor checkpoint interaction mode differs")
        return _recover_pending_actor(
            packet=pending, store=store, complete=lambda: complete_actor(pending)
        )

    run.load_completed_session = load_completed_session
    return run


def _direct_execution_record(harness) -> tuple[dict, list[dict]]:
    """Preserve received evidence like SimTrace; clipping belongs to query projections."""
    events = list(getattr(harness, "visible_events", []) or [])
    steps = list(getattr(harness, "last_steps", []) or [])
    provenance = "reply_steps"
    if not steps:
        provenance = "stdout_progress"
        for event in events:
            raw = event.get("raw") if isinstance(event, dict) else None
            if not isinstance(raw, dict):
                continue
            progress = raw if raw.get("type") == "progress" else raw.get("progress", {})
            if isinstance(progress, dict) and progress.get("text"):
                step = dict(progress)
                step.pop("type", None)  # Frame type remains in events; steps use kind.
                step.setdefault("kind", "progress")
                steps.append(step)
    return {
        "contract_version": 1,
        "source": "launcher_received",
        "storage_policy": "received_full",
        "reviewer_visibility": "terminal_reply_only",
        "events": events,
        "events_total": len(events),
        "events_omitted": 0,
        "steps_source": provenance,
        "steps_total": len(steps),
        "steps_omitted": 0,
    }, steps


def make_direct_run_session_fn(
    *,
    client_factory: Callable[[], PersonaClient],
    tracker: IssueTracker,
    store: SessionStore,
    sim_personas: dict[str, SimPersona],
    round_provider: Callable[[], int | None] | None = None,
) -> Callable[..., Session]:
    """Build the no-intermediate-control runner used by mixed benchmark tasks.

    Direct mode sends the frozen task description exactly once and never sends
    a heartbeat, follow-up, interrupt, or acceptance message to the harness.
    After the harness reaches its terminal reply, the assigned user persona
    gets one bounded review call to inspect the reply/artifact and produce the
    same feedback/issue handoff consumed by triage. Thus direct removes the
    intermediate control loop, not the user feedback signal.
    """

    observation_root = Path(
        os.environ.get("AHE_BETA_OBSERVATION_ROOT", str(store.root.parent / "observations"))
    )
    # Spec-0070/T3: preserve the old framework contract while freezing checked transport.
    from ahe_beta.observations.preflight import prepare_observations

    prepare_observations(tracker=tracker, root=observation_root)

    def complete_actor(packet, workspace):
        from ahe_beta.user.sim.persona_client import drain_call_traces
        from ahe_beta.user.sim.prompt import build_direct_review_turn, build_system

        payload = packet["payload"]
        actor = payload["actor"]
        persona = Persona.from_dict(payload["persona"])
        scenario = SeedScenario.from_dict(payload["scenario"])
        params = dict((scenario.workspace.params if scenario.workspace else {}) or {})
        task_key = str(params.get("task_key") or persona.identity or "direct-task")
        session_id = packet["session_id"]
        provenance = packet["provenance"]
        round_no = provenance.get("round_no") or (
            round_provider() if round_provider else current_usage_context().round_no
        )
        reply, harness_error = actor["reply"], actor["harness_error"]
        execution_record, harness_steps = actor["execution_record"], actor["harness_steps"]
        execution_contract = payload["execution_contract"]
        snapshot, workspace_evidence = _capture_completed_actor(
            packet=packet,
            store=store,
            session_id=session_id,
            provenance=provenance,
            observation_root=observation_root,
            workspace=workspace,
        )
        review_error = None
        review: dict = {}
        review_client = None
        sim_persona = sim_personas.get(persona.identity)
        review_system = (
            build_system(sim_persona)
            if sim_persona
            else "Review only the frozen outputs. Return JSON."
        )
        try:
            review_client = client_factory()
            if sim_persona is not None and hasattr(review_client, "bind_session"):
                review_client.bind_session(persona=sim_persona, workspace_dir=snapshot)
            with bind_usage_context(
                session_id=session_id,
                instance_id=params.get("task_id") or task_key,
                role="user",
                agent_id=f"user-{session_id}" if provenance else f"user-{persona.identity}",
                round_no=round_no,
                operation="direct_review",
            ):
                review = dict(
                    review_client.respond(
                        review_system,
                        build_direct_review_turn(scenario.description, reply, snapshot.read_diff()),
                    )
                    or {}
                )
        except Exception as exc:  # noqa: BLE001
            review_error = str(exc)
        text = str(
            review.get("feedback") or review.get("message") or review.get("issue") or ""
        ).strip()
        assessment = review.get("task_assessment", "unknown")
        if assessment not in ("fulfilled", "unfulfilled", "unknown"):
            assessment = "unknown"
        opportunities = []
        for row in (
            review.get("opportunities", []) if isinstance(review.get("opportunities"), list) else []
        ):
            if isinstance(row, dict) and isinstance(row.get("body"), str) and row["body"].strip():
                opportunities.append(
                    {
                        "kind": "feature" if row.get("kind") == "feature" else "diagnostic",
                        "title": str(row.get("title") or task_key),
                        "body": row["body"].strip(),
                    }
                )
        # Explicit old-style reviewer complaints can be retained, but a generic fallback
        # or a missing review never manufactures a ticket or a successful task judgment.
        if (
            "opportunities" not in review
            and isinstance(review.get("issue"), str)
            and review["issue"].strip()
        ):
            opportunities.append(
                {"kind": "diagnostic", "title": task_key, "body": review["issue"].strip()}
            )
        attribution = review.get("attribution") or {}
        claims = attribution.get("claims", []) if isinstance(attribution, dict) else []
        if not isinstance(claims, list):
            claims = []
        feedback = {
            "schema_version": 1,
            "task_assessment": {
                "status": assessment,
                "source": "direct_terminal_review",
                "evidence_refs": ["transcript", "workspace_evidence"],
            },
            "experience": experience_feedback(
                review, source="direct_terminal_review", error=review_error
            ),
            # The subjective reviewer cannot establish the implementation root cause.
            "attribution": {"status": "uncertain" if claims else "unknown", "claims": claims},
            "opportunities": opportunities,
        }
        drafts = []
        for opportunity in opportunities:
            labels = [
                "feature" if opportunity["kind"] == "feature" else "bug",
                NEEDS_TRIAGE,
                "direct",
            ]
            if round_no is not None:
                labels.append(round_label(round_no))
            body = opportunity["body"]
            if opportunity["kind"] == "diagnostic":
                body += "\n\nAttribution: an observed task gap; the root cause is unconfirmed."
            drafts.append(IssueDraft(title=opportunity["title"][:80], body=body, labels=labels))
        status = "infrastructure_failure" if harness_error else "completed"
        session = Session(
            persona=persona,
            scenario=scenario,
            transcript=Transcript(
                turns=[
                    Turn(role="user", content=scenario.description),
                    Turn(role="harness", content=reply, steps=harness_steps),
                    Turn(role="user", content=text),
                ]
            ),
            feeling=None,
            feedback=feedback,
            execution_contract=execution_contract,
            execution_receipt={
                "interaction_mode": "direct",
                "harness_messages": 1,
                "followups": 0,
                "user_assistance": "none",
            },
            report_plan=_report_plan(drafts, session_id),
            issue_refs=[],
            session_provenance=provenance,
            session_id=session_id,
            user_outcome={
                "interaction_mode": "direct",
                "execution_record": execution_record,
                "user_model": getattr(review_client, "model", None),
                "user_turns": 1,
                "harness_messages": 1,
                "review_calls": 1 if review_client else 0,
                "followups": 0,
                "heartbeat": False,
                "status": status,
                "review_status": "infrastructure_failure" if review_error else "completed",
                "review_verdict": str(review.get("verdict") or assessment),
                "review_feedback": text,
                "harness_reply": reply,
                "review_trace": drain_call_traces(review_client) if review_client else [],
                **({"error": harness_error} if harness_error else {}),
                **({"review_error": review_error} if review_error else {}),
            },
            request_outcomes=list(actor["request_outcomes"]),
            workspace_evidence=workspace_evidence,
            accept_validity="not_applicable",
            audit_events=_audit_events(
                workspace_evidence=workspace_evidence,
                request_outcomes=list(actor["request_outcomes"]),
            ),
        )
        validate_session_provenance(session, provenance)
        return _save_and_publish(session, tracker=tracker, store=store, packet=packet)

    def run(
        persona: Persona,
        scenario: SeedScenario,
        harness: HarnessInterface,
        *,
        workspace_dir: Workspace | None = None,
    ) -> Session:
        params = dict((scenario.workspace.params if scenario.workspace else {}) or {})
        task_key = str(params.get("task_key") or persona.identity or "direct-task")
        session_id = current_usage_context().session_id or uuid.uuid4().hex
        provenance = bound_session_provenance()
        recovered = store.reconcile(session_id, expected_provenance=provenance)
        if recovered is not None:
            return _reconcile_saved_session(recovered, tracker=tracker, store=store)
        pending = store.load_actor_checkpoint(session_id, expected_provenance=provenance)
        if pending is not None:
            return complete_actor(pending, None)
        connector = HarnessConnector(harness)
        round_no = round_provider() if round_provider else current_usage_context().round_no
        reply = ""
        harness_error = None
        if workspace_dir is not None:
            _freeze_prediction_base(as_runtime(workspace_dir))
        execution_contract = _execution_contract(
            session_id=session_id,
            scenario=scenario,
            provenance=provenance,
            harness=harness,
            direct=True,
        )
        try:
            connector.reset()
            bind = getattr(harness, "bind_execution_contract", None)
            if callable(bind):
                bind(execution_contract)
            with bind_usage_context(
                session_id=session_id,
                instance_id=params.get("task_id") or task_key,
                role="direct",
                agent_id=f"direct-{task_key}",
                round_no=round_no,
            ):
                reply = connector.send(scenario.description)
        except Exception as exc:  # noqa: BLE001 - retain actor failures independently of review
            harness_error = str(exc)
            reply = f"[harness error] {harness_error}"
        finally:
            execution_record, harness_steps = _direct_execution_record(harness)
            packet = store.stage_actor(
                session_id,
                provenance=provenance,
                payload=_actor_checkpoint_payload(
                    mode="direct",
                    persona=persona,
                    scenario=scenario,
                    execution_contract=execution_contract,
                    workspace=workspace_dir,
                    actor={
                        "reply": reply,
                        "harness_error": harness_error,
                        "execution_record": execution_record,
                        "harness_steps": harness_steps,
                        "request_outcomes": list(getattr(harness, "request_outcomes", []) or []),
                    },
                    observation=_observation_binding(harness),
                ),
            )
            if workspace_dir is not None and packet["payload"]["collection_binding"] is not None:
                workspace_dir.evidence["collection_pending"] = True
            connector.close()
        return complete_actor(packet, workspace_dir)

    def load_completed_session(session_id):
        provenance = bound_session_provenance()
        session = store.reconcile(session_id, expected_provenance=provenance)
        if session is not None:
            return _reconcile_saved_session(session, tracker=tracker, store=store)
        pending = store.load_actor_checkpoint(session_id, expected_provenance=provenance)
        if pending is None:
            return None
        if pending["payload"]["mode"] != "direct":
            raise EnvironmentInfrastructureError("Actor checkpoint interaction mode differs")
        return _recover_pending_actor(
            packet=pending, store=store, complete=lambda: complete_actor(pending, None)
        )

    run.load_completed_session = load_completed_session
    return run


def make_mixed_run_session_fn(
    *,
    client_factory: Callable[[], PersonaClient],
    tracker: IssueTracker,
    store: SessionStore,
    sim_personas: dict[str, SimPersona],
    on_turn: SimTurnHook | None = None,
    round_provider: Callable[[], int | None] | None = None,
) -> Callable[..., Session]:
    """Dispatch a frozen task to simulated-user or direct interaction mode."""

    simulated = make_sim_run_session_fn(
        client_factory=client_factory,
        tracker=tracker,
        store=store,
        sim_personas=sim_personas,
        on_turn=on_turn,
        round_provider=round_provider,
    )
    direct = make_direct_run_session_fn(
        client_factory=client_factory,
        tracker=tracker,
        store=store,
        sim_personas=sim_personas,
        round_provider=round_provider,
    )

    def run(
        persona: Persona, scenario: SeedScenario, harness: HarnessInterface, *, workspace_dir=None
    ):
        mode = str(
            (scenario.workspace.params if scenario.workspace else {}).get(
                "interaction", "simulated_user"
            )
        )
        if mode == "direct":
            return direct(persona, scenario, harness, workspace_dir=workspace_dir)
        if mode != "simulated_user":
            raise ValueError(f"unsupported interaction mode: {mode}")
        return simulated(persona, scenario, harness, workspace_dir=workspace_dir)

    def load_completed_session(session_id):
        packet = store.load_actor_checkpoint(
            session_id, expected_provenance=bound_session_provenance()
        )
        chosen = (
            direct if packet is not None and packet["payload"]["mode"] == "direct" else simulated
        )
        return chosen.load_completed_session(session_id)

    run.load_completed_session = load_completed_session
    return run
