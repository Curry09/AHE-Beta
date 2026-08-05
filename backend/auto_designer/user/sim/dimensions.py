"""
dimensions.py
Persona 维度定义 + 取值枚举 + 派生函数。

Spec-0037/T2: tempo 时间气质；过程卷入语义；D6Authz 标为会话策略（非卡库人轴）。

人的真源（卡库可改）与会话派生分层：
  A 能力底座: D1 评估能力, D2 领域&深度
  B 验收:     D3 验收阈值            (可由 D1×D2 派生；卡 grounded 时覆盖)
  C 相处方式: D4_1 委派粒度, D4_2 过程卷入, D4_3 质量失败策略, tempo 时间气质
  D 自主期望: D5 自主性期望
  E 会话策略: D6 授权尺度            (非卡库人轴；由自主性+任务风险半派生)
  F 信任:     trust                  (可由 D1×D2 派生；卡 grounded 时覆盖)

铁律:
- persona 是静态系数（会话开始定死），不在循环中变化。
- 质量失败策略 ⊥ 时间气质：较真但能等、随手接受但等两分钟就炸，都真实。
- 维度 -> 文案 / 配置 是确定性映射（见 clauses.py），可复现、可 codegen。
- 不把当前 harness UX（interrupt / queued / slash）焊进维度枚举。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


# --------------------------------------------------------------------------
# A. 能力底座
# --------------------------------------------------------------------------
class D1Eval(StrEnum):
    """D1 评估能力 —— 决定感知带宽 + 判断上限。自由采样。"""

    BLIND = "blind"  # 盲信: 几乎不核查
    SHALLOW = "shallow"  # 浅层: 读报错、跑一次, 不写测试/不审 diff
    COMPETENT = "competent"  # 胜任: 跑测试、读 diff, 能识破多数似是而非的 API
    EXPERT = "expert"  # 专家: 系统性验证, 识破幻觉/边界/DST 类 bug


class D2Depth(StrEnum):
    NOVICE = "novice"
    PROFICIENT = "proficient"
    SENIOR = "senior"


@dataclass(frozen=True)
class D2Domain:
    """D2 领域&深度。自由采样。weak 集合内的领域, D1 有效带宽降一档。"""

    stack: tuple[str, ...] = ("python",)
    depth: D2Depth = D2Depth.PROFICIENT
    weak: tuple[str, ...] = ()  # e.g. ("timezone", "pytz")


# --------------------------------------------------------------------------
# B. 验收 (派生)
# --------------------------------------------------------------------------
class D3Accept(StrEnum):
    RUNS = "runs"  # 能跑就行
    FUNCTIONAL = "functional"  # 功能正确(测过的常规用例)
    IDIOMATIC = "idiomatic"  # 现代规范
    RIGOROUS = "rigorous"  # 类型/边界严谨


# --------------------------------------------------------------------------
# C. 相处方式 (自由采样)
# --------------------------------------------------------------------------
class D41Grain(StrEnum):
    ONE_LINER = "one_liner"  # 甩一句
    HALF_CONTEXT = "half_context"  # 半上下文
    SPEC_LEVEL = "spec_level"  # 规范级(含信息供给)


class D42Supervise(StrEnum):
    """过程卷入（原名 supervision）：对「助手在干什么」需要多少可见感。

    枚举字符串保留兼容旧测试/卡映射；语义是人的过程焦虑，不是产品按钮。
    """

    EVERY_STEP = "every_step"  # 高卷入: 过程不可见就不安
    PHASE_CHECK = "phase_check"  # 中卷入: 关键节点要有把握
    FIRE_FORGET = "fire_forget"  # 低卷入: 只要结果


class D43Correct(StrEnum):
    """质量失败后的策略（只答「结果不对时怎么办」；不驱动等待耐心）。"""

    FEEDBACK = "feedback"  # 给反馈让它改
    HANDOVER = "handover"  # 接管自己写
    RESEND = "resend"  # 重发请求
    GIVE_UP = "give_up"  # 放弃
    FILE_ISSUE = "file_issue"  # 上报结构化 issue


class TimeTemperament(StrEnum):
    """时间气质：对等待与空转的耐受（与质量失败策略正交）。"""

    PATIENT = "patient"
    STEADY = "steady"
    IMPATIENT = "impatient"


# --------------------------------------------------------------------------
# D. 自主期望
# --------------------------------------------------------------------------
class D5Autonomy(StrEnum):
    ADVISORY = "advisory"
    COLLABORATIVE = "collaborative"
    AGENTIC = "agentic"


# --------------------------------------------------------------------------
# E. 会话策略（非卡库人轴）
# --------------------------------------------------------------------------
class D6Authz(StrEnum):
    """授权尺度：会话/产品策略，由自主性期望半派生；不进卡库。"""

    READ_ONLY = "read_only"  # 只读
    WRITE_NO_RUN = "write_no_run"  # 可写不可跑
    FULL_AUTO = "full_auto"  # 全自动(可写可跑)


# --------------------------------------------------------------------------
# F. 信任
# --------------------------------------------------------------------------
class TrustStance(StrEnum):
    BLIND = "blind"  # 盲信
    BALANCED = "balanced"  # 平衡
    SKEPTICAL = "skeptical"  # 怀疑


# --------------------------------------------------------------------------
# Persona 聚合
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Persona:
    persona_id: str
    # 自由采样（人轴）
    d1: D1Eval
    d2: D2Domain
    d41: D41Grain
    d42: D42Supervise
    d43: D43Correct
    d5: D5Autonomy
    tempo: TimeTemperament = TimeTemperament.STEADY
    # 派生 / 半派生：默认 None 表示「未提供，待 finalize_persona 派生填齐」。
    # 若调用方（如 0006/T2 注入层）显式给了 grounded 值，finalize 不再改写（fallback-only）。
    d3: D3Accept | None = None
    d6: D6Authz | None = None
    trust: TrustStance | None = None


# --------------------------------------------------------------------------
# 派生函数 (确定性)
# --------------------------------------------------------------------------
def derive_d3(d1: D1Eval, d2: D2Domain) -> D3Accept:
    """验收阈值 = f(D1, D2)。能力越高 + 越资深 -> 阈值越严。"""
    base = {
        D1Eval.BLIND: D3Accept.RUNS,
        D1Eval.SHALLOW: D3Accept.FUNCTIONAL,
        D1Eval.COMPETENT: D3Accept.IDIOMATIC,
        D1Eval.EXPERT: D3Accept.RIGOROUS,
    }[d1]
    # 资深再抬一档, 新手再降一档(在枚举序内 clamp)
    order = [D3Accept.RUNS, D3Accept.FUNCTIONAL, D3Accept.IDIOMATIC, D3Accept.RIGOROUS]
    idx = order.index(base)
    if d2.depth == D2Depth.SENIOR:
        idx = min(idx + 1, len(order) - 1)
    elif d2.depth == D2Depth.NOVICE:
        idx = max(idx - 1, 0)
    return order[idx]


def derive_trust(d1: D1Eval, d2: D2Domain) -> TrustStance:
    """信任初值 = f(D1, D2)。盲信能力 -> 盲信; 高能力 -> 平衡偏怀疑。"""
    if d1 == D1Eval.BLIND:
        return TrustStance.BLIND
    if d1 == D1Eval.EXPERT:
        return TrustStance.SKEPTICAL
    return TrustStance.BALANCED


def derive_d6(d5: D5Autonomy, task_risk: str = "low") -> D6Authz:
    """授权尺度 半派生: 由自主性期望 + 任务风险共同决定（会话策略，非卡库）。"""
    base = {
        D5Autonomy.ADVISORY: D6Authz.READ_ONLY,
        D5Autonomy.COLLABORATIVE: D6Authz.WRITE_NO_RUN,
        D5Autonomy.AGENTIC: D6Authz.FULL_AUTO,
    }[d5]
    # 高风险任务收紧一档
    if task_risk == "high":
        downgrade = {
            D6Authz.FULL_AUTO: D6Authz.WRITE_NO_RUN,
            D6Authz.WRITE_NO_RUN: D6Authz.READ_ONLY,
            D6Authz.READ_ONLY: D6Authz.READ_ONLY,
        }
        base = downgrade[base]
    # collaborative 在低风险下通常允许跑(贴合"会自己跑一下"的核查习惯)
    if d5 == D5Autonomy.COLLABORATIVE and task_risk == "low":
        base = D6Authz.FULL_AUTO
    return base


def finalize_persona(p: Persona, task_risk: str = "low") -> Persona:
    """填齐派生维度, 返回不可变的完整 persona。

    fallback-only：只对未提供（None）的派生维度调用 derive_* 填齐；调用方已显式给的
    grounded 值原样保留、不被改写。这样 0006/T2 注入层可让卡里 grounded 的验收(d3)/信任(trust)
    覆盖派生——否则 expert×over-trust（Karpathy）会被模拟成 skeptical×rigorous 的反面。
    """
    return Persona(
        persona_id=p.persona_id,
        d1=p.d1,
        d2=p.d2,
        d41=p.d41,
        d42=p.d42,
        d43=p.d43,
        d5=p.d5,
        tempo=p.tempo,
        d3=p.d3 if p.d3 is not None else derive_d3(p.d1, p.d2),
        d6=p.d6 if p.d6 is not None else derive_d6(p.d5, task_risk),
        trust=p.trust if p.trust is not None else derive_trust(p.d1, p.d2),
    )
