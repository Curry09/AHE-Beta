"""
dimensions.py
Persona 维度定义 + 取值枚举 + 派生函数。

9 维框架（5 层）:
  A 能力底座: D1 评估能力, D2 领域&深度
  B 验收:     D3 验收阈值            (派生 D1×D2)
  C 交互行为: D4_1 委派粒度, D4_2 监督强度, D4_3 纠偏策略
  D 会话配置: D5 自主性期望, D6 授权尺度  (D6 半派生)
  E 派生:     trust 信任模型          (派生 D1×D2)

设计铁律:
- persona 是静态系数（会话开始定死），不在循环中变化。
- 维度 -> 文案 / 配置 是确定性映射（见 clauses.py），可复现、可 codegen。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


# --------------------------------------------------------------------------
# A. 能力底座
# --------------------------------------------------------------------------
class D1Eval(StrEnum):
    """D1 评估能力 —— 决定感知带宽 + 判断上限。自由采样。"""
    BLIND = "blind"          # 盲信: 几乎不核查
    SHALLOW = "shallow"      # 浅层: 读报错、跑一次, 不写测试/不审 diff
    COMPETENT = "competent"  # 胜任: 跑测试、读 diff, 能识破多数似是而非的 API
    EXPERT = "expert"        # 专家: 系统性验证, 识破幻觉/边界/DST 类 bug


class D2Depth(StrEnum):
    NOVICE = "novice"
    PROFICIENT = "proficient"
    SENIOR = "senior"


@dataclass(frozen=True)
class D2Domain:
    """D2 领域&深度。自由采样。weak 集合内的领域, D1 有效带宽降一档。"""
    stack: tuple[str, ...] = ("python",)
    depth: D2Depth = D2Depth.PROFICIENT
    weak: tuple[str, ...] = ()        # e.g. ("timezone", "pytz")


# --------------------------------------------------------------------------
# B. 验收 (派生)
# --------------------------------------------------------------------------
class D3Accept(StrEnum):
    RUNS = "runs"            # 能跑就行
    FUNCTIONAL = "functional"  # 功能正确(测过的常规用例)
    IDIOMATIC = "idiomatic"  # 现代规范
    RIGOROUS = "rigorous"    # 类型/边界严谨


# --------------------------------------------------------------------------
# C. 交互行为 (自由采样)
# --------------------------------------------------------------------------
class D41Grain(StrEnum):
    ONE_LINER = "one_liner"      # 甩一句
    HALF_CONTEXT = "half_context"  # 半上下文
    SPEC_LEVEL = "spec_level"    # 规范级(含信息供给)


class D42Supervise(StrEnum):
    EVERY_STEP = "every_step"    # 盯每步
    PHASE_CHECK = "phase_check"  # 阶段抽查
    FIRE_FORGET = "fire_forget"  # 发完不管


class D43Correct(StrEnum):
    FEEDBACK = "feedback"    # 给反馈让它改
    HANDOVER = "handover"    # 接管自己写
    RESEND = "resend"        # 重发请求
    GIVE_UP = "give_up"      # 放弃
    FILE_ISSUE = "file_issue"  # 上报结构化 issue


# --------------------------------------------------------------------------
# D. 会话配置
# --------------------------------------------------------------------------
class D5Autonomy(StrEnum):
    ADVISORY = "advisory"
    COLLABORATIVE = "collaborative"
    AGENTIC = "agentic"


class D6Authz(StrEnum):
    READ_ONLY = "read_only"      # 只读
    WRITE_NO_RUN = "write_no_run"  # 可写不可跑
    FULL_AUTO = "full_auto"      # 全自动(可写可跑)


# --------------------------------------------------------------------------
# E. 派生: 信任模型
# --------------------------------------------------------------------------
class TrustStance(StrEnum):
    BLIND = "blind"        # 盲信
    BALANCED = "balanced"  # 平衡
    SKEPTICAL = "skeptical"  # 怀疑


# --------------------------------------------------------------------------
# Persona 聚合
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Persona:
    persona_id: str
    # 自由采样
    d1: D1Eval
    d2: D2Domain
    d41: D41Grain
    d42: D42Supervise
    d43: D43Correct
    d5: D5Autonomy
    # 派生 / 半派生 (由 derive() 填)
    d3: D3Accept = field(default=D3Accept.FUNCTIONAL)
    d6: D6Authz = field(default=D6Authz.WRITE_NO_RUN)
    trust: TrustStance = field(default=TrustStance.BALANCED)


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
    """授权尺度 半派生: 由自主性期望 + 任务风险共同决定。"""
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
    """填齐派生维度, 返回不可变的完整 persona。"""
    return Persona(
        persona_id=p.persona_id,
        d1=p.d1, d2=p.d2, d41=p.d41, d42=p.d42, d43=p.d43, d5=p.d5,
        d3=derive_d3(p.d1, p.d2),
        d6=derive_d6(p.d5, task_risk),
        trust=derive_trust(p.d1, p.d2),
    )
