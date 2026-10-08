---
number: "0052"
title: Synthesizer 提案覆盖与重复合并权责
issue: 0
slug: synthesizer-covers-consolidation
summary: 由 Synthesizer 基于全量 ProposalView 决定哪些 triage/proposal 被结构提案吸收；covers 作为唯一简化指令，目标提案创建后直接合并关闭被覆盖来源，Owner 只负责交付路由。
tasks:
  - id: T1
    title: Synthesizer covers 合并语义与状态迁移
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/demand/synthesizer.py
      - backend/auto_designer/demand/issue_schema.py
      - backend/auto_designer/demand/role_contract.py
    scope: 把 Synthesizer 产出的 covers 定义为吸收指令。结构提案创建成功后，将仍处于 report/proposal 平面的 covered 来源合并关闭并记录 merged-into；未被 covers 的提案保持独立。不得新增 Owner 语义复核或验收映射验证。
    acceptance: Synthesizer 创建带 covers 的结构提案后，covered triage/proposal 进入 closed+merged，结构提案保持 proposal；无 covers 或未被覆盖的提案保持 open；covers 仍只引用当轮可见的开放来源。
  - id: T2
    title: Owner 退回纯交付路由
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/demand/owner.py
      - backend/auto_designer/demand/agent_contract.py
      - backend/agent_defs/synthesizer/systemprompt.md
      - backend/agent_defs/owner/systemprompt.md
      - backend/agent_defs/owner/tools/submit_admission.tool.yaml
    scope: 移除 Owner 对 covers 和语义合并的责任；Owner 只处理交接 admission，保留既有精确重复兼容路径但不承担跨提案去重。同步模型可见语义。
    acceptance: Owner prompt 不再声称 covers 只作关系或由 Owner merge；Synthesizer prompt 明确 covers 会吸收并关闭来源；Owner 不会因 covers 关系关闭来源。
  - id: T3
    title: 覆盖合并回归测试与规格验证
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/tests/loop/test_synthesizer.py
      - backend/tests/demand/test_owner.py
      - backend/tests/demand/test_role_contract.py
      - backend/tests/demand/test_agent_contract.py
      - docs/specs/0052-synthesizer-covers-consolidation.md
    scope: 更新 Synthesizer/Owner 行为测试与 tool/schema drift 检查，并完成 spec validate/render/graph 及 Python 静态检查。
    acceptance: 覆盖合并、非覆盖保留、Owner 纯路由和 prompt/schema 语义测试通过；pytest、ruff、spec validate/render/graph 与 git diff --check 通过。
---

# 0052 · Synthesizer 提案覆盖与重复合并权责

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

需求面不再由 Owner 重新裁决提案之间的语义重复。Synthesize/Synthesizer 读取统一的
ProposalView，已经拥有跨 triage、Divergent 与既有结构提案的上下文，因此由它通过
`covers` 明确哪些开放 report/proposal 被当前结构提案吸收。结构提案创建成功后，driver
直接把 `covers` 中的开放来源合并关闭，并写入 `merged-into` 审计行。Owner 仅负责将仍然
开放的 proposal 交接到 OpenAgents；不新增第二道语义审核、验收映射或人工确认。

## Motivation

当前未提交的角色治理改动把 Owner 改成 Delivery Router，同时把 `covers` 降格为仅供
规划展示的关系元数据。这会留下一个实际空洞：Triage 产生的 proposal 与 Synthesizer 产生
的结构 proposal 即使明显重复，也没有角色负责将其从独立交付集合中去掉；Owner 还会把
未列出的提案默认交接。结果是重复工作进入 OpenAgents，且决定权与最有上下文的角色错位。

本组只恢复必要的合并闭环，不恢复 Owner 的产品评审职责。目标是让“是否被结构提案吸收”
成为 Synthesizer 的单一语义决定，同时保持 issue 状态迁移、审计关系和失败隔离等既有平台能力。

## Guide-level explanation

一轮需求面按以下规则运行：

1. Triage、Divergent 和 Synthesizer 生成 proposal；Synthesizer 在本轮可见的 ProposalView 上
   形成结构提案。
2. Synthesizer 提交结构提案时，`covers` 列出它决定吸收的开放来源票号。`covers` 不再是
   “请 Owner 考虑”的建议，而是 Synthesizer 已作出的合并决定。
3. driver 先创建结构提案，取得目标票号，再对 `covers` 中仍在 report/proposal 平面的
   来源执行现有 `MERGED` 状态迁移，并追加 `merged-into: #目标票号`。
4. 没有出现在 `covers` 中的来源继续开放；Owner 后续把这些 proposal（包括新的结构提案）
   直接交接。Owner 不重新判断价值方向、根因或实现方案。

本组不表示 issue 可以“半关闭”：单个来源要么整体并入并关闭，要么保留为独立交付项。
需要独立验收的部分不应放入 `covers`；以后若需要拆分，应先把来源拆成多个 issue。

## Reference-level explanation

### 权责

| 角色 | 合并权责 |
|---|---|
| Triage | 只处理当前 report 的规范化，不跨票判重 |
| Divergent | 发现能力类 proposal，不关闭既有票 |
| Synthesizer/Synthesize | 基于全量 ProposalView 决定结构提案及其 `covers` 来源 |
| Owner | 只将开放 proposal 打包交接；不消费 `covers` 进行语义合并 |
| driver/tracker | 按 Synthesizer 已提交的 `covers` 执行创建后状态迁移和审计记录 |

### `covers` 与状态

`covers: #n #m` 是结构提案正文中的唯一机器行。Synthesizer driver 继续过滤不存在、已
关闭或不在 report/proposal 平面的票号，避免新提案引用已不可合并的对象。有效来源在目标
创建后使用既有 `transition_issue(state="closed", labels=...)` 迁移到 `MERGED`；目标
提案自身仍位于 `PROPOSAL` 平面，等待 Owner 交接。合并关系通过来源评论中的
`merged-into: #目标` 保留，既有 issue 正文和历史评论不删除。

合并动作应按来源票号确定性执行，并允许重复运行时跳过已经不是开放来源的票；单条迁移
失败不影响目标提案或其他来源，失败应进入 Synthesizer outcome/事件，而不是静默吞掉。
这属于现有 tracker 的可靠状态迁移，不是新的语义验证层。

### Owner 边界

Owner 的模型输入和 submit schema 不需要新增合并字段。Owner 不读取 `covers` 来关闭来源，
未被模型列出的 proposal 仍按现有 fail-open 规则直接交接。保留已有 exact-duplicate
兼容路径时，它只是历史数据的机械兼容，不代表 Owner 获得语义去重权；新的跨票语义合并
唯一由 Synthesizer 的 `covers` 触发。

## Drawbacks

Synthesizer 的判断错误会直接影响哪些票继续独立交付；这是把决定权放回拥有全局上下文的角色
所接受的代价。为保持流程简单，本组不增加验收映射或第二个模型审核，因此结构提案必须
承担被覆盖来源的完整目标表达。`covers` 只能整体关闭来源，不能表达同一 issue 的部分
验收被承接。

## Rationale and alternatives

选择 Synthesizer 而不是 Owner，是因为 Synthesizer 同时看到开放 triage/proposal、ready 参照、
体验趋势和运行聚合，最适合判断共同机制与重复关系；Owner 的上下文和职责已经收敛为交付
路由。选择复用 `covers` 而不是新增 `consolidates` 字段，是为了减少 schema、prompt、
状态解析和前端字段的同步面。

不采用“Owner 继续做语义去重”：这会重新引入职责重叠，并使生成器与交付路由器都拥有
产品合并判断。不采用自动文本判重作为主路径：标题/正文完全相同只能识别狭窄的机械重复，
无法解决 triage 与结构提案的语义覆盖。不采用新的“部分关闭”状态：它会扩散到 plane、
Owner 过滤、OpenAgents intake 和 UI，且一个 issue 的交付边界不再清楚。

## Prior art

Spec-0029 曾把 `covers` 级联合并放在 Owner 准入阶段；Spec-0042 后续把 Owner 改为轻量
路由器并暂时将 `covers` 定义为关系。0052 恢复“结构提案可吸收来源”的行为，但将语义
决定点前移到 Synthesizer，保留三平面标签和 `MERGED`/`merged-into` 的既有机器表示。

## Unresolved questions

本组暂不解决以下问题：多个 Synthesizer 并行时对同一来源产生冲突的结构提案如何仲裁；来源
被合并后是否需要在前端默认折叠；以及跨多个结构提案的优先级如何展示。这些问题不改变
本组的最小语义：单次 Synthesizer 产物中的 `covers` 是关闭依据。

## Future possibilities

如果未来需要保留部分验收或允许一票被多个结构提案共同承接，可在不改变 Synthesizer 语义
权责的前提下增加显式拆票/子验收模型。任何新状态或新机器行都必须先更新 issue_schema、
OpenAgents intake、web 投影和对应 spec，不能把“部分关闭”继续隐含在 `covers` 中。
