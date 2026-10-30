"""把 spec-0005 控制信封 sim 用户 agent 接进 spec-0003/0007 闭环。

Orchestrator 只认 run_session_fn(persona, scenario, harness)（返回值不管，落盘/提交由实现负责）。
本模块产出这样一个 fn：内部跑 sim.loop.run_session（真 persona LLM × 真 harness），逐轮经 on_turn
回调供观测层（看板）实时展示；会话末把 issue_artifact 提交到真 tracker、SessionResult 转 models.Session
落 store。persona 以 9 维 sim persona 为准，展示用 models.Persona 由调用方反向派生后按 identity 配对传入。
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import uuid
from collections.abc import Callable
from pathlib import Path

from auto_designer.demand.issue_schema import NEEDS_TRIAGE, round_label
from auto_designer.harness.connector import HarnessConnector
from auto_designer.harness.interface import HarnessInterface
from auto_designer.loop.recovery import operation_key
from auto_designer.models import (
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
from auto_designer.tracker.base import IssueTracker
from auto_designer.usage import bind_usage_context, current_usage_context
from auto_designer.user.patches import preserve_prediction
from auto_designer.user.session_store import SessionStore
from auto_designer.user.sim.deps import ensure_deps
from auto_designer.user.sim.dimensions import Persona as SimPersona
from auto_designer.user.sim.feeling import experience_feedback
from auto_designer.user.sim.loop import SessionResult
from auto_designer.user.sim.loop import run_session as sim_run_session
from auto_designer.user.sim.persona_client import PersonaClient
from auto_designer.user.sim.runtime import (
    ReviewSnapshot,
    Workspace,
    as_runtime,
    capture_review_snapshot,
    utc_now,
)
from auto_designer.user.sim.workspace import materialize as materialize_workspace

# 观测回调：(identity, sim_persona, 进行中/最终的 SessionResult, running, *, session_id) -> None。
# session_id 仅收尾（running=False）时携带（session 已落 store），供看板归档关联全量会话。
SimTurnHook = Callable[..., None]


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
    from auto_designer.evaluation.artifacts import collect_session_artifacts

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
    *, workspace, scenario, store, session_id, provenance, evidence
) -> ReviewSnapshot:
    """One actor output boundary for both modes; review never re-exports its own modifications."""
    if workspace is None:
        evidence["prediction_error"] = {"status": "unavailable", "reason": "no_workspace"}
        return ReviewSnapshot({}, omissions=["no_workspace"])
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
            return ReviewSnapshot({}, omissions=["actor_not_quiescent"])
        patch, _ = _export_prediction(
            workspace=workspace, store=store, session_id=session_id, evidence=evidence
        )
        files = {}
        for row in evidence["evaluation_artifacts"]["entries"]:
            if row["status"] == "collected":
                data = (store.root.parent / row["path"]).read_bytes()
                if hashlib.sha256(data).hexdigest() != row["sha256"]:
                    raise ValueError("frozen artifact digest changed")
                files[f"artifacts/{row['id']}"] = data
        snapshot = capture_review_snapshot(workspace, patch=patch, files=files)
        evidence["review_snapshot"] = dict(snapshot.evidence)
        return snapshot
    finally:
        workspace.close()
        for key, value in dict(getattr(workspace, "evidence", {}) or {}).items():
            if key not in {"prediction", "diff_sha256", "diff_bytes"}:
                evidence[key] = value


def _execution_contract(*, session_id, scenario, provenance, harness, direct):
    from auto_designer.execution_contract import canonical_sha256, make_execution_contract

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
    from auto_designer.execution_contract import canonical_sha256

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
    from auto_designer.demand.evidence_contract import build_evidence_envelope
    from auto_designer.execution_contract import canonical_sha256
    from auto_designer.user.session_store import _atomic_json

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


def _save_and_publish(session: Session, *, tracker, store) -> Session:
    from auto_designer.demand.evidence_contract import build_evidence_envelope

    session.user_feedback_envelope = build_evidence_envelope(session).to_dict()
    store.save(session)
    return _publish_reports(session, tracker=tracker, store=store)


def _export_prediction(
    *, workspace: Workspace, store: SessionStore, session_id: str, evidence: dict
) -> tuple[str, str]:
    """Spec-0075/T1: export and preserve full bytes before session save/cleanup."""
    evidence.update(dict(getattr(workspace, "evidence", {}) or {}))
    evidence.pop("prediction", None)
    try:
        if evidence.get("diff_base_error"):
            raise RuntimeError("original patch base could not be captured")
        patch, patch_sha = workspace.export_patch()
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
    """SessionResult → models.Turn 序列：每轮先 harness 文本、后 user 消息（空则跳过）。

    `TurnLog.harness_output` 是「本轮 persona 看到的*上一轮* harness 回复」快照，可能跨空转
    轮重复携带同一值。故按「相邻去重」只在 harness
    回复真正变化（= 有新一轮回复）时记一条 harness 轮，否则同一条 completion 会被展开成多条、
    与 user 消息错位（曾使落盘 transcript 现 `user, harness×N, user` 的假象）。
    """
    turns: list[Turn] = []
    prev_ho: str | None = None
    for t in res.turns:
        ho = t.harness_output.strip()
        if ho and ho != prev_ho:  # 仅新一轮 harness 回复才记，连续相同快照视为同一条
            # steps = 该回复的内层迭代过程（观测层展开才看，persona 只吃 content）
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
    # 悬挂中的 harness 回复（已到手、尚未随下一条 TurnLog 落日志）：实时快照补上这半边
    pending = (res.pending_harness_output or "").strip()
    if pending and pending != prev_ho:
        turns.append(
            Turn(role="harness", content=pending, steps=list(res.pending_harness_steps or []))
        )
    return turns


def result_to_sim_trace(res: SessionResult) -> SimTrace:
    """SessionResult → 可落盘的 god-view：TurnLog 决策时间线原样投影，心路与对话片段同条共置。"""
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
    """Spec-0025/T2：粗判 issue kind（type 标签）。sim issue 绝大多数是失败/不满驱动 → bug；
    出现明确"希望/能不能/增加/支持…"这类诉求词则猜 feature。**只是暂定**——triage agent 会确认/纠正。
    """
    text = (body or "").lower()
    feature_hints = ("希望", "能不能", "增加", "支持", "feature", "would be nice", "add a", "wish")
    return "feature" if any(h in text for h in feature_hints) else "bug"


def _issue_draft_from_body(body: str, *, round_no: int | None = None) -> IssueDraft:
    """raw 用户 issue → Gitea 建 issue 入参（Spec-0025/T2）。

    body = 用户可见报告原文（persona 第一人称，用户看不到代码 → 只有用户视角症状）。标签三件套：
    暂定 type(bug/feature，triage 会确认) + `needs-triage`(待 triage，dev 不领) + 可选 `round-N`。
    标题取正文首行。TRIAGE 区字段（根因/边界/验收）留空待 triage agent 读码+轨迹补。
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
    """返回 Orchestrator 用的 run_session_fn。

    client_factory: 每局新建 persona client（Spec-0017/T2）。AgenticPersonaClient 是会话级
    有状态的（bind_session 写 _persona/_workspace_dir），a 段多用户会话并行后跨局复用单实例
    必串台（后 bind 覆盖先 bind）；底层 ApiPersonaClient.complete 无会话态可全局共享，工厂
    只新建外壳。
    sim_personas: 展示用 models.Persona.identity -> 9 维 sim persona（权威画像）。
    on_turn: 逐轮（含终止轮）+ 收尾各回调一次，供调用方发 agent 活动到看板。
    round_provider: Spec-0025/T6——每局收尾建 issue 前调一次取当前轮号，给 raw issue 盖 `round-N`
    标签（供增量 triage 与观测曲线）。None（或返回 None）则不盖轮号，兼容旧调用。
    """

    observation_root = Path(
        os.environ.get("AUTO_DESIGNER_OBSERVATION_ROOT", str(store.root.parent / "observations"))
    )
    # Spec-0070/T3: preserve the old framework contract while freezing checked transport.
    from auto_designer.observations.preflight import prepare_observations

    prepare_observations(tracker=tracker, root=observation_root)

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
            return _publish_reports(recovered, tracker=tracker, store=store)
        client = client_factory()  # Spec-0017/T2：每局独立实例，bind 互不覆盖

        # spec-0008/T1 v2：共享工作区。orchestrator 每局先 materialize 一份工作区，经 launcher 注入
        # harness（SANDBOX_WORK_DIR）并把同一目录 workspace_dir 传到这里——两侧 cwd 同指一处，harness
        # 改、用户 agent 同目录核实。这里复用传入目录绑定内层 client，不再自行 materialize。
        # 兼容直连调用（不经 orchestrator）：未传 workspace_dir 但 scenario 带 workspace 时，回落自行
        # materialize（等价 v1）。守卫式 bind_session：仅 AgenticPersonaClient 暴露，Scripted/Api 跳过。
        ws = as_runtime(workspace_dir) if workspace_dir is not None else None
        if ws is None and scenario.workspace is not None:
            ws = as_runtime(materialize_workspace(scenario.workspace), owns_tmp=True)
            # Spec-0009/T3：回落路径 materialize 后对称调 ensure_deps（与 orchestrator 主路径同构），
            # 使这条生产接缝「建了工作区即备好依赖」，不静默缺依赖。orchestrator 已传 workspace_dir
            # 的主路径依赖由 orchestrator 就位，故仅在此回落分支 ensure，不重复调。
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

        def freeze_before_review() -> None:
            nonlocal actor_closed
            if actor_closed:
                return
            actor_closed = True
            connector.close()
            source = getattr(harness, "observation_source", None)
            if source is not None:
                workspace_evidence["observation"] = source.collect(
                    root=observation_root, session_id=session_id
                )
            snapshot = _freeze_actor_outputs(
                workspace=ws,
                scenario=scenario,
                store=store,
                session_id=session_id,
                provenance=provenance,
                evidence=workspace_evidence,
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
                )
            finally:
                freeze_before_review()
        request_outcomes = [dict(row) for row in (getattr(harness, "request_outcomes", None) or [])]

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
            execution_contract=execution_contract,
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
        _save_and_publish(session, tracker=tracker, store=store)
        if on_turn is not None:
            # 收尾：标 running=False，带 session_id 供看板归档关联全量会话。
            on_turn(persona.identity, sim_persona, res, False, session_id=session.session_id)
        return session

    # The orchestrator uses this read path to reconcile a crash after SessionStore
    # committed but before the recovery completion marker was published.
    def load_completed_session(session_id):
        session = store.reconcile(session_id, expected_provenance=bound_session_provenance())
        return (
            _publish_reports(session, tracker=tracker, store=store) if session is not None else None
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
        os.environ.get("AUTO_DESIGNER_OBSERVATION_ROOT", str(store.root.parent / "observations"))
    )
    # Spec-0070/T3: preserve the old framework contract while freezing checked transport.
    from auto_designer.observations.preflight import prepare_observations

    prepare_observations(tracker=tracker, root=observation_root)

    def run(
        persona: Persona,
        scenario: SeedScenario,
        harness: HarnessInterface,
        *,
        workspace_dir: Workspace | None = None,
    ) -> Session:
        from auto_designer.user.sim.persona_client import drain_call_traces
        from auto_designer.user.sim.prompt import build_direct_review_turn, build_system

        params = dict((scenario.workspace.params if scenario.workspace else {}) or {})
        task_key = str(params.get("task_key") or persona.identity or "direct-task")
        session_id = current_usage_context().session_id or uuid.uuid4().hex
        provenance = bound_session_provenance()
        recovered = store.reconcile(session_id, expected_provenance=provenance)
        if recovered is not None:
            return _publish_reports(recovered, tracker=tracker, store=store)
        connector = HarnessConnector(harness)
        round_no = round_provider() if round_provider else current_usage_context().round_no
        reply = ""
        harness_error = None
        workspace_evidence: dict = {}
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
            connector.close()
            source = getattr(harness, "observation_source", None)
            if source is not None:
                workspace_evidence["observation"] = source.collect(
                    root=observation_root, session_id=session_id
                )
        snapshot = _freeze_actor_outputs(
            workspace=workspace_dir,
            scenario=scenario,
            store=store,
            session_id=session_id,
            provenance=provenance,
            evidence=workspace_evidence,
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
            request_outcomes=list(getattr(harness, "request_outcomes", []) or []),
            workspace_evidence=workspace_evidence,
            accept_validity="not_applicable",
            audit_events=_audit_events(
                workspace_evidence=workspace_evidence,
                request_outcomes=list(getattr(harness, "request_outcomes", []) or []),
            ),
        )
        validate_session_provenance(session, provenance)
        return _save_and_publish(session, tracker=tracker, store=store)

    def load_completed_session(session_id):
        session = store.reconcile(session_id, expected_provenance=bound_session_provenance())
        return (
            _publish_reports(session, tracker=tracker, store=store) if session is not None else None
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

    run.load_completed_session = simulated.load_completed_session
    return run
