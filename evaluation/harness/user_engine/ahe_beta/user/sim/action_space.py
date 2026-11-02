"""
action_space.py
动作空间派生 + 能力掩码 + 自由产出的事后校验 + 路由。

派生公式（框架只钉唯一的结构边界，所有"判断"交给有判断力的模型）:
  本轮动作空间 = 局面合法集(phase)                          # 外部对话动作统一为 send_message
               ∪ (ACTIVE ? {accept, accept_with_reservations, file_issue, give_up})  # 四个终止全放开，模型自判

为何终止动作(含 accept)不再被框架门控:
  旧设计里 accept 门槛低(有产物即可)、file_issue/give_up 门槛高(耐心耗尽/连续坐实 2 次), 这种不
  对称会在开局把"明显失败"漏斗式挤进 accept——菜单里只剩正向出口(R4 就是首条即超时却被验收)。根因
  不是模型不会判断, 而是它想退却只有 accept 一个出口。出口补齐后, 一个有判断力的用户面对崩溃/超时
  自然会开单/走人而非验收。故连"accept 需真产物"这条也去掉: 能不能验收(包括能不能验收一次崩溃)本就
  是模型该判的, [harness error] 照样原样喂它感知, 由 prompt(G6 + ACTION SEMANTICS 的终止时机条 +
  D43_CLAUSE 性格 + <mood> 耐心)主导。真正防"验收虚无"的是 OPENING 边界(还没发任务→无 accept);
  进了 ACTIVE 就至少有一条 harness 回合可反应。耐心/consec_blame 照常算, 只喂 prompt/体感, 不锁动作。

生成纪律:
  LLM 优先从动作空间挑; 若无合适项可返回 action:"free" + message, 框架事后归类。
  缺失、越权或 channel<->message 不一致一律报 typed evaluator error，禁止猜测或投影。
"""

from __future__ import annotations

from .actions import CATALOG, Effect, Phase, assert_channel
from .dimensions import Persona
from .state import State

# --------------------------------------------------------------------------
# 局面合法集
# --------------------------------------------------------------------------
LEGAL_BY_PHASE: dict[Phase, set[str]] = {
    Phase.OPENING: {"send_message"},
    Phase.ACTIVE: {"interrupt", "keep_waiting", "send_message"},
}


class ActionResolutionError(ValueError):
    """Spec-0048/T4: action 缺失、越界或 channel 不一致，禁止猜测终态。"""

    def __init__(self, code: str, action_id: str = "") -> None:
        self.code = code
        self.action_id = action_id
        super().__init__(f"invalid action ({code}): {action_id!r}")


# --------------------------------------------------------------------------
# 派生
# --------------------------------------------------------------------------
def derive_action_space(
    phase: Phase,
    persona: Persona,
    state: State,  # noqa: ARG001  接口保留：状态不再锁动作（耐心/产物皆交模型判断），签名沿用备后用
) -> list[str]:
    space = set(LEGAL_BY_PHASE[phase])

    if phase == Phase.ACTIVE:
        # 进了 ACTIVE（= 已发过消息、至少有一条 harness 回合，哪怕是 [harness error]），四个终止动作
        # 全放开，由模型按 persona 性格(D43_CLAUSE) + <mood> 自判：验收 / 带保留验收 / 走人 / 开单。
        # 框架不替它判断"能不能验收"——包括 harness 崩溃/超时：错误照样喂它感知，有判断力的用户面对
        # 崩溃自然开单/走人而非验收（R4 的假验收纯是当时"只有 accept 一个出口"的漏斗所迫，已补齐）。
        space.update({"accept", "accept_with_reservations", "file_issue", "give_up"})

    return sorted(space)


# --------------------------------------------------------------------------
# 自由产出归类 (逃逸口)
# --------------------------------------------------------------------------
def classify_free_action(message: str, space: list[str], persona: Persona) -> str:
    """action:'free' 但未经模型自评归类时的**安全兜底**。

    不再用关键词猜意图 —— 极不准且危险: 一句 "looks good" 可能被误判成 accept、"report this"
    误判成 file_issue, 直接污染体感/issue 信号(方案 B 的动机)。真实归类由 client 的 LLM 自评完成
    (见 loop 里 resolve 前的 classify_action 接缝); 这里只在自评缺席/失败时兜底: 一律落到安全的
    **非终止**动作(优先反馈), 绝不从 prose 推断 accept/file_issue/give_up 这类终止意图。
    """
    if "send_message" in space and message.strip():
        return "send_message"
    non_terminal = [a for a in space if CATALOG[a].effect is not Effect.TERMINATE]
    if message.strip() and non_terminal:
        return sorted(non_terminal)[0]
    raise ActionResolutionError("unclassifiable_free", "free")


def project_to_legal(action_id: str, space: list[str]) -> str:
    """只确认已合法动作；排序、Effect 或历史 id 均不得承担 fallback 语义。"""
    if action_id in space:
        return action_id
    code = "missing_action" if not action_id else "action_not_in_space"
    raise ActionResolutionError(code, action_id)


# --------------------------------------------------------------------------
# resolve: 生成结果 -> 合法、归属一致的动作
# --------------------------------------------------------------------------
def resolve_action(ret: dict, space: list[str], persona: Persona) -> tuple[str, str]:
    """
    ret: LLM 返回的 dict, 含 action / message。
    返回 (action_id, message): 动作已在空间内; message 一律取模型原文, 框架绝不代写。

    message 是否必填由动作自己的 message_policy 决定。这里不 fabricate、不清空、不投影；
    accept/give_up 的可选终止说明不会创建 harness 请求。
    """
    action_id = ret.get("action", "")
    message = ret.get("message", "") or ""

    if action_id == "free":
        action_id = classify_free_action(message, space, persona)
    action_id = project_to_legal(str(action_id).strip(), space)

    try:
        assert_channel(action_id, message)
    except ValueError as exc:
        raise ActionResolutionError("channel_mismatch", action_id) from exc
    return action_id, message.strip()
