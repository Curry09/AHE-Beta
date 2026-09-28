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

    每条 disposition：`issue`(int) + `disposition`(三值枚举，Spec-0029：duplicate 退役、跨提案吸收归 Designer)
    必填；accept 另给 `kind`(∈USER_KINDS)、`priority`(∈P0-P3 建议值)、任务无关的
    `proposal_title`、`fields`(键∈规范化字段并集)；
    reject/needs_info 给 `reason`。additionalProperties=false 杜绝 issue_number/status/平铺 root_cause
    这类自创字段；enum 让 "high" 这类非法优先级吐不出来。per-kind 条件必填仍由 driver 的 validate
    二次把关（json_schema 不表达）。
    """
    item = {
        "type": "object",
        "properties": {
            "issue": {"type": "integer"},
            "disposition": {
                "type": "string",
                "enum": ["accept", "reject", "needs_info"],
            },
            "kind": {"type": "string", "enum": list(USER_KINDS)},
            "priority": {"type": "string", "enum": list(PRIORITIES)},
            "proposal_title": {"type": "string"},
            "fields": _fields_object_schema(_triage_field_labels()),
            "reason": {"type": "string"},
            "artifact": {
                "type": "object",
                "properties": {
                    "reported_problem": {"type": "string"},
                    "user_impact": {"type": "string"},
                    "scope_boundary": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "uncertainties": {"type": "array", "items": {"type": "string"}},
                    "implementation_target": {
                        "type": "string",
                        "enum": ["harness", "outside_harness", "uncertain"],
                    },
                },
                "required": [
                    "reported_problem",
                    "user_impact",
                    "scope_boundary",
                    "evidence",
                    "uncertainties",
                    "implementation_target",
                ],
                "additionalProperties": False,
            },
        },
        "required": ["issue", "disposition", "artifact"],
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
    `covers`(int 数组，声明该结构提案吸收并关闭的开放来源票号)。fields 键取自 issue_schema 的
    rfc 声明。
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


def pm_input_schema() -> dict:
    """Product PM: infer product meaning/opportunity from user behaviour."""
    item = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "user_goal": {"type": "string"},
            "observed_behaviors": {"type": "array", "items": {"type": "string"}},
            "experience_tension": {"type": "string"},
            "product_opportunity": {"type": "string"},
            "desired_outcome": {"type": "string"},
            "evidence_sessions": {"type": "array", "items": {"type": "string"}},
            "related_proposals": {"type": "array", "items": {"type": "integer"}},
            "solution_level": {
                "type": "string",
                "enum": ["product_capability", "implementation_design"],
            },
            "abstraction_rationale": {"type": "string"},
        },
        "required": [
            "title",
            "user_goal",
            "observed_behaviors",
            "experience_tension",
            "product_opportunity",
            "desired_outcome",
            "evidence_sessions",
            "solution_level",
            "abstraction_rationale",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"proposals": {"type": "array", "items": item}},
        "required": ["proposals"],
        "additionalProperties": False,
    }


def synthesis_input_schema() -> dict:
    """Synthesize: explain relationships and common mechanisms across proposals."""
    item = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "source_proposals": {"type": "array", "items": {"type": "integer"}},
            "relationship": {"type": "string"},
            "common_tension": {"type": "string"},
            "structural_direction": {"type": "string"},
            "expected_leverage": {"type": "string"},
            "covers": {"type": "array", "items": {"type": "integer"}},
            "solution_level": {
                "type": "string",
                "enum": ["structural_mechanism", "implementation_design"],
            },
            "abstraction_rationale": {"type": "string"},
        },
        "required": [
            "title",
            "source_proposals",
            "relationship",
            "common_tension",
            "structural_direction",
            "expected_leverage",
            "solution_level",
            "abstraction_rationale",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"proposals": {"type": "array", "items": item}},
        "required": ["proposals"],
        "additionalProperties": False,
    }


def admission_input_schema() -> dict:
    """Owner handoff 工具契约：只打包交接，不评审产品方案或选择实现层。"""
    item = {
        "type": "object",
        "properties": {
            "issue": {"type": "integer"},
            "decision": {"type": "string", "enum": ["admit", "merge", "hold"]},
            "into": {"type": "integer"},
            "priority": {"type": "string", "enum": list(PRIORITIES)},
            "reason": {"type": "string"},
            "handoff_summary": {"type": "string"},
            "preserved_capabilities": {"type": "array", "items": {"type": "string"}},
            "acceptance_groups": {"type": "array", "items": {"type": "string"}},
            "delivery_overlaps": {
                "type": "array",
                "items": {"type": "integer"},
                "uniqueItems": True,
            },
        },
        "required": [
            "issue",
            "decision",
            "handoff_summary",
            "preserved_capabilities",
            "acceptance_groups",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"decisions": {"type": "array", "items": item}},
        "required": ["decisions"],
        "additionalProperties": False,
    }
