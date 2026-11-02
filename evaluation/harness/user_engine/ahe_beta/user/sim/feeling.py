"""
feeling.py
体感评分 (FeelingScore 1–4 + 理由) —— 对齐 AHE-Beta spec-0001 的训练信号契约。

两路并出 (会话末各产一次, 互为校验):
- ① LLM 自评 (parse_feeling_llm): persona 在角色内给"这次体验"打 1–4 + 理由,
     对齐 spec-0001/T3"会话结束后经 LLM 产出 FeelingScore"的产出方式 (类 CC 评分)。
- ② 框架派生 (derive_feeling): 从主观末态 (end_reason / verdict / trust) 确定性聚合,
     可复现，仅作独立诊断，不填补缺失自评。

铁律:
- 体感是 *主观* 信号, 只从 persona 的末态 (end_reason / verdict / patience / trust)
  派生, 绝不读客观真值 (gold)。这与项目"训练信号=用户体感, benchmark held-out"一致。
- 会话末一次性产出 (不逐轮打分), 对齐 FeelingScore"一局一个总分"的形态。

评分细则 (类 CC 1–4, 数值越高体感越好):
  4  顺畅满意 : 接受交付, 过程基本没反复 (failed_blame_harness <= 1 且信任未转怀疑)
  3  有摩擦但接受: 最终接受, 但中途多次怪 harness 或信任已转 skeptical
  2  未真正解决: 跑满轮次未收敛 / 提了 issue 收场 (建设性但挫败)
  1  放弃     : 主动 give_up 中途弃用
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# end_reason -> 基线分。其余 (terminated 等) 落默认 2。
_BASE_BY_END = {
    "accepted": 4,
    "max_turns": 2,
    "issue_filed": 2,
    "abandoned": 1,
}

_VERDICT_TEXT = {
    4: "用户顺畅接受了交付。",
    3: "用户最终接受, 但过程有反复/信任下降。",
    2: "未真正解决就收场 (跑满轮次或提 issue)。",
    1: "用户中途放弃。",
}


@dataclass
class FeelingScore:
    """1–4 体感评分 + 理由 (会话末产出, 作训练信号)。越界即构造期失败。"""

    score: int
    reason: str

    def __post_init__(self) -> None:
        assert type(self.score) is int and 1 <= self.score <= 4, (
            f"体感分须为 1..4 的整数: {self.score!r}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "reason": self.reason}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FeelingScore:
        return cls(score=data["score"], reason=data["reason"])


def parse_feeling_llm(ret: dict) -> FeelingScore | None:
    """从 persona LLM 的会话末自评 dict 解析 1–4 体感分 (spec-0001/T3 的产出方式)。

    期望 ret 形如 {"score": <1..4>, "reason": "<...>"}。无效 (缺字段 / 非整数 / 越界)
    返回 None，缺测不能回填派生分。越界经 FeelingScore.__post_init__
    断言失败 -> 捕获为 None, 既守住"越界即非法"又不崩 loop。
    """
    if not isinstance(ret, dict) or "score" not in ret:
        return None
    score = ret["score"]
    if type(score) is not int:
        return None
    reason = str(ret.get("reason", "")).strip()
    try:
        return FeelingScore(score=score, reason=reason)
    except AssertionError:
        return None


def experience_feedback(ret: dict | None, *, source: str, error: str | None = None) -> dict:
    """Spec-0084/T2: one strict scale for both interaction modes, including missingness."""
    if error is not None:
        return {"status": "unavailable", "score": None, "source": source, "reason": error}
    value = ret if isinstance(ret, dict) else {}
    feeling = parse_feeling_llm(value)
    return {
        "status": "rated" if feeling else ("missing" if value.get("score") is None else "invalid"),
        "score": feeling.score if feeling else None,
        "source": source,
        "reason": feeling.reason
        if feeling
        else str(value.get("reason") or "No valid integer rating supplied"),
    }


def derive_feeling(end_reason: str, turns: list) -> FeelingScore:
    """从一局会话末态派生体感分。只吃主观信号 (end_reason / verdict / trust)。

    turns: list[TurnLog]; 仅读 verdict / trust 两个主观字段, 不依赖客观线。
    """
    fails = sum(1 for t in turns if t.verdict == "failed_blame_harness")
    stucks = sum(1 for t in turns if t.verdict == "stuck")
    final_trust = turns[-1].trust if turns else "balanced"

    score = _BASE_BY_END.get(end_reason, 2)
    # 即便最终接受, 多次怪 harness / 多次卡住 / 信任崩到 skeptical -> 降一档为"有摩擦的接受"
    if score == 4 and (fails >= 2 or stucks >= 2 or final_trust == "skeptical"):
        score = 3

    reason = (
        f"end={end_reason}; harness-blamed failures={fails}; stuck turns={stucks}; "
        f"final trust={final_trust}. " + _VERDICT_TEXT[score]
    )
    return FeelingScore(score=score, reason=reason)
