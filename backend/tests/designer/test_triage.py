# Spec-0029/T3：Triager 单测——三值 disposition（accept/reject/needs_info），accept 就地升 proposal。
"""stub agent（回放固定 submit_triage 返回）+ FakeTracker + 临时 SessionStore：验证 driver 把每条
disposition 正确落成三平面标签/评论/关闭；不判重；支持分片传入 pending。不跑真 nexau。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from auto_designer.designer import issue_schema as sc
from auto_designer.designer.triage import TriageOutcome, Triager, _proposal_labels, _proposal_title
from auto_designer.loop.recovery import RecoveryConflictError, RecoveryIdentity, RecoveryStore, operation_key
from auto_designer.models import IssueDraft
from auto_designer.tracker.fake import FakeTracker
from auto_designer.tracker.gitea import GiteaError, IssueMigrationError
from auto_designer.usage import bind_usage_context
from auto_designer.user.session_store import SessionStore


class _StubTriager(Triager):
    """覆盖 _run_agent：不跑真 nexau，回放固定 submit 返回，并记录喂进的 pending 集合。"""

    def __init__(self, *args, canned: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._canned = canned
        self.seen_pending: list = []
        self.agent_calls = 0

    def _run_agent(self, *, pending: list) -> str:
        self.agent_calls += 1
        self.seen_pending = pending
        return self._canned


def _triager(tmp_path: Path, tracker: FakeTracker, canned: str) -> _StubTriager:
    store = SessionStore(tmp_path / "sessions")
    return _StubTriager(
        tracker, store, str(tmp_path / "harness"), str(tmp_path / "agent_def"), canned=canned
    )


def _report(tracker: FakeTracker, title: str, kind: str = "bug") -> int:
    return tracker.create_issue(
        IssueDraft(title=title, body="x", labels=[kind, sc.REPORT, "round-1"])
    ).number


def _submit(dispositions: list) -> str:
    """打成 submit_triage 的返回形状（stop tool binding 的输出）。"""
    return json.dumps({"dispositions": dispositions}, ensure_ascii=False)


def _recovery(tmp_path: Path) -> RecoveryStore:
    store = RecoveryStore.initialize(
        root=tmp_path / "recovery",
        identity=RecoveryIdentity("exp", "run", "config", "controller", "plan"),
    )
    store.freeze_round(round_no=1, user_sha="user", plan=[])
    started = operation_key("round-started")
    store.begin_unit(
        round_no=1,
        stage="round_started",
        key=started,
        input_value={},
        expected_postconditions={"completed": True},
    )
    store.complete_unit(round_no=1, stage="round_started", key=started)
    store.complete_stage(round_no=1, stage="round_started")
    key = operation_key("users", "empty")
    store.begin_unit(
        round_no=1,
        stage="users",
        key=key,
        input_value={},
        expected_postconditions={"completed": True},
        dependencies=("round_started",),
    )
    store.complete_unit(round_no=1, stage="users", key=key)
    store.complete_stage(round_no=1, stage="users")
    return store


def _accept(n: int, *, kind: str = "bug", priority: str = "P1", fields: dict | None = None) -> dict:
    default_fields = {
        "根因区域": "entry.py 无预算感知",
        "边界": "只改通用能力",
        "验收": "预算内交付",
    }
    return {
        "issue": n,
        "disposition": "accept",
        "kind": kind,
        "priority": priority,
        "proposal_title": "精确任务执行缺少预算感知",
        "fields": fields if fields is not None else default_fields,
        "artifact": {
            "reported_problem": "任务执行超出预算",
            "user_impact": "用户未获得可用交付",
            "scope_boundary": "通用 harness 执行行为",
            "evidence": [f"report:#{n}"],
            "uncertainties": [],
            "implementation_target": "harness",
        },
    }


def test_submit_triage_yaml_matches_contract() -> None:
    """drift-guard：submit_triage.tool.yaml 的 input_schema 与 dispositions_input_schema() 深度相等。"""
    import yaml

    from auto_designer.designer.agent_contract import dispositions_input_schema

    p = (
        Path(__file__).resolve().parents[2]
        / "agent_defs"
        / "triage_agent"
        / "tools"
        / "submit_triage.tool.yaml"
    )
    tool_def = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert tool_def["input_schema"] == dispositions_input_schema()
    # 三值 enum：duplicate 已退役（跨提案吸收归 Designer）
    enum = tool_def["input_schema"]["properties"]["dispositions"]["items"]["properties"][
        "disposition"
    ]["enum"]
    assert enum == ["accept", "reject", "needs_info"]


def test_no_pending_is_noop(tmp_path) -> None:
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="已是提案", body="x", labels=["bug", sc.PROPOSAL]))
    t = _triager(tmp_path, tracker, _submit([]))
    out = t.triage_once()
    assert out.handled == 0
    assert t.agent_calls == 0  # 无 report → 不跑 LLM


def test_accept_promotes_report_to_proposal(tmp_path) -> None:
    tracker = FakeTracker()
    n = _report(tracker, "unidecode 超时", kind="bug")
    out = _triager(tmp_path, tracker, _submit([_accept(n)])).triage_once()

    assert isinstance(out, TriageOutcome) and out.accepted == [n]
    snap = tracker.issue(n)
    assert sc.PROPOSAL in snap["labels"] and sc.FROM_TRIAGE in snap["labels"]
    assert "bug" in snap["labels"] and "P1" in snap["labels"]
    assert sc.REPORT not in snap["labels"]  # 离开 report 平面
    assert "round-1" in snap["labels"]  # 属性保留
    assert snap["state"] == "open"
    # 提案不可领（由 Delivery Router 打 openagents 交接令牌后进入交付面）
    assert not sc.is_ready(labels=snap["labels"], state=snap["state"])
    assert sc.plane(snap["labels"]) == sc.PROPOSAL
    assert snap["body"].startswith("## Triage 规范化提案（实施对象：harness）")
    assert "entry.py 无预算感知" in snap["body"]
    assert snap["title"] == "精确任务执行缺少预算感知"
    assert "原始用户报告" not in snap["body"]
    assert any("原始标题" in c and "unidecode 超时" in c and "x" in c for c in snap["comments"])
    assert "根因区域" in snap["body"] and "entry.py 无预算感知" in snap["body"]


def test_long_multibyte_proposal_title_is_bounded_without_splitting_utf8(tmp_path) -> None:
    tracker = FakeTracker()
    number = _report(tracker, "原报告")
    disposition = _accept(number)
    model_title = "中文提案" * 35
    disposition["proposal_title"] = model_title

    outcome = _triager(tmp_path, tracker, _submit([disposition])).triage_once()

    title = tracker.issue(number)["title"]
    assert title == _proposal_title(model_title)
    assert model_title.startswith(title[:-1]) and title.endswith("…")
    assert len(title.encode("utf-8")) <= 240
    assert outcome.warnings[number] == ["proposal-title-shortened"]


def test_accept_old_needs_triage_data_also_works(tmp_path) -> None:
    """旧数据（needs-triage 标签）经 plane 映射进 pending，accept 后同样升 proposal、旧标签清除。"""
    tracker = FakeTracker()
    n = tracker.create_issue(
        IssueDraft(title="旧数据", body="x", labels=["bug", sc.NEEDS_TRIAGE, "round-2"])
    ).number
    out = _triager(tmp_path, tracker, _submit([_accept(n)])).triage_once()
    assert out.accepted == [n]
    snap = tracker.issue(n)
    assert sc.PROPOSAL in snap["labels"] and sc.NEEDS_TRIAGE not in snap["labels"]


def test_accept_reclassifies_kind(tmp_path) -> None:
    tracker = FakeTracker()
    n = _report(tracker, "其实是需求", kind="bug")  # sim 暂定 bug
    fields = {"边界": "只加通用能力", "交付物": "导出接口", "验收": "能批量导出"}
    out = _triager(
        tmp_path, tracker, _submit([_accept(n, kind="feature", priority="P2", fields=fields)])
    ).triage_once()
    assert out.accepted == [n]
    labels = tracker.issue(n)["labels"]
    assert "feature" in labels and "bug" not in labels  # 纠正 kind


def test_accept_invalid_priority_not_labeled(tmp_path) -> None:
    tracker = FakeTracker()
    n = _report(tracker, "超时")
    _triager(tmp_path, tracker, _submit([_accept(n, priority="紧急")])).triage_once()
    labels = tracker.issue(n)["labels"]
    assert sc.PROPOSAL in labels and not any(p in labels for p in sc.PRIORITIES)


def test_accept_missing_fields_downgrades_to_needs_info(tmp_path) -> None:
    tracker = FakeTracker()
    n = _report(tracker, "坏了")
    out = _triager(
        tmp_path, tracker, _submit([_accept(n, fields={"根因区域": "只填了这个"})])
    ).triage_once()
    assert out.needs_info == [n] and out.accepted == []
    snap = tracker.issue(n)
    assert sc.DECLINED in snap["labels"] and snap["state"] == "closed"


def test_accept_missing_normalized_title_downgrades_to_needs_info(tmp_path) -> None:
    tracker = FakeTracker()
    n = _report(tracker, "某被测对象的具体问题")
    disposition = _accept(n)
    disposition.pop("proposal_title")
    out = _triager(tmp_path, tracker, _submit([disposition])).triage_once()
    assert out.needs_info == [n] and out.accepted == []


@pytest.mark.parametrize(
    ("target", "bucket"),
    [("uncertain", "needs_info"), ("outside_harness", "rejected")],
)
def test_out_of_scope_accept_closes_report_and_recovery_unit(tmp_path, target, bucket) -> None:
    tracker = FakeTracker()
    number = _report(tracker, "缺少输入文件")
    frozen_issue = tracker.list_open_issues()[0]
    disposition = _accept(number)
    disposition["artifact"]["implementation_target"] = target
    disposition["reason"] = "文件接入的实现归属尚待确认"
    recovery = _recovery(tmp_path)
    triager = _StubTriager(
        tracker,
        SessionStore(tmp_path / "sessions"),
        str(tmp_path / "harness"),
        str(tmp_path / "agent"),
        canned=_submit([disposition]),
        recovery=recovery,
    )

    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        outcome = triager.triage_once(pending=[frozen_issue])

    assert getattr(outcome, bucket) == [number]
    assert outcome.accepted == [] and outcome.failed == {}
    assert outcome.warnings[number] == ["out-of-product-scope-normalized"]
    snap = tracker.issue(number)
    assert snap["state"] == "closed" and sc.DECLINED in snap["labels"]
    assert sc.PROPOSAL not in snap["labels"]
    assert any("原分诊为 accept" in comment and target in comment for comment in snap["comments"])
    unit = recovery.unit(
        round_no=1,
        stage="triage",
        key=operation_key("triage-worker-0", "report", number),
    )
    assert unit["status"] == "completed"
    assert unit["observed_postconditions"]["bucket"] == bucket


def test_accept_invalid_kind_downgrades(tmp_path) -> None:
    tracker = FakeTracker()
    n = _report(tracker, "怪 kind")
    out = _triager(tmp_path, tracker, _submit([_accept(n, kind="rfc")])).triage_once()
    assert out.needs_info == [n]


def test_reject_and_needs_info_decline_with_reason(tmp_path) -> None:
    tracker = FakeTracker()
    a = _report(tracker, "超范围的")
    b = _report(tracker, "说不清的")
    canned = _submit(
        [
            {"issue": a, "disposition": "reject", "reason": "要改的是 launcher（编排层）"},
            {"issue": b, "disposition": "needs_info", "reason": "轨迹无有效信息"},
        ]
    )
    out = _triager(tmp_path, tracker, canned).triage_once()
    assert out.rejected == [a] and out.needs_info == [b]
    for n in (a, b):
        snap = tracker.issue(n)
        assert sc.DECLINED in snap["labels"] and snap["state"] == "closed"
        assert sc.plane(snap["labels"]) is None  # 终态不在任何平面
    assert any("launcher" in c for c in tracker.issue(a)["comments"])


def test_no_submit_is_noop(tmp_path) -> None:
    """agent 没调 submit（散文返回）→ 本轮 no-op，report 原样留下轮。"""
    tracker = FakeTracker()
    n = _report(tracker, "留下轮")
    out = _triager(tmp_path, tracker, "我跑完了但没提交").triage_once()
    assert out.handled == 0
    assert sc.REPORT in tracker.issue(n)["labels"]  # 未被动过


def test_core_update_failure_is_reported_and_report_remains(tmp_path: Path) -> None:
    class BrokenUpdateTracker(FakeTracker):
        def update_issue(self, number: int, *, title: str, body: str, labels: list[str]) -> None:
            raise RuntimeError("write failed")

    tracker = BrokenUpdateTracker()
    n = _report(tracker, "具体案例")
    out = _triager(tmp_path, tracker, _submit([_accept(n)])).triage_once()
    assert n in out.failed and "write failed" in out.failed[n]
    assert out.accepted == []
    snap = tracker.issue(n)
    assert sc.REPORT in snap["labels"] and snap["title"] == "具体案例" and snap["body"] == "x"


def test_audit_comment_failure_is_warning_but_proposal_is_created(tmp_path: Path) -> None:
    class BrokenCommentTracker(FakeTracker):
        def add_comment(self, number: int, body: str) -> None:
            raise RuntimeError("comment failed")

    tracker = BrokenCommentTracker()
    n = _report(tracker, "具体案例")
    out = _triager(tmp_path, tracker, _submit([_accept(n)])).triage_once()
    assert out.accepted == [n]
    assert out.warnings[n] == ["原始报告审计评论写入失败"]
    assert sc.PROPOSAL in tracker.issue(n)["labels"]


def test_out_of_batch_issue_skipped(tmp_path) -> None:
    """disposition 指向不在本批的票号 → 跳过（防越界改动）。"""
    tracker = FakeTracker()
    n = _report(tracker, "在批内")
    out = _triager(tmp_path, tracker, _submit([_accept(999), _accept(n)])).triage_once()
    assert out.accepted == [n]


def test_shard_pending_param_scopes_batch(tmp_path) -> None:
    """Spec-0029/T8 分片支持：传入 pending 子集则只处理该子集，其余 report 不动、也不喂给 agent。"""
    tracker = FakeTracker()
    a = _report(tracker, "片内")
    b = _report(tracker, "片外")
    backlog = tracker.list_open_issues()
    shard = [i for i in backlog if i.number == a]
    t = _triager(tmp_path, tracker, _submit([_accept(a)]))
    out = t.triage_once(pending=shard)
    assert out.accepted == [a]
    assert [i.number for i in t.seen_pending] == [a]  # 只喂本片
    assert sc.REPORT in tracker.issue(b)["labels"]  # 片外不动


def test_proposal_labels_keep_attributes_only() -> None:
    cur = ["bug", sc.REPORT, "round-3", "misc"]
    out = _proposal_labels(cur, "feature", "P0")
    assert set(out) == {"misc", "round-3", "feature", sc.PROPOSAL, sc.FROM_TRIAGE, "P0"}


def test_recovery_replays_saved_triage_output_without_model_or_duplicate_comment(tmp_path) -> None:
    tracker = FakeTracker()
    number = _report(tracker, "recover me")
    frozen_issue = tracker.list_open_issues()[0]
    recovery = _recovery(tmp_path)

    class CrashBeforeCompletion(_StubTriager):
        crashed = False

        def _complete_recovery_item(self, **kwargs) -> None:
            if not self.crashed:
                self.crashed = True
                raise RuntimeError("injected after tracker apply")
            return super()._complete_recovery_item(**kwargs)

    first = CrashBeforeCompletion(
        tracker,
        SessionStore(tmp_path / "sessions"),
        str(tmp_path / "harness"),
        str(tmp_path / "agent"),
        canned=_submit([_accept(number)]),
        recovery=recovery,
    )
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        with pytest.raises(RuntimeError, match="injected"):
            first.triage_once(pending=[frozen_issue])
    assert sc.PROPOSAL in tracker.issue(number)["labels"]

    resumed = _StubTriager(
        tracker,
        SessionStore(tmp_path / "sessions"),
        str(tmp_path / "harness"),
        str(tmp_path / "agent"),
        canned="must not be used",
        recovery=recovery,
    )
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        outcome = resumed.triage_once(pending=[frozen_issue])
    assert outcome.accepted == [number]
    assert resumed.agent_calls == 0
    assert len(tracker.issue(number)["comments"]) == 1


@pytest.mark.parametrize("external_edit", [False, True])
def test_recovery_reconciles_partial_proposal_only_if_content_is_ours(tmp_path, external_edit) -> None:
    model_title = "中文提案" * 35

    class PartialWriteTracker(FakeTracker):
        fail_once = True

        def update_issue(self, number, *, title, body, labels):
            if self.fail_once:
                self.fail_once = False
                super().update_issue(number, title=model_title[:70] + "…", body=body, labels=labels)
                raise RuntimeError("simulated server title normalization")
            return super().update_issue(number, title=title, body=body, labels=labels)

    tracker = PartialWriteTracker()
    number = _report(tracker, "原报告")
    frozen_issue = tracker.list_open_issues()[0]
    disposition = _accept(number)
    disposition["proposal_title"] = model_title
    recovery = _recovery(tmp_path)
    args = (
        tracker, SessionStore(tmp_path / "sessions"),
        str(tmp_path / "harness"), str(tmp_path / "agent"),
    )
    first = _StubTriager(*args, canned=_submit([disposition]), recovery=recovery)
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        with pytest.raises(RecoveryConflictError, match="remain incomplete"):
            first.triage_once(pending=[frozen_issue])
    assert recovery.unit(
        round_no=1, stage="triage", key=operation_key("triage-worker-0", "report", number)
    )["output_digest"]

    if external_edit:
        current = tracker.issue(number)
        FakeTracker.update_issue(
            tracker, number, title=current["title"], body="human edit", labels=current["labels"]
        )
    resumed = _StubTriager(*args, canned="must not be used", recovery=recovery)
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        if external_edit:
            with pytest.raises(RecoveryConflictError, match="remain incomplete"):
                resumed.triage_once(pending=[frozen_issue])
        else:
            outcome = resumed.triage_once(pending=[frozen_issue])
            assert outcome.accepted == [number]
    assert resumed.agent_calls == 0
    assert len(tracker.issue(number)["comments"]) == 1
    if external_edit:
        assert tracker.issue(number)["body"] == "human edit"
    else:
        assert tracker.issue(number)["title"] == _proposal_title(model_title)


def test_recovery_retries_transient_read_without_rerunning_model(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("auto_designer.designer.triage.time.sleep", lambda _: None)

    class FlakyReadTracker(FakeTracker):
        reads = 0

        def get_issue(self, *, number):
            self.reads += 1
            if self.reads == 1:
                raise requests.ConnectionError("connection reset")
            return super().get_issue(number=number)

    tracker = FlakyReadTracker()
    number = _report(tracker, "原报告")
    frozen = tracker.list_open_issues()[0]
    recovery = _recovery(tmp_path)
    triager = _StubTriager(
        tracker, SessionStore(tmp_path / "sessions"), str(tmp_path / "harness"),
        str(tmp_path / "agent"), canned=_submit([_accept(number)]), recovery=recovery,
    )
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        result = triager.triage_once(pending=[frozen])
    assert result.accepted == [number] and result.failed == {}
    assert triager.agent_calls == 1 and tracker.reads == 2
    assert result.warnings[number] == ["tracker-write-retried"]
    assert len(tracker.issue(number)["comments"]) == 1
    assert recovery.unit(
        round_no=1, stage="triage", key=operation_key("triage-worker-0", "report", number)
    )["status"] == "completed"


def test_recovery_reconciles_lost_update_response_without_second_write(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("auto_designer.designer.triage.time.sleep", lambda _: None)

    class LostResponseTracker(FakeTracker):
        writes = 0

        def update_issue(self, number, *, title, body, labels):
            self.writes += 1
            super().update_issue(number, title=title, body=body, labels=labels)
            if self.writes == 1:
                raise requests.ConnectionError("response lost after write")

    tracker = LostResponseTracker()
    number = _report(tracker, "原报告")
    frozen = tracker.list_open_issues()[0]
    recovery = _recovery(tmp_path)
    triager = _StubTriager(
        tracker, SessionStore(tmp_path / "sessions"), str(tmp_path / "harness"),
        str(tmp_path / "agent"), canned=_submit([_accept(number)]), recovery=recovery,
    )
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        result = triager.triage_once(pending=[frozen])
    assert result.accepted == [number] and result.failed == {}
    assert tracker.writes == 1 and triager.agent_calls == 1
    assert len(tracker.issue(number)["comments"]) == 1


def test_recovery_reconciles_lost_decline_response_without_second_write(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("auto_designer.designer.triage.time.sleep", lambda _: None)

    class LostResponseTracker(FakeTracker):
        writes = 0

        def transition_issue(self, number, *, state, labels):
            self.writes += 1
            super().transition_issue(number, state=state, labels=labels)
            if self.writes == 1:
                raise requests.ConnectionError("response lost after close")

    tracker = LostResponseTracker()
    number = _report(tracker, "原报告")
    frozen = tracker.list_open_issues()[0]
    recovery = _recovery(tmp_path)
    disposition = {"issue": number, "disposition": "reject", "reason": "范围外"}
    triager = _StubTriager(
        tracker, SessionStore(tmp_path / "sessions"), str(tmp_path / "harness"),
        str(tmp_path / "agent"), canned=_submit([disposition]), recovery=recovery,
    )
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        result = triager.triage_once(pending=[frozen])
    assert result.rejected == [number] and result.failed == {}
    assert tracker.writes == 1 and triager.agent_calls == 1
    assert tracker.issue(number)["state"] == "closed"
    assert len(tracker.issue(number)["comments"]) == 1


def test_recovery_stops_after_bounded_transient_retries(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("auto_designer.designer.triage.time.sleep", lambda _: None)

    class UnavailableTracker(FakeTracker):
        reads = 0

        def get_issue(self, *, number):
            self.reads += 1
            raise requests.ConnectionError("Gitea unavailable")

    tracker = UnavailableTracker()
    number = _report(tracker, "原报告")
    frozen = tracker.list_open_issues()[0]
    recovery = _recovery(tmp_path)
    triager = _StubTriager(
        tracker, SessionStore(tmp_path / "sessions"), str(tmp_path / "harness"),
        str(tmp_path / "agent"), canned=_submit([_accept(number)]), recovery=recovery,
    )
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        with pytest.raises(RecoveryConflictError, match="remain incomplete"):
            triager.triage_once(pending=[frozen])
    assert tracker.reads == 3 and triager.agent_calls == 1
    assert tracker.issue(number)["title"] == "原报告"
    assert recovery.unit(
        round_no=1, stage="triage", key=operation_key("triage-worker-0", "report", number)
    )["status"] == "failed"


def test_recovery_replays_only_our_partial_migration(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("auto_designer.designer.triage.time.sleep", lambda _: None)

    class PartialMigrationTracker(FakeTracker):
        writes = 0

        def update_issue(self, number, *, title, body, labels):
            self.writes += 1
            if self.writes == 1:
                original_labels = self.issue(number)["labels"]
                super().update_issue(number, title=title, body=body, labels=original_labels)
                raise IssueMigrationError(
                    number=number, operation="update_issue",
                    primary=requests.ConnectionError("labels response lost"),
                    rollback=None, observed=self.issue(number),
                )
            return super().update_issue(number, title=title, body=body, labels=labels)

    tracker = PartialMigrationTracker()
    number = _report(tracker, "原报告")
    frozen = tracker.list_open_issues()[0]
    triager = _StubTriager(
        tracker, SessionStore(tmp_path / "sessions"), str(tmp_path / "harness"),
        str(tmp_path / "agent"), canned=_submit([_accept(number)]), recovery=_recovery(tmp_path),
    )
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        result = triager.triage_once(pending=[frozen])
    assert result.accepted == [number] and result.failed == {}
    assert tracker.writes == 2 and triager.agent_calls == 1
    assert sc.PROPOSAL in tracker.issue(number)["labels"]
    assert len(tracker.issue(number)["comments"]) == 1


def test_recovery_does_not_overwrite_external_edit_after_lost_response(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("auto_designer.designer.triage.time.sleep", lambda _: None)

    class ConcurrentEditTracker(FakeTracker):
        writes = 0

        def update_issue(self, number, *, title, body, labels):
            self.writes += 1
            super().update_issue(number, title=title, body="external edit", labels=labels)
            raise requests.ConnectionError("response lost")

    tracker = ConcurrentEditTracker()
    number = _report(tracker, "原报告")
    frozen = tracker.list_open_issues()[0]
    triager = _StubTriager(
        tracker, SessionStore(tmp_path / "sessions"), str(tmp_path / "harness"),
        str(tmp_path / "agent"), canned=_submit([_accept(number)]), recovery=_recovery(tmp_path),
    )
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        with pytest.raises(RecoveryConflictError, match="remain incomplete"):
            triager.triage_once(pending=[frozen])
    assert tracker.writes == 1
    assert tracker.issue(number)["body"] == "external edit"


def test_recovery_retries_temporary_server_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("auto_designer.designer.triage.time.sleep", lambda _: None)

    class TemporaryServerErrorTracker(FakeTracker):
        reads = 0

        def get_issue(self, *, number):
            self.reads += 1
            if self.reads == 1:
                raise GiteaError(503, f"/issues/{number}")
            return super().get_issue(number=number)

    tracker = TemporaryServerErrorTracker()
    number = _report(tracker, "原报告")
    frozen = tracker.list_open_issues()[0]
    triager = _StubTriager(
        tracker, SessionStore(tmp_path / "sessions"), str(tmp_path / "harness"),
        str(tmp_path / "agent"), canned=_submit([_accept(number)]), recovery=_recovery(tmp_path),
    )
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        result = triager.triage_once(pending=[frozen])
    assert result.accepted == [number] and tracker.reads == 2


def test_recovery_reuses_saved_output_after_previous_tracker_outage(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("auto_designer.designer.triage.time.sleep", lambda _: None)

    class RecoveredTracker(FakeTracker):
        unavailable = True

        def get_issue(self, *, number):
            if self.unavailable:
                raise requests.ConnectionError("Gitea unavailable")
            return super().get_issue(number=number)

    tracker = RecoveredTracker()
    number = _report(tracker, "原报告")
    frozen = tracker.list_open_issues()[0]
    recovery = _recovery(tmp_path)
    args = (
        tracker, SessionStore(tmp_path / "sessions"), str(tmp_path / "harness"),
        str(tmp_path / "agent"),
    )
    first = _StubTriager(*args, canned=_submit([_accept(number)]), recovery=recovery)
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        with pytest.raises(RecoveryConflictError, match="remain incomplete"):
            first.triage_once(pending=[frozen])
    assert first.agent_calls == 1
    tracker.unavailable = False
    resumed = _StubTriager(*args, canned="model must not run again", recovery=recovery)
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        result = resumed.triage_once(pending=[frozen])
    assert result.accepted == [number] and result.failed == {}
    assert resumed.agent_calls == 0
    assert len(tracker.issue(number)["comments"]) == 1
