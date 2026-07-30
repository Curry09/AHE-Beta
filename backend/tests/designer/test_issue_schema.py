# Spec-0025/T1 + Spec-0027/T1：平台层 issue schema 单测——收敛为规范化字段（去 USER 段模板）。
"""验证 issue_schema：每 kind 只声明规范化产物字段（triage/RFC agent 填的定位字段）；
validate 拒未知 kind / 缺必填 / 空值；render 布局稳定、缺字段占位；section 参数向后兼容。"""

from __future__ import annotations

from auto_designer.designer import issue_schema as sc


def test_bug_fields_are_normalized_only() -> None:
    keys = {f.key for f in sc.fields_of(kind="bug")}
    assert keys == {"root_cause", "boundary", "acceptance"}  # 只剩定位/验收，无 USER 复现模板
    assert "repro" not in keys and "expected" not in keys  # 原 USER 段已删


def test_feature_fields_are_normalized_only() -> None:
    keys = {f.key for f in sc.fields_of(kind="feature")}
    assert keys == {"boundary", "deliverable", "acceptance"}
    assert "background" not in keys and "scenario" not in keys


def test_rfc_is_independent_kind() -> None:
    keys = {f.key for f in sc.fields_of(kind="rfc")}
    assert keys == {"problem", "root_cause", "related", "direction", "acceptance"}
    assert "rfc" in sc.kinds() and "rfc" not in sc.USER_KINDS  # RFC 不由用户提


def test_validate_unknown_kind() -> None:
    errs = sc.validate(kind="nonsense", fields={})
    assert errs and "未知" in errs[0]


def test_validate_missing_required() -> None:
    errs = sc.validate(
        kind="bug", fields={"root_cause": "entry.py 无预算感知"}
    )  # 缺 boundary/acceptance
    joined = " ".join(errs)
    assert "boundary" in joined and "acceptance" in joined


def test_validate_empty_string_is_missing() -> None:
    errs = sc.validate(kind="bug", fields={"root_cause": "   ", "boundary": "b", "acceptance": "c"})
    assert any("root_cause" in e for e in errs)  # 空白视为缺


def test_validate_optional_not_required() -> None:
    # chore 的 boundary 可选 → 只填 acceptance 即通过
    assert sc.validate(kind="chore", fields={"acceptance": "跑通"}) == []
    # document 仅 acceptance 且可选 → 空也通过
    assert sc.validate(kind="document", fields={}) == []


def test_validate_section_param_back_compat() -> None:
    # section 退化为单一值：所有字段归 TRIAGE；查 USER 区无字段可查 → 恒通过。
    fields = {"root_cause": "a", "boundary": "b", "acceptance": "c"}
    assert sc.validate(kind="bug", fields=fields, section=sc.TRIAGE) == []
    assert sc.validate(kind="bug", fields={}, section=sc.USER) == []  # 无 USER 字段


def test_render_layout_stable() -> None:
    body = sc.render(
        kind="bug",
        fields={
            "root_cause": "entry.py 无预算感知",
            "boundary": "只改 harness 本体",
            "acceptance": "该类任务预算内给交付",
        },
    )
    assert "### 根因区域\n\nentry.py 无预算感知" in body
    assert body.index("### 根因区域") < body.index("### 边界")  # 声明顺序稳定


def test_render_missing_field_placeholder() -> None:
    full = sc.render(kind="bug", fields={"root_cause": "a"})
    assert "### 验收\n\n_（待补）_" in full  # 缺字段占位


def test_render_unknown_kind_raises() -> None:
    try:
        sc.render(kind="nope", fields={})
        raise AssertionError("应抛 ValueError")
    except ValueError:
        pass


def test_divergent_and_gate_dropped_status_and_backlog() -> None:
    # Spec-0027/T1：候选不可领；丢弃终态；promote 后可进 backlog。
    assert sc.triage_status([sc.DIVERGENT, "round-1"]) == sc.DIVERGENT
    assert sc.triage_status([sc.GATE_DROPPED, sc.DIVERGENT]) == sc.GATE_DROPPED
    assert not sc.is_backlog_by_labels([sc.DIVERGENT, "feature"])
    assert not sc.is_backlog_by_labels([sc.GATE_DROPPED])
    assert sc.is_backlog_by_labels([sc.TRIAGED, "feature"])  # promote 后


# ---- Spec-0029/T1：三平面投影 + is_ready 白名单 + covers/merged-into 机器行 ----


def test_plane_new_labels() -> None:
    assert sc.plane([sc.REPORT, "bug", "round-1"]) == sc.REPORT
    assert sc.plane([sc.PROPOSAL, sc.FROM_TRIAGE, "bug", "P1"]) == sc.PROPOSAL
    assert sc.plane([sc.READY, "feature", "P0"]) == sc.READY
    assert sc.plane(["bug"]) is None  # 无平面标签
    assert sc.plane([]) is None


def test_plane_openagents_handoff_is_ready() -> None:
    # Spec-0032/T3：openagents（Owner 准入交接令牌）与 ready 同属 READY 平面；
    # vigil 盖 ready 后两标签并存仍是 READY（幂等）。
    assert sc.plane([sc.OPENAGENTS, "bug", "P1"]) == sc.READY
    assert sc.plane([sc.OPENAGENTS, sc.READY, "bug"]) == sc.READY
    assert sc.is_ready(labels=[sc.OPENAGENTS], state="open")
    assert not sc.is_ready(labels=[sc.OPENAGENTS], state="closed")
    # 与 ready 同序：新平面标签优先于终态判定（写侧关闭时本会摘掉平面标签，此处仅锁定优先级一致）
    assert sc.plane([sc.OPENAGENTS, sc.MERGED]) == sc.READY


def test_plane_terminal_labels_are_no_plane() -> None:
    # 新终态 + 老终态：都不在任何平面
    for t in (sc.DECLINED, sc.MERGED, sc.REJECTED, sc.NEEDS_INFO, sc.GATE_DROPPED, sc.SUPERSEDED):
        assert sc.plane([t, "bug"]) is None
    # 旧 triaged+superseded 组合是终态（对齐旧「越决定性者胜」）
    assert sc.plane([sc.TRIAGED, sc.SUPERSEDED]) is None


def test_plane_old_label_mapping() -> None:
    # 旧数据读侧映射：needs-triage→report、triaged|RFC→ready、divergent→proposal
    assert sc.plane([sc.NEEDS_TRIAGE, "bug"]) == sc.REPORT
    assert sc.plane([sc.TRIAGED, "bug", "P1"]) == sc.READY
    assert sc.plane([sc.RFC_LABEL]) == sc.READY
    assert sc.plane([sc.DIVERGENT, "feature"]) == sc.PROPOSAL


def test_is_ready_whitelist() -> None:
    assert sc.is_ready(labels=[sc.READY, "bug"], state="open")
    assert not sc.is_ready(labels=[sc.READY, "bug"], state="closed")  # 已关不可领
    assert not sc.is_ready(labels=[sc.PROPOSAL, "bug"], state="open")  # 提案不可领
    assert not sc.is_ready(labels=[sc.REPORT], state="open")
    assert sc.is_ready(labels=[sc.TRIAGED, "bug"], state="open")  # 旧数据映射后可领
    # fail-closed：未知/新增流程标签默认不可领
    assert not sc.is_ready(labels=["some-future-label"], state="open")


def test_covers_line_roundtrip() -> None:
    line = sc.format_covers_line([12, 15])
    assert line == "covers: #12 #15"
    assert sc.parse_covers_line(f"正文\n\n{line}\n") == [12, 15]
    assert sc.parse_covers_line("无机器行") == []
    assert sc.format_covers_line([]) == ""  # 空列表不写行
    # 多条取最后一条
    assert sc.parse_covers_line("covers: #1\n中间\ncovers: #2 #3") == [2, 3]


def test_merged_into_roundtrip() -> None:
    line = sc.format_merged_into(7)
    assert line == "merged-into: #7"
    assert sc.parse_merged_into(f"gate 决定合并\n{line}") == 7
    assert sc.parse_merged_into("无") is None


def test_provenance_of() -> None:
    assert sc.provenance_of([sc.PROPOSAL, sc.FROM_TRIAGE]) == sc.FROM_TRIAGE
    assert sc.provenance_of([sc.PROPOSAL, sc.FROM_SYNTHESIZE]) == sc.FROM_SYNTHESIZE
    assert sc.provenance_of([sc.PROPOSAL, sc.FROM_DIVERGENT]) == sc.FROM_DIVERGENT
    assert sc.provenance_of(["bug"]) is None
