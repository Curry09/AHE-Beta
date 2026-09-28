# 实验矩阵

本文固定论文实验的组别、比较问题和报告口径。工程 canary（例如 ordinary N=1）不
进入论文主表，除非它同时满足正式 task/grader freeze。

## 统一控制变量

除被消融的变量外，各组保持一致：初始 harness revision、五轮闭环、任务/机制类别
比例、persona/seed、模型、token budget、官方 task timeout、Daytona 资源、grader、
owner gate 和最终 held-out evaluation。每条实验线独立运行，不能共享中间 revision。

主指标：官方 grader accuracy。并列报告 harness completion、user feeling、交互失败率、
deadline 率、token/cost、wall time；基础设施失败单独统计，不并入任务错误。

## A. 主实验

| ID | 名称 | 构成 | 轮数 | 用途 |
|---|---|---:|---:|---|
| M32 | Full-32 | 20 ordinary + 12 mechanism | 5 | 论文主实验；完整用户交互、设计、开发、机械 owner、revision carry-forward |

M32 是唯一主实验。其他条件均作为消融或稳健性分析，不与 M32 混称“主实验”。

## B. 数量 scaling 消融

| ID | Session 数/轮 | 推荐构成 | 轮数 | 说明 |
|---|---:|---:|---:|---|
| S4 | 4 | 3 ordinary + 1 mechanism | 5 | 最小的分层子集 |
| S8 | 8 | 5 ordinary + 3 mechanism | 5 | 保持接近 M32 的类别比例 |
| S16 | 16 | 10 ordinary + 6 mechanism | 5 | M32 的严格子集 |
| M32 | 32 | 20 ordinary + 12 mechanism | 5 | 主实验锚点 |
| S64 | 64 sessions | 40 ordinary + 24 mechanism sessions | 5 | 32 个 task/scenario identity 各用第二个固定 persona/seed 再跑一次 |

S4 ⊂ S8 ⊂ S16 ⊂ M32。S64 在当前 32 个 identity 的基础上增加第二个固定交互
replicate，因此论文中必须写成 **64 sessions**，不能写成 64 个独立任务。若后续真的
补齐 64 个唯一 task/scenario，则另建 `S64-unique`，不能与此版本混用。

之前的 ordinary N=1/N=4 五轮配置是工程链路与小规模 pilot；其中 N=4 不含机制题，
因此不能直接充当这里的 S4，否则“数量”和“数据构成”会同时变化。

## C. 用户交互消融

使用同一组 8 个同时支持两种协议的任务、相同初始 revision 和 seed，做配对比较：

| ID | 条件 | N | 轮数 | 唯一变化 |
|---|---|---:|---:|---|
| I8-D | Direct | 8 | 5 | 只有初始用户请求，无后续用户介入 |
| I8-U | Simulated user | 8 | 5 | 使用历史 persona/heartbeat 用户循环 |

τ³ 的 benchmark-native user 不强行改成 direct；它不进入这组配对实验。该组回答“用户
交互是否为闭环提供额外有效信号”，并报告 task accuracy 与 user feeling，而不是只看
harness 是否返回最终文本。

## D. 闭环组件消融

建议以 M32 为底座，至少保留以下三组：

| ID | 条件 | 移除内容 | 要回答的问题 |
|---|---|---|---|
| L-NF | No user feedback | designer/developer 看不到用户 trace、issue notes、feeling，只保留 objective grader | 用户反馈是否提供了超出 grader 的改进信号？ |
| L-ND | No designer | developer 直接读取冻结的 session + grader packet | designer 是否带来结构化归因和更稳定的修改？ |
| L-NC | No carry-forward | 每轮都从 baseline v0 开始，其他运行次数不变 | 提升是否来自跨轮 revision 累积，而不是重复采样/算力？ |

不建议用“No developer”作为单独主消融：它与静态 baseline/L-NC 信息高度重叠，而且
没有可演化对象。可以把第 1 轮 v0 结果作为 static baseline 报告。

## E. 机制 seed 组别消融

12 个机制 seed 冻结后按 3 个 family、每组 4 个组织。最终 seed 名称未冻结前，只固定
family 语义，不提前虚构 task ID：

| Family | 覆盖语义 | 例子 |
|---|---|---|
| F-CORD | 协作与任务分解 | multi-agent、subagent、loop/handoff、并行协调 |
| F-STATE | 意图和状态管理 | goal、plan mode、memory、跨步骤状态保持 |
| F-CTRL | 用户控制与旁路沟通 | permission、`/btw`、steer/nudge、interrupt/cancel |

做 leave-one-family-out：

| ID | 条件 | N | 保持 N 不变的方法 |
|---|---|---:|---|
| M-CO | 去掉 F-CORD | 32 | 用 4 个匹配难度的 ordinary session 替换 |
| M-ST | 去掉 F-STATE | 32 | 用 4 个匹配难度的 ordinary session 替换 |
| M-CT | 去掉 F-CTRL | 32 | 用 4 个匹配难度的 ordinary session 替换 |

不能简单把 32 减成 28，否则机制 family 和样本数量同时变化。替换任务按 benchmark、
难度、预期时长配对，并在 freeze record 中固定。

## F. 次级/附录实验

以下组别有价值，但不建议挤进主消融表：

| ID | 条件 | 类型 | 原因 |
|---|---|---|---|
| R-PM | `+ PM/divergent` | 角色扩展 | 主配置 PM 关闭；这是加组件，不是移除组件 |
| R-OWN | mechanical owner → LLM owner | 角色稳健性 | 同时改变成本和 release policy，解释较复杂 |
| R-MODEL | 更换 harness/user 模型 | 模型稳健性 | 回答跨模型泛化，不是 harness 机制因果消融 |
| R-SEED | 更换 persona/random seed | 方差分析 | 用于置信区间与稳定性，不是系统组件消融 |

session drop、tool failure、budget pressure 等属于工程压力测试；它们不进入本文主实验
矩阵，单独作为 reliability appendix，避免和机制语义、task distribution 混在一起。

## 推荐的论文表结构

1. 主表：M32 的最终 held-out accuracy、completion、feeling、成本，以及五轮曲线。
2. 数量图：S4/S8/S16/M32/S64 的横轴为 sessions/round，明确 S64 为 replicate。
3. 交互表：I8-D vs I8-U 的逐任务配对差值。
4. 闭环消融表：M32、L-NF、L-ND、L-NC。
5. 机制 family 表：M32、M-CO、M-ST、M-CT。
6. 附录：R-PM、R-OWN、R-MODEL、R-SEED 和工程压力测试。

若预算有限，执行优先级为：M32 → S8/S16/S64 → I8-D/I8-U → L-NF/L-ND/L-NC
→ 三个 mechanism family leave-one-out → 附录稳健性。
