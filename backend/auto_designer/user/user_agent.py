"""用户 agent 驱动器（spec-0001/T3）：模拟真实用户多轮使用 harness，产体感与 issue。

训练信号的产生点。由注入的 LLM 后端（Callable）驱动：UserAgent 把 Persona/SeedScenario/Transcript
组织成提示、解析输出。自判终止（显式结束标记）+ max_turns 兜底；体感与 issue 于会话末一次性产出。
issue 为最小桩（方案 a，见 spec open-questions）。harness 生命周期（reset/close）归编排层 T4。
"""

from __future__ import annotations

import json
from collections.abc import Callable

from auto_designer.harness.interface import HarnessInterface
from auto_designer.models import (
    FeelingScore,
    IssueDraft,
    Persona,
    SeedScenario,
    Transcript,
    Turn,
)

# 显式结束标记：LLM 在消息输出中携带即视为「用户决定结束本局」。
END_SENTINEL = "[[END]]"


def _parse_message(raw: str) -> tuple[str, bool]:
    """解析消息输出为 (user_msg, end_flag)。含 sentinel 即结束；解析失败安全降级为未结束。"""
    end = END_SENTINEL in raw
    user_msg = raw.replace(END_SENTINEL, "").strip()
    return user_msg, end


def _parse_feeling(raw: str) -> FeelingScore:
    """解析体感输出 '<score> <reason>'：首 token 为 1..4 分，余下为理由。越界由 FeelingScore 构造期收口。"""
    parts = raw.strip().split(maxsplit=1)
    score = int(parts[0])
    reason = parts[1] if len(parts) > 1 else ""
    return FeelingScore(score=score, reason=reason)


def _parse_issues(raw: str) -> list[IssueDraft]:
    """解析 issue 输出为 0..n 条 IssueDraft。空/[]→0 条；否则按 JSON 列表解析。"""
    text = raw.strip()
    if not text or text == "[]":
        return []
    return [IssueDraft.from_dict(item) for item in json.loads(text)]


class UserAgent:
    """persona 驱动的多轮对话驱动器。run 不触碰 harness.reset/close（生命周期归 T4）。"""

    def __init__(self, llm: Callable[..., str], persona: Persona, max_turns: int) -> None:
        assert max_turns > 0, f"max_turns 须为正：{max_turns}"
        self._llm = llm
        self._persona = persona
        self._max_turns = max_turns

    def run(
        self, scenario: SeedScenario, harness: HarnessInterface
    ) -> tuple[Transcript, FeelingScore, list[IssueDraft]]:
        transcript = Transcript()
        turns = 0
        while True:
            user_msg, end = _parse_message(
                self._llm(kind="message", prompt=self._message_prompt(scenario, transcript))
            )
            if end:  # 自判终止：达成 / 放弃 / 受够
                break
            reply = harness.send(user_msg)  # 异常不在本层吞，向上传播交 T4
            transcript.turns.append(Turn("user", user_msg))
            transcript.turns.append(Turn("harness", reply))
            turns += 1
            if turns >= self._max_turns:  # 兜底防不收敛
                break
        feeling = _parse_feeling(
            self._llm(kind="feeling", prompt=self._feeling_prompt(scenario, transcript))
        )
        drafts = _parse_issues(
            self._llm(kind="issue", prompt=self._issue_prompt(scenario, transcript))
        )
        return transcript, feeling, drafts

    def _message_prompt(self, scenario: SeedScenario, transcript: Transcript) -> str:
        return (
            f"你扮演用户：{self._persona.to_dict()}。\n诉求：{scenario.description}\n"
            f"对话至今：{transcript.to_dict()}\n"
            f"产出你这一轮要发的话；若已达成或决定放弃，附带 {END_SENTINEL}。"
        )

    def _feeling_prompt(self, scenario: SeedScenario, transcript: Transcript) -> str:
        return (
            f"基于这段使用过程给 1-4 体感分 + 理由（格式：'<分> <理由>'）。\n"
            f"诉求：{scenario.description}\n对话：{transcript.to_dict()}"
        )

    def _issue_prompt(self, scenario: SeedScenario, transcript: Transcript) -> str:
        return (
            f"从这段使用中归纳 0..n 条 issue（JSON 列表，每条 title/body/labels；无则 []）。\n"
            f"诉求：{scenario.description}\n对话：{transcript.to_dict()}"
        )
