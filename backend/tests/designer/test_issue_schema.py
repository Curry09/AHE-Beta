# Spec-0025/T1：平台层 issue schema 单测——USER/TRIAGE 分区、每 kind render、validate 各失败分支。
"""验证 issue_schema：字段分区正确；bug 有复现三段、feature 有背景/交付、RFC 字段独立；
validate 拒未知 kind / 缺必填 / 空值；render 布局稳定、按区渲染、缺字段占位。"""

from __future__ import annotations

from auto_designer.designer import issue_schema as sc


def test_bug_partition() -> None:
    user = {f.key for f in sc.fields_of(kind="bug", section=sc.USER)}
    triage = {f.key for f in sc.fields_of(kind="bug", section=sc.TRIAGE)}
    assert user == {"repro", "expected", "actual"}  # 复现三段在用户区
    assert triage == {"root_cause", "boundary", "acceptance"}  # 定位/验收在 triage 区
    assert user.isdisjoint(triage)


def test_feature_partition() -> None:
    user = {f.key for f in sc.fields_of(kind="feature", section=sc.USER)}
    triage = {f.key for f in sc.fields_of(kind="feature", section=sc.TRIAGE)}
    assert user == {"background", "goal", "scenario"}
    assert triage == {"boundary", "deliverable", "acceptance"}


def test_rfc_is_independent_kind() -> None:
    keys = {f.key for f in sc.fields_of(kind="rfc")}
    assert keys == {"problem", "root_cause", "related", "direction", "acceptance"}
    assert "repro" not in keys  # RFC 不套 bug 复现模板
    assert "rfc" in sc.kinds() and "rfc" not in sc.USER_KINDS  # RFC 不由用户提


def test_validate_unknown_kind() -> None:
    errs = sc.validate(kind="nonsense", fields={})
    assert errs and "未知" in errs[0]


def test_validate_missing_required() -> None:
    errs = sc.validate(kind="bug", fields={"repro": "点了就崩"})  # 缺 expected/actual + triage 全缺
    keys_missing = " ".join(errs)
    assert "expected" in keys_missing and "actual" in keys_missing and "root_cause" in keys_missing


def test_validate_section_scoped() -> None:
    # 用户只填了 USER 区 → user 区通过、triage 区仍报缺
    fields = {"repro": "a", "expected": "b", "actual": "c"}
    assert sc.validate(kind="bug", fields=fields, section=sc.USER) == []
    assert sc.validate(kind="bug", fields=fields, section=sc.TRIAGE)  # triage 区未填 → 有错


def test_validate_empty_string_is_missing() -> None:
    errs = sc.validate(kind="bug", fields={"repro": "   "}, section=sc.USER)
    assert any("repro" in e for e in errs)  # 空白视为缺


def test_validate_optional_not_required() -> None:
    # chore 的 boundary 是可选 → 只填 goal + acceptance 即通过
    assert sc.validate(kind="chore", fields={"goal": "清缓存", "acceptance": "跑通"}) == []


def test_render_layout_stable() -> None:
    body = sc.render(
        kind="bug",
        fields={
            "repro": "跑 unidecode 就超时",
            "expected": "装好能用",
            "actual": "反复超时",
            "root_cause": "entry.py 无预算感知",
            "boundary": "只改 harness 本体",
            "acceptance": "该类任务预算内给交付",
        },
    )
    assert "### 复现步骤\n\n跑 unidecode 就超时" in body
    assert "### 根因区域\n\nentry.py 无预算感知" in body
    assert body.index("### 复现步骤") < body.index("### 根因区域")  # 声明顺序稳定


def test_render_section_scoped_and_placeholder() -> None:
    # 用户侧只渲染 USER 区
    user_body = sc.render(
        kind="bug",
        fields={"repro": "a", "expected": "b", "actual": "c"},
        section=sc.USER,
    )
    assert "复现步骤" in user_body and "根因区域" not in user_body
    # 全渲染时 triage 区缺 → 占位
    full = sc.render(kind="bug", fields={"repro": "a", "expected": "b", "actual": "c"})
    assert "### 根因区域\n\n_（待补）_" in full


def test_render_unknown_kind_raises() -> None:
    try:
        sc.render(kind="nope", fields={})
        raise AssertionError("应抛 ValueError")
    except ValueError:
        pass
