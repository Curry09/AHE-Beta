---
number: "0055"
title: 目标感知的需求面证据分层与角色可见性
issue: 0
slug: goal-aware-demand-evidence-boundaries
summary: 在不把完整用户 trace 灌入需求面角色的前提下，将用户目标演化、关键交互行为和客观执行结果编成有来源的分层证据；Triage 默认获得当前 report 的有界目标感知证据，产品 PM 保持全局体验视野，Architect 只沿 proposal 关系下钻，避免额外延迟、跨题过拟合和主观 accept 冒充客观通过。
tasks:
  - id: T1
    title: 定义目标感知证据包与分层读取契约
    status: done
    priority: P0
    tags: []
    depends-on:
      - 0054/T4
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/evidence_contract.py
      - backend/tests/demand/test_evidence_contract.py
    scope: 定义 report、user_goal、interaction、objective、harness_source 五类证据及 provenance；定义 L0 report、L1 compact goal-aware summary、L2 timeline、L3 targeted beat、L4 step/objective detail 的字段、字符上限、调用条件和角色权限。L1 必须由落盘数据确定性生成，不新增 LLM 调用。
    acceptance: 每个证据字段有来源、用途和最大大小；L1 不含完整 raw persona prompt、全量 stdout、目标项目源码或 benchmark oracle；缺失字段显式为 unavailable；契约单测覆盖旧 session 兼容、空 goal ledger 和超长截断。
  - id: T2
    title: 用户反馈 handoff 与 Triage 单报告输入
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
      - 0054/T4
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/triage.py
      - backend/ahe_beta/demand/role_contract.py
      - backend/agent_defs/triage_agent/systemprompt.md
      - backend/agent_defs/triage_agent/tools/get_session_timeline.tool.yaml
      - backend/tests/demand/test_triage.py
    scope: session 结束时生成可交接的 user_feedback envelope；Triage 的默认输入为当前 report + L1 目标感知摘要 + 该 session 的 feeling/终止原因，L2/L3 只能按当前 report 的证据缺口按需读取。保留单 report 隔离，不向同一调用暴露其他 report、全局聚合或无关 session。
    acceptance: Triage 能看到 B0 初始目标、当前目标、revision before/after/reason、关键 target/action/effect 和用户明确反馈；每个证据带 session/turn 来源；没有证据时能返回 needs_info；Triage 不将 goal met、user accept 或具体目标项目答案当作客观通过；handoff 可被 triage 直接消费且不需重新解析整段聊天。
  - id: T3
    title: 产品 PM 全局体验输入与产品视角边界
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
      - 0054/T4
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/divergent.py
      - backend/agent_defs/divergent_pm/systemprompt.md
      - backend/agent_defs/divergent_pm/tools/get_session_timeline.tool.yaml
      - backend/tests/demand/test_divergent_gate.py
    scope: PM 保留跨 session 的体验索引和全局观察权，但默认消费 L1/L2 摘要；可引用有 report 或无 report 的 session，比较用户目标、行为、体验矛盾和期望结果。PM 的 artifact 不得携带代码位置、协议字段、固定阈值或实施步骤；重复与否由 Owner 决定。
    acceptance: PM 输入能表达目标变化和用户反馈而非只有 feeling 分数；PM 可以引用多个 session 但每个引用有证据来源；产物字段只包含 user_goal、observed_behaviors、experience_tension、product_opportunity、desired_outcome、evidence_sessions；未报告 session 不因 novelty 规则被拒；PM 不因 trace 过大而默认读取 L3/L4。
  - id: T4
    title: Architect 提案关系输入与证据下钻约束
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
      - T2
      - T3
      - 0054/T4
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/architect.py
      - backend/agent_defs/architect/systemprompt.md
      - backend/ahe_beta/demand/session_timeline.py
      - backend/tests/loop/test_architect.py
    scope: Architect 默认以 ProposalView 和 proposal artifact 关系为输入，仅对已引用 proposal 的 session evidence 做 L2/L3 验证；禁止从无来源 raw session 重新发掘单票需求。目标 ledger 作为引用 proposal 的用户意图证据，不作为实现规格或客观验收。
    acceptance: 每个结构提案至少引用两条本轮可见 proposal 并解释关系；下钻调用包含来源 proposal 和理由；越权 session、无来源需求和具体实现处方被拒或转为可观测 revise；Architect 的默认 token 和工具调用量不因全量 trace 线性膨胀。
  - id: T5
    title: 角色可见性、过拟合和延迟回归评测
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
      - T3
      - T4
    relates-to: []
    parallel: false
    files:
      - tools/dev/audit/evaluate_role_traces.py
      - backend/tests/demand/test_role_contract_flow.py
    scope: 增加同一批 session 的旧输入/新分层输入对照回放，分别记录每角色输入 token、工具调用数、墙钟时间、证据引用、跨题专有名词泄漏和 artifact 语义违规；用户主观结论与 objective evaluator 结果独立评分。
    acceptance: 对照报告能证明 Triage 只消费单 report 证据、PM 保持全局产品视角、Architect 只做 proposal 关系综合；L1 默认路径不新增模型调用；L2/L3 超预算或越权读取可观测并降级；trace 中的目标项目文件名/答案不能进入通用 proposal 字段；`accept` 与 objective failed/unverified 的组合不被评为整体成功。
---

# 0055 · 目标感知的需求面证据分层与角色可见性

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG）。正文是第一性原理、角色边界和实现契约。 -->

## Summary

用户目标机制解决了一个旧问题：从 trace 中可以知道用户为什么等待、打断、修改请求或接受结果。但如果把完整
`sim_trace` 直接塞进所有需求面角色，系统会出现两个反作用：上下文和工具调用增加，Triage 变慢；目标项目的
文件名、命令、测试答案进入模型视野，角色开始针对单题过拟合。

本 spec 不把“看 trace”理解为“读取全部日志”，而是把用户证据做成有来源、分层、按需读取的输入契约：

```text
raw report
  + L1 目标感知摘要（默认、确定性生成）
  + L2 当前问题相关的时间线（按需）
  + L3 某一拍活动（按需）
  + L4 单步/客观细节（严格按需）
```

Triage、产品 PM 和 Architect 使用不同的层级和视野。这样目标机制进入需求面，但不会把三个角色重新变成同一
个“读全量日志再给技术方案”的 Agent。

## First principles

### 1. Triage 的问题是“这条报告准确描述了什么”

Triage 要把用户观察转换为事实边界、用户影响和不确定性，并判断问题是否属于 harness。要回答这个问题，
它至少需要知道：

- 用户最初想完成什么；
- 用户在交互中实际做了什么；
- 目标是否被修订，修订的理由是什么；
- 用户为什么继续等待、打断、提出反馈或接受；
- 哪些是用户主观判断，哪些是客观执行证据。

因此，Triage 完全看不到用户 trace 是错误的；它会退化成对 issue 正文的语言整理器，容易输出泛化的 prompt
建议或错误地把用户误解当成 harness 缺陷。

但 Triage 不需要全量 trace。它不负责跨 issue 的产品综合，也不负责重放每个工具步骤。默认 L1 摘要足以判定
是否需要进一步取证，只有存在明确证据缺口时才允许 L2/L3 下钻。

### 2. 产品 PM 的问题是“用户体验意味着什么产品机会”

PM 需要比 Triage 更宽的观察面：它必须能比较多个 session，也必须能看到没有正式 issue 的反复行为，否则只能
在已有 report 上做局部修补。因此 PM 保留全局 session 索引和跨 session 体验证据是必要的。

PM 的边界不是“看不到 trace”，而是“看到了 trace 也只能用产品语言表达”：用户目标、观察行为、体验矛盾、
产品机会和期望结果。文件名、协议、固定超时、关键词阈值和实现步骤不属于 PM artifact。

### 3. Architect 的问题是“已有 proposal 之间有什么共同机制”

Architect 不是第二个 PM，也不是更大的 Triage。它应先以 ProposalView 为认知对象，再沿 proposal 已声明的
证据引用下钻 session。若它可以任意读取所有 raw session，就会绕过 Triage/PM 的中间产物，重新发现一批没有
来源的需求，角色分工和审计链都会失效。

所以 Architect 保持跨 proposal 视野，但 raw trace 采用引用门控：没有来源 proposal 的 session 只能作为
不可见对象，不能直接成为 from-architect 提案的依据。

## Motivation

过去的需求面输入有两个相反的问题。Triage 完全没有用户行为证据时，只能把自由文本报告改写成泛化的
“请改进 prompt”；而把完整 `sim_trace`、工具 stdout 和目标项目细节直接交给角色时，又会让调用变慢，并诱发
针对某一道题的实现。新的用户目标机制让意图变成了结构化事实，但如果没有可见性边界，它仍然可能被错误地
当作验收结果，或者让所有角色读取同样的大包证据而再次同质化。

本 spec 因此同时解决三个根因：

1. 用户意图没有进入需求面交接，导致“为什么等待/打断/改口”不可解释；
2. trace 的观察权没有按角色职责分层，造成延迟、上下文污染和过拟合；
3. 用户主观 accept、目标状态和客观 evaluator 没有在输入中保持来源隔离。

不采用“完全不给 Triage trace”的方案，因为那会使事实定位退化为文本猜测；也不采用“所有角色看全量 raw
trace”的方案，因为它违反单条分诊、产品全景和 proposal 关系三种不同的认知边界。

### 4. 目标状态不是验收结论

`goal_ledger`、`target_goal_ids`、`expected_progress` 和 `goal_effect` 是用户意图与行为依据；
`goal_acceptance` 是主观用户结论；objective evaluator 是客观技术结论。三者必须在证据包中分区并带 provenance：

```text
user_goal_status = met
user_verdict = accepted
objective_status = failed | unverified
```

这是一个合法且重要的结果，不能被压成“整体成功”。目标机制用于解释用户行为，不用于替代测试或给 proposal
凭空增加事实。

## Evidence envelope

每条角色调用的输入通过一个逻辑上的 `EvidenceEnvelope` 表示。它可以落盘为 handoff，也可以在 prompt 中投影，
但不得让角色通过相对路径或自由 shell 发现未授权数据。

```json
{
  "report": {"issue_id": "...", "title": "...", "body": "...", "labels": [...]},
  "user_evidence": {
    "session_id": "...",
    "goal_summary": {
      "baseline_id": "B0",
      "initial": "...",
      "current": "...",
      "revisions": [{"before": "...", "after": "...", "reason": "..."}],
      "unresolved": ["..."]
    },
    "key_events": [
      {"turn": 0, "action": "send_message", "target_goal_ids": ["B0"], "effect": "advance"},
      {"turn": 4, "action": "interrupt", "target_goal_ids": ["B0"], "effect": "wait"}
    ],
    "feedback": "...",
    "user_outcome": "accepted"
  },
  "objective_evidence": {"status": "unverified", "source": "evaluator"},
  "harness_source": {"repo": "read-only", "ref": "..."}
}
```

字段含义必须保持分区：`user_evidence` 描述用户的目标和经验，`objective_evidence` 描述可执行结果，
`harness_source` 只描述角色可读的 harness 源码范围。任何角色都不得把一类证据改写成另一类证据。

## Evidence levels and budgets

### L0 · raw report

当前 issue 的 title/body/labels。它是用户主观报告和上下文，不是已证实的根因。

### L1 · compact goal-aware summary

由 SessionStore 和 sim trace 确定性投影，不新增模型调用。包括：

- B0 初始目标、当前目标和 revision 摘要；
- 每次 revision 的 before/after/reason；
- 关键用户动作、目标指向和 effect；
- 用户明确反馈、interrupt/等待/终止原因；
- feeling、请求终态和已有 objective 摘要（如该阶段已经产生）。

L1 有固定字符和事件数量上限，去掉完整 persona prompt、raw LLM 输出、全量 stdout、完整工具正文和目标项目源码。

### L2 · projected timeline

当前 report 对应 session 的用户可见交互、harness 回复和活动摘要。Triage 需要确认事实边界时可以读取；
PM 用于解释跨 session 体验；Architect 仅沿已引用 proposal 下钻。

### L3 · targeted beat

某一个 turn 的 harness 活动和 stop kind。调用必须说明 turn 和理由，并记录调用结果。它用于区分“助手正在探索”、
“请求已排队”“工具报错”等局部原因，不是默认上下文。

### L4 · step/objective detail

单步正文、测试结果或 evaluator 细节。仅当 L2/L3 无法解释当前证据缺口时允许，且必须保留来源、调用理由和
截断状态。L4 不得把目标项目的答案、补丁或专有路径写入通用 proposal 字段。

## Role visibility matrix

| 角色 | 默认输入 | 可按需读取 | 明确禁止 | 产物关注点 |
|---|---|---|---|---|
| Triage | 当前 report + 当前 session 的 L1 + feeling/终止原因 | 当前 session L2/L3；必要的 L4 objective 摘要 | 其他 report、全局聚合、目标项目完整源码、无理由 raw step | 事实、用户影响、边界、证据、不确定性 |
| 产品 PM / Divergent | 全局体验索引 + 多 session L1/L2 + report/proposal 索引 | 相关 session L3；必要时 L4 结果 | 代码位置、协议处方、固定阈值、实施步骤 | 用户目标、行为、体验矛盾、产品机会、期望结果 |
| Architect | ProposalView + proposal artifact 关系 | 已引用 proposal 的 session L2/L3/L4 | 无来源 raw session、单票改写、脱离 proposal 发掘新需求 | 来源关系、共同矛盾、结构方向、预期杠杆 |
| Owner | 角色 artifact、ready queue、证据引用和体验摘要 | 不自由搜索源码或 raw session | 重新诊断、替角色补事实、把 accept 当通过 | 用户价值、证据强度、范围内聚、风险、裁决 |

“默认输入”不是把数据拼成一段无限长的 prompt，而是把 envelope 中允许的字段投影到角色专属 schema。工具调用
应当是显式、可计数、可回放的。

## Reference-level explanation

### Architect 的单次协议收尾

若模型返回文本但没有结构化提交 proposals，驱动器最多再次调用一次相同角色，复用本轮的
ready、proposal、trend 和 runtime 输入，并追加只调用 `submit_rfcs` 提交 0..n 条结果的收尾提示。
合法空数组也是成功收尾，不再重试；再次缺少提交则保持空结果，不从散文推断产物。
这是一次新的角色调用，并不恢复模型上一调用的内部推理；“只提交”是指令约束，不是工具权限硬限制。
重试异常仍向上暴露，临时提示状态在 finally 中复位。该行为归属 T4，测试覆盖正常不重试、
成功恢复、最多两次调用及异常后复位；不改变证据访问范围或提案准入标准。

### 输入构造与权限执行

SessionStore 是用户证据的权威来源。会话收尾时，确定性投影器先生成 L1，并把目标 ledger 的 revision、关键
动作和反馈事件写入 handoff；它不调用模型，也不从目标项目源码反推目标。角色运行时通过绑定的 evidence store
拿到 envelope，workspace jail 继续只允许需求面角色读取 harness 仓，不允许用相对路径发现 sessions、
harness_runs 或宿主目录。

Triage 的运行仍然一次只处理一条 report。它的初始消息只包含 report 和“可调用当前 report 证据”的说明；L1
可以作为确定性短摘要随 handoff 注入，L2/L3/L4 必须由工具按需取得。若调用参数指向别的 report、无关 session
或未引用 proposal，工具返回越权 violation，而不是静默提供数据。

PM 的全景不等于全量原文：全局索引使用 L1，比较体验时才取相关 session 的 L2；它不能把目标项目的具体
文件、命令写进产品 artifact。Architect 的输入先是 ProposalView；证据下钻必须携带来源 proposal，这样
“看得广”与“能凭空发新需求”被分开。

### 产物与状态投影

Triage、PM 和 Architect 继续使用 Spec-0043 的专属 artifact schema。本 spec 不增加一个“目标已满足所以
proposal 合格”的快捷字段：目标字段只作为证据引用或用户目标上下文。用户 handoff 的 `user_outcome`、
`goal_acceptance` 和 objective evaluator 结果分别投影，任何角色都不能覆写它们。

### 观测指标

每次角色调用都记录输入证据层级、输入字符/token 估计、工具调用数、每次下钻层级、耗时、证据引用、截断和
越权拒绝。评测器同时输出 artifact 语义违规、专有名词泄漏和主观/客观结论冲突。指标只用于回归和调参，
不由模型自报数字来判断是否通过。

## Triage artifact and handoff

用户 session 结束时生成的 handoff 是后续闭环的正式交接面，不要求 Triage 重新从 sessions 文件猜测用户意图。它
至少包含：

```text
source_report
session_id
goal_summary
feedback_events
user_outcome
objective_evidence（若已产生）
evidence_refs
```

Triage 的 artifact 仍沿用 Spec-0043 的事实型语言：

```text
reported_problem
user_impact
scope_boundary
evidence
uncertainties
implementation_target
```

其中 `goal_summary` 是证据，不是新增的实现字段；`implementation_target` 只能是 harness、outside_harness 或
uncertain。目标项目的 issue 标识、文件名和专有参数可以存在于 `evidence_refs`，但不得进入任务无关的
`proposal_title`、通用边界或实施方案。

Triage 的调查顺序固定为：

```text
L0/L1 → 判断证据缺口 → L2 → 必要时 L3 → 极少数情况下 L4
```

没有足够证据时产出 `needs_info`，不能通过增加更多日志来强行产生确定性结论。

## Latency and overfitting safeguards

### 延迟控制

- L1 由代码确定性生成，不新增 persona/triage LLM 调用；
- Triage 不因每条 report 自动调用完整 timeline；
- L2/L3/L4 每次调用写入 `evidence_access` 事件，记录层级、turn、reason、字符数和耗时；
- 每角色设置输入 token、工具调用数和墙钟预算，达到上限后返回已有证据或 `needs_info`；
- PM 的跨 session 索引使用短摘要，不把所有 session 的 L2 拼成一段；
- Architect 的证据下钻按 proposal 引用集合去重，避免随 proposal 数量重复拉同一 trace。

### 过拟合控制

- 角色只能通过 EvidenceEnvelope 和已注册工具取证，不能读 `data/sessions`、`harness_runs` 或宿主路径；
- 目标项目源码不是需求面角色的实现工作区；harness 源码仍是独立、只读的进化对象；
- 通用 proposal 字段禁止目标项目名、票号、专有文件名、答案、固定超时和关键词阈值；
- 具体案例只保留在原始报告和带来源的 evidence 中；
- Triage 必须显式记录 uncertainties；PM/Architect 的语义产物由角色专属 contract 检查，不由事故关键词黑名单判断；
- `user accept`、`goal met`、私有 pytest 和 evaluator 结果永远分开记录。

## Rationale and alternatives

### 为什么 Triage 必须看到 trace

Triage 的职责是把用户观察界定为事实、影响、边界和不确定性。仅有 raw report 时，它无法区分“用户目标不清”、
“harness 没有能力”、“harness 回复慢”与“目标项目自身失败”。当前 session 的用户行为和目标修订是这些判断
的第一手证据，因此完全屏蔽 trace 会直接损害 Triage 的准确性。

### 为什么不能把完整 trace 给 Triage

Triage 不负责跨任务架构设计。完整工具正文、目标项目路径和测试答案会同时增加 token 成本和过拟合概率，并诱导
它把案例修复写成 harness 的通用 proposal。L1/L2/L3/L4 的渐进层级让它先拿到足够解释行为的证据，再在有理由时
下钻；这比在 prompt 中重复一份大日志更可审计。

### 为什么 PM 和 Architect 不能共享同一输入

PM 的价值来自全局体验比较和未报告行为观察，它需要比 Triage 更宽的视野；Architect 的价值来自已有 proposal
之间的结构关系，它必须受来源 proposal 约束。让二者共享全量 trace 会让 PM 变成技术调查器，也会让 Architect
绕过 Triage/PM 重新发掘需求。角色差异必须体现在输入范围和 artifact，而不只写在 system prompt 中。

### 备选方案

- **只把目标摘要附在 raw issue 后**：成本低，但没有用户动作和 harness 活动，无法解释等待/打断原因；作为 L1
  的一部分保留，但不能是完整方案。
- **所有角色读取完整 `sim_trace`**：实现简单，但上下文、泄漏和过拟合风险不可接受，否决。
- **只让 PM 看 trace**：保留了产品观察，却让 Triage 重新退回文本猜测，否决。
- **让模型自行决定是否读取任意 trace**：权限和调用成本不可审计，否决；改用角色矩阵、工具参数校验和预算。

## Interaction with existing specs

- Spec-0024 提供 god-view 落盘和 timeline/beat/step 渐进下钻，本 spec 为其增加目标感知 L1 和角色权限矩阵；
- Spec-0025 定义 raw report → Triage → Architect 的漏斗，本 spec 增加 user feedback handoff，不改变角色职责；
- Spec-0029 保留 Triage 单 report、PM/Architect 的不同视野和 Owner 唯一准入，本 spec 把“不同视野”落实为可机检的输入层级；
- Spec-0043 定义角色专属 artifact，本 spec 不重写 artifact 语义，只规定其证据来源和可见性；
- Spec-0053 定义用户动作、目标和客观结果的独立生命周期，本 spec 将这些结果投影到需求面证据包，不让需求面重新判定生命周期。

## Validation plan

验证不是“JSON 合法就算成功”，而是至少比较以下结果：

1. **输入边界**：Triage 不串 report；PM 可引用未报告 session；Architect 不接受无来源 session；Owner 不自由读码。
2. **目标利用**：目标 revision 能解释 interrupt、等待和明确反馈；角色不会把 goal status 当客观验收。
3. **延迟**：L1 默认路径不新增模型调用；L2/L3 调用数和字符量有界；同批 session 的墙钟和 token 不出现线性爆炸。
4. **泛化**：任务专有文件、命令、答案只能落在 evidence 引用，不能出现在通用 proposal 字段。
5. **结论分离**：`accepted + objective_failed`、`accepted + objective_unverified` 和 `abandoned + objective_passed`
   均能被独立审计，不被压成一个总状态。

离线回放应使用同一组冻结 session 对比旧输入和新 envelope，并输出每个角色的输入 token、tool calls、耗时、
artifact、evidence refs 和 violation。只有行为质量和证据边界同时满足，才允许进入完整闭环实验。

## Unresolved questions

- L1 的事件数量和字符上限需要用现有 session 分布校准，但不能为了省 token 删除目标 revision 的 reason；
- L4 是否允许 Triage 读取 evaluator 的单步正文，需要根据目标项目泄漏风险决定，默认应只给结构化结果；
- 历史没有 goal ledger 的 session 使用 `goal_evidence=unavailable`，不能回填或猜造 B0；
- user feedback envelope 是直接作为 Gitea comment 还是仅作为 role invocation input，需要在 T2 实现时固定，二者均须保留原始 session 引用。
