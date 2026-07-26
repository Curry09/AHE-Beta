# Spec-0027/T1：agent 结构化产出契约的单一真源生成器。
"""由 issue_schema.SCHEMAS 生成各 producer 的 submit 工具 input_schema——契约与 schema 同源，
改字段只改 SCHEMAS。

nexau 在工具调用层用 jsonschema 校验工具参数（archs/tool/tool.py：`jsonschema.validate(params,
input_schema)`，违规抛 ToolValidationError→agent 重试）。故把这些 schema 挂到 submit 工具的
input_schema 上，agent「发出即合规」——无需事后第二次 LLM 重排、也无需括号扫描解析。

- `dispositions_input_schema()`：triage 的 submit_triage 工具入参（dispositions 数组）。
- `rfc_input_schema()`：synthesize 的 submit_rfcs 工具入参（proposals 数组）。

二者的 fields 键、可选 kind/priority 枚举全部取自 issue_schema，不在此另抄一份。
"""

from __future__ import annotations

from auto_designer.designer.issue_schema import PRIORITIES, USER_KINDS, fields_of


def _fields_object_schema(labels: list[str]) -> dict:
    """某组字段的 fields 对象 schema：键 = 中文 label，值 = string；不允许多余键。"""
    return {
        "type": "object",
        "properties": {label: {"type": "string"} for label in labels},
        "additionalProperties": False,
    }


def _triage_field_labels() -> list[str]:
    """全部 user kind 的规范化字段 label 并集（保持声明顺序、去重）——triage fields 的合法键。"""
    labels: list[str] = []
    for kind in USER_KINDS:
        for f in fields_of(kind=kind):
            if f.label not in labels:
                labels.append(f.label)
    return labels


def dispositions_input_schema() -> dict:
    """triage submit_triage 工具的 input_schema。

    每条 disposition：`issue`(int) + `disposition`(四值枚举) 必填；accept 另给 `kind`(∈USER_KINDS)、
    `priority`(∈P0-P3)、`fields`(键∈规范化字段并集)；duplicate 给 `of`；reject/needs_info 给 `reason`。
    additionalProperties=false 杜绝 issue_number/status/平铺 root_cause 这类自创字段；enum 让 "high"
    这类非法优先级吐不出来。per-kind 条件必填仍由 driver 的 validate 二次把关（json_schema 不表达）。
    """
    item = {
        "type": "object",
        "properties": {
            "issue": {"type": "integer"},
            "disposition": {
                "type": "string",
                "enum": ["accept", "duplicate", "reject", "needs_info"],
            },
            "kind": {"type": "string", "enum": list(USER_KINDS)},
            "priority": {"type": "string", "enum": list(PRIORITIES)},
            "fields": _fields_object_schema(_triage_field_labels()),
            "of": {"type": "integer"},
            "reason": {"type": "string"},
        },
        "required": ["issue", "disposition"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"dispositions": {"type": "array", "items": item}},
        "required": ["dispositions"],
        "additionalProperties": False,
    }


def rfc_input_schema() -> dict:
    """synthesize submit_rfcs 工具的 input_schema。

    每条 proposal：`title`(str) + `fields`(RFC 字段：问题/根因/涉及 issue/方向/验收) 必填，可选
    `covers`(int 数组，声明该 RFC 综合的 triaged 票号)。fields 键取自 issue_schema 的 rfc 声明。
    """
    rfc_labels = [f.label for f in fields_of(kind="rfc")]
    item = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "fields": _fields_object_schema(rfc_labels),
            "covers": {"type": "array", "items": {"type": "integer"}},
        },
        "required": ["title", "fields"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"proposals": {"type": "array", "items": item}},
        "required": ["proposals"],
        "additionalProperties": False,
    }
