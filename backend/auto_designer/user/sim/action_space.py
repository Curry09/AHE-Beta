"""
action_space.py
动作空间派生 + 能力掩码 + 自由产出的事后校验 + 路由。

派生公式:
  本轮动作空间 = 局面合法集(phase)
               ∩ 能力掩码(D1)
               ∩ 授权尺度(D6)
               ∪ 耐心门解锁的终止动作(patience<=0 时, 由 D4.3 选)
               ∪ (有可接受产物 ? {accept})

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
    assert_channel,
)
from .dimensions import (
    D1Eval,
    D6Authz,
    D43Correct,
    Persona,
)
from .state import State

# --------------------------------------------------------------------------
# 局面合法集
# --------------------------------------------------------------------------
LEGAL_BY_PHASE: dict[Phase, set[str]] = {
    Phase.OPENING: {"send_task"},
    Phase.ACTIVE: {
        "refine_request", "give_feedback",
        "verify_self", "ask_harness_run", "request_evidence",
        "grant_autorun",
    },
}

# 诊断驱动升级阈值: 连续 N 次坐实 harness 失败(含"婉拒/声称做不到")即认定能力缺口。
_DIAGNOSIS_BLAME_THRESHOLD = 2


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


def _d43_terminal(p: Persona) -> str:
    """耐心耗尽时 D4.3 决定走哪个终止动作。"""
    return {
        D43Correct.GIVE_UP: "give_up",
        D43Correct.FILE_ISSUE: "file_issue",
        D43Correct.FEEDBACK: "give_up",   # 反馈型耗尽后默认放弃
        D43Correct.RESEND: "give_up",
        D43Correct.HANDOVER: "give_up",   # 接管本演示当作放弃 harness 路径
    }[p.d43]


# --------------------------------------------------------------------------
# 派生
# --------------------------------------------------------------------------
def derive_action_space(
    phase: Phase,
    persona: Persona,
    state: State,
    has_artifact: bool,
) -> list[str]:
    legal = set(LEGAL_BY_PHASE[phase])
    space = _cap_filter(legal, cap_mask(persona))
    space = _authz_filter(space, persona.d6)

    # 耐心门(消耗驱动): 耗尽才解锁终止动作
    if state.patience <= 0:
        space.add(_d43_terminal(persona))

    # 诊断门(诊断驱动): 高能力档连续坐实 harness 失败即认定能力缺口, 立即解锁升级,
    # 不必等耐心磨到 0("婉拒=无能力, 看穿即可升级")。低能力档(blind/shallow)无此快速
    # 通道——识别"结构性无能力"本身需要能力, 他们仍靠耐心消耗终止。
    if (state.consec_blame >= _DIAGNOSIS_BLAME_THRESHOLD
            and persona.d1 in (D1Eval.COMPETENT, D1Eval.EXPERT)):
        space.add(_d43_terminal(persona))

    # accept 与耐心无关: 有可接受产物即可
    if has_artifact and phase == Phase.ACTIVE:
        space.add("accept")

    return sorted(space)


# --------------------------------------------------------------------------
# 自由产出归类 (逃逸口)
# --------------------------------------------------------------------------
def classify_free_action(message: str, space: list[str], persona: Persona) -> str:
    """把 action:'free' 的自由文本映射到一个合法动作 id。
    极简启发式; 生产中可换成 [COUNTERPARTY] 感知器 / 小分类模型。"""
    m = (message or "").lower()
    if any(k in m for k in ("looks good", "lgtm", "就这样", "可以了", "accept", "fine, ")):
        if "accept" in space:
            return "accept"
    if any(k in m for k in ("give up", "算了", "不弄了", "forget it")):
        if "give_up" in space:
            return "give_up"
    if any(k in m for k in ("file an issue", "提个 issue", "report this")):
        if "file_issue" in space:
            return "file_issue"
    if any(k in m for k in ("run", "跑一下", "execute", "试一下")):
        if "ask_harness_run" in space:
            return "ask_harness_run"
        if "verify_self" in space:
            return "verify_self"
    # 默认归为反馈(最常见的推进动作)
    if "give_feedback" in space:
        return "give_feedback"
    return space[0]


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
    返回 (action_id, message), 已保证: 在动作空间内 + channel<->message 一致。
    """
    action_id = ret.get("action", "")
    message = ret.get("message", "") or ""

    if action_id == "free":
        action_id = classify_free_action(message, space, persona)
    if action_id not in space:
        action_id = project_to_legal(action_id, space)

    spec = CATALOG[action_id]
    # channel 修正: SILENT 强制清空 message; EMIT 但空 -> 兜底填充
    if spec.channel is Channel.SILENT:
        message = ""
    elif spec.channel is Channel.EMIT and not message.strip():
        message = _fallback_message(action_id)

    assert_channel(action_id, message)  # 最终一致性断言
    return action_id, message


def _fallback_message(action_id: str) -> str:
    return {
        "send_task": "Please implement the requested function.",
        "give_feedback": "That isn't working yet, please fix it.",
        "ask_harness_run": "Please run it once and show me the result.",
        "accept": "Looks good, thanks.",
        "give_up": "I'll stop here for now.",
        "file_issue": "I'm filing an issue about this.",
    }.get(action_id, "Please continue.")
