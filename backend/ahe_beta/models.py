"""Common data structures for the minimal user-side pipeline (spec-0001/T1).

All are pure-data dataclasses with no behavior, supporting bidirectional dict serialization (to_dict / from_dict).
User experience data and Session are persisted locally under data/sessions/ (T6); issues are not persisted locally, but are submitted to Gitea via IssueTracker, with only an IssueRef receipt kept locally (T5). Session.sim_trace optionally carries the god-view (decision timeline + inner monologue).
Lightweight invariants are asserted in __post_init__, without introducing external validators.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Set of valid conversation roles (the role of each turn in a Transcript must be one of these).
_ROLES = ("user", "harness")
# Set of valid issue statuses (semantically aligned with the Gitea state).
ISSUE_STATES = ("open", "closed")


@dataclass
class Persona:
    """User profile (given input): identity/level/domain/goals/speaking style. Provenance is deferred to a later distill spec."""

    identity: str
    level: str
    domain: str
    goal: str
    speaking_style: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "level": self.level,
            "domain": self.domain,
            "goal": self.goal,
            "speaking_style": self.speaking_style,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Persona:
        return cls(
            identity=data["identity"],
            level=data["level"],
            domain=data["domain"],
            goal=data["goal"],
            speaking_style=data["speaking_style"],
        )


@dataclass
class WorkspaceSpec:
    """Seed workspace spec: materialize an isolated workspace directory through a pluggable SeedSource (dispatched by kind).

    spec-0009/T1: `kind` selects the provider implementation (default `local-fixture`, matching 0008 behavior); `params`
    carries source-specific inputs (such as doc/doc_name for the empty source), so new sources do not require extending WorkspaceSpec.
    `fixture` is the backend/seed_workspaces/<fixture>/ directory name used by the local-fixture source;
    `setup` is a command hook run by spec-0009/T3's `ensure_deps` after materialize (by convention, create
    a per-workspace `.venv` and install dependencies with pip). Separate from the benchmark held-out boundary: the workspace contains no gold tests.
    """

    fixture: str = ""
    kind: str = "local-fixture"
    params: dict[str, Any] = field(default_factory=dict)
    setup: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        # Default kind/empty params are not serialized to disk, preserving the existing line 0008 serialization shape (backward compatible).
        d: dict[str, Any] = {"fixture": self.fixture, "setup": list(self.setup)}
        if self.kind != "local-fixture":
            d["kind"] = self.kind
        if self.params:
            d["params"] = dict(self.params)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkspaceSpec:
        return cls(
            fixture=data.get("fixture", ""),
            kind=data.get("kind", "local-fixture"),
            params=dict(data.get("params", {})),
            setup=list(data.get("setup", [])),
        )


@dataclass
class SeedScenario:
    """Seed scenario (given input): the initial request/task description for one session (not a test case).

    workspace is optional: when non-null, carries a baseline project workspace (spec-0008/T1) for the inner tool-using
    user agent to execute and verify in its own sandbox; when None, uses the existing text-only scenario.
    """

    description: str
    workspace: WorkspaceSpec | None = None

    def to_dict(self) -> dict[str, Any]:
        # When workspace=None, this key is not serialized, preserving the existing shape of pure-text scenarios (backward compatible).
        d: dict[str, Any] = {"description": self.description}
        if self.workspace is not None:
            d["workspace"] = self.workspace.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SeedScenario:
        ws = data.get("workspace")
        return cls(
            description=data["description"],
            workspace=WorkspaceSpec.from_dict(ws) if ws else None,
        )


@dataclass
class Turn:
    """One turn of conversation: role ∈ {user, harness} with content. A constituent unit of Transcript.

    steps: optional, only for harness turns — the process flow of this harness turn's inner iterations ({kind, text} sequence,
    assistant utterances / tool calls / results). content is the final answer shown to the user; steps is the complete inner
    process visible only when observations are expanded (persona consumes content, not steps). Default empty; only included
    in to_dict when non-empty (does not change existing serialization shape).
    """

    role: str
    content: str
    steps: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        assert self.role in _ROLES, f"Invalid role: {self.role!r} (must be one of {_ROLES})"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.steps:
            d["steps"] = self.steps
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Turn:
        return cls(role=data["role"], content=data["content"], steps=data.get("steps", []))


@dataclass
class Transcript:
    """Ordered multi-turn conversation record (process artifact). Each turn has role ∈ {user, harness}, validated at construction."""

    turns: list[Turn] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"turns": [t.to_dict() for t in self.turns]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Transcript:
        return cls(turns=[Turn.from_dict(t) for t in data.get("turns", [])])


@dataclass
class FeelingScore:
    """1–4 subjective rating + rationale (output at session end, used as training signal). Out-of-range causes construction failure."""

    score: int
    reason: str

    def __post_init__(self) -> None:
        assert type(self.score) is int and 1 <= self.score <= 4, (
            f"Experience score out of range: {self.score} (must be 1..4)"
        )

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "reason": self.reason}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FeelingScore:
        return cls(score=data["score"], reason=data["reason"])


def validate_feedback(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate independent observation axes without fabricating missing ratings (Spec-0084/T1)."""
    import json

    from ahe_beta.execution_contract import canonical_bytes

    expected = {"schema_version", "task_assessment", "experience", "attribution", "opportunities"}
    if (
        not isinstance(value, Mapping)
        or set(value) != expected
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
    ):
        raise ValueError("feedback must use the complete schema 1")
    task, experience, attribution = (
        value[key] for key in ("task_assessment", "experience", "attribution")
    )
    if not isinstance(task, dict) or task.get("status") not in {
        "fulfilled",
        "unfulfilled",
        "unknown",
    }:
        raise ValueError("invalid task assessment")
    if not isinstance(task.get("source"), str) or not isinstance(task.get("evidence_refs"), list):
        raise ValueError("task assessment requires a source and evidence references")
    if not isinstance(experience, dict) or experience.get("status") not in {
        "rated",
        "missing",
        "invalid",
        "unavailable",
    }:
        raise ValueError("invalid experience status")
    score = experience.get("score")
    if experience["status"] == "rated":
        if type(score) is not int or not 1 <= score <= 4:
            raise ValueError("rated experience requires an integer from 1 to 4")
    elif score is not None:
        raise ValueError("missing experience cannot carry a rating")
    if any(not isinstance(experience.get(key), str) for key in ("source", "reason")):
        raise ValueError("experience requires source and reason")
    if (
        not isinstance(attribution, dict)
        or attribution.get("status") not in {"confirmed", "uncertain", "unknown"}
        or not isinstance(attribution.get("claims"), list)
    ):
        raise ValueError("invalid attribution")
    if not isinstance(value["opportunities"], list):
        raise ValueError("opportunities must be an array")
    return json.loads(canonical_bytes(dict(value)))


@dataclass
class PersonaCallTrace:
    """Raw trace of a single user agent LLM call (persisted in full first, filtered later).

    system/user preserve the complete original text for post-hoc analysis of KV reuse (high repetition → prompt optimization needed).
    raw = model original output; parsed = parsed contract JSON; steps = agentic inner tool process flow.
    """

    role: str
    system: str
    user: str
    raw: str
    parsed: dict[str, Any] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "role": self.role,
            "system": self.system,
            "user": self.user,
            "raw": self.raw,
            "parsed": dict(self.parsed),
        }
        if self.steps:
            d["steps"] = list(self.steps)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PersonaCallTrace:
        return cls(
            role=data.get("role", ""),
            system=data.get("system", ""),
            user=data.get("user", ""),
            raw=data.get("raw", ""),
            parsed=dict(data.get("parsed") or {}),
            steps=list(data.get("steps") or []),
        )


@dataclass
class SimTurn:
    """One turn from sim god-view: conversation fragment + reasoning co-located (aligned with user.sim.loop.TurnLog).

    Not 1:1 with Transcript — one SimTurn = one persona decision (including waiting heartbeat, silent self-observation);
    message / harness_output are the conversation fragment at that decision moment, perceive / verdict / action are the reasoning.
    persona_trace: the user agent LLM raw call triggered by this decision (including system/user for KV reuse analysis).
    Spec-0024/T6: utterance_id / delivery / queued_behind / answers_* explicitly pair requests and replies.
    """

    turn: int
    phase: str
    action_space: list[Any]
    perceive: str
    verdict: str
    action: str
    message: str
    executor: str
    channel: str
    patience: int
    trust: str
    harness_output: str = ""
    harness_steps: list[dict[str, Any]] = field(default_factory=list)
    harness_events: list[dict[str, Any]] = field(default_factory=list)
    persona_trace: list[PersonaCallTrace] = field(default_factory=list)
    utterance_id: str = ""
    delivery: str = ""
    queued_behind: str = ""
    answers_utterance_id: str = ""
    answers_said: str = ""
    goal_before: dict[str, Any] = field(default_factory=dict)
    goal_reading: list[dict[str, Any]] = field(default_factory=list)
    target_goal_ids: list[str] = field(default_factory=list)
    expected_progress: str = ""
    goal_updates: list[dict[str, Any]] = field(default_factory=list)
    goal_after: dict[str, Any] = field(default_factory=dict)
    goal_effect: dict[str, Any] = field(default_factory=dict)
    goal_field_audit: dict[str, Any] = field(default_factory=dict)
    acceptance_basis: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "turn": self.turn,
            "phase": self.phase,
            "action_space": list(self.action_space),
            "perceive": self.perceive,
            "verdict": self.verdict,
            "action": self.action,
            "message": self.message,
            "executor": self.executor,
            "channel": self.channel,
            "patience": self.patience,
            "trust": self.trust,
            "harness_output": self.harness_output,
        }
        if self.harness_steps:
            d["harness_steps"] = list(self.harness_steps)
        if self.harness_events:
            d["harness_events"] = list(self.harness_events)
        if self.persona_trace:
            d["persona_trace"] = [c.to_dict() for c in self.persona_trace]
        # Spec-0024/T6: default empty string is not serialized, compatible with older JSON
        if self.utterance_id:
            d["utterance_id"] = self.utterance_id
        if self.delivery:
            d["delivery"] = self.delivery
        if self.queued_behind:
            d["queued_behind"] = self.queued_behind
        if self.answers_utterance_id:
            d["answers_utterance_id"] = self.answers_utterance_id
        if self.answers_said:
            d["answers_said"] = self.answers_said
        if self.goal_before:
            d["goal_before"] = dict(self.goal_before)
        if self.goal_reading:
            d["goal_reading"] = [dict(item) for item in self.goal_reading]
        if self.target_goal_ids:
            d["target_goal_ids"] = list(self.target_goal_ids)
        if self.expected_progress:
            d["expected_progress"] = self.expected_progress
        if self.goal_updates:
            d["goal_updates"] = [dict(item) for item in self.goal_updates]
        if self.goal_after:
            d["goal_after"] = dict(self.goal_after)
        if self.goal_effect:
            d["goal_effect"] = dict(self.goal_effect)
        if self.goal_field_audit:
            d["goal_field_audit"] = dict(self.goal_field_audit)
        if self.acceptance_basis:
            d["acceptance_basis"] = dict(self.acceptance_basis)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SimTurn:
        return cls(
            turn=data["turn"],
            phase=data["phase"],
            action_space=list(data.get("action_space", [])),
            perceive=data.get("perceive", ""),
            verdict=data.get("verdict", ""),
            action=data.get("action", ""),
            message=data.get("message", ""),
            executor=data.get("executor", ""),
            channel=data.get("channel", ""),
            patience=int(data.get("patience", 0)),
            trust=data.get("trust", ""),
            harness_output=data.get("harness_output", ""),
            harness_steps=list(data.get("harness_steps", [])),
            harness_events=list(data.get("harness_events", [])),
            persona_trace=[PersonaCallTrace.from_dict(c) for c in data.get("persona_trace", [])],
            utterance_id=str(data.get("utterance_id") or ""),
            delivery=str(data.get("delivery") or ""),
            queued_behind=str(data.get("queued_behind") or ""),
            answers_utterance_id=str(data.get("answers_utterance_id") or ""),
            answers_said=str(data.get("answers_said") or ""),
            goal_before=dict(data.get("goal_before") or {}),
            goal_reading=[dict(item) for item in data.get("goal_reading", [])],
            target_goal_ids=[str(item) for item in data.get("target_goal_ids", [])],
            expected_progress=str(data.get("expected_progress") or ""),
            goal_updates=[dict(item) for item in data.get("goal_updates", [])],
            goal_after=dict(data.get("goal_after") or {}),
            goal_effect=dict(data.get("goal_effect") or {}),
            goal_field_audit=dict(data.get("goal_field_audit") or {}),
            acceptance_basis=dict(data.get("acceptance_basis") or {}),
        )


@dataclass
class SimTrace:
    """Complete decision trace of one session (SessionResult persistent projection).

    transcript is still the conversation projection (for dashboards / aggregation); sim_trace is the authoritative decision timeline.
    persona_tail: calls not attached to any turn at session end (file_issue body / subjective rating).
    Old sessions lack this field → None.
    """

    persona_id: str
    end_reason: str
    turns: list[SimTurn] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)
    feeling_derived: FeelingScore | None = None
    persona_tail: list[PersonaCallTrace] = field(default_factory=list)
    # valid | invalid. invalid indicates the user evaluator's own protocol/parsing failure, not harness task failure.
    evaluation_status: str = "valid"
    evaluation_error: dict[str, Any] | None = None
    # completed | protocol_repaired | protocol_unrecoverable; separate from evaluation_status,
    # old sessions default to completed.
    interaction_status: str = "completed"
    # Raw protocol recovery evidence (malformed output, parser code, attempt number).
    protocol_events: list[dict[str, Any]] = field(default_factory=list)
    goal_ledger: dict[str, Any] = field(default_factory=dict)
    goal_acceptance: dict[str, Any] | None = None
    goal_audit: dict[str, Any] = field(default_factory=dict)
    terminal_audit: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "persona_id": self.persona_id,
            "end_reason": self.end_reason,
            "turns": [t.to_dict() for t in self.turns],
            "signals": list(self.signals),
        }
        if self.feeling_derived is not None:
            d["feeling_derived"] = self.feeling_derived.to_dict()
        if self.persona_tail:
            d["persona_tail"] = [c.to_dict() for c in self.persona_tail]
        if self.evaluation_status != "valid":
            d["evaluation_status"] = self.evaluation_status
        if self.evaluation_error is not None:
            d["evaluation_error"] = dict(self.evaluation_error)
        if self.interaction_status != "completed":
            d["interaction_status"] = self.interaction_status
        if self.protocol_events:
            d["protocol_events"] = [dict(event) for event in self.protocol_events]
        if self.goal_ledger:
            d["goal_ledger"] = dict(self.goal_ledger)
        if self.goal_acceptance is not None:
            d["goal_acceptance"] = dict(self.goal_acceptance)
        if self.goal_audit:
            d["goal_audit"] = dict(self.goal_audit)
        if self.terminal_audit:
            d["terminal_audit"] = dict(self.terminal_audit)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SimTrace:
        fd = data.get("feeling_derived")
        return cls(
            persona_id=data["persona_id"],
            end_reason=data["end_reason"],
            turns=[SimTurn.from_dict(t) for t in data.get("turns", [])],
            signals=list(data.get("signals", [])),
            feeling_derived=FeelingScore.from_dict(fd) if fd else None,
            persona_tail=[PersonaCallTrace.from_dict(c) for c in data.get("persona_tail", [])],
            evaluation_status=str(data.get("evaluation_status") or "valid"),
            evaluation_error=(
                dict(data["evaluation_error"])
                if isinstance(data.get("evaluation_error"), dict)
                else None
            ),
            interaction_status=str(data.get("interaction_status") or "completed"),
            protocol_events=[dict(event) for event in data.get("protocol_events", [])],
            goal_ledger=dict(data.get("goal_ledger") or {}),
            goal_acceptance=(
                dict(data["goal_acceptance"])
                if isinstance(data.get("goal_acceptance"), dict)
                else None
            ),
            goal_audit=dict(data.get("goal_audit") or {}),
            terminal_audit=dict(data.get("terminal_audit") or {}),
        )


@dataclass
class IssueDraft:
    """Issue draft produced by user agent (title/body/labels), 0..n per session. Aligns with Gitea issue creation parameters."""

    title: str
    body: str
    labels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "body": self.body, "labels": list(self.labels)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IssueDraft:
        return cls(
            title=data["title"],
            body=data["body"],
            labels=list(data.get("labels", [])),
        )


@dataclass
class OpenIssue:
    """One issue read back from tracker (number/title/body/labels/state).

    Used by developer side to claim issues (spec-0003/T3): IssueTracker's write path produces IssueRef, read path (list_open_issues) produces OpenIssue.
    """

    number: int
    title: str
    body: str
    labels: list[str] = field(default_factory=list)
    state: str = "open"

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "body": self.body,
            "labels": list(self.labels),
            "state": self.state,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpenIssue:
        return cls(
            number=data["number"],
            title=data["title"],
            body=data["body"],
            labels=list(data.get("labels", [])),
            state=data.get("state", "open"),
        )


@dataclass
class IssueRef:
    """Receipt after issue submission to Gitea (number/url/state); locally stored as receipt only, authoritative source is Gitea."""

    number: int
    url: str
    state: str

    def to_dict(self) -> dict[str, Any]:
        return {"number": self.number, "url": self.url, "state": self.state}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IssueRef:
        return cls(number=data["number"], url=data["url"], state=data["state"])


@dataclass
class Session:
    """Complete encapsulation of one session: aggregates persona/scenario/transcript/feeling/issue_refs, with built-in id and timestamp.

    session_id and created_at default to auto-generation (need not be explicitly passed at T4 construction), to_dict/from_dict preserve fidelity.
    sim_trace: optional god-view (decision timeline); default None, backward compatible with old JSON lacking this key.
    """

    persona: Persona
    scenario: SeedScenario
    transcript: Transcript
    feeling: FeelingScore | None = None
    issue_refs: list[IssueRef] = field(default_factory=list)
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime = field(default_factory=datetime.now)
    sim_trace: SimTrace | None = None
    user_outcome: dict[str, Any] = field(default_factory=dict)
    request_outcomes: list[dict[str, Any]] = field(default_factory=list)
    workspace_evidence: dict[str, Any] = field(default_factory=dict)
    objective_evaluation: dict[str, Any] | None = None
    accept_validity: str = "not_applicable"
    audit_events: list[dict[str, Any]] = field(default_factory=list)
    # Spec-0055: deterministic user→demand handoff.  Kept optional for old
    # sessions; SessionStore can reconstruct an unavailable/legacy envelope.
    user_feedback_envelope: dict[str, Any] = field(default_factory=dict)
    # Spec-0073/T4: one frozen source of session, task and persona ownership.
    session_provenance: dict[str, Any] = field(default_factory=dict)

    # Spec-0084/T1: optional only for read-only historical records.
    feedback: dict[str, Any] = field(default_factory=dict)
    execution_contract: dict[str, Any] = field(default_factory=dict)
    execution_receipt: dict[str, Any] = field(default_factory=dict)
    report_plan: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        if self.feedback:
            self.feedback = validate_feedback(self.feedback)
            experience = self.feedback["experience"]
            self.feeling = (
                FeelingScore(experience["score"], experience["reason"])
                if experience["status"] == "rated"
                else None
            )
        if self.execution_contract:
            from ahe_beta.execution_contract import validate_execution_contract

            self.execution_contract = validate_execution_contract(self.execution_contract)
            if self.execution_contract["session_id"] != self.session_id:
                raise ValueError("execution contract session identity mismatch")

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "persona": self.persona.to_dict(),
            "scenario": self.scenario.to_dict(),
            "transcript": self.transcript.to_dict(),
            "feeling": self.feeling.to_dict() if self.feeling is not None else None,
            "issue_refs": [r.to_dict() for r in self.issue_refs],
        }
        for name in ("feedback", "execution_contract", "execution_receipt"):
            if getattr(self, name):
                d[name] = dict(getattr(self, name))
        if self.report_plan is not None:
            d["report_plan"] = list(self.report_plan)
        if self.sim_trace is not None:
            d["sim_trace"] = self.sim_trace.to_dict()
        if self.user_outcome:
            d["user_outcome"] = dict(self.user_outcome)
        if self.request_outcomes:
            d["request_outcomes"] = [dict(row) for row in self.request_outcomes]
        if self.workspace_evidence:
            d["workspace_evidence"] = dict(self.workspace_evidence)
        if self.objective_evaluation is not None:
            d["objective_evaluation"] = dict(self.objective_evaluation)
        d["accept_validity"] = self.accept_validity
        if self.audit_events:
            d["audit_events"] = [dict(row) for row in self.audit_events]
        if self.session_provenance:
            d["session_provenance"] = dict(self.session_provenance)
        if self.user_feedback_envelope:
            d["user_feedback_envelope"] = dict(self.user_feedback_envelope)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        st = data.get("sim_trace")
        return cls(
            persona=Persona.from_dict(data["persona"]),
            scenario=SeedScenario.from_dict(data["scenario"]),
            transcript=Transcript.from_dict(data["transcript"]),
            feeling=FeelingScore.from_dict(data["feeling"]) if data.get("feeling") else None,
            issue_refs=[IssueRef.from_dict(r) for r in data.get("issue_refs", [])],
            session_id=data["session_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            sim_trace=SimTrace.from_dict(st) if st else None,
            user_outcome=dict(data.get("user_outcome") or {}),
            request_outcomes=[dict(row) for row in data.get("request_outcomes", [])],
            workspace_evidence=dict(data.get("workspace_evidence") or {}),
            objective_evaluation=(
                dict(data["objective_evaluation"])
                if isinstance(data.get("objective_evaluation"), dict)
                else None
            ),
            accept_validity=str(data.get("accept_validity") or "not_applicable"),
            audit_events=[dict(row) for row in data.get("audit_events", [])],
            user_feedback_envelope=dict(data.get("user_feedback_envelope") or {}),
            session_provenance=dict(data.get("session_provenance") or {}),
            feedback=dict(data.get("feedback") or {}),
            execution_contract=dict(data.get("execution_contract") or {}),
            execution_receipt=dict(data.get("execution_receipt") or {}),
            report_plan=data.get("report_plan"),
        )


def bound_session_provenance() -> dict[str, Any]:
    """Read the immutable experiment binding; legacy sessions have no binding."""
    from ahe_beta.usage import current_usage_context

    ctx = current_usage_context()
    if ctx.task_digest is None:
        return {}
    result = {
        "contract_version": 1,
        **{
            name: getattr(ctx, name)
            for name in (
                "run_id",
                "round_no",
                "slot",
                "persona_id",
                "task_id",
                "task_digest",
                "task_kind",
                "harness_sha",
            )
        },
    }
    # Interaction belongs to the frozen task, and is bound before provisioning.
    result["interaction"] = ctx.interaction_mode
    if any(value is None for value in result.values()):
        raise ValueError("incomplete logical session provenance")
    return result


def validate_session_provenance(
    session: Session, expected: Mapping[str, Any] | None = None
) -> None:
    """Reject wrong-task results before authoritative save, index repair or admission."""
    provenance = session.session_provenance
    if not provenance:
        if expected:
            raise ValueError("session has no frozen provenance")
        return
    required = {
        "contract_version",
        "run_id",
        "round_no",
        "slot",
        "persona_id",
        "task_id",
        "task_digest",
        "task_kind",
        "interaction",
        "harness_sha",
    }
    if (
        set(provenance) != required
        or type(provenance.get("contract_version")) is not int
        or provenance.get("contract_version") != 1
    ):
        raise ValueError("invalid session provenance contract")
    if (
        isinstance(provenance["round_no"], bool)
        or not isinstance(provenance["round_no"], int)
        or provenance["round_no"] < 1
        or isinstance(provenance["slot"], bool)
        or not isinstance(provenance["slot"], int)
        or provenance["slot"] < 0
    ):
        raise ValueError("invalid session provenance round/slot")
    if session.persona.identity != provenance["persona_id"] or session.scenario.workspace is None:
        raise ValueError("session persona/workspace provenance mismatch")
    if (
        any(
            not isinstance(provenance[key], str) or not provenance[key]
            for key in (
                "run_id",
                "persona_id",
                "task_id",
                "task_digest",
                "task_kind",
                "interaction",
                "harness_sha",
            )
        )
        or provenance["task_kind"] not in {"ordinary", "swebench", "benchmark"}
        or provenance["interaction"] not in {"direct", "simulated_user"}
    ):
        raise ValueError("invalid session provenance identities")
    if session.sim_trace is not None and session.sim_trace.persona_id != provenance["persona_id"]:
        raise ValueError("session trace persona provenance mismatch")
    params = session.scenario.workspace.params
    for key in ("task_id", "task_digest", "task_kind", "interaction"):
        if params.get(key) != provenance[key]:
            raise ValueError(f"session {key} provenance mismatch")
    if expected and dict(expected) != provenance:
        raise ValueError("session does not match its immutable logical binding")
