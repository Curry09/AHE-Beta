"""
action_space.py
动作空间派生 + 能力掩码 + 自由产出的事后校验 + 路由。

派生公式（框架只钉唯一的结构边界，所有"判断"交给有判断力的模型）:
  本轮动作空间 = 局面合法集(phase)                          # 唯一结构边界: OPENING 还没东西可评→只能发任务
               ∩ 能力掩码(D1)                              # persona 保真: 做不做得到(盲评不读 diff)
               ∩ 授权尺度(D6)                              # persona 保真: 被不被允许(只读不给自动跑)
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
  越权动作投影回合法集。channel<->message 一致性强校验。
"""

from __future__ import annotations

from .actions import (
    CATALOG,
    Channel,
    Effect,
    Phase,
)
from .dimensions import (
    D1Eval,
    D6Authz,
    Persona,
)
from .state import State

# --------------------------------------------------------------------------
# 局面合法集
# --------------------------------------------------------------------------
LEGAL_BY_PHASE: dict[Phase, set[str]] = {
    Phase.OPENING: {"send_task"},
    Phase.ACTIVE: {
        "refine_request",
        "give_feedback",
        "verify_self",
        "ask_harness_run",
        "request_evidence",
        "grant_autorun",
    },
}


# --------------------------------------------------------------------------
# 能力掩码: D1 决定哪些核查动作可用
# --------------------------------------------------------------------------
def cap_mask(p: Persona) -> dict[str, bool]:
    d1 = p.d1
    return {
        "read_code": d1 != D1Eval.BLIND,
        "run_once": d1 in (D1Eval.SHALLOW, D1Eval.COMPETENT, D1Eval.EXPERT),
        "run_tests": d1 in (D1Eval.COMPETENT, D1Eval.EXPERT),
        "review_diff": d1 in (D1Eval.COMPETENT, D1Eval.EXPERT),
    }


def _cap_filter(space: set[str], mask: dict[str, bool]) -> set[str]:
    out = set(space)
    # verify_self 需要至少能 read_code 或 run_once
    if not (mask["read_code"] or mask["run_once"]):
        out.discard("verify_self")
    # request_evidence(要 diff / 测试报告) 需要 review_diff 或 run_tests
    if not (mask["review_diff"] or mask["run_tests"]):
        out.discard("request_evidence")
    return out


def _authz_filter(space: set[str], authz: D6Authz) -> set[str]:
    out = set(space)
    if authz == D6Authz.READ_ONLY:
        out.discard("ask_harness_run")
        out.discard("grant_autorun")
    elif authz == D6Authz.WRITE_NO_RUN:
        out.discard("grant_autorun")  # 可写不可跑 -> 不放开全自动
    return out


# --------------------------------------------------------------------------
# 派生
# --------------------------------------------------------------------------
def derive_action_space(
    phase: Phase,
    persona: Persona,
    state: State,  # noqa: ARG001  接口保留：状态不再锁动作（耐心/产物皆交模型判断），签名沿用备后用
) -> list[str]:
    legal = set(LEGAL_BY_PHASE[phase])
    space = _cap_filter(legal, cap_mask(persona))
    space = _authz_filter(space, persona.d6)

    if phase == Phase.ACTIVE:
        # 进了 ACTIVE（= 已发过任务、至少有一条 harness 回合，哪怕是 [harness error]），四个终止动作
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
    for prefer in ("give_feedback", "refine_request", "ask_harness_run"):
        if prefer in space:
            return prefer
    non_terminal = [a for a in space if CATALOG[a].effect is not Effect.TERMINATE]
    return sorted(non_terminal)[0] if non_terminal else space[0]


def project_to_legal(action_id: str, space: list[str]) -> str:
    """越权动作投影回合法集。"""
    if action_id in space:
        return action_id
    if action_id in CATALOG:
        want = CATALOG[action_id].effect
        # 负向终止(file_issue/give_up)未解锁时, 绝不投影到 accept —— 语义相反, 会把
        # "不满想升级"误记成"满意接受", 双重污染体感/issue 信号。降级为继续反馈, 把终止权
        # 交回闸门(耐心 or 诊断): 下一轮闸门开了, persona 自然会真正落地 file_issue/give_up。
        if want is Effect.TERMINATE and action_id != "accept":
            if "give_feedback" in space:
                return "give_feedback"
            non_term = [a for a in space if CATALOG[a].effect is not Effect.TERMINATE]
            if non_term:
                return sorted(non_term)[0]
        same = [a for a in space if CATALOG[a].effect is want]
        if same:
            return same[0]
    return space[0]


# --------------------------------------------------------------------------
# resolve: 生成结果 -> 合法、归属一致的动作
# --------------------------------------------------------------------------
def resolve_action(ret: dict, space: list[str], persona: Persona) -> tuple[str, str]:
    """
    ret: LLM 返回的 dict, 含 action / message。
    返回 (action_id, message): 动作已在空间内; message 一律取模型原文, 框架绝不代写。

    空 message 的补齐**只**发生在 client 侧（选了要发话的动作却空 message → 重问模型自己补，见
    persona_client._retry_reminder）。这里不再 fabricate 任何罐头：SILENT 动作清空 message（铁律）;
    EMIT 动作若仍为空，就保持空，由 run_session 决定「本轮不外发、不入 transcript」——宁可空转，
    也绝不把框架编的话当成用户原话发给 harness / 落进体感信号。
    """
    action_id = ret.get("action", "")
    message = ret.get("message", "") or ""

    if action_id == "free":
        action_id = classify_free_action(message, space, persona)
    if action_id not in space:
        action_id = project_to_legal(action_id, space)

    spec = CATALOG[action_id]
    if spec.channel is Channel.SILENT:  # SILENT 铁律：内部动作不发话
        message = ""
    return action_id, message.strip()
