"""
actions.py
动作模型 —— 框架的核心。根除 run_once 的归属歧义。

三根属性轴(任何动作必须同时声明):
  executor 执行者:  PERSONA_LOCAL / HARNESS / FRAMEWORK
  channel  信道:    EMIT (发 B 线 NL) / SILENT (内部动作, 不发话)
  effect   效果:    ADVANCE (推进) / VERIFY (核查) / TERMINATE (终止)

铁律:
  channel == EMIT   <=> message 必须非空
  channel == SILENT <=> message 必须为空
违反由 assert_channel() 强校验。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Executor(StrEnum):
    PERSONA_LOCAL = "persona_local"  # 用户本地心智动作(发话/接受/放弃)
    HARNESS = "harness"  # 通过 B 线驱动 harness 执行
    FRAMEWORK = "framework"  # 框架代 persona 执行, 取 ground truth 后按能力掩码过滤


class Channel(StrEnum):
    EMIT = "emit"  # 产生一句给 harness 的自然语言
    SILENT = "silent"  # 内部动作, B 线无消息


class Effect(StrEnum):
    ADVANCE = "advance"  # 推进对话
    VERIFY = "verify"  # 核查动作
    TERMINATE = "terminate"  # 终止 loop


class Phase(StrEnum):
    OPENING = "opening"  # 尚未发出首个任务
    ACTIVE = "active"  # 已有来回


@dataclass(frozen=True)
class ActionSpec:
    id: str
    executor: Executor
    channel: Channel
    effect: Effect
    end_reason: str | None = None  # 仅 TERMINATE 动作有


# --------------------------------------------------------------------------
# 动作目录 (五属性钉死)
# --------------------------------------------------------------------------
CATALOG: dict[str, ActionSpec] = {
    "send_task": ActionSpec("send_task", Executor.HARNESS, Channel.EMIT, Effect.ADVANCE),
    "refine_request": ActionSpec("refine_request", Executor.HARNESS, Channel.EMIT, Effect.ADVANCE),
    "give_feedback": ActionSpec("give_feedback", Executor.HARNESS, Channel.EMIT, Effect.ADVANCE),
    # —— 核查: 这里就是 run_once 拆出来的两个, 归属彻底分离 ——
    "verify_self": ActionSpec("verify_self", Executor.FRAMEWORK, Channel.SILENT, Effect.VERIFY),
    "ask_harness_run": ActionSpec("ask_harness_run", Executor.HARNESS, Channel.EMIT, Effect.VERIFY),
    "request_evidence": ActionSpec(
        "request_evidence", Executor.HARNESS, Channel.EMIT, Effect.VERIFY
    ),
    "grant_autorun": ActionSpec("grant_autorun", Executor.HARNESS, Channel.EMIT, Effect.ADVANCE),
    # —— 终止 ——
    "accept": ActionSpec(
        "accept", Executor.PERSONA_LOCAL, Channel.EMIT, Effect.TERMINATE, "accepted"
    ),
    "give_up": ActionSpec(
        "give_up", Executor.PERSONA_LOCAL, Channel.EMIT, Effect.TERMINATE, "abandoned"
    ),
    "file_issue": ActionSpec(
        "file_issue", Executor.PERSONA_LOCAL, Channel.EMIT, Effect.TERMINATE, "issue_filed"
    ),
}

TERMINAL_IDS = {aid for aid, s in CATALOG.items() if s.effect is Effect.TERMINATE}


def assert_channel(action_id: str, message: str) -> None:
    """强校验 channel <-> message 一致性。违反即抛, 由 resolver 捕获修正。"""
    spec = CATALOG[action_id]
    msg = (message or "").strip()
    if spec.channel is Channel.EMIT and not msg:
        raise ValueError(f"action '{action_id}' is EMIT but message is empty")
    if spec.channel is Channel.SILENT and msg:
        raise ValueError(f"action '{action_id}' is SILENT but message is non-empty")
