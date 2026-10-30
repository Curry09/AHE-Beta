"""skill 占位接口（spec-0008/T3）。

为高深度 persona 预留「领域 playbook」扩展位：D2 深度驱动地挂上一些**通用方法论**片段，
拼进内层 system。本轮仅占位——只给极简内置通用集合，不接真实 playbook 库。

红线（held-out）：skill 必须是通用、可迁移的工作方法，**绝不**含具体 bug、答案、
benchmark 或场景特定知识。
"""

from __future__ import annotations

from dataclasses import dataclass

from .dimensions import D2Depth, Persona


@dataclass(frozen=True)
class Skill:
    """一段通用方法论片段：name 标识，prompt 注入内层 system。"""

    name: str
    prompt: str


# 通用、非场景特定的方法论（占位集合）。仅 senior 深度挂载，演示扩展位。
_SENIOR_PLAYBOOK: list[Skill] = [
    Skill(
        "reproduce-first",
        "Before judging whether something works, reproduce it with the smallest possible run "
        "rather than reasoning about it in your head.",
    ),
    Skill(
        "probe-boundaries",
        "When you do decide to check, spend your effort on the boundary/edge inputs that are "
        "most likely to break things, not the happy path you already expect to pass.",
    ),
]


def select_skills(persona: Persona) -> list[Skill]:
    """按 persona 的 D2 深度选 skill（占位）。senior -> 通用 playbook；其余 -> 空。"""
    if persona.d2.depth == D2Depth.SENIOR:
        return list(_SENIOR_PLAYBOOK)
    return []
