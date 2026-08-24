---
number: "0042"
title: 需求面角色契约治理：统一术语、规范化提案投影与可靠状态迁移
issue: 0
slug: role-contract-governance
summary: 消除需求面多代工作流语义并存的问题，以正式术语和角色职责矩阵为权威定义，建立统一 ProposalView，修复 Triage/Owner 非原子且静默失败的状态迁移，统一 System Prompt、运行时消息与 submit-tool 契约，并以跨角色测试和历史会话回放验证。
tasks:
  - id: T1
    title: 权威术语表、角色职责矩阵与现行流程基线
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - docs/specs/0042-role-contract-governance.md
      - docs/specs/OVERVIEW.md
    scope: 定义 report/proposal/ready item、Triage/Divergent/Synthesize/Owner、渐进式证据检索、merge target、covers 等正式术语；明确各角色输入、输出、权限和禁止事项；本 Spec 显式取代 0029 中机械准入、旧 Triage 落库、旧 Owner 输入和 dev 阶段描述，不改写历史决策记录。
    acceptance: 每个活动概念只有一个正式名称与机器标识；角色矩阵覆盖五个需求面角色；列出被取代的 0029 条款；OVERVIEW 指向本 Spec 作为现行补充规范。
  - id: T2
    title: Canonical ProposalView 与规范化提案版本
    status: done
    priority: P0
    tags: []
    depends-on: [T1]
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/designer/proposal_view.py
      - backend/auto_designer/designer/designer.py
      - backend/auto_designer/designer/divergent.py
      - backend/tests/designer/test_proposal_view.py
    scope: 建立任务无关的规范化提案投影单一真源，统一标题、字段、标签、优先级、来源和 covers 格式；Designer、Divergent、Owner 不再分别拼接和截断正文；原始 report 与执行细节仅经评论审计或 timeline/beat/step 渐进检索。
    acceptance: 三角色基于同一 ProposalView 数据模型生成职责适配的显式投影；Divergent 参照不含正文，Synthesize 与 Owner 获得规范化正文；默认投影不含原始报告和旧工作流标签；截断策略只有一处；相关单测通过。
  - id: T3
    title: Triage 可靠规范化迁移与结构化失败结果
    status: done
    priority: P0
    tags: []
    depends-on: [T1, T2]
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/designer/triage.py
      - backend/auto_designer/tracker/base.py
      - backend/auto_designer/tracker/fake.py
      - backend/auto_designer/tracker/gitea.py
      - backend/tests/designer/test_triage.py
      - backend/tests/tracker/test_fake.py
      - backend/tests/tracker/test_gitea.py
    scope: 将 title/body/labels 的规范化更新收敛为 tracker 单次可重试语义操作；Gitea 按其 EditIssue 与 labels 端点分步执行、校验写后状态并在可观测后步失败时补偿回滚；TriageOutcome 增加 failed，核心写入异常不得静默吞掉；原始报告审计评论失败可降级但必须产生可观测警告；重复执行不嵌套、不破坏原始证据。
    acceptance: Fake 以单次内存更新实现，Gitea 使用符合 Swagger 的分步调用、写后校验和补偿回滚；迁移失败以包含票号、主失败、回滚结果和观测状态的专用错误呈现；评论失败不改变 proposal 状态但可观测；相关测试通过。
  - id: T4
    title: Owner 决策图验证与可靠批量落库
    status: done
    priority: P0
    tags: []
    depends-on: [T1, T2]
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/designer/owner.py
      - backend/tests/designer/test_owner.py
    scope: Owner 保持轻量批量准入；执行前验证决策图，merge target 只能是既有 ready item 或本批最终 admit 的 proposal，拒绝自环、链式 merge、指向 hold/decline/merge；核心落库失败进入 failed/held 并可观测，不得静默丢失裁决。
    acceptance: 所有 proposal 仍经模型评审；owner=0 全 hold；非法 merge 图不改状态；单条失败不影响其余但明确出现在 outcome；covers 只合并未显式裁决且状态合法的对象；相关测试通过。
  - id: T5
    title: 五角色专业化 Prompt 与 Tool 契约统一
    status: done
    priority: P1
    tags: []
    depends-on: [T1, T2, T3, T4]
    relates-to: []
    parallel: false
    files:
      - backend/agent_defs/user_agent/prompt.md
      - backend/agent_defs/triage_agent/systemprompt.md
      - backend/agent_defs/divergent_pm/systemprompt.md
      - backend/agent_defs/designer/systemprompt.md
      - backend/agent_defs/owner/systemprompt.md
      - backend/agent_defs/triage_agent/tools/submit_triage.tool.yaml
      - backend/agent_defs/divergent_pm/tools/submit_divergent.tool.yaml
      - backend/agent_defs/designer/tools/submit_rfcs.tool.yaml
      - backend/agent_defs/owner/tools/submit_admission.tool.yaml
    scope: System Prompt 只声明角色不变量，运行时消息只携带本轮上下文，Tool description 只描述调用契约；统一正式术语并清除退役工作流语义；机器枚举保留英文，首次出现给出固定中文定义。user_agent 文件定义与生产 simulator 的运行时组装分别审查，不宣称两者是同一活动路径。
    acceptance: 需求面角色定义只表达现行职责、输入边界和输出契约；System Prompt、运行时消息与 Tool description 不改变彼此的工作流状态；tool schema drift-guard 与跨角色行为测试通过。
  - id: T6
    title: 跨角色契约测试、规格索引与历史会话回放
    status: done
    priority: P1
    tags: []
    depends-on: [T3, T4, T5]
    relates-to: []
    parallel: false
    files:
      - backend/tests/designer/test_role_contract_flow.py
      - backend/scripts/replay_design_from_sessions.py
    scope: 新增 report→Triage→Synthesize/Divergent 投影→Owner 的跨角色行为测试；运行设计/loop/tracker 回归，并以既有16份会话回放到 Owner 后停止，不启动 OpenAgents。
    acceptance: 无 API 测试验证 Triage 产生的精确票号集合经 Divergent 参照、Synthesize 输入到达 Owner；原始题面不进入默认下游上下文；非法状态图不可落库；相关测试、ruff、diff-check 全部通过；真实回放冻结模型、裁决、产物校验和与未启动 OpenAgents，并明确其只验证需求方向而非实现就绪度。
---

# 0042 · 需求面角色契约治理

## Summary

将需求面从多个历史版本叠加的 Prompt 与状态语义，收敛为一个可测试的角色契约体系。正式流程为：
`report（原始报告） → proposal（规范化提案） → Owner → ready item（已准入工作项）`。Triage 负责单条
规范化，Divergent 负责基于会话行为的能力发现，Synthesize 负责跨提案结构综合，Owner 只负责批量准入、
合并与优先级裁决。所有角色默认读取统一 ProposalView，具体案例通过渐进式证据检索获取。

## Motivation

当前 Spec、System Prompt、运行时消息、Tool description、Schema 与 driver 校验分别保存了不同版本的
角色制度。测试能够证明局部字段和标签可运行，却不能证明信息确实传到下一角色，也不能防止旧机械准入、
superseded 或开发完成后 covers 级联等语义重新进入活动 Prompt。多次局部修复进一步产生三份 proposal
格式化逻辑和多请求半迁移风险，需要从契约、状态和验证三个层面统一治理。

## Canonical terminology

| 正式术语 | 机器标识 | 定义 |
|---|---|---|
| 原始报告 | `report` | 用户产生的原始证据，不要求产品抽象 |
| 规范化提案 | `proposal` | 任务无关、尚未准入的需求描述 |
| 已准入工作项 | `ready` / `openagents` | 已通过 Owner 裁决，可进入交付面 |
| 报告规范化 | Triage | 单条 report 的分类、定位、标题与字段规范化 |
| 能力发现 | Divergent | 从未显式形成 report 的会话行为中识别产品能力缺口 |
| 结构综合 | Synthesize | 在规范化 backlog 上识别跨提案结构性根因 |
| 准入评审 | Owner | 批量 admit/merge/decline/hold 与优先级裁决 |
| 渐进式证据检索 | timeline→beat→step | 从摘要到执行细节的按需证据访问 |

## Role boundaries

| 角色 | 默认输入 | 输出 | 不负责 |
|---|---|---|---|
| User Simulator | 场景、persona、harness 响应 | 原始报告与体验评价 | 产品抽象和准入 |
| Triage | 单条 report、对应会话证据、只读 harness | 规范化 proposal 或 reject/needs_info | 跨提案判重 |
| Divergent | 体验索引、按需会话证据、ProposalView 参照 | 能力类 proposal | 结构性机制综合和准入 |
| Synthesize | 全量 ProposalView、ready 参照、体验与运行聚合 | 结构类 proposal 与 covers 建议 | 准入和实现设计 |
| Owner | ProposalView、ready queue、体验索引 | admit/merge/decline/hold | 重新诊断、架构设计和代码实现 |

## Superseded behavior

本 Spec 取代 0029 中以下现行描述：Owner 机械准入、`owner=0` 机械降级、Triage 规范化字段只写评论、
Owner 不读取规范化正文、Designer 使用旧 triaged/superseded 生命周期、进程内 dev 阶段。0029 保留为
历史决策记录；活动实现与 Overview 以 0032 和本 Spec 为准。

## Reliability requirements

核心状态迁移不得使用静默 `except Exception: pass`。观测与审计评论允许 best effort，但失败必须进入
事件或 outcome。多字段 issue 更新必须由 tracker 提供可重试语义操作；后端无法原子提交时必须执行写后校验，并对可观测的后步失败补偿回滚。该语义不等同于跨 HTTP 请求事务；进程在请求间终止时可能留下可识别的中间状态，调用方必须以幂等重试恢复，不得宣称原子性。Owner 必须先验证整批决策图，再执行
单条状态迁移；失败不得产生悬空 merge 关系。

## Reference-level explanation

规范化边界位于 Triage：report 保留为审计证据，活动 backlog 只暴露 ProposalView。ProposalView 是
Designer、Divergent 与 Owner 的共同只读数据模型，负责统一正文提取、规范化元数据和长度限制；Divergent 使用不含正文的紧凑判重投影，Synthesize 与 Owner 使用规范化正文投影。写入边界由 tracker
提供两类语义操作：`update_issue` 迁移 title/body/labels，`transition_issue` 迁移 state/labels。Fake 后端
可原子完成；Gitea 1.22 分别调用 EditIssue 与 labels 端点，校验最终状态，并在可观测的后续步骤失败时恢复操作前快照。Gitea 不提供覆盖两个端点的事务，故进程终止窗口由幂等重试处理。
Owner 先验证整批 decision graph，再按 admit、merge、decline、hold 顺序执行；`covers` 仅在结构提案
成功 admit 且覆盖项无显式 decision 时参与默认 merge。

## Compatibility

旧标签只允许在 tracker/issue projection 的兼容入口转换为 canonical model，不得进入活动角色 Prompt。
保留既有类名、环境变量和 submit 工具名作为 API 兼容标识，但文档和模型可见语义统一使用正式术语。

## Rationale and alternatives

未采用提示词禁词表：词汇黑名单只能覆盖已知事故，无法证明角色职责正确。专业表达通过权威术语和职责边界
评审，自动测试验证数据隔离、状态迁移和决策图等行为结果。未将原始 report 继续嵌入 proposal body，因为
下游批量读取会扩大案例泄漏与 Token 消耗；审计评论和渐进式证据工具仍保留完整可追溯性。未采用逐字段
tracker 写入，因为中途失败会产生无法可靠重试的半迁移状态。

## Validation

验证分为静态契约、单元状态机、跨角色闭环和真实回放四层。真实回放复用既有会话与报告，不重新消耗用户
模拟调用；运行至 Owner 后停止，OpenAgents 不启动。
