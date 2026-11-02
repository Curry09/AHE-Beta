# Spec-0027/T1：agent_contract 契约生成器单测——由 issue_schema.SCHEMAS 单一真源生成 submit
# 工具的 input_schema（triage dispositions / RFC proposals）。
"""验证生成的 input_schema：结构正确、枚举锁死、fields 键与 SCHEMAS 同源、拒多余字段。"""

from __future__ import annotations

import jsonschema
import pytest

from ahe_beta.demand import agent_contract as ac
from ahe_beta.demand import issue_schema as sc


@pytest.mark.parametrize("count", [0, 2])
def test_dispositions_schema_rejects_non_single_decisions(count) -> None:
    decision = {
        "issue": 1,
        "disposition": "needs_info",
        "artifact": {
            "reported_problem": "unclear",
            "user_impact": "unknown",
            "scope_boundary": "harness",
            "evidence": [],
            "uncertainties": ["missing evidence"],
            "implementation_target": "uncertain",
        },
    }
    schema = ac.dispositions_input_schema()
    jsonschema.validate({"dispositions": [decision]}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"dispositions": [decision] * count}, schema)


def test_dispositions_schema_shape_and_enums() -> None:
    schema = ac.dispositions_input_schema()
    assert schema["required"] == ["dispositions"]
    assert schema["additionalProperties"] is False
    item = schema["properties"]["dispositions"]["items"]
    props = item["properties"]
    # disposition 三值（Spec-0029：duplicate 退役、跨提案吸收归 Architect）、kind∈USER_KINDS、priority∈P0-P3
    assert props["disposition"]["enum"] == ["accept", "reject", "needs_info"]
    assert props["kind"]["enum"] == list(sc.USER_KINDS)
    assert props["priority"]["enum"] == list(sc.PRIORITIES)
    # 顶层只允许契约字段——杜绝 issue_number/status/平铺散字段
    assert item["additionalProperties"] is False
    assert set(props) == {
        "issue",
        "disposition",
        "kind",
        "priority",
        "proposal_title",
        "fields",
        "reason",
        "artifact",
    }
    assert item["required"] == ["issue", "disposition", "artifact"]


def test_dispositions_fields_keys_are_union_from_schemas() -> None:
    """fields 的合法键 = 全部 user kind 规范化字段 label 的并集（与 SCHEMAS 同源）。"""
    schema = ac.dispositions_input_schema()
    field_keys = set(
        schema["properties"]["dispositions"]["items"]["properties"]["fields"]["properties"]
    )
    expected: set[str] = set()
    for k in sc.USER_KINDS:
        expected |= {f.label for f in sc.fields_of(kind=k)}
    assert field_keys == expected
    assert "根因区域" in field_keys and "交付物" in field_keys  # bug/feature 的 triage 字段
    # fields 不允许多余键
    assert (
        schema["properties"]["dispositions"]["items"]["properties"]["fields"][
            "additionalProperties"
        ]
        is False
    )


def test_rfc_schema_shape_and_fields() -> None:
    schema = ac.rfc_input_schema()
    assert schema["required"] == ["proposals"]
    item = schema["properties"]["proposals"]["items"]
    assert item["required"] == ["title", "fields"]
    assert item["additionalProperties"] is False
    field_keys = set(item["properties"]["fields"]["properties"])
    assert field_keys == {f.label for f in sc.fields_of(kind="rfc")}
    assert item["properties"]["covers"]["items"]["type"] == "integer"


def test_single_source_new_field_flows_through() -> None:
    """契约与 SCHEMAS 同源：bug 的每个字段 label 都出现在 dispositions 的 fields 键里。"""
    disp_field_keys = set(
        ac.dispositions_input_schema()["properties"]["dispositions"]["items"]["properties"][
            "fields"
        ]["properties"]
    )
    for f in sc.fields_of(kind="bug"):
        assert f.label in disp_field_keys
