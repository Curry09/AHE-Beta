---
number: "0029"
title: 三平面 issue 流：证据→提案→工作队列，唯一准入 Owner（白名单可领、生成器自由并行、去 gate 特殊通道）
issue: 0
slug: three-plane-issue-flow
summary: 现行 issue 流的三大病根：①「谁有权把活放进 dev 队列」有三个写手（triage accept、synthesize 直建 RFC 且能 supersede 别人、gate promote），入场规则不统一——synthesize 产出免审进队、divergent 产出要过 gate，纯历史演化无原则可言；② 标签把「工作项资格 / 流程状态 / 属性」压成一个平面，dev 可领判定是一张随新状态不断增长的黑名单（每加 divergent、gate-dropped 都得记得改 dev 排除集）；③ 去重被塞在想并行的生成侧（triage 边规范化边判重），与并行天然打架——此前 triage 分片讨论卡壳的根因。本 spec 重构为三平面单一准入模型：平面1 证据（用户报告/体感/runtime，输入）→ 平面2 提案（proposal，一律不可领；triage/synthesize/divergent 都只是生成器，产出为非约束性提案，故可自由并行、重复无害）→ 唯一准入 Owner（每轮一次批量评审：admit→ready / merge 去重合并 / decline / hold；机械模式对字段齐全的单条修复案零 LLM 自动准入）→ 平面3 工作队列（ready 唯一可领白名单，dev 按 priority→age 拉取，done 级联关闭 covers 链）。配套：公共 agent 运行时抽出（消 triage/divergent 对 designer 私有符号的依赖）、gate/divergent 特殊通道与 superseded/gate-dropped 中间态退役、proposal/ready 队列深度背压告警（= CLAUDE.md 退化信号落地）。不动纯 trunk/直推 main/benchmark held-out/submit-tool 契约（0027 复用，Owner 仅新增 submit_admission）。
tasks:
  - id: T1
    title: issue_schema 三平面标签收敛：report/proposal/ready 白名单 + 老标签读侧映射
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: true
    files:
      - backend/auto_designer/designer/issue_schema.py
      - backend/tests/designer/test_issue_schema.py
    scope: 新增平面常量 REPORT/PROPOSAL/READY 与终态标签 DECLINED/MERGED、provenance 标签 FROM_TRIAGE/FROM_SYNTHESIZE/FROM_DIVERGENT；新增 plane(labels) 投影（report/proposal/ready 三值 + None）与 is_ready(labels,state) 白名单判定（dev 唯一入口）；covers 机器行解析（parse_covers_line）与 merged-into 机器行 helper 收进本模块作单一真源（web/designer 后续统一引用）。老标签（needs-triage/triaged/RFC/superseded/divergent/gate-dropped）保留常量并在读侧投影里映射到新平面（needs-triage→report、triaged|RFC→ready、divergent→proposal、superseded/gate-dropped→closed 终态展示），保证旧数据可显示；写侧不再产生老标签。SCHEMAS/validate/render/PRIORITIES/round_label 不动。
    acceptance: plane/is_ready 对新旧标签组合返回正确值；covers/merged-into 解析单测；老标签映射覆盖；既有 validate/render 测试不回归。
  - id: T2
    title: agent_runtime 公共运行时抽出：跑 agent + 读 submit 一处实现
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: true
    files:
      - backend/auto_designer/designer/agent_runtime.py
      - backend/tests/designer/test_agent_runtime.py
    scope: 新建 agent_runtime.py，收拢四个 driver 各抄一份的公共逻辑：run_with_timeout（contextvars.copy_context 跨线程）、run_agent_def(agent_def_dir, message, *, store, repo, on_event, timeout, max_iterations=None)（设 SANDBOX_WORK_DIR 绝对路径、AgentConfig.from_yaml、StepTracer、bind_session_store、返回值非 str 时 dumps）、read_submit(text, key)（有界逐层 json.loads 直到 dict、取 key 数组、失败返回 None）、norm_label。纯新增模块，不改既有文件——各 driver 在各自 task 内切换 import（T3/T4/T5/T6），全部切换后 designer.py 内旧副本随 T4 删除。
    acceptance: read_submit 对正常/再编码一层/散文/未调 submit 四路正确；run_with_timeout 跨线程传 contextvars 单测（复用现有断言式样）；norm_label 空白容忍。
  - id: T3
    title: triage 改纯规范化生成器：accept→就地升 proposal，判重职责移出
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: true
    files:
      - backend/auto_designer/designer/triage.py
      - backend/agent_defs/triage_agent/agent.yaml
      - backend/agent_defs/triage_agent/systemprompt.md
      - backend/agent_defs/triage_agent/tools/submit_triage.tool.yaml
      - backend/tests/designer/test_triage.py
    scope: disposition 收敛为三值 accept/reject/needs_info——duplicate 退役（判重全权移交 Owner，triage 回归单条视野、不再喂「已 triaged 判重参照」，输入随之变小）。accept→就地升 proposal：去 REPORT、加 PROPOSAL+FROM_TRIAGE+确认 kind+建议优先级（P0-P3 标签，Owner 可改）、TRIAGE 字段渲染挂 comment；reject/needs_info→DECLINED+原因+关闭。agent_contract.dispositions_input_schema 同步收敛（enum 三值），submit_triage.tool.yaml 重生成（drift-guard 照旧）；systemprompt 删判重段、改三值契约。driver 切换 agent_runtime import，删对 designer.py 的依赖。
    acceptance: accept 后 issue 为 proposal 平面（非 ready、dev 不可领）；三值路径正确；无 duplicate 路径残留；不再喂判重参照；test_triage 重写为三值+proposal 断言且绿。
  - id: T4
    title: synthesize 收窄为纯生成器：产 proposal(from-synthesize)，gate_once 退役
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: true
    files:
      - backend/auto_designer/designer/designer.py
      - backend/agent_defs/designer/agent.yaml
      - backend/agent_defs/designer/systemprompt.md
      - backend/agent_defs/designer/tools/submit_rfcs.tool.yaml
      - backend/agent_defs/designer/tools/submit_gate.tool.yaml
      - backend/tests/loop/test_designer.py
    scope: propose_once 产出改落 PROPOSAL+FROM_SYNTHESIZE（不再直建 RFC 标签、不再打 superseded——covers 关系保留为 body 机器行，仅是**建议**，合并裁决权移交 Owner）；输入改为 ready backlog+proposal 紧凑索引+体感+runtime（编排保证跑在本轮 triage 之后，紧凑索引含本轮新升的 from-triage 提案）。gate_once/GateOutcome/_gate_from_submit/submit_gate 全部退役（准入职责归 Owner/T6）：designer agent.yaml 删 submit_gate、stop_tools 收回 [submit_rfcs]，submit_gate.tool.yaml 删除；systemprompt 删 gate 模式注记。driver 切换 agent_runtime import，删本文件内 run_with_timeout/_unwrap_result 旧副本。submit_rfcs 工具名保留（口语「RFC」= 结构提案），仅落库标签变化。
    acceptance: 产出为 proposal 平面、带 from-synthesize 与 covers 行、不打 superseded；gate 符号零残留；test_designer 按新落库断言重写且绿。
  - id: T5
    title: divergent 对齐纯生成器：产 proposal(from-divergent)，专属通道退役
    status: pending
    priority: P2
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: true
    files:
      - backend/auto_designer/designer/divergent.py
      - backend/agent_defs/divergent_pm/agent.yaml
      - backend/agent_defs/divergent_pm/systemprompt.md
      - backend/agent_defs/divergent_pm/tools/submit_divergent.tool.yaml
      - backend/tests/designer/test_divergent_gate.py
    scope: 产出改落 PROPOSAL+FROM_DIVERGENT（DIVERGENT 老标签退役为读侧映射）；每轮硬顶 3 条保留。driver 切换 agent_runtime import，删对 Designer 内部（_proposals_from_submit/_DESIGN_TIMEOUT）的依赖（read_submit 通用化后直接用）。test_divergent_gate.py 拆分：divergent 生成部分留此改写，gate 三路测试删除（Owner 侧 T6 重建同等覆盖）。
    acceptance: 候选为 proposal 平面 from-divergent、dev 不可领；对 designer.py 零 import；divergent 测试绿。
  - id: T6
    title: Owner 唯一准入：机械+评审双模式批量裁决（admit/merge/decline/hold）
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: true
    files:
      - backend/auto_designer/designer/owner.py
      - backend/auto_designer/designer/agent_contract.py
      - backend/auto_designer/designer/submit_tools.py
      - backend/agent_defs/owner/
      - backend/tests/designer/test_owner.py
    scope: 新建 Owner driver（owner.py）：admit_once() 每轮一次批量准入。输入=全部 open proposal（紧凑索引：号/标题/kind/provenance/建议优先级/covers，正文按需 get_session_timeline 下钻）+ready backlog+体感曲线。两级裁决：①机械段（零 LLM）——from-triage 的单条修复案、TRIAGE 字段齐全、与既有 ready/本批提案无标题近似冲突（norm 后简单相似度）→ 自动 admit；②评审段（一次 LLM 批量）——其余（结构/产品提案、冲突组、机械段拿不准的）走 owner agent，submit_admission 收尾。决策落库：admit→去 PROPOSAL 加 READY+终优先级；merge→关闭+merged-into 机器行链主票；decline→DECLINED+原因关闭；hold→保持 proposal（未列出默认 hold）。covers 裁决也在此：admit 结构提案时其 covers 的 proposal **默认 merge 归并，但 Owner 可裁量部分保留**——如其中的 P0 急修可单独 admit 与结构案并行推进（先止血、结构改造随后），取代旧 superseded 的全有全无。agent_contract 增 admission_input_schema()（decision 四值 enum、into/priority/reason），gate_input_schema 删除；submit_tools 增 submit_admission、删 submit_gate。agent_defs/owner/ 新建（只读工具+timeline 下钻+submit_admission，systemprompt=准入职责与判据）。
    acceptance: 机械段对合格单条案零 LLM 准入；评审段四路（admit/merge/decline/hold）落库正确、未列出默认 hold；merge 链主票、covers 统一收敛；drift-guard（yaml==admission_input_schema）；无候选跳过 LLM；test_owner 覆盖以上。
  - id: T7
    title: dev 白名单领取：ready-only + priority→age 排序 + 级联关闭
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: true
    files:
      - backend/auto_designer/dev/agentic_developer.py
      - backend/tests/dev/test_agentic_developer.py
    scope: _eligible 从黑名单改白名单 is_ready（issue_schema 单一真源）；排序从纯票号 FIFO 改 priority（P0>P1>P2>P3>无）→ 票号（同优先级内 FIFO 防饿死）；预算按 kind 分档保留（结构提案 from-synthesize 最高档，取代原 RFC 档判定）；resolved→close+comment+级联关闭 covers 链（单层，机器行来自 issue_schema 解析）。
    acceptance: 只领 ready；P0 插队生效、同级 FIFO；预算分档按新判定；级联关闭 covers 的 proposal；test 重写且绿。
  - id: T8
    title: 编排/roster/run 接线：生成段全并行（triage 可分片）→ Owner → dev + 背压告警
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T3
      - T4
      - T5
      - T6
      - T7
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/loop/orchestrator.py
      - backend/auto_designer/loop/roster.py
      - backend/run.py
      - backend/tests/loop/test_orchestrator.py
      - backend/tests/loop/test_roster.py
    scope: run_round 重排为 a → 生成段**两拍**——第一拍 triage 分片×N_TRIAGERS（pending 轮询切片、线程池并行；判重已移 Owner 故分片自由）、第二拍 synthesize ∥ divergent（线程池并行；跑在 triage 全部收尾之后，输入因此含**本轮**新升的 from-triage 提案，结构综合不滞后一轮）→ Owner.admit_once（恒 1）→ b dev → c；gate 段删除。roster 加 owner（默认 1；0=纯机械准入、不跑 LLM 评审段），退役 gate 语义。run.py 接线 Owner、背压告警：proposal 深度与 ready 深度超过阈值（env PROPOSAL_DEPTH_ALARM/READY_DEPTH_ALARM，缺省各 20）→ 状态回调+stdout 告警（不自动扩容，人工介入信号 = CLAUDE.md「issue 长期不降=退化」的落地）。单 agent 崩溃记日志跳过照旧。
    acceptance: 段顺序断言（triage 全部完成 → synthesize/divergent → owner → dev）；triage 分片各自处理不重叠子集；synthesize 输入含本轮新升提案；owner=0 时评审段跳过、机械准入仍走；背压超阈值触发告警回调；test_orchestrator/test_roster 重写且绿（git 依赖用例走 CI）。
  - id: T9
    title: 观测后端适配：plane 字段 + ready 深度曲线 + 漏斗计数
    status: pending
    priority: P2
    tags: []
    depends-on:
      - T6
      - T7
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/web/api.py
      - backend/auto_designer/loop/metrics.py
      - backend/tests/web/test_api.py
      - backend/tests/loop/test_metrics.py
    scope: /api/issues 每条附 plane（report/proposal/ready/closed 终态）与 provenance、merged_into；covers 解析改引 issue_schema 单一真源；老标签数据经 T1 读侧映射正常展示。metrics：issue_curve 口径改 ready 深度随时间（开/关事件累计，排除 proposal/report）；新增漏斗计数端点数据（report/proposal/ready/done 四段当前量 + 背压阈值状态）。
    acceptance: plane/provenance/merged_into 字段正确（新旧标签都对）；曲线只数 ready；漏斗计数与阈值状态可读；test_api/test_metrics 覆盖。
  - id: T10
    title: 前端适配：三平面分组 + Owner 房间 + 漏斗与背压展示
    status: pending
    priority: P3
    tags: []
    depends-on:
      - T9
    relates-to: []
    parallel: false
    files:
      - frontend/src/types.ts
      - frontend/src/lib/issueMeta.ts
      - frontend/src/components/SidePanel.tsx
      - frontend/src/components/detail/IssueDetail.tsx
      - frontend/src/App.tsx
      - frontend/src/api.ts
    scope: AgentRole 加 owner、App ROLES 插「准入」房间（生成段房间与其区分）；SidePanel issue 分组改三平面（报告/提案[按 provenance 徽标]/Ready/已关闭），merged-into 链展示；漏斗四段计数 + 背压告警条（超阈值高亮）；issueMeta 按 plane 投影重写（老标签兜底映射与后端一致）；IssueDetail 补 plane/provenance/merged_into。老后端缺字段退化不崩。
    acceptance: mock 下三平面分组正确、Owner 房间可见、漏斗与告警条渲染；缺字段退化；npm build 通过。
---

# 0029 · 三平面 issue 流：证据→提案→工作队列，唯一准入 Owner

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

把 issue 流从「多写手、黑名单、语气分工」重构为**三平面单一准入**：证据（用户报告/体感/runtime）→ **提案**（proposal，一律不可领；triage / synthesize / divergent 全部降格为生成器，产出是非约束性提案，因此可自由并行、重复无害）→ **唯一准入 Owner**（每轮一次批量裁决：admit / merge / decline / hold；对字段齐全的单条修复案走零 LLM 机械准入）→ **工作队列**（`ready` 唯一可领白名单，dev 按优先级→票龄拉取，done 级联关闭 covers 链）。配套抽出公共 agent 运行时消除 driver 间私有依赖、退役 gate 特殊通道与 superseded/gate-dropped/divergent 中间标签、增加 proposal/ready 队列深度背压告警。

## Motivation

现行流程的病根（均有代码证据）：

1. **dev 队列有三个写手、入场规则不统一**。triage accept→`triaged`、synthesize 直建 `RFC`（且能把别人的 triaged 打成 `superseded`）、gate promote→`feature+triaged`——三条路标准各异。最刺眼的不对称：**synthesize 的产出免审直接进队，divergent 的产出必须过 gate**，没有原则性理由，纯历史演化（divergent 后加、不被信任）。
2. **标签一锅炖，dev 可领判定是增长型黑名单**。`(TRIAGED or RFC) and not SUPERSEDED and not NEEDS_TRIAGE and not DIVERGENT`——每加一种流程状态（这次是 divergent/gate-dropped）都要记得改 dev 排除集，漏一个就是事故。资格/状态/属性三类语义压在一个平面上。
3. **去重放错了位置**。判重塞给 triage（生成侧），而生成侧天然想并行、判重天然要全局——此前 triage 分片讨论反复卡壳（轮询漏判重、hash 分区半吊子、按区分拣仍别扭），根因就是职责错位。
4. **三个「想活儿」agent 靠 prompt 语气区分**：synthesize/divergent/gate 吃同一份信号、吐同一个 shape，区别只在系统提示姿态；gate 还复用 designer agent 换任务消息，`Designer` 一个类两份人格。
5. **模块耦合实打实**：triage.py、divergent.py 各自 import designer.py 的私有符号（`_run_with_timeout`/`_norm_label`/`_proposals_from_submit`/`_DESIGN_TIMEOUT`），公共「跑 agent+读 submit」逻辑抄了三份变体。

## Guide-level explanation

重构后一条 issue 的一生（单票就地推进，不复制票）：

```
用户 sim 落 report（自由文本 + round-N）
  │ triage（生成器，单条视野）：调查→就地升 proposal（kind+字段+建议优先级）
  │                            或 decline（reject/needs_info，关闭带原因）
  ▼
proposal 平面（不可领）  ←──── synthesize / divergent 也在此新建结构/产品提案
  │                             （带 provenance 与 covers 机器行）
  │ Owner（唯一准入，每轮一次批量）：
  │   admit → ready（定终优先级）      merge → 关闭、merged-into 链主票（去重在此！）
  │   decline → 关闭带原因             hold → 留下轮（未列出默认 hold）
  ▼
ready 平面（唯一可领白名单）
  │ dev 按 priority→票龄拉取，直推 main
  ▼
done（级联关闭该票 covers 的提案/报告）
```

角色宪章（每个一句话）：

| 角色 | 职责 | 数量 | 并行性 |
|---|---|---|---|
| user sim | 用 harness，产证据 | N | 已并行 |
| triager | 逐条调查报告→修复提案；**不判重** | N | **自由分片**（产出非约束，重复无害） |
| synthesize | 跨条结构根因→结构提案 | 0..1 | 与其它生成器并行 |
| divergent | 产品能力缺口→能力提案 | 0..N | 同上 |
| **Owner** | **唯一准入**：去重合并、冲突裁决、定优先级、admit/decline/hold | **恒 1** | 单点（全局视野；紧凑索引+背压保上下文有界） |
| dev | 从 ready 拉活直推 main | N | 已并行 |

用户可感知的收益：dev 过滤器变一个词（`ready`）；triage 想怎么并行怎么并行；synthesize 和 divergent 地位对称（都过同一道门）；去重集中在唯一有全局视野的点；每轮 LLM 决策调用量级不变（Owner 替换 gate，还吃掉了散落各处的判重/supersede 判断）。

## Reference-level explanation

**平面与标签（T1）**：资格只看三个词 `report / proposal / ready`；终态 `declined / merged`（+关闭）；属性（kind、P0-P3、round-N、provenance `from-triage/from-synthesize/from-divergent`）不参与资格判定。`plane(labels)` 与 `is_ready(labels,state)` 为唯一投影；covers 与 merged-into 机器行解析收进 issue_schema 作单一真源。老标签写侧退役、读侧映射（旧数据可显示）：needs-triage→report、triaged|RFC→ready、divergent→proposal、superseded/gate-dropped→关闭终态。

**公共运行时（T2）**：`agent_runtime.py` 收拢 run_with_timeout（contextvars 跨线程）、run_agent_def（SANDBOX_WORK_DIR/AgentConfig/StepTracer/bind_session_store/超时）、read_submit（有界逐层 json.loads 取 key）、norm_label。四个 driver 瘦成「拼 prompt → run_agent_def → read_submit → 写 tracker」。

**生成器（T3/T4/T5）**：
- triage：disposition 收敛三值（accept/reject/needs_info），**duplicate 退役**——不再喂判重参照，输入变小、单条视野更纯。accept 就地升 proposal（非 ready）。
- synthesize：产 proposal(from-synthesize)+covers 行；**不再打 superseded**（supersede 是准入裁决，归 Owner）。
- divergent：产 proposal(from-divergent)；专属 gate 通道消失。
- 三者 submit 契约照旧走 agent_contract 生成 + drift-guard（0027 机制复用）。

**Owner（T6）**：`admit_once()` 两级裁决——①机械段（零 LLM）：from-triage 单条案、字段齐全、无标题近似冲突 → 自动 admit（保守：拿不准就进评审段）；②评审段（一次 LLM 批量）：结构/产品提案、冲突组。契约 `submit_admission`：`[{issue, decision: admit|merge|decline|hold, into?, priority?, reason?}]`，未列出默认 hold。admit 结构提案时对其 covers 的 proposal 统一 merge（覆盖裁决唯一落点）。

**dev（T7）**：白名单 `is_ready`；排序 priority→票号；done 级联关闭 covers 链（单层）。

**编排与背压（T8）**：`a → 生成段两拍[先 triage×N 分片并行；再 synthesize ∥ divergent] → Owner(1) → dev → c`；gate 段删除。两拍而非全并行：synthesize 必须看到**本轮**新升的 from-triage 提案（否则结构综合滞后一轮、dev 先逐条修症状），而它等 triage 收尾只多一拍墙钟——值得。真正值钱的并行（triage 分片之间、synthesize∥divergent 之间）都保留。roster 加 owner（1；0=纯机械准入）。背压：proposal/ready 深度超阈值（env，缺省 20）→ 告警回调+stdout，**不自动扩容**——这是 CLAUDE.md「issue 长期不降=退化」观测指标的可执行化。

**观测（T9/T10）**：issue 附 plane/provenance/merged_into；曲线=ready 深度；漏斗四段计数（report/proposal/ready/done）+ 背压状态；前端三平面分组 + Owner 房间 + 告警条。

**DAG**：T1、T2 并行起步 → T3/T4/T5/T6 并行（文件互不重叠）→ T7（仅依赖 T1）→ T8 汇合 → T9 → T10。

**Non-goal**：不动纯 trunk/dev 直推 main/无门禁（0007）；不动 benchmark held-out 与体感唯一训练信号；不动 submit-tool 契约机制（0027）；不做 embedding 语义去重（Owner 先用 LLM 批量判 + 机械段标题近似，够用再说）；不做 triage 按机制区分拣（分片自由后轮询即可，按区留作后续优化）。

## Drawbacks

- **Owner 评审段多一次批量 LLM 调用**——但它替换了 gate（原本就有一次），且吃掉 triage 的判重负担（其输入随之变小），净成本≈持平；机械段让「平凡多数」（字段齐全的单条修复案）零 LLM 通过。
- **Owner 是单点**：它挂了整轮无准入（提案积压、dev 无新活）。缓解：崩溃记日志跳过（提案留存下轮再审）+ owner=0 的纯机械降级模式。
- **迁移期新旧标签并存**：读侧映射保证展示，但历史曲线在口径切换处会有台阶（旧 triaged 深度 vs 新 ready 深度）；接受并在看板标注切换点。
- 改动面大（10 个 task），靠文件单一归属 + 每 task 行为断言 + 机械模式先行（行为等价再收紧）控风险。

## Rationale and alternatives

- **就地升级 vs 另建提案票**：三平面纯粹主义会让每条报告再配一张提案票（票数翻倍、链路更绕）。取就地推进（report→proposal→ready 同一张票走完），只有跨条的结构/产品提案才新建票——状态机不变小写成本减半。
- **唯一准入 vs 三写手现状**：真实组织的通行做法（Kanban backlog grooming、Scrum Definition of Ready、K8s 的 triage/accepted+milestone 准入）——谁都能提案，进 Ready 只有 owner 说了算。去重/优先级/覆盖裁决集中到唯一全局视野点，生成侧彻底解耦得以自由并行。
- **Owner 恒 1 vs 可扩**：准入需要全局视野，且输入被「紧凑索引+按需下钻+背压」三重限界，单实例上下文可控（此前讨论已论证 designer 单开即可，Owner 同理）。扩容信号=背压告警，处置是人工调 B/加 dev，不是多开 Owner。
- **白名单 vs 黑名单**：黑名单随状态数增长且要求「每个新状态记得去改 dev」；白名单一个词、新状态默认安全（fail-closed）。
- **备选：保留 gate 只修不对称**（让 RFC 也过 gate）——治了不对称但去重仍在 triage、黑名单仍在、耦合仍在；不如收敛成一个 Owner。
- **备选：Owner 全 LLM（无机械段）**——每轮平凡单条案也烧评审，浪费且慢；机械段是对「多数提案本来就该过」的承认。
- **生成段两拍 vs 全并行**（评审修订）：全并行下 synthesize 看不到本轮 triage 新升的提案，结构综合要么滞后一轮（dev 先逐条修症状再被结构案覆盖，白烧 dev 预算）、要么倒退回吃 raw 报告；等 triage 收尾只多一拍墙钟，取两拍。「triage 提案被结构案覆盖」不是浪费——逐条的根因区域/优先级/证据正是聚类与合并裁决的依据（K8s 里 issue 也是先 triage 再被 umbrella/KEP 吸收）；且覆盖在 0029 里从 synthesize 单方面盖 superseded 变为 covers 建议 + Owner 裁决（可部分保留急修）。

## Prior art

- Kanban / Scrum：backlog grooming 与 Definition of Ready——提案自由、准入唯一，本 spec 的直接原型。
- K8s issue triage：needs-triage → SIG 分拣 → `triage/accepted`，milestone 准入另有把关——分拣（规范化）与准入（决定做什么）是两道门。
- 竞争消费者/分区讨论（本组前序讨论）：并行与去重的冲突在生成侧无解，在准入侧自然消解——生成产非约束提案即可 at-least-once，幂等收敛由准入完成。
- 0025 立 triage 漏斗、0027 立 submit-tool 契约、0028 引入 divergent/gate——本 spec 是三者的收敛与纠偏：保留 triage 的调查价值、0027 的契约机制、divergent 的探索职能，重排它们的权力边界。

## Unresolved questions

- **hold 生命周期上限**：提案连续 hold K 轮（K=3?）后自动 decline 还是升级告警？暂定只计数+看板标龄，不自动处置。
- **机械段「无冲突」判据**：norm 后标题相似度阈值多少算冲突（进评审段）？初值保守（宁进评审勿误放行），实测后调。
- **旧数据迁移**：读侧映射 vs 一次性迁移脚本刷标签？暂定只读侧映射（不改历史票），若观测口径混乱再补脚本。
- **owner agent 定义**：全新 agent_defs/owner/ 还是复用 designer 定义？暂定新建最小定义（职责宪章不同），若 prompt 高度重合再合并。

## Future possibilities

- triage 分片从轮询升级为按机制区（SIG 式）分拣：区内上下文常驻、判重前移一部分；Owner 仍兜全局。
- Owner 机械段引入 embedding 相似度辅助去重（替代标题近似）。
- 背压阈值自适应（按 dev 吞吐滚动估计），告警升级为自动调节每轮会话数 B。
- 漏斗转化率（report→proposal→ready→done 各段转化）作为 harness 进化质量的次级观测指标。
