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
    errs = sc.validate(kind="bug", fields={"root_cause": "entry.py 无预算感知"})  # 缺 boundary/acceptance
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
