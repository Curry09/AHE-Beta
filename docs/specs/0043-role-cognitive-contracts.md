---
number: "0043"
title: 需求面角色认知契约：专属产物语言与行为质量门
issue: 0
slug: role-cognitive-contracts
summary: 在共享证据之上为 Triage、产品 PM、Architect 与 Owner 建立不同的认知任务、角色专属产物契约和可执行质量门，防止多角色退化为同一种技术分析 Agent。
tasks:
  - id: T1
    title: 角色产物模型与共享质量门契约
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/role_contract.py
      - backend/ahe_beta/demand/agent_contract.py
      - backend/ahe_beta/demand/submit_tools.py
      - backend/tests/demand/test_role_contract.py
      - backend/tests/demand/test_agent_contract.py
    scope: 定义四角色专属 artifact schema、来源引用、确定性不变量与结构化 revise/hold violation；保留 canonical proposal 落库投影，但不再让四角色共享同一认知表单。
    acceptance: 四角色 schema 在字段和语义目的上明确不同；Triage 单 report 来源、PM 用户/产品视角、Architect 多 proposal 关系、Owner 投资裁决均有可机检不变量；非法来源、越权票号和缺失关系被拒绝并返回结构化 violation；契约与 submit binding 单测通过。
  - id: T2
    title: Triage 单报告认知隔离与事实型提案
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/triage.py
      - backend/agent_defs/triage_agent/systemprompt.md
      - backend/agent_defs/triage_agent/tools/submit_triage.tool.yaml
      - backend/tests/demand/test_triage.py
    scope: 将 Triage 调度改为每个 report 独立上下文，可并行但不在同一模型调用暴露其他 report/proposal；产物只界定报告事实、用户影响、边界、证据与不确定项，再投影为 canonical proposal。
    acceptance: 处理 report A 的模型输入和工具作用域不含 B；Triage 不能提交跨票判重、产品机会或实现方案字段；批量运行仍可并发且 outcome 精确归属每票；正反行为测试与现有状态迁移测试通过。
  - id: T3
    title: 产品 PM 全景洞察契约
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/divergent.py
      - backend/agent_defs/divergent_pm/systemprompt.md
      - backend/agent_defs/divergent_pm/tools/submit_divergent.tool.yaml
      - backend/tests/demand/test_divergent_gate.py
    scope: 保留 PM 对全部体验、已有 report/proposal 和按需会话证据的观察权，将任务改为解释用户目标、行为、体验矛盾、产品机会与期望结果；不把 PM 定义为未报告项扫描器或去重器。
    acceptance: PM 可引用有或无 report 的 session，也可重构已有问题视角；输出必须包含用户目标、观察行为、体验矛盾、产品机会、期望结果和证据引用；不得携带代码位置、协议、阈值或实施步骤；是否重复不在 PM driver 拒绝，而由 Owner 裁决；行为测试覆盖上述正反例。
  - id: T4
    title: Architect 提案关系综合契约
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/architect.py
      - backend/agent_defs/architect/agent.yaml
      - backend/agent_defs/architect/systemprompt.md
      - backend/agent_defs/architect/tools/submit_rfcs.tool.yaml
      - backend/tests/loop/test_architect.py
    scope: 将 Architect 的认知对象锁定为 ProposalView 关系：声明来源提案、关系类型、共同矛盾、结构方向与预期杠杆；证据下钻只能验证已引用提案关系，不能脱离 proposal 自行发掘新需求。
    acceptance: 每条结构产物引用至少两条本轮可见 proposal 并解释关系；不存在或越权来源被拒绝；单条改写、无来源 session 派生和具体实现处方不能落为 from-architect；covers 仍只是 Owner 的非约束建议；行为及落库测试通过。
  - id: T5
    title: Owner 投资判断与组合质量门
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
      - T4
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/owner.py
      - backend/agent_defs/owner/agent.yaml
      - backend/agent_defs/owner/systemprompt.md
      - backend/agent_defs/owner/tools/submit_admission.tool.yaml
      - backend/tests/demand/test_owner.py
    scope: Owner 只基于角色产物、ready queue、体验摘要和证据引用判断用户价值、证据强度、范围内聚、重叠关系、投入风险与优先级；移除自由源码调查和重新诊断路径，保留 admit/merge/decline/hold。
    acceptance: Owner 只能裁决本批输入并为每项给出价值、证据、范围、重叠/风险依据；证据不足、范围不内聚或过早实施化时可观测 hold/revise，不能无理由全量放行；Owner 不调用源码搜索或自由 timeline 重新诊断；决策图和状态迁移回归通过。
  - id: T6
    title: 跨角色行为评测与真实回放验收
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
      - T3
      - T4
      - T5
    relates-to: []
    parallel: false
    files:
      - backend/tests/demand/test_role_contract_flow.py
      - tools/dev/replay/replay_roles_from_sessions.py
      - tools/dev/audit/evaluate_role_traces.py
    scope: 建立角色正例、反例与越界样例，验证同一证据经过四种认知任务产生不同 artifact；真实回放冻结完整输入、角色产物、裁决和逐角色合规评分，不以 JSON 合法或状态迁移成功代替行为验收。
    acceptance: 测试证明 Triage 不串票、PM 保持产品视角且不受 novelty 限制、Architect 解释多提案关系、Owner 做投资组合裁决并拦截越界产物；trace evaluator 输出逐角色 contract violations 和证据位置；真实回放无 OpenAgents 且完整产物可独立审计；ruff、相关 pytest、spec validate/render/graph 通过。
---

# 0043 · 需求面角色认知契约：专属产物语言与行为质量门

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

需求面角色目前共享相近的证据、工具和 `问题/根因/方向/验收` 表单，真实回放中因而反复退化为
“读取大量会话、重新技术诊断、提出实现方案”的同一种 Agent。本组把角色差异从 Prompt 描述提升为三层
可验证契约：每个角色回答不同的认知问题，提交不同的结构化 artifact，并经过与职责相匹配的质量门。

正式分工为：Triage 准确界定单条报告；产品 PM 全面观察用户行为并解释产品问题与机会；Architect
解释既有提案之间的结构关系与共同机制；Owner 判断哪些方向值得投入以及应 admit、merge、decline 或
hold。PM 不被降格为“未报告项扫描器”，重复也不在生成侧强行消除；Owner 保留全局组合裁决权。

## Motivation

Spec 0042 已统一 report/proposal/ready 状态、ProposalView、迁移可靠性和角色名称，但回放显示“数据流
正确”不等于“角色行为正确”。早期回放中，产品 PM 提出的直接操作层、原始输出可信度和变更对账接近产品
能力表达；后续回放却逐渐输出命令指纹、固定超时、关键词触发等技术处方。Triage 从保留用户任务原文摇摆到
替产品设计解决方案；Architect 有时能形成“探索/执行分层”这样的结构判断，有时又脱离 proposal 重新从
session 发掘需求；Owner 从有选择的 admit/hold/decline 退化为全部 admit、全部 covers merge。

偏差来自同质化契约：多个角色看近似证据、使用近似调查工具、提交相同字段，测试又主要断言 JSON、标签和
状态迁移。Prompt 虽写明“不负责什么”，运行时没有专属 artifact、来源关系或越界结果，因而模型只需换一个
提交按钮就能继续采用相同的技术分析范式。本组目标不是减少 PM 的观察范围，而是让全面证据经过不同认知
任务后产生真正不同、可审查的中间产物。

## Guide-level explanation

每个角色契约固定三个部分：它必须回答的认知问题、允许使用的产物语言、产物失败的条件。

| 角色 | 认知问题 | 专属产物语言 | 质量门 |
|---|---|---|---|
| Triage | 这条报告准确描述了什么问题？ | 报告事实、用户影响、边界、证据、不确定项 | 忠于单条 report；不跨票判重，不提前给产品/实现方案 |
| 产品 PM | 用户行为意味着什么产品问题和机会？ | 用户目标、观察行为、体验矛盾、产品机会、期望结果 | 以用户价值和产品能力表达；技术实现不是 PM 产物 |
| Architect | 已有提案之间有什么结构关系和共同机制？ | 来源提案、关系类型、共同矛盾、结构方向、预期杠杆 | 必须解释多提案关系；不能改写单票或脱离 proposal 发掘新需求 |
| Owner | 哪些方向值得投入，如何组成队列？ | 用户价值、证据强度、范围内聚、重叠、风险、优先级、裁决 | 只能裁决输入；证据不足、边界混乱或过早方案化时 hold/revise |

PM 继续获得全部体验索引、已有 report/proposal 参照和按需会话证据。它可以重新解释已有报告，也可以从未
报告行为发现机会；系统不要求每条 PM 洞察证明“前所未有”。PM 与其他生成器的重叠是合法输入，是否合并由
Owner 判断。其边界是产品视角而非 novelty：输出回答用户目标、体验矛盾和期望结果，而不是指定代码位置、
协议、阈值或实现步骤。

质量门分为两类。机器可证明的不变量在落库前硬拒绝，例如来源票不存在、Triage 同时引用多份 report、
Architect 少于两条来源或 Owner 裁决越权。产品视角、抽象层级和范围内聚等语义质量不能用关键词黑名单
可靠判断，采用角色正反例、结构化 revise 原因和回放评分验证；首次不合格允许同轮修订，仍不合格则产生
可观测 hold/revise，不伪装成合格 proposal。

## Reference-level explanation

### Artifact 与 canonical proposal

新增角色 artifact 契约层。artifact 保存角色原始认知产物及来源，再由确定性投影生成现有 canonical
proposal，保持 tracker、前端和 OpenAgents 的 report/proposal/ready 流程兼容。四个 submit tool 不再共享
同一个 RFC item schema：

- Triage artifact：`source_report`、`reported_problem`、`user_impact`、`scope_boundary`、
  `evidence`、`uncertainties`。
- PM artifact：`user_goal`、`observed_behaviors`、`experience_tension`、`product_opportunity`、
  `desired_outcome`、`evidence_sessions`，可选 `related_proposals` 只作参照，不表达 merge。
- Architect artifact：`source_proposals`、`relationship`、`common_tension`、
  `structural_direction`、`expected_leverage`，可选 `covers` 仍只是 Owner 建议。
- Owner decision：既有 `decision/into/priority/reason` 外，增加 `user_value`、`evidence_strength`、
  `scope_cohesion`、`overlap` 与 `delivery_risk`，使投资判断可观察。

`role_contract.py` 负责 schema 之外的集合和来源不变量，并返回稳定 violation code，例如
`foreign-source`、`not-cross-proposal`、`decision-out-of-batch`。不得用事故词汇黑名单推断角色质量。

### 角色执行边界

Triage 可并行处理多个 report，但每个模型 invocation 只包含当前 report、其关联 session 证据和只读 harness
背景；结果按票号独立归属。产品 PM 保持全景输入，不做生成侧去重。Architect 首先读取全量 ProposalView；
timeline/beat 下钻必须由当前可见 proposal 的证据引用发起，仅用于验证关系，不允许成为无来源新 proposal
的依据。Owner 接收角色 artifact、ProposalView、ready queue、体验摘要和证据摘要，不提供自由源码搜索；
它评估投入价值而非重新生成根因和方案。

### 质量门与行为评测

运行时先执行 schema 校验，再执行来源/集合硬不变量，最后记录语义自审结果。语义门使用稳定维度而非禁词：
`evidence_fidelity`、`product_orientation`、`cross_proposal_reasoning`、`investment_judgment`、
`abstraction_level`。它可以由同一角色结构化自审或独立评测器实现，但评测输入、结果和证据位置必须落 trace；
任何自动模型评测都不得直接改 tracker 状态，状态仍由 driver 的确定性规则和 Owner 裁决控制。

正反例测试使用任务无关的合成证据：同一组会话分别经过四角色，断言 Triage 产事实边界、PM 产产品机会、
Architect 产关系解释、Owner 产投资裁决。测试拒绝“字段存在即合格”的断言，必须覆盖典型串岗产物。

### DAG 与文件分配

| Task | 内容 | 依赖 |
|---|---|---|
| T1 | artifact schema、共享不变量与 violation | — |
| T2 | Triage 单报告隔离 | T1 |
| T3 | 产品 PM 全景洞察 | T1 |
| T4 | Architect 关系综合 | T1、T2、T3 |
| T5 | Owner 投资质量门 | T1、T4 |
| T6 | 跨角色行为评测与真实回放 | T2、T3、T4、T5 |

文件由 frontmatter 的 Task `files` 独占。端到端入口为
`tools/dev/audit/evaluate_role_traces.py` 配合 `replay_roles_from_sessions.py`：回放运行到 Owner 停止，
输出完整 artifact、来源关系、violation、裁决和逐角色评分，不启动 OpenAgents。

## Drawbacks

角色专属 schema 增加迁移成本，历史 proposal 只能通过兼容投影参与新 Owner 评审。Triage 从一批一次调用改为
逐票隔离会增加请求次数，但可通过并发保持墙钟时间。Architect 的来源约束可能漏掉仅有一条 proposal 却很
重要的结构信号；这种信号应由 PM 先形成产品 proposal，再进入下一轮综合。语义质量不能完全由确定性代码
判断，引入评测器会增加成本和不确定性，因此语义评分默认用于 revise/hold 与观测，不直接拥有状态写权限。

## Rationale and alternatives

未采用“给四份 Prompt 增加更多禁止事项”：既有回放已经证明，角色共享输入和表单时，Prompt 身份容易被通用
调查范式覆盖。未采用“严格隔离 PM，只允许查看无 report session”：产品 PM 需要全面理解体验，也应能重构
已有报告的产品意义；限制其提交内容的视角比限制其观察范围更符合职责。未采用生成侧强制 novelty/去重：
相似提案可能表达不同产品机会，过早去重会损失信息，Owner 才拥有组合视角和合并权。

选择“专属 artifact + 可证明不变量 + 语义行为评测”，因为三层分别解决表达同质化、来源越权和抽象层漂移；
同时保留 canonical proposal 作为下游兼容层，避免重写 tracker 与交付面协议。

## Prior art

现有 ProposalView 已证明统一只读数据模型能消除格式漂移，本组在其上增加角色专属投影和 artifact。现有 Owner
decision graph 已证明先验证整批再迁移状态的模式可行，本组把相同思路扩展到来源集合和投资裁决字段。编译器
的 typed intermediate representation 提供了相近原则：各阶段可以共享底层事实，但必须通过不同、可校验的
中间表示交接，不能只靠阶段名称约束行为。

## Unresolved questions

语义质量门首版采用角色自审、独立低成本模型评测，还是只在离线回放中评分，需在实现 T1 前根据调用成本与
误拒绝率选定；无论选择哪种，自动评测都不拥有 tracker 写权限。历史 canonical proposal 缺少角色 artifact
时，Owner 是直接按兼容低置信输入评审，还是先进入一次迁移/重述队列，也留待实现前确定。

## Future possibilities

积累足够 trace 后，可建立按角色分层的长期指标：Triage 事实保真率、PM 产品视角得分、Architect 跨提案
杠杆率、Owner hold/merge 校准度。角色 artifact 也可支持多模型分工、人工抽样校准和从 Owner 反馈反向改进
上游契约，但不得把 Owner 的单次偏好固化为事故词汇规则。
