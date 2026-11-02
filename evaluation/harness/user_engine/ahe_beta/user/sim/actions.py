"""
actions.py
动作模型 —— 框架的核心。根除 run_once 的归属歧义。

三根属性轴(任何动作必须同时声明):
  executor 执行者:  PERSONA_LOCAL / HARNESS / FRAMEWORK
  channel  信道:    EMIT (发 B 线 NL) / SILENT (内部动作, 不发话)
  effect   效果:    ADVANCE (推进) / VERIFY (核查) / TERMINATE (终止)

消息不是信道的同义词：终止动作可以有可选的用户说明，但该说明不应被投影成
harness 消息。因此每个动作还声明 message_policy：required / optional / forbidden。
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


class MessagePolicy(StrEnum):
    """动作正文策略，与是否存在外部信道正交。"""

    REQUIRED = "required"
    OPTIONAL = "optional"
    FORBIDDEN = "forbidden"


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
    message_policy: MessagePolicy = MessagePolicy.OPTIONAL


# --------------------------------------------------------------------------
# 动作目录 (六属性钉死：executor/channel/effect/end_reason/message_policy + id)
# --------------------------------------------------------------------------
CATALOG: dict[str, ActionSpec] = {
    # 与 harness 的外部交互以自然语言消息为主；“查验/读文件/跑命令”是
    # 用户 agent 的私有内层行为，不是外层 action。
    "send_message": ActionSpec(
        "send_message",
        Executor.HARNESS,
        Channel.EMIT,
        Effect.ADVANCE,
        message_policy=MessagePolicy.REQUIRED,
    ),
    # 用户也可像真实 CLI 一样不追加新消息而继续等待，或打断仍在运行/排队的 harness 工作。
    "keep_waiting": ActionSpec(
        "keep_waiting",
        Executor.PERSONA_LOCAL,
        Channel.SILENT,
        Effect.ADVANCE,
        message_policy=MessagePolicy.FORBIDDEN,
    ),
    "interrupt": ActionSpec(
        "interrupt",
        Executor.HARNESS,
        Channel.SILENT,
        Effect.ADVANCE,
        message_policy=MessagePolicy.FORBIDDEN,
    ),
    # —— 终止 ——
    "accept": ActionSpec(
        "accept",
        Executor.PERSONA_LOCAL,
        Channel.EMIT,
        Effect.TERMINATE,
        "accepted",
        message_policy=MessagePolicy.OPTIONAL,
    ),
    # 接受但有保留：照样交付(end_reason=accepted)，同时以本人口吻留一条体感落差 issue。
    # 把「提 issue」从「失败终止」解耦——完成了但不达预期，也该说出体感（由模型自行决定选它）。
    "accept_with_reservations": ActionSpec(
        "accept_with_reservations",
        Executor.PERSONA_LOCAL,
        Channel.EMIT,
        Effect.TERMINATE,
        "accepted",
        message_policy=MessagePolicy.REQUIRED,
    ),
    "give_up": ActionSpec(
        "give_up",
        Executor.PERSONA_LOCAL,
        Channel.EMIT,
        Effect.TERMINATE,
        "abandoned",
        message_policy=MessagePolicy.OPTIONAL,
    ),
    "file_issue": ActionSpec(
        "file_issue",
        Executor.PERSONA_LOCAL,
        Channel.EMIT,
        Effect.TERMINATE,
        "issue_filed",
        message_policy=MessagePolicy.REQUIRED,
    ),
}

TERMINAL_IDS = {aid for aid, s in CATALOG.items() if s.effect is Effect.TERMINATE}


def assert_channel(action_id: str, message: str) -> None:
    """校验动作正文策略；终止动作的 optional message 不会路由到 harness。"""
    spec = CATALOG[action_id]
    msg = (message or "").strip()
    if spec.message_policy is MessagePolicy.REQUIRED and not msg:
        raise ValueError(f"action '{action_id}' requires a non-empty message")
    if spec.message_policy is MessagePolicy.FORBIDDEN and msg:
        raise ValueError(f"action '{action_id}' forbids a message")
