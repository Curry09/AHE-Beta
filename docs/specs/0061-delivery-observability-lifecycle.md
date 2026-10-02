---
number: "0061"
title: 开发侧观测使用与制品日志演进闭环
issue: 0
slug: delivery-observability-lifecycle
summary: 制品维护诊断日志和版本说明，平台提供受限证据包；维护者取证缺口形成诊断补强，用户状态反馈走普通产品提案；功能设计分别说明两类影响并独立验收。
tasks:
  - id: T1
    title: NexAU 起点的制品自有观测包
    status: done
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
      - backend/tests/harness/test_template_entry.py
      - backend/harness_template/params.yaml
    scope: 将种子已有 tracer 接成制品自有文件输出与说明，不依赖外部脚本包装私有函数；内部事件格式可演进。
    acceptance: 正常、错误、中断、重试和退出可按说明定位；记录失败不改变任务结果，资源有界，敏感数据不导出。
  - id: T2
    title: 会话收集、版本绑定与历史留存
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/user/sim/runtime.py
      - backend/auto_designer/loop/sim_user.py
      - backend/auto_designer/harness/launcher.py
      - backend/auto_designer/observations/publication.py
      - backend/auto_designer/observations/__main__.py
      - backend/auto_designer/demand/observation_provider.py
      - backend/tests/observations/test_publication.py
    scope: 启动时约定观测输出目录，清理容器前按受限清单收集，平台绑定真实 session 和制品版本，校验发布完整性并保留旧包。
    acceptance: 正常或放弃会话均尝试收集；崩溃留下明确缺失状态；路径、大小、版本摘要校验，旧轮不被覆盖。
  - id: T3
    title: 跨容器开发证据交接
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/demand/owner.py
      - backend/auto_designer/demand/delivery_evidence.py
      - backend/auto_designer/observations/grants.py
      - backend/auto_designer/tracker/gitea.py
      - backend/tests/demand/test_delivery_evidence.py
    scope: 从准入票的授权引用发布审计过的交付证据包；通过现有 Gitea 边界提供可解析句柄，避免宿主路径和全量 session 挂载。平台范围的缺口不得误投 harness 队列。
    acceptance: 开发容器能定位对应版本包；引用在合并和截断后保留；权限失败明确降级，禁止外链下载与扩权。
  - id: T4
    title: 开发设计、实现、评审的观测职责
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/harness_template/META_SPEC.md
      - backend/deploy/vigil/observability-overlay.Dockerfile
      - backend/deploy/vigil/observation-runtime.json
      - docs/audits/0061-observation-goal-boundaries.json
      - OpenAgents/openagents/runtime/engine.py
      - OpenAgents/openagents/runtime/context.py
      - OpenAgents/openagents/recipes/stages.py
      - OpenAgents/openagents/recipes/vigil.py
      - OpenAgents/openagents/utils/gitea.py
      - OpenAgents/openagents/observations/evidence.py
      - OpenAgents/tests/test_observation_evidence.py
    scope: 交付角色按任务读取版本匹配证据；功能契约分别说明用户反馈与诊断观测影响，实现维护对应输出、记录、说明与测试，两类目标独立验收。跨仓变更须单独交付并更新 pin。
    acceptance: 新旧版本证据不混用；用户决策时刻的可见信息与维护者诊断问题分别验证；无影响可说明理由；无新常驻评审角色。
  - id: T5
    title: 诊断观测缺口提案与可恢复提交
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/observations/gaps.py
      - backend/auto_designer/observations/delivery_gaps.py
      - backend/auto_designer/demand/agent_runtime.py
      - backend/auto_designer/demand/triage.py
      - backend/auto_designer/demand/divergent.py
      - backend/auto_designer/demand/synthesizer.py
      - backend/agent_defs/triage_agent/systemprompt.md
      - backend/agent_defs/triage_agent/agent.yaml
      - backend/agent_defs/divergent_pm/systemprompt.md
      - backend/agent_defs/divergent_pm/agent.yaml
      - backend/agent_defs/synthesizer/systemprompt.md
      - backend/agent_defs/synthesizer/agent.yaml
      - backend/agent_defs/owner/systemprompt.md
      - backend/agent_defs/owner/agent.yaml
      - backend/agent_defs/triage_agent/tools/submit_observation_gap.tool.yaml
      - backend/agent_defs/divergent_pm/tools/submit_observation_gap.tool.yaml
      - backend/agent_defs/synthesizer/tools/submit_observation_gap.tool.yaml
      - backend/agent_defs/owner/tools/submit_observation_gap.tool.yaml
      - backend/tests/observations/test_gaps.py
      - OpenAgents/openagents/observations/gaps.py
      - OpenAgents/openagents/v02/openagents_adapter.py
    scope: 需求与开发角色均可提交维护者诊断取证缺口；平台确定性落普通 proposal，保留来源、组件、原因与验收。用户反馈不足走普通产品提案，不经诊断补强入口；重试幂等，不回写冻结目标。
    acceptance: 两类需求不互相设前置门槛；用户反馈与诊断补强独立验收和记录状态；PM 来源隔离保持；同一提交重试不重复建票；离线请求重启后补交。
  - id: T6
    title: 跨轮与替代 harness 验证
    status: done
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
      - backend/tests/observations/fixtures/alternate_v1.py
      - backend/tests/observations/fixtures/alternate_v2.py
      - tools/dev/replay/replay_observation_lifecycle.py
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

功能建设分别考虑“用户如何理解当前状况并决定下一步”和“维护者如何还原经过、区分原因、
验证改动”。本组观测补强专指后者；前者属于 0035 的用户侧状态反馈和普通产品需求。
不要求每个改动新增日志，不规定统一内部事件字典，不新增常驻日志评审角色。

实施和验证状态见任务表及 `docs/audits/0061-observation-lifecycle-validation.md`。
工程闭环验证与真实模型是否主动、有效使用观测是两种证据，不能相互冒充。

本次目标边界澄清已同步角色提示、诊断工具字段说明、提案标题和开发上下文；现有观测、
角色交接与模板入口回归 70 项通过，OpenAgents 观测回归 15 项通过。它们验证接线、
兼容性和既有行为，不证明真实模型已经稳定区分两类需求；此前受控闭环也不替代此项验证。
新版交付镜像在无网络、无宿主挂载容器中核实安装源码摘要及八类角色上下文，记录见
`docs/audits/0061-observation-goal-boundaries.json`，版本见部署 pin；未替换运行中实验。

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

### 0. 两类目标与提案入口

| 类别 | 服务对象与判断 | 需求入口 | 验收 |
|---|---|---|---|
| 用户侧状态反馈 | 使用中的用户理解当前状况，决定等待、补充要求、打断或接受 | 既有 Triage 或独立 PM 普通产品提案 | 决策时刻真实可见的信息准确、及时，并支持所需判断 |
| 设计开发侧诊断观测 | 维护者还原经过、区分原因、验证改动 | `submit_observation_gap` 或开发侧诊断请求文件 | 对应版本的获准证据能回答具体诊断问题 |

分类依据是信息服务谁、支持什么判断，不依据发现者的角色或底层事件来源。PM 自己查证
缺少内部证据时提交诊断补强；PM 发现用户无法理解状态时提交产品提案。本文“两侧”均指
需求设计侧和开发交付侧，不指用户与维护者；`observation-gap` 和工具名保留为诊断入口的
兼容标识，不新增类别字段或语义分类器。

例如同一次长等待，用户需要及时知道当前状况及可采取的行动，维护者需要事后区分正常
执行、调用失败与恢复。补日志不自动改善用户反馈，加状态提示也不自动补齐诊断证据。
两类需求可以独立成立：用户反馈不足无需先证明内部根因，诊断缺口无需先证明用户不满意。
只有具体工作确实依赖另一项时才走已有阻塞/修订机制，不按类别自动建立前置关系。

二者可共享事件来源和一次交付，但交接保留各自目标与验收；一张票同时包含两类目标时
分别列出验收，关联的不同票保持各自状态，不强制拆票，也不以一项完成关闭另一项。

### 1. 三方职责

| 所属方 | 负责内容 | 不负责内容 |
|---|---|---|
| harness 制品 | 记录什么、何时记录、关联语义、文件格式、说明、开销与脱敏；随实现共同演进 | 将当前事件名变成平台永久字段 |
| 迭代框架（实验开始前固定） | 提供输出位置，预检存储和附件能力，收集声明文件，绑定可信版本/session，安全留存并按任务授权交接 | 通过固定私有函数包装猜测内部过程，统一解释所有日志，混入 harness 自我演进 |
| 设计与开发角色 | 带问题取证、区分事实与解释、指出缺口、实现和验证补强 | 把日志条数当质量分、把记录缺失当行为没发生 |

### 2. 开发侧如何使用

| 阶段 | 使用观测的方式 | 应留下的结果 |
|---|---|---|
| Spec Writer / Drafter | 从 issue 的受限证据入口读该版本说明，查影响方案选择的事实；不默认重读全部日志 | 已知事实、未验证假设、要改变的行为及观测影响 |
| Architect（该流程启用时） | 检查证据能否区分候选根因，是否误将当前日志形态当成实现要求 | 能证伪方案的验证方法；必要的补强提案或 REWORK 原因 |
| Developer | 对照历史证据与当前代码，复现相关行为；实现功能时维护受影响的事件、说明和测试 | 功能变更与观测变更在同一交付内，或说明无需改变观测 |
| Reviewer / 测试验证 | 按对应版本说明实际定位执行，验证行为和诊断可区分性 | 行为证据、观测证据及负例结果，不以“有日志”代替功能通过 |

新功能的 SDD Spec / Objective Contract 在既有章节内分别说明“用户反馈影响”和
“诊断观测影响”：前者说明用户何时需要知道什么、支持什么决定，后者说明维护者需要
还原或区分什么、现有证据是否足够；分别说明改变与验证。无影响时给出简短理由，不
强行增加事件或固定表格。实现同步维护受影响的用户输出/帮助、诊断记录/阅读说明和
回归测试；不因二者共享 tracer 就认定两个目标同时完成。

日志取证不替代源码与黑盒验证：例如出现“cancelled”只能证明记录发出，仍需验证
任务实际停止及队列处理符合目标。新增诊断也不能把必须实时生效的功能变成等待阶段结束。

### 3. 需求设计与开发交付角色都能发现诊断缺口

| 发现者 | 典型触发点 | 既有边界继续有效 |
|---|---|---|
| Triage | 单条报告查证时，无法区分失败、等待或中断后的状态 | 只使用当前 report 的授权证据 |
| PM | 用户行为与内部证据无法对照，不能判断某种体验差异 | 独立 PM 路线到 Owner，不把产品机会写成固定事件方案 |
| Synthesizer | 对多条交付路线提案验证共同机制时缺少区分证据 | 只查可见来源的 session；不借补强入口读取 PM 或发现无关需求 |
| Owner | 上游交接材料缺少可解析引用、版本或完成判断所需信息 | 不新增原始会话/日志读取权；缺口依据是交接材料本身 |
| 开发、架构、评审与验证角色 | 无法复现、区分假设、确认改动效果或验证恢复边界 | 只用当前 issue 授权证据与自己产生的测试证据 |

大家共同遵循：明确问题 → 读取该版本说明及相关记录 → 区分“未找到”和“未记录” →
确认缺口并提交补强提案。不能把偶然没搜到、权限不足、文件尚未发布都解释为 harness
缺事件；也不要求无限搜索后才允许承认未知。

### 4. 补强提案长什么样

这是普通诊断能力 proposal，兼容标记 observation-gap，标题使用“诊断观测补强”；
不新增工作平面或专属准入捷径。用户反馈需求仍走普通产品提案，不能仅因“用户不知道
发生什么”就投到此入口。question、impact 和 verification 应明确维护者要回答的问题、
受影响的判断和诊断验证，不把用户收到进度提示当作诊断验收。
例如：

> 想判断用户打断后正在运行的是旧请求还是新请求。已读取该 session 的 manifest、
> 说明和相关运行区间，现有记录没有能辨别两者的关联信息，导致无法验证旧请求是否
> 复活。希望维护者能够区分请求归属、终止与后续执行。验收以旧/新请求并存的受控
> 场景验证可区分性；不预先指定 request_id 字段、某种状态机或存储格式。

提案保留：查证问题、来源版本与引用、已查范围、仍不可区分的情况、对判断的影响、
期望诊断能力及验证场景。根因未知也能成立；目标是补足辨别能力，不是宣称原问题根因。

发现者提交一个独立缺口请求，平台落普通提案并返回票号。PM 来源保留 from-divergent，
不进入 Synthesizer；其他来源保留来源角色和原 issue 关系。缺口提案不受 Synthesizer
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

启动器提供专用输出目录 HARNESS_OBSERVATION_DIR，制品在 params.yaml 声明
`observations: artifact-observations-v1`；未声明的旧制品返回 not_supported，不假装有日志。
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

框架在用户交互开始前检查存储读写、剩余空间、待恢复积压、Gitea 附件能力及仓库写权限，
把观测根目录绑定到当前仓库，拒绝复用其它仓库的授权数据。发布使用临时目录与原子切换、
摘要及幂等运行 ID；中途失败不破坏旧版本。收集重试有界，失败时停止并保留原容器/本地源，
落恢复回执，不先删唯一现场；显式恢复命令复用原身份。积压过多在下次启动前要求维护，
不在用户交互中无限重试。不能承诺磁盘/守护进程永久无故障，但不能以隐藏故障伪装闭环。

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
限制与部署 pin 由真实集成验证。当前实现使用 issue assets API 与有界 gzip JSON 文本包；
压缩包及解压都有字节预算，附件以内容摘要命名。发布及回读校验成功后才打交付令牌；失败保留
proposal 和归档，下一次普通准入重试同一附件，不自动绕过交付。超过传输预算的条目明确 unavailable，
原始有界包仍在平台归档，不静默截断文本。

取回只允许配置中的 Gitea origin 与该 issue 获准对象，校验摘要、安全解包，不跟随
任意外链，不执行包内脚本。凭证由运行器掌管，不写进 issue、文件或模型输入。访问有
角色/issue/包的取回记录与获准文件摘要。普通文件工具的实际阅读与下载/授予不是一回事，
不把下载回执冒充角色已经理解证据。平台保存的包是不可变证据，开发侧在隔离目录读其副本；
若副本发生改动，摘要校验使它不能充当原始证据。

历史证据与当前工作树同时标注版本。开发者在自己的测试中生成的新日志绑定当前 head，
不能拿修复后的日志证明修复前发生过什么。对测试路径、脱敏投影与源码漂移保持显式区分。
补充取证只从既有授权清单选择，不因为 Developer 好奇就开放同仓全部用户记录。

本设计扩展的是既有 Gitea 交接边界，不新增公网日志服务。相关 OpenAgents 改动单独
提交其仓库并更新构建 pin；auto-designer 的 spec 不等于已修改了部署中的 OpenAgents。

### C. 缺口提案的提交、路由与恢复

设计侧提供非终结的 submit_observation_gap 诊断补强能力，提交后仍完成原角色产物；它只记录
缺口、引用和作用范围，不直接创建 ready 或修改其他票。Owner 使用时仅能引用交接材料。
开发侧通过同等结构的交付报告/automation 注释返回缺口请求，平台从认证的运行来源
处理，不把任意用户评论或日志内伪造 JSON 当作系统提交。

平台按提交请求 ID 幂等落库并回执票号；接口暂不可用时保留 durable outbox，重启或下轮
重试，不能靠 agent 最终一句话就宣称建票成功。两侧均可先写不确定性并继续有依据的工作。
不同请求是否语义重复由既有提案协调过程判断，不用字符串相似度自动删掉独立诊断能力。

缺口需区分三个归属：

- harness 没有记录/关联/说明所需事实：制品观测能力提案，正常 Owner→OpenAgents；
- 迭代框架没有导出、权限映射错误或历史文件丢失：基础设施诊断与维护回执，实验中框架固定，
  不创建 harness proposal，不打 openagents，不要求 harness 开发者越权修框架；
- 原日志已可回答而只缺检索或版本定位：先完成定位；确有说明/发现性缺陷时提出对应补强。

不把所有观测提案自动提升为 P0，也不因提案很多而扩张记录范围。期望诊断结果、真实
影响与验证必要性决定优先级。提案进入工作队列后仍经过正常工程质量与范围约束。

设计侧 schema 位于 observations.gaps，四角色 YAML 有 drift guard。PM 来源及其后续
Owner/开发补强按可信来源保留 from-divergent，不能借补强绕回 Synthesizer。Synthesizer 的原始
证据权限来自框架保存的来源授权，而非模型正文里新增的 session_id。没有可信授权的历史
票不从文字补权限；这类迁移必须从可信会话/调用来源重建授权。

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
4. 真实基础设施闭环：至少一项补强真正合并，再以 sealed SHA 跑新版本用户/受控复现；记录
   原诊断问题是否变得可回答，以及功能效果。不能用两局同版本实验代替这一层。
   本次受控验证使用脚本化角色决策、真实 Docker/Gitea/PR 合并和已安装开发镜像；不是
   长时模型自主进化，也不是 vigil 工程质量闸的全链路验收，报告必须明确区分。

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

0059 提供制品文件按需读取，平台不解释事件字段；0060 保留 PM 独立路线且 Synthesizer
不读取 PM。0032/0033 分离需求与容器交付；0045 固定工具链 pin；0050 在交付封口后
才进入下一轮。当前 Meta-Spec 已要求基于 ownership/delivery/control_effect 与
行为证据开发，本组把观测能力明确纳入这套职责，不替换目标契约。

最近真实实验的日志入口放入 harness 副本，但发布依赖实验脚本；它是可参考的 NexAU
起点验证，不是上述六项任务已经实现的证明。

## Unresolved questions

Gitea 的实际附件接口和私有仓跨容器访问已由受控验证确认，部署更新仍须使用记录的镜像 pin。
字节预算、留存期限与历史版本保留成本需结合真实包规模确定，并以配置表达，不写死在
角色 prompt。输出不依赖具体事件 schema，但发布外壳升级仍需兼容性验证。

运行中的旧实验不被替换。新代码接在公共 engine，并覆盖独立 v0.2 Developer、Spec Writer、
Acceptance 及传统 Drafter/Architect/Implementer/Reviewer；生产新实验须选择对应镜像与新版种子。
暂不引入运行中动态 DAG 插入；
关键补强如何拆为独立先行交付，使用现有阻塞/修订路径并由受控验证确认。

## Future possibilities

后续可比较补强前后的“诊断问题可回答率、错误归因、缺包率、额外开销与重复调查时间”，
不以日志量作为优化目标。若其他 harness 起点只改变制品记录与说明、平台无需改变事件
解析即可被两侧使用，就验证了本组的演进边界。
