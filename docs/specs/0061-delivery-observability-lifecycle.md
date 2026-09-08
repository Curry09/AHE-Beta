---
number: "0061"
title: 开发侧观测使用与制品日志演进闭环
issue: 0
slug: delivery-observability-lifecycle
summary: 制品维护日志起点和版本说明，平台收集并向交付侧提供受限证据包；功能设计与验收覆盖观测影响，已确认观测缺口形成普通补强提案。
tasks:
  - id: T1
    title: NexAU 起点的制品自有观测包
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/harness_template/entry.py
      - backend/harness_template/observability.py
      - backend/harness_template/OBSERVABILITY.md
      - backend/harness_template/tests/test_observability.py
    scope: 将种子已有 tracer 接成制品自有文件输出与说明，不依赖外部脚本包装私有函数；内部事件格式可演进。
    acceptance: 正常、错误、中断、重试和退出可按说明定位；记录失败不改变任务结果，资源有界，敏感数据不导出。
  - id: T2
    title: 会话收集、版本绑定与历史留存
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/user/sim/runtime.py
      - backend/auto_designer/user/sim/runner.py
      - backend/auto_designer/observations/publication.py
      - backend/auto_designer/designer/observation_provider.py
      - backend/tests/observations/test_publication.py
    scope: 启动时约定观测输出目录，清理容器前按受限清单收集，平台绑定真实 session 和制品版本，校验发布完整性并保留旧包。
    acceptance: 正常或放弃会话均尝试收集；崩溃留下明确缺失状态；路径、大小、版本摘要校验，旧轮不被覆盖。
  - id: T3
    title: 跨容器开发证据交接
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/designer/owner.py
      - backend/auto_designer/designer/delivery_evidence.py
      - backend/auto_designer/tracker/gitea.py
      - backend/auto_designer/loop/orchestrator.py
      - backend/tests/designer/test_delivery_evidence.py
    scope: 从准入票的授权引用发布审计过的交付证据包；通过现有 Gitea 边界提供可解析句柄，避免宿主路径和全量 session 挂载。平台范围的缺口不得误投 harness 队列。
    acceptance: 开发容器能定位对应版本包；引用在合并和截断后保留；权限失败明确降级，禁止外链下载与扩权。
  - id: T4
    title: 开发设计、实现、评审的观测职责
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/harness_template/META_SPEC.md
      - OpenAgents/openagents/agents/drafter.py
      - OpenAgents/openagents/agents/architect.py
      - OpenAgents/openagents/agents/reviewer.py
      - OpenAgents/openagents/observations/evidence.py
      - OpenAgents/tests/test_observation_evidence.py
    scope: 交付角色按任务读取版本匹配证据；功能契约说明观测影响，实现同步更新事件说明与测试，评审验证行为及诊断可区分性。跨仓变更须单独交付并更新 pin。
    acceptance: 新旧版本证据不混用；新增功能不以日志存在替代行为验收；无观测影响可说明理由；无新常驻评审角色。
  - id: T5
    title: 观测缺口提案与可恢复提交
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/observations/gaps.py
      - backend/auto_designer/designer/agent_contract.py
      - backend/auto_designer/designer/submit_tools.py
      - backend/agent_defs/triage_agent/systemprompt.md
      - backend/agent_defs/triage_agent/agent.yaml
      - backend/agent_defs/divergent_pm/systemprompt.md
      - backend/agent_defs/divergent_pm/agent.yaml
      - backend/agent_defs/designer/systemprompt.md
      - backend/agent_defs/designer/agent.yaml
      - backend/agent_defs/owner/systemprompt.md
      - backend/agent_defs/owner/agent.yaml
      - backend/agent_defs/triage_agent/tools/submit_observation_gap.tool.yaml
      - backend/agent_defs/divergent_pm/tools/submit_observation_gap.tool.yaml
      - backend/agent_defs/designer/tools/submit_observation_gap.tool.yaml
      - backend/agent_defs/owner/tools/submit_observation_gap.tool.yaml
      - backend/tests/observations/test_gaps.py
      - OpenAgents/openagents/observations/gaps.py
    scope: 需求与开发角色均可提交缺口；平台确定性落普通 proposal，保留来源身份、目标组件、证据不足原因和独立验收，重试幂等，不自动 ready 或回写冻结目标。
    acceptance: 缺日志本身不阻止提案；不让 PM 缺口泄漏到 Designer 输入；同一提交重试不重复建票；离线请求在重启后补交；原问题与观测补强分别记录状态。
  - id: T6
    title: 跨轮与替代 harness 验证
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
      - T3
      - T4
      - T5
    relates-to: []
    parallel: false
    files:
      - backend/tests/observations/test_delivery_lifecycle.py
      - backend/scripts/replay_observation_lifecycle.py
      - docs/audits/0061-observation-lifecycle-validation.md
    scope: 先合成双轮测试，再真实交付一项观测补强并在新版本会话复查；用非 NexAU 起点验证平台不解析内部事件。
    acceptance: v1 缺口到 proposal、Owner、交付、v2 实际观测形成闭环；旧包保留；泄漏、乱序、缺包、预算与恶意输入有负例；不使用 benchmark 作开发信号。
---

# 0061 · 开发侧观测使用与制品日志演进闭环

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

日志是 harness 的可演进能力，不是平台对当前运行时的外置适配。NexAU 起点使用其现有
tracer 生成观测文件与说明，换其他 harness 起点时替换制品侧实现；平台只固定收集、
版本关联、留存和授权边界。设计与开发角色按需使用这些证据，遇到已确认的观测缺口时
都能提出普通补强提案，经过既有 Owner 和交付流程完善能力。

功能建设同时考虑“用户获得什么行为”和“维护者如何辨别该行为实际发生了什么”。
不要求每个改动新增日志，不规定统一内部事件字典，不新增常驻日志评审角色。

本文件为设计方案，T1–T6 均 pending；创建 spec 不代表生产收集和开发读取已实现。

## Motivation

当前 NexAU harness 已有 `_StepCollector`，通过 steps/progress/usage 输出运行信息。
0059 的 ObservationProvider 已能按 session 的 manifest 读取制品文件，但没有把种子
观测机制完整接成每轮自动发布，也没有交付容器可用的受限证据传输。最近的两会话实验
通过额外包装内部函数、容器收尾复制文件补齐这一段，验证了读取，不是生产整合完成。

开发者目前拿到提案、session 引用与工作树，不等于拿到了该历史版本的可读日志。
宿主绝对路径在 vigil 容器中不可用；当前工作树也不必然等于事件发生时的版本。
若只凭文字根因编写修复，或重构功能时保留过期日志说明，下轮角色仍可能误判。

另一方面，查不到信息本身就是可改进的能力缺口。不能要求先用缺失的日志证明根因
才能提补强，也不能让发现者只在回答中写“证据不足”而没有后续交付入口。

## Guide-level explanation

### 1. 三方职责

| 所属方 | 负责内容 | 不负责内容 |
|---|---|---|
| harness 制品 | 记录什么、何时记录、关联语义、文件格式、说明、开销与脱敏；随实现共同演进 | 将当前事件名变成平台永久字段 |
| 平台 | 提供输出位置，收集声明文件，绑定可信版本/session，安全留存并按任务授权交接 | 通过固定私有函数包装猜测内部过程，统一解释所有日志 |
| 设计与开发角色 | 带问题取证、区分事实与解释、指出缺口、实现和验证补强 | 把日志条数当质量分、把记录缺失当行为没发生 |

### 2. 开发侧如何使用

| 阶段 | 使用观测的方式 | 应留下的结果 |
|---|---|---|
| Spec Writer / Drafter | 从 issue 的受限证据入口读该版本说明，查影响方案选择的事实；不默认重读全部日志 | 已知事实、未验证假设、要改变的行为及观测影响 |
| Architect（该流程启用时） | 检查证据能否区分候选根因，是否误将当前日志形态当成实现要求 | 能证伪方案的验证方法；必要的补强提案或 REWORK 原因 |
| Developer | 对照历史证据与当前代码，复现相关行为；实现功能时维护受影响的事件、说明和测试 | 功能变更与观测变更在同一交付内，或说明无需改变观测 |
| Reviewer / 测试验证 | 按对应版本说明实际定位执行，验证行为和诊断可区分性 | 行为证据、观测证据及负例结果，不以“有日志”代替功能通过 |

新功能的 SDD Spec / Objective Contract 增加一个简短“观测影响”小节：要辨别什么、
现有信息是否足够、需要改变什么、如何验证。无影响时给出理由，不强行增加事件或
固定表格。功能实现、相关观测、阅读说明与回归测试一并进入原交付；后续维护者不应
需要私下询问本轮 agent 才能理解新记录。

日志取证不替代源码与黑盒验证：例如出现“cancelled”只能证明记录发出，仍需验证
任务实际停止及队列处理符合目标。新增诊断也不能把必须实时生效的功能变成等待阶段结束。

### 3. 两侧都发现观测缺口

| 发现者 | 典型触发点 | 既有边界继续有效 |
|---|---|---|
| Triage | 单条报告查证时，无法区分失败、等待或中断后的状态 | 只使用当前 report 的授权证据 |
| PM | 用户行为与内部证据无法对照，不能判断某种体验差异 | 独立 PM 路线到 Owner，不把产品机会写成固定事件方案 |
| Designer | 对多条交付路线提案验证共同机制时缺少区分证据 | 只查可见来源的 session；不借补强入口读取 PM 或发现无关需求 |
| Owner | 上游交接材料缺少可解析引用、版本或完成判断所需信息 | 不新增原始会话/日志读取权；缺口依据是交接材料本身 |
| 开发、架构、评审与验证角色 | 无法复现、区分假设、确认改动效果或验证恢复边界 | 只用当前 issue 授权证据与自己产生的测试证据 |

大家共同遵循：明确问题 → 读取该版本说明及相关记录 → 区分“未找到”和“未记录” →
确认缺口并提交补强提案。不能把偶然没搜到、权限不足、文件尚未发布都解释为 harness
缺事件；也不要求无限搜索后才允许承认未知。

### 4. 补强提案长什么样

这是普通 proposal，建议标记 observation-gap，不新增工作平面或专属准入捷径。
例如：

> 想判断用户打断后正在运行的是旧请求还是新请求。已读取该 session 的 manifest、
> 说明和相关运行区间，现有记录没有能辨别两者的关联信息，导致无法验证旧请求是否
> 复活。希望维护者能够区分请求归属、终止与后续执行。验收以旧/新请求并存的受控
> 场景验证可区分性；不预先指定 request_id 字段、某种状态机或存储格式。

提案保留：查证问题、来源版本与引用、已查范围、仍不可区分的情况、对判断的影响、
期望诊断能力及验证场景。根因未知也能成立；目标是补足辨别能力，不是宣称原问题根因。

发现者提交一个独立缺口请求，平台落普通提案并返回票号。PM 来源保留 from-divergent，
不进入 Designer；其他来源保留来源角色和原 issue 关系。缺口提案不受 Designer
“综合多个 proposal”的提交契约限制，因为它是对一次受限取证失败的能力请求，不是
新的结构综合产物，也不授予额外取证范围。

明确发现覆盖不足就留下提案；已存在等价提案则补充证据并引用它。不以“我们已经写了
一条日志”关闭提案，需验证目标现象实际可以区分。

## Reference-level explanation

### A. 制品日志起点与发布边界

首版在 harness 内整合现有 NexAU tracer，不再由实验外壳替换 `_make_step_collector`
或 `_run_supervised`。新增、迁移到其他运行时或多 agent 的实现由制品自己决定。
本组只为 NexAU seed 给出默认记录范围：模型/工具活动、请求执行、错误恢复、中断与
退出，配套解释其能证明和不能证明的内容；不是所有未来 harness 必须共享的事件 schema。

启动器提供专用输出目录（建议配置名 HARNESS_OBSERVATION_DIR，T1/T2 统一落地），
制品在其中写文件清单与阅读说明。输出目录是收集契约，不是一个可由日志内容发起执行
或读宿主文件的接口。制品清单只声明相对文件，平台最终封装 0059 可读的 manifest。

平台从运行控制面绑定 session、实际 harness commit、运行时/镜像 pin 和运行标识，
不能盲信制品自报版本。包的稳定外壳包括文件清单、阅读入口、内容摘要和完整性状态；
日志字段及文件名属于该制品版本。新旧包并存，不把旧包改写为新格式，新增说明也不能
事后冒充旧版本原始说明。重试发布幂等；同 session 的不同运行另有运行标识，不覆盖旧包。

正常、放弃、错误、中断和超时收尾均在容器清理前尝试有界收集；未能导出时记录原因，
不得把缺包伪装成空日志。崩溃、截断或尚未写完的内容标为 partial/unavailable，只有
完成校验的包成为完整可用入口。日志异常不能把产品行为改成成功，也不能因持续写日志
耗尽磁盘或无限阻塞退出。必要时优先保留有界元数据并明确丢弃/采样范围。

平台检查相对路径、符号链接/硬链接、文件数量与大小、归档解包安全和摘要；导出不包含
原始凭证、persona 隐藏提示、benchmark gold/oracle 或任务答案。仅靠显示时脱敏不够，
制品默认最小记录且在发布边界再次筛选。用户行为证据采用既有获准投影，不交付全量 session 库。

### B. 从需求面到开发容器的证据交接

Owner 仍只看到引用，不负责下载日志。平台为准入票解析其可信来源引用，生成受限证据
清单：历史制品版本、获准 session/文件、摘要、阅读入口和不可用原因。不能因模型在
正文新写一个 session_id 就扩权，授权必须追溯到该来源调用的已授权集合。长正文截断、
来源 merged/closed 不能丢掉引用。

首选在现有 Gitea 内发布筛选后的证据附件及索引，交付运行器按 issue 清单取回到独立
证据目录，再为 agent 提供普通文件读取与搜索入口。不得把宿主 observations 或 sessions
根目录整体挂给开发 agent，也不得将大包/raw trace 放进 harness main。附件接口、大小
限制与部署 pin 由 T3 集成验证；当前 gitea tracker 尚无该能力，不声称已可直接调用。

取回只允许配置中的 Gitea origin 与该 issue 获准对象，校验摘要、安全解包，不跟随
任意外链，不执行包内脚本。凭证由运行器掌管，不写进 issue、文件或模型输入。访问有
角色/issue/包/文件级审计。平台保存的包是不可变证据，开发侧在隔离目录读其副本；
若副本发生改动，摘要校验使它不能充当原始证据。

历史证据与当前工作树同时标注版本。开发者在自己的测试中生成的新日志绑定当前 head，
不能拿修复后的日志证明修复前发生过什么。对测试路径、脱敏投影与源码漂移保持显式区分。
补充取证只从既有授权清单选择，不因为 Developer 好奇就开放同仓全部用户记录。

本设计扩展的是既有 Gitea 交接边界，不新增公网日志服务。相关 OpenAgents 改动单独
提交其仓库并更新构建 pin；auto-designer 的 spec 不等于已修改了部署中的 OpenAgents。

### C. 缺口提案的提交、路由与恢复

设计侧提供非终结的 submit_observation_gap 能力，提交后仍完成原角色产物；它只记录
缺口、引用和作用范围，不直接创建 ready 或修改其他票。Owner 使用时仅能引用交接材料。
开发侧通过同等结构的交付报告/automation 注释返回缺口请求，平台从认证的运行来源
处理，不把任意用户评论或日志内伪造 JSON 当作系统提交。

平台按提交请求 ID 幂等落库并回执票号；接口暂不可用时保留 durable outbox，重启或下轮
重试，不能靠 agent 最终一句话就宣称建票成功。两侧均可先写不确定性并继续有依据的工作。
不同请求是否语义重复由既有提案协调过程判断，不用字符串相似度自动删掉独立诊断能力。

缺口需区分三个归属：

- harness 没有记录/关联/说明所需事实：制品观测能力提案，正常 Owner→OpenAgents；
- 平台没有导出、权限映射错误或历史文件丢失：平台范围提案，进入平台维护队列，
  不打 harness 仓的 openagents 令牌，不要求 harness 开发者越权修平台；
- 原日志已可回答而只缺检索或版本定位：先完成定位；确有说明/发现性缺陷时提出对应补强。

不把所有观测提案自动提升为 P0，也不因提案很多而扩张记录范围。期望诊断结果、真实
影响与验证必要性决定优先级。提案进入工作队列后仍经过正常工程质量与范围约束。

如果原功能能凭其他证据独立实现和验证，观测补强可并行，二者保持独立验收；如果缺口
阻止安全选方案或证明目标，明确原任务的阻塞原因，并让补强作为先行交付。不得偷偷
扩展已冻结 Objective Contract。需要变更依赖/拆分时走现有契约修订和交付规划；本组
不把新提案动态插进已运行的 DAG，也不绕过 0050 的本轮交付闸。

补强已在当前改动范围内时仍引用其提案，将任务与验收纳入同一正式交付，不重复实现。
补强合并后，新版本复现/会话再次询问原诊断问题；原旧日志缺失的事实不能被追溯补造。
补强关闭与原功能修复关闭是两个判定。

### D. 交付验证与任务边界

T1 实现制品起点；T2 实现平台收集；T3 实现跨容器交接；T4 接入开发角色与制品开发规范；
T5 接入两侧提案；T6 验证完整闭环。任务 files 是预期控制点，不冻结未来 harness 文件布局。
OpenAgents/ 前缀表示独立仓交付范围，不应在 auto-designer 中创建一个同名 vendor 副本。

验证分层：

1. 工程回归：正常/错误/中断路径，日志预算与失败隔离、完整性、越权、恶意路径、
   版本错配、重复提交和离线重试；PM 输入隔离与 Owner 无原始观测权限继续成立。
2. 行为与观测联合测试：同一用户表象、不同内部情形，按随版说明能区分；也验证日志
   中的成功字样不能掩盖产品失败。缺失或采样记录必须保留不确定性。
3. 合成跨轮：v1 记录不足→两侧分别提出缺口→Owner/交付→v2 新格式和说明→开发与设计
   读同一获准包；旧版本仍可查。非 NexAU fixture 改字段/文件但不修改平台解析代码。
4. 真实闭环：至少一项补强真正合并，再以 sealed SHA 跑新版本用户/受控复現；记录
   原诊断问题是否变得可回答，以及功能效果。不能用两局同版本实验代替这一层。

CI 只验证工程行为与安全契约；benchmark 全程 held-out，不作为日志选择、提案、实现
或发版门禁的训练信号。用户体感用于观测，不恢复体感 gate。

## Drawbacks

记录、保存与查询都增加成本。制品需维护诊断说明，平台需处理脱敏、留存和附件失败，
跨仓 pin 更新也增加集成工作。观测包不是全知记录，有限样本不能证明根因唯一成立。
补强提案可能挤占功能工作，因此必须围绕实际查证问题，不能追求“所有事情都记录”。

附件访问只隔离到当前实验仓/受控运行器时，不等于已经具备完整多租户权限体系；若未来
共享用户数据跨租户交付，必须另行设计身份隔离，不能放宽本组授权边界。

## Rationale and alternatives

选择制品自有日志而非平台统一埋点，因为只有当前实现知道什么事件有意义，换起点时
也应一并替换记录方式。平台稳定外壳保留收集与读取兼容性，不冻结内部 schema。

不继续保留实验脚本包装私有函数：这会让日志能力不随正常交付更新。也不默认接入一套
新日志服务，先复用现有 Gitea 交接边界；若容量实测不适用，再单独设计内容存储，不
临时挂载整份宿主数据。平台输出有界包不是要求角色预先固定如何查询。

不新增日志分析/审核角色，也不只让 Developer 发现缺口：设计时的推理同样可能受限。
两侧在已有工作中提出具体补强，经同一提案和交付机制推进，比额外独立检查流程更直接。

## Prior art

0059 提供制品文件按需读取，平台不解释事件字段；0060 保留 PM 独立路线且 Designer
不读取 PM。0032/0033 分离需求与容器交付；0045 固定工具链 pin；0050 在交付封口后
才进入下一轮。当前 Meta-Spec 已要求基于 ownership/delivery/control_effect 与
行为证据开发，本组把观测能力明确纳入这套职责，不替换目标契约。

最近真实实验的日志入口放入 harness 副本，但发布依赖实验脚本；它是可参考的 NexAU
起点验证，不是上述六项任务已经实现的证明。

## Unresolved questions

T3 必须验证部署中 Gitea 的附件接口、权限与限额；不能预先假设 API 已被 tracker 支持。
字节预算、留存期限与历史版本保留成本需结合真实包规模确定，并以配置表达，不写死在
角色 prompt。输出不依赖具体事件 schema，但发布外壳升级仍需兼容性验证。

OpenAgents 当前部署 pin 可能与本地源码不同；T4 开始前必须核对实际启用的 Objective
Contract/SDD 流程及角色，不能只改未被执行的 prompt。暂不引入运行中动态 DAG 插入；
关键补强如何拆为独立先行交付，使用现有阻塞/修订路径并由受控验证确认。

## Future possibilities

后续可比较补强前后的“诊断问题可回答率、错误归因、缺包率、额外开销与重复调查时间”，
不以日志量作为优化目标。若其他 harness 起点只改变制品记录与说明、平台无需改变事件
解析即可被两侧使用，就验证了本组的演进边界。
