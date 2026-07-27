# Spec-0027/T2：submit-tool binding——agent 以工具参数原生吐结构化，binding 回显参数供 driver 读。
"""submit 工具的 binding。

nexau 在工具调用层已用 input_schema 做 jsonschema 强校验（archs/tool/tool.py：违规抛 ValueError→
executor 组 is_error 结果回灌模型→下一轮重试）。故 agent「发出即合规」，无需第二次 LLM 重排/括号扫描。

submit 工具设为 **stop tool**：其 binding 的返回值成为 `agent.run()` 的返回（executor 的
stop_tool_result → final_response）。因此这里把已校验的参数**原样回显**成 JSON 字符串——driver 对
`agent.run` 的返回 `json.loads` 即取回 `{"dispositions": [...]}`，无 side-channel。
"""

from __future__ import annotations

import json
from typing import Any


def submit_triage(*, dispositions: list | None = None, **kwargs: Any) -> str:
    """triage 收尾工具：回显已校验的 dispositions 数组（成为 agent.run 的返回值）。

    dispositions 已由 input_schema 校验（四值 disposition、P0-P3、fields 键锁定、无自创字段）。
    额外的 nexau 注入参数（agent_state / global_storage / ctx 等）由 **kwargs 吸收、不落入产物。
    """
    return json.dumps({"dispositions": dispositions or []}, ensure_ascii=False)


def submit_rfcs(*, proposals: list | None = None, **kwargs: Any) -> str:
    """synthesize(designer) 收尾工具：回显已校验的 proposals 数组（成为 agent.run 的返回值）。

    proposals 已由 input_schema 校验（每条 title + fields[RFC 字段键锁定] 必填、可选 covers[int]、
    无自创字段）。额外的 nexau 注入参数（agent_state / global_storage / ctx 等）由 **kwargs 吸收。
    """
    return json.dumps({"proposals": proposals or []}, ensure_ascii=False)


def submit_divergent(*, proposals: list | None = None, **kwargs: Any) -> str:
    """divergent PM 收尾工具（Spec-0028）：回显已校验的候选 proposals（成为 agent.run 的返回值）。

    与 submit_rfcs 同 shape（title + fields[RFC 字段] + 可选 covers）——divergent 候选形态即 RFC 提案，
    只是 driver 落库时打 `divergent` 标签、不进可领 backlog。
    """
    return json.dumps({"proposals": proposals or []}, ensure_ascii=False)


def submit_gate(*, gate_decisions: list | None = None, **kwargs: Any) -> str:
    """gate（晋升评审）收尾工具（Spec-0028）：回显已校验的 gate_decisions（成为 agent.run 的返回值）。

    每条已由 input_schema 校验（issue + disposition[promote/hold/drop] 必填、可选 note、无自创字段）。
    """
    return json.dumps({"gate_decisions": gate_decisions or []}, ensure_ascii=False)
