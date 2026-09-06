"""把 spec-0005 控制信封 sim 用户 agent 接进 spec-0003/0007 闭环。

Orchestrator 只认 run_session_fn(persona, scenario, harness)（返回值不管，落盘/提交由实现负责）。
本模块产出这样一个 fn：内部跑 sim.loop.run_session（真 persona LLM × 真 harness），逐轮经 on_turn
回调供观测层（看板）实时展示；会话末把 issue_artifact 提交到真 tracker、SessionResult 转 models.Session
落 store。persona 以 9 维 sim persona 为准，展示用 models.Persona 由调用方反向派生后按 identity 配对传入。
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable

from auto_designer.designer.issue_schema import NEEDS_TRIAGE, round_label
from auto_designer.evaluation.swebench import SWEbenchEvaluator, derive_accept_validity
from auto_designer.harness.connector import HarnessConnector
from auto_designer.harness.interface import HarnessInterface
from auto_designer.models import (
    FeelingScore,
    IssueDraft,
    Persona,
    PersonaCallTrace,
    SeedScenario,
    Session,
    SimTrace,
    SimTurn,
    Transcript,
    Turn,
)
from auto_designer.tracker.base import IssueTracker
from auto_designer.usage import bind_usage_context
from auto_designer.user.session_store import SessionStore
from auto_designer.user.sim.deps import ensure_deps
from auto_designer.user.sim.dimensions import Persona as SimPersona
from auto_designer.user.sim.loop import SessionResult
from auto_designer.user.sim.loop import run_session as sim_run_session
from auto_designer.user.sim.persona_client import PersonaClient
from auto_designer.user.sim.runtime import Workspace, as_runtime, utc_now
from auto_designer.user.sim.workspace import materialize as materialize_workspace

# 观测回调：(identity, sim_persona, 进行中/最终的 SessionResult, running, *, session_id) -> None。
# session_id 仅收尾（running=False）时携带（session 已落 store），供看板归档关联全量会话。
SimTurnHook = Callable[..., None]


def _audit_events(
    *,
    workspace_evidence: dict,
    request_outcomes: list[dict],
    objective_evaluation: dict | None,
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
    if objective_evaluation is not None:
        append(
            "objective_evaluation_terminal",
            str(objective_evaluation.get("finished_at") or ""),
            {
                "status": objective_evaluation.get("status"),
                "passed": objective_evaluation.get("passed"),
                "exit_code": objective_evaluation.get("exit_code"),
                "patch_sha256": objective_evaluation.get("patch_sha256"),
            },
        )
    return events


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


def _issue_draft(res: SessionResult) -> IssueDraft:
    """兼容旧单测：仅从终结收场的 issue_artifact 建 draft（无轮号）。"""
    return _issue_draft_from_body(res.issue_artifact or "")


def _flush_issues(
    tracker: IssueTracker, res: SessionResult, *, round_no: int | None = None
) -> list:
    """中途 report_issue notes + 终结 issue_artifact 一并建单（顺序：先中途、后收场）。

    round_no 由编排层透传（Spec-0025/T6）：给每条 raw issue 盖 `round-N`，供增量 triage 与观测曲线。
    """
    refs = []
    for body in res.issue_notes:
        refs.append(tracker.create_issue(_issue_draft_from_body(body, round_no=round_no)))
    if res.issue_artifact:
        refs.append(
            tracker.create_issue(_issue_draft_from_body(res.issue_artifact, round_no=round_no))
        )
    return refs


def make_sim_run_session_fn(
    *,
    client_factory: Callable[[], PersonaClient],
    tracker: IssueTracker,
    store: SessionStore,
    sim_personas: dict[str, SimPersona],
    on_turn: SimTurnHook | None = None,
    round_provider: Callable[[], int | None] | None = None,
    evaluator: SWEbenchEvaluator | None = None,
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

    def run(
        persona: Persona,
        scenario: SeedScenario,
        harness: HarnessInterface,
        *,
        workspace_dir: Workspace | None = None,
    ) -> Session:
        sim_persona = sim_personas[persona.identity]
        session_id = uuid.uuid4().hex
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
        if ws is not None and hasattr(client, "bind_session"):
            client.bind_session(persona=sim_persona, workspace_dir=ws)

        def progress(partial: SessionResult) -> None:
            if on_turn is not None:
                on_turn(persona.identity, sim_persona, partial, True, session_id=None)

        connector = HarnessConnector(harness)
        connector.reset()  # 开局责任归编排层；connector 只做平台侧适配，不把平台元数据传入 harness
        instance_id = None
        if scenario.workspace is not None:
            instance_id = scenario.workspace.params.get("instance_id")
        round_no = round_provider() if round_provider is not None else None
        with bind_usage_context(
            session_id=session_id,
            instance_id=instance_id,
            role="user",
            agent_id=f"user-{persona.identity}",
            round_no=round_no,
            operation="persona",
        ):
            try:
                res = sim_run_session(
                    sim_persona,
                    client,
                    connector,
                    scenario.description,
                    # 该版本 harness 的帮助文本：让 persona 的能力预期锚定"这工具文档说的"，
                    # 而非空泛先验；缺省空串（后端无 help_text 属性时为空）。
                    help_text=connector.help_text,
                    on_progress=progress,
                )
            finally:
                # 关闭时才到达的 usage 仍须继承本 session/instance/turn 归属。
                connector.close()  # 无论成败都释放 harness 子进程

        request_outcomes = [dict(row) for row in (getattr(harness, "request_outcomes", None) or [])]
        patch = ""
        patch_sha = ""
        workspace_evidence: dict = {}
        if ws is not None:
            try:
                patch, patch_sha = ws.export_patch()
                workspace_evidence["patch_exported_at"] = utc_now()
            except Exception as exc:  # noqa: BLE001 - evidence must fail closed
                workspace_evidence["patch_export_error"] = str(exc)
            workspace_evidence.update(dict(getattr(ws, "evidence", {}) or {}))
            if patch_sha:
                workspace_evidence["diff_sha256"] = patch_sha
                workspace_evidence["diff_bytes"] = len(patch.encode())
            # The interaction boundary is no longer needed once its patch is exported.
            # Close before the fresh official evaluation so stop evidence is durable.
            ws.close()
            workspace_evidence.update(dict(getattr(ws, "evidence", {}) or {}))

        objective_evaluation = None
        active_evaluator = evaluator if evaluator is not None else SWEbenchEvaluator.from_env()
        if active_evaluator is not None and instance_id and patch_sha:
            try:
                objective_evaluation = active_evaluator.evaluate(
                    instance_id=str(instance_id), patch=patch
                )
            except Exception as exc:  # noqa: BLE001 - persist failed verification as evidence
                objective_evaluation = {
                    "evaluator": "swebench.harness.run_evaluation",
                    "instance_id": str(instance_id),
                    "patch_sha256": patch_sha,
                    "status": "crashed",
                    "passed": False,
                    "error": str(exc),
                    "finished_at": utc_now(),
                }
        elif evaluator is None and os.environ.get(
            "AUTO_DESIGNER_OBJECTIVE_EVALUATION", "1"
        ).strip().lower() in {"0", "false", "no", "off", "skip"}:
            # Preserve an explicit audit marker; skipped is not a pass.
            objective_evaluation = {
                "evaluator": "swebench.harness.run_evaluation",
                "instance_id": str(instance_id) if instance_id else None,
                "patch_sha256": patch_sha or None,
                "status": "skipped",
                "passed": None,
                "reason": "disabled_by_experiment_config",
                "finished_at": utc_now(),
            }
        accept_validity = derive_accept_validity(
            end_reason=res.end_reason,
            request_outcomes=request_outcomes,
            evaluation=objective_evaluation,
        )
        terminal_note = next(
            (
                t.message.strip()
                for t in reversed(res.turns)
                if t.action in {"accept", "accept_with_reservations", "file_issue", "give_up"}
                and t.message.strip()
            ),
            "",
        )

        round_no = round_provider() if round_provider is not None else None
        issue_refs = _flush_issues(tracker, res, round_no=round_no)
        feel = res.feeling or res.feeling_derived
        session = Session(
            persona=persona,
            scenario=scenario,
            transcript=Transcript(turns=result_to_turns(res)),
            feeling=FeelingScore(score=feel.score, reason=feel.reason),
            issue_refs=issue_refs,
            sim_trace=result_to_sim_trace(res),
            session_id=session_id,
            user_outcome={"end_reason": res.end_reason, "terminal_note": terminal_note},
            request_outcomes=request_outcomes,
            workspace_evidence=workspace_evidence,
            objective_evaluation=objective_evaluation,
            accept_validity=accept_validity,
            audit_events=_audit_events(
                workspace_evidence=workspace_evidence,
                request_outcomes=request_outcomes,
                objective_evaluation=objective_evaluation,
            ),
        )
        # Spec-0055/T2: materialize the bounded, deterministic user feedback
        # handoff at session close.  Demand roles consume this projection rather
        # than reparsing the complete persona trace.
        from auto_designer.designer.evidence_contract import build_evidence_envelope

        session.user_feedback_envelope = build_evidence_envelope(session).to_dict()
        store.save(session)  # 体感 + session 落本地（issue 权威源在 Gitea）
        if on_turn is not None:
            # 收尾：标 running=False，带 session_id 供看板归档关联全量会话。
            on_turn(persona.identity, sim_persona, res, False, session_id=session.session_id)
        return session

    return run
