# 统一实验入口的既有能力迁移审计

日期：2026-10-03。审计分支：`feat/unified-experiment-entry`，包含未提交的 Spec-0071 清理改动。本次只核对能力与运行路径，没有修业务代码、commit、push、启动模型或操作云资源。

## 结论

统一入口尚未完整迁移已有能力。问题不仅是 Synthesizer 分组：一些真实可用的开关失去配置入口，一些已有能力被 schema 明确限制，还有 schema 接受但执行失败的情况。大部分问题在 Spec-0069 建立 schema 2 时已经出现；Spec-0071 删除旧入口后，原来还能使用的旁路也退出当前源码。这次审计未发现 0071 新改坏角色调度或持久化恢复语义，但原先的清理验收不能证明旧功能已经全部迁移。

优先处理三类问题：local 单轮启动误判；E2B 真实代码交付的运行用户与权限差异；将已有分组、reasoning、计时和交付控制参数接入可验证、可冻结的配置。不能仅增加文档，让用户回到旧 checkout；也不应通过重新开放旧 wrapper 或继承任意宿主环境补洞。

## 审计范围与方法

对照以下版本与实际调用链：

- 统一入口实现前：commit `bbdbf2113034ad06030cbcfda8515140d7984dd7` 的 ordinary/SWE runner、凭证和环境传递。
- 统一入口实现后、清理前：commit `6d213f6f1383f6aed89111ddc83a076ba3f93976` 的 schema、context、runtime、后端与旧入口。
- 当前未提交工作树：包内控制器、schema 2、材料冻结、监督器、local/E2B 后端、用户/需求角色、实时 API。
- 历史 auditable/mixed 和 N1/scaling launcher：从 research 归档核对真正执行的配置，而非只看计划 JSON。
- OpenAgents：固定 reader candidate `a752e8830a13f44d97a3043d1f3e8dd16bd8d8aa` 的 Claude backend 与实际 argv。

分别检查“旧输入 → 真实消费者”和“新 schema → 凭证读取 → context → 后端 → 控制器 → 消费者”。用临时目录和虚构凭证验证环境过滤、schema 拒绝、认证映射和单轮启动；没有读取真实 token，也没有模型/provider 请求。不能把只有 Spec、只有赋值、只有测试的接口当作过去完整运行过的功能。

当前 build_controller_environment 的主体与 `6d213f6` 相同；0071 增加的是控制器输入要求及迁移相关接线，没有增加下面这套环境白名单。

## 一、已复现的行为问题

### 1. local 单轮用户试用被错误判为启动失败

旧 ordinary runner 支持 TOTAL_ROUNDS=1，只有用户试用，不启动 Vigil。新 schema 的 rounds.count 最小值也是 1；[当前 ordinary 控制器](../../backend/auto_designer/experiment/controllers/ordinary.py#L1345)和 SWE 控制器仍仅在多轮时启动交付面。

但 [LocalBackend.launch](../../backend/auto_designer/experiment/backends/local.py#L1125)无条件等待 owned Vigil ready。单轮根本不会启动它：用户会话若先完成，报 Controller exited before owned Vigil became ready；会话还未完成，则最多等 180 秒后报 readiness 失败。schema 接受的合法用户试用因此无法获得成功启动结果。

离线用一个正常完成、exit 0 的模拟单轮 controller 复现了上述拒绝。这验证的是后端误判，不声称执行了真实用户会话。E2B launch 没有同样的 Vigil-ready 等待，只检查 live runner receipt；没有发现其同类问题。

归因：0069。修复应按这次运行是否需要交付决定 readiness，保留多轮交付的实际就绪检查。

### 2. 交付认证类型被凭证变量名推断

旧交付链支持三种显式凭证：ANTHROPIC_API_KEY、ANTHROPIC_AUTH_TOKEN、CLAUDE_CODE_OAUTH_TOKEN；包括用户通过 claude setup-token 提供的订阅 token。当前[底层控制器](../../backend/auto_designer/experiment/controllers/ordinary.py#L384)仍保留这三种分支。它们不依赖自动读取宿主 CLI 登录目录。

新 schema 允许 delivery.api_key_env 指向任意大写变量名，但 [context 认证映射](../../backend/auto_designer/experiment/context.py#L247)只把名字恰好等于 ANTHROPIC_API_KEY 的引用当作 API key，其他全部变成 ANTHROPIC_AUTH_TOKEN。

离线验证：

| 配置引用的变量名 | schema 接受 | 最终导出的交付认证变量 |
| --- | --- | --- |
| ANTHROPIC_API_KEY | 是 | ANTHROPIC_API_KEY |
| MY_ANTHROPIC_KEY | 是 | ANTHROPIC_AUTH_TOKEN |
| CLAUDE_CODE_OAUTH_TOKEN | 是 | ANTHROPIC_AUTH_TOKEN |

因此旧的显式 setup-token 模式不能通过统一入口保留原认证语义；自定义名称的 API key 也会被当成 Bearer。真实服务器如何拒绝不在本次离线验证范围，但错误的变量映射已复现。

归因：0069。应显式描述认证类型，凭证变量名只用于寻找值。禁止隐式读取本机 Claude 登录态是另一个设计选择，不能解释显式 OAuth token 为什么也不能配置。

## 二、已确认漏接的配置与交互能力

新 [credentials_v2](../../backend/auto_designer/experiment/runtime.py#L60)只读取 provider 凭证和模型 URL/key；[context 环境构造](../../backend/auto_designer/experiment/context.py#L180)只继承 PATH/HOME 等基本宿主字段，再生成固定变量。下面这些原有效设置即使写入显式 env 文件也不会传给 controller，schema 也没有相应字段。local 与 E2B 都使用这一构造器。

| 能力 | 旧的实际启用和消费者 | 当前影响 |
| --- | --- | --- |
| Synthesizer 分组 | execution.synthesizer_grouping → SYNTHESIZER_GROUPING；[旧审计 runner](../../research/archives/legacy-runtime/backend/scripts/run_auditable_experiment.py#L634)实际导出；[group_synthesizer_stage](../../backend/auto_designer/demand/grouped_synthesizer.py#L156)实际切换实现 | 分组代码仍在，但新实验不能开启。多个 Synthesizer 仍走普通 worker 模式；N1 产生多条提案时也会受影响，并非只限多用户 |
| USER reasoning effort | USER_LLM_REASONING_EFFORT；[persona_client](../../backend/auto_designer/user/sim/persona_client.py#L161)传入 completion 请求 | 原可配置强度消失；未设时，非 GLM-5.2/5.3 模型继续走 enable_thinking=false 分支。新入口无法表达旧选项 |
| DEMAND reasoning effort | DEMAND_LLM_REASONING_EFFORT；[agent_runtime](../../backend/auto_designer/demand/agent_runtime.py#L181)写入 NexAU extra_params；分组请求也消费 | Triage/Synthesizer/PM 等需求角色不能设置原有推理强度 |
| 排除 API 等待的计时策略 | 历史 [N1 launcher](../../research/archives/harness-suite-20260920/run_n1_e2b.py#L249)从 timing policy 导出 AUTO_DESIGNER_LATENCY_ISOLATED_TIMEOUT / AUTO_DESIGNER_LATENCY_WALL_GUARD_SECONDS；[agent_runtime](../../backend/auto_designer/demand/agent_runtime.py#L242)实际消费 | 退回完整墙钟超时，慢 API/长 thinking 重新计入角色预算，机制耗时与基础设施等待的区分也会改变；影响实验可比性 |
| 轮次交付等待边界 | ROUND_DELIVERY_TIMEOUT_SEC / ROUND_DELIVERY_POLL_SEC；[round_gate](../../backend/auto_designer/loop/round_gate.py#L103)实际消费；旧 scaling 导出前者 | 固定回到默认 86400 秒等待、15 秒轮询；门禁仍存在，可配置性丢失 |
| OpenAgents coordination | VIGIL_COORDINATION；[配置 writer](../../backend/auto_designer/experiment/controllers/ordinary.py#L338)支持 soft/off/dependencies | 默认 soft 可用，但用户不能选择另外两种已有策略 |
| proposal/ready 深度告警 | PROPOSAL_DEPTH_ALARM / READY_DEPTH_ALARM；[ordinary](../../backend/auto_designer/experiment/controllers/ordinary.py#L1065)读取 | 阈值固定回到 20；仅影响观测告警，不影响准入，也不提供自动扩容 |
| OpenAgents 交付参数 | OPENAGENTS_PERMISSION_MODE；旧 subprocess 能继承 OPENAGENTS_CLAUDE_IDLE_TIMEOUT，固定 OA backend 确有消费者 | 新入口没有权限/idle 配置。idle 的丢失证据适用于原 subprocess 路径，不能说旧 Docker 路径也一定传过它；E2B 权限变化另见下一节 |
| direct 交互 | [旧 mixed runner](../../research/archives/legacy-runtime/backend/scripts/run_mixed_closed_loop.py#L59)冻结 interaction；[mixed session dispatcher](../../backend/auto_designer/loop/sim_user.py#L712)实际分派 direct / simulated_user | 新 task package 无 interaction，SWE 控制器不选择 mixed factory。即使只有一个 direct 任务，也不能通过当前入口配置 |
| 指定逐轮 persona/task 计划 | 旧 SWE runner 校验并消费 SWEBENCH_INTERACTION_PLAN；[当前同名加载器](../../backend/auto_designer/experiment/controllers/swebench.py#L66)仍保留消费者 | [materials](../../backend/auto_designer/experiment/materials.py#L232)只能生成一个任务、persona 按轮循环的计划，没有自定义 plan 输入。单任务也不能指定 A、A、B、B 等安排 |
| 实时看板绑定当前实验 | 旧普通 runner 写 backend/data，默认 web app 读取该目录 | v2 数据在独立 run 下，但 [默认 web app](../../backend/auto_designer/web/api.py#L402)仍读 backend/data/sessions，Gitea 配置也独立。不会自动展示选择的 v2 run；文档已澄清，能力尚未接入 |

以上接口遗漏都在 0069 已存在；0071 退出旧直接/审计/mixed runner 后，不能再将旧入口当作当前使用办法。归档与冻结 checkout 用于历史复现，不能替代已有能力的正式迁移。

## 三、E2B 交付默认值存在需要验证的变化

旧 [scaling E2B launcher](../../research/archives/harness-suite-20260920/run_scaling_bundle_e2b.py#L393)显式选择 bypassPermissions，并在非 root 的 user 用户下执行 controller。新 [E2BBackend._command](../../backend/auto_designer/experiment/backends/e2b.py#L98)使用 root；controller 启动和 OpenAgents subprocess 继承这一身份。新 context 不传 OPENAGENTS_PERMISSION_MODE，固定 OpenAgents 的 Claude backend 则默认 acceptEdits，并把它写入实际 Claude argv。

已确认的是运行身份与权限参数不同。旧 ordinary 的 Docker 分支记录过 acceptEdits 在 headless 场景不能完成 git commit/push，并使用非 root 容器用户加 bypass；新 E2B 路径没有沿用该配置。不能仅向 root 进程补 bypass 就当问题已解决。对当前固定版本是否阻断交付，本次没有通过模型/Claude CLI 实跑复现，必须标为风险待验，不能写成已经观测到的代码交付失败。

[原 N1 实跑报告](../validation/spec-0069-new-user.md)有一个关键边界：local 的 R4 确有真实 PR #2 合并，但 E2B 的五轮没有反馈 issue、准入票或代码交付。因此 E2B 五轮完成证明了空需求闭环，不足以证明这条交付路径能修改并提交代码。

后续验收必须让 E2B 真正完成至少一次非空 issue → 实现 → commit/push → PR → merge → 下一轮使用新 SHA；不能只看进程启动、reader 技术自检和空需求封口。

## 四、已有但被明确收窄或暂未接入的范围

这些同样说明当前入口不是旧能力的全集，但不能一概当作无意丢变量，也不能未经设计就全部打开。

| 范围 | 旧能力 | 当前选择与迁移缺口 |
| --- | --- | --- |
| Owner 模型评审 | N_OWNERS=1 会使 [Owner](../../backend/auto_designer/experiment/controllers/ordinary.py#L1299)进行模型评审；默认 0 使用机械路由 | schema owner_mode 只接受 mechanical，context 强制 N_OWNERS=0。Owner 本身没有删除，但模型评审不可选 |
| 工程 CI | 旧本地基建含 act_runner，VIGIL_CI_STAGE 可选择 agent/human/skip | schema ci_enabled 只接受 false，context 固定 skip；不能仅改 boolean，需要同时恢复 Runner 注册和生命周期 |
| 官方 SWE 评分 | 旧审计 runner 可设置 objective_evaluation，并核验官方 evaluator | 当前 official_grading 只允许 false，角色环境明确关闭；评估模块及独立 held-out 评分仍在，尚无入口内选项 |
| N4/N8、多任务池与批量实验 | 旧 SWE/mixed/scaling 执行器能冻结多任务、每轮多用户及交互分配 | 当前每轮只接受一个 session；批量/scaling 入口未接入。此前已明确声明暂不支持，并不是完整迁移 |
| 历史追加轮、指定重放起始轮 | 旧研究流程可用 replay source/base/start-round 与 mixed manifest 续实验过程 | v2 resume 仅续同一身份的未完成运行；它不导入历史产物创建下一轮。这一缺口仍存在 |
| 旧 seed 卡库输入、纯文本任务 | 旧 --seed-library / seed adapter 支持 seed 卡和 [workspace=None](../../backend/auto_designer/distill/seed_adapter.py#L74) | 当前任务包必需 source、setup；不能直接输入旧 seed 库，也没有纯文本任务模式。真实代码任务可改写为 task package，但该输入工作流未提供自动适配 |
| 自定义 Gitea provider | 旧流程可以绑定已有自建 Gitea | 当前两套只支持 local+localhost、E2B+Gitea.com。这是此次公开运行模式的明确选择，不应宣称通用 provider 已完整迁移 |
| OpenAgents alternative flow/backend | 两仓有 v0.2/NexAU 的替代配置示例，但旧普通 controller 也固定生成 standard/Claude | 当前 Claude-only 不代表旧 controller 曾自动支持任意 backend；独立 OpenAgents 能力与 auto-designer 可配置能力应分开 |

v1 命令名、私人模型快捷脚本、无 context 的单例启动、隐式私人文件发现，属于已批准退出的旧接口。需要恢复的是可用能力及明确配置，不是这些接口本身。

## 五、已保留以及不能误算为回归的项目

确认仍正常接线的能力：

- USER/HARNESS/DEMAND/DELIVERY 四面模型、地址与独立凭证映射；角色数量中的 triager/synthesizer/divergent/developer，developer 数量确实进入 Vigil parallel。
- 末轮仅用户、非末轮交付封口、三平面处理、PM 与 Synthesizer 双轨、证据授权和持久化恢复。
- 源材料与 controller 冻结、旧 v2 使用自己的冻结入口、身份/哈希校验、repo_guard、Git sealed SHA。
- local 四种镜像覆盖及实际 image_id 固定；E2B CPU/RAM/timeout 均进入实际资源调用与核验。
- Gitea.com 证据发布/读取与 gzip/ZIP 契约；收集、停止、销毁的资源所有权检查。
- 自定义 Harness archive 的 YAML、params.yaml.env、协议和 observation 配置；环境清洗没有把这些档案内配置一概删除。

不能以“名字在旧代码中出现过”断言以前已有完整功能：

- capacity/health 模块存在，但只找到测试调用，没有生产启动路径的容量 acquire 或 health.record；不能声称旧监督器原有完整跨实验排队/错误率自动保护。
- certification 当时未落地；旧 E2B lifecycle guardian 引用的脚本未入仓，缺失时直接返回 None，不能把它当成已经实现的续租/自动快照能力。
- ROLE_RUNS_TRANSCRIPT 和若干 HSE_* timeout 字段有旧赋值，但未找到主链有效消费者。
- 旧配置要求多个需求角色模型名，实际 runner 仍只把 models.synthesizer 映射到共享 DEMAND_LLM_MODEL；没有证明旧入口支持每个需求角色独立模型。
- 用户 temperature、token/context 上限、五轮请求重试、24 外轮/90 秒心跳等仍保持常量或 Python 构造参数。没有找到旧公开 env/config 真正调整它们的路径，不能算这次迁移丢失。
- builtin Harness 未确认消费 HARNESS_LLM_REASONING_EFFORT 转写后的 plain 环境变量；不能据 runner 的转写就宣称 builtin 思考开关回归。自定义 Harness 是否消费它须按自身源码判断。
- SESSION_SEED 在冻结 plan 分支不参与抽样，不能以宿主 seed 不再透传推断当前正常运行随机性改变。

## 六、离线复现实证与验证缺口

临时审计程序保存在 `/tmp/unified-entry-audit-20261003/`，不作为仓库新启动入口。使用现有测试 fixture 创建本地假材料/虚构凭证；只调用 schema validator、环境构造和模拟后端，运行后不留 provider 资源。

| 实证 | 结果 |
| --- | --- |
| 12 个原控制变量同时放 host 和显式 env profile | credentials 均不保留；controller 环境均无这些键。甚至直接放入传给 builder 的 credentials，仍不成为运行设置 |
| 给当前 schema 增加分组、reasoning、timeout、coordination 等候选字段 | 均拒绝；不存在另一条文档支持的配置入口 |
| 单轮、正常完成 controller，未启动 Vigil | local.launch 报 exited before owned Vigil became ready |
| 旧 SWE 计划加载器处理一任务 A、A、B、B | 正常接受；当前自动生成器给 A、B、A、B，且无覆盖入口 |
| 三种 delivery 凭证引用名 | 自定义 API key 与 OAuth token 均被映射成 ANTHROPIC_AUTH_TOKEN |
| 对照清理前 builder 主体 | 内容相同，确认上述环境过滤在 0069 已存在 |

之前 1304 passed、2 skipped 的结果是真实的，但测试主要验证当前 v2 定义和新目录合同，未逐项比较旧接口与新入口的能力覆盖；部分测试反而明确断言 Owner=0、CI/评分关闭等新默认。两份 N1 五轮示例也覆盖不到单轮、direct、自定义 plan、分组或各种可选开关。

因此不能用“当前测试全过”或“默认 N1 跑完”替代迁移完整性验收。本次只读审计未执行真实模型调用，也未重新执行两后端 live smoke。

## 七、后续修复顺序

1. 先修 schema 已接受却执行错误的单轮 local readiness，以及认证类型映射；验证 E2B 非空交付的运行用户与权限行为。
2. 将分组、USER/DEMAND reasoning、延迟隔离计时、交付 deadline/poll、coordination 接入 schema 和冻结 context。提供明确默认值，补两后端实际传递与消费者验证，不恢复任意 env 透传。
3. 补 direct 与显式逐轮 plan，先覆盖单任务，再设计多任务。默认前端按 run 绑定属于同一运行入口的观测接线缺口。
4. 对 Owner 模型评审、工程 CI、独立官方评分、旧 seed 输入及 N4/N8/历史 continuation 明确产品选择和工程依赖，再分别实现；不以某个 const 已设 false 就视为没有迁移问题。
5. 以“旧功能 → 新字段 → 冻结材料 → 两后端环境 → 真正消费者 → 验收”的矩阵做评审。每个已有功能只有迁入、明确退出或待迁三种处置，不能悄悄变成归档后就不再支持。

当前只完成审计与说明修正，以上修复尚未实施。

## 审计后的实现状态

用户于 2026-10-03 授权实施；清理基线独立提交为 `81b3f56`。随后 Spec-0072 补齐本报告中的分组、推理强度、计时、交付策略、告警、Owner 模型评审、direct、显式计划和看板接线，修复两个已复现问题，并将新交付运行路径改为非 root。新增策略进入冻结配置，旧 run 不升级。

上述正文保留审计当时的结论；实现与测试边界见[能力迁移验收](../validation/spec0072-capability-migration.md)。工程 CI、多任务/N4/N8、历史续跑导入及其他列明范围仍待迁入；真实云端非空交付也尚未验收，不能据离线测试称全部迁移完成。

### Spec-0073—0075 后的更新

上段是 Spec-0072 完成时的状态，不代表后续能力仍未迁入。按当前统一入口分别记录：

| 能力 | 当前处置与验收边界 |
| --- | --- |
| 分组、reasoning、计时、交付策略、告警、Owner 模型评审、direct、显式计划、看板 | Spec-0072 已迁入冻结配置；见对应验收，不能仅凭字段存在扩大真实 provider 覆盖 |
| 多任务、同轮多用户、ordinary/SWE 混合及 N4/N8 | Spec-0073 已迁入同一 workload 契约。真实 local/E2B N4 各完成八个会话及停止/恢复；这两次运行未产生准入交付票，不能作为真实非空 OpenAgents 交付证明。见[多任务验收](../validation/spec0073-multi-task-users.md) |
| 批量实验管理 | Spec-0074 已提供同后端完整配置列表与 check/prepare/run/status/stop/resume/collect。真实 local 两成员批次完成并清理；E2B 批次未实测。它不是跨账户容量调度或参数矩阵。见[批次验收](../validation/batch-experiments.md) |
| 官方 SWE 任务评分 | Spec-0075 通过独立事后 `grade` 命令接入终态完整归档与官方 evaluator。新控制器保存完整会话补丁；旧 hash-only 会话不可还原。`evaluation.official_grading` 仍为 false，不开启循环内评分。见[评分教程](../tutorials/post-run-grading.zh-CN.md)及[评分验收](../validation/post-run-grading.md) |

事后任务成绩不是对 Harness 的新留出泛化测试。官方 dataset 的 gold patch/test_patch 不进入演化输入，成绩不反馈为需求、proposal、Issue 或工程 CI 门禁。评分接线的离线替身验收与实际官方 Docker 成绩分开记录；不能把前者称作官方测试通过。

剩余范围仍需单独设计或保持明确收窄：工程 CI runner 注册与生命周期、历史产物导入追加轮、旧 seed 卡库/纯文本输入适配。自定义 Gitea provider 仍是公开 local+localhost 与 E2B+Gitea.com 两模式之外的选择；替代 OpenAgents backend 不因独立项目有此能力就自动成为本仓控制器接口。当前 resume 仍只续原身份未完成的 run，不导入历史实验、不升级冻结 controller。已批准退出的旧 wrapper、隐式私人配置和任意宿主 env 透传不恢复。

### Spec-0075 实测边界补记与 Spec-0076 输入迁移

Spec-0075 已于提交 `7a8176a` 完成评分实测更新；上文的离线与官方运行区分继续有效。官方 Verified 的 `psf__requests-6028` 正对照由验收 Harness 施加 gold patch，负对照只新增无关文件，真实官方结果为一项 passed、一项 failed；这不是模型能力成绩。重复评分前后，原实验的 642 个文件逐一 SHA-256 一致。公开 pvlib dev 任务的官方镜像因 NumPy 2 移除 `np.Inf` 而在 conftest 启动阶段失败，重新分类为 `crashed / official_test_start_failed`，不能计为任务失败或修复通过。详见[评分验收](../validation/post-run-grading.md)，原始证据保存在仓外。

Spec-0076 将旧 seed 卡库和明确非 benchmark 的文本指令接入现有 ordinary 任务包：统一入口新增 `task import-seeds` / `task from-text`，转换返回绝对 `task_packages` 数组供原 workload 使用。输出 `tasks.json` 只作相对路径索引，不新增运行入口；后续仍用 check/prepare/run，并冻结既有任务/source/setup 合同。无仓库输入使用带说明 README 的 scratch 源目录，不写答案；oracle、env.test_cmd、gates、provenance 不进入包或 sidecar。旧 setup 依赖不自动锁定，旧 base image、外部服务和元数据未自动复现，不能把输入迁入等同于原研究环境通过复现门。

公开示例仅使用一张明确非 benchmark 的合成文本卡和一份用户任务指令；真实历史七卡不搬入主 examples。双语[输入教程](../tutorials/seed-task-import.zh-CN.md)提供将转换数组写入 local/E2B N1 配置副本的精确命令和完整离线检查。转换与离线验收不代表真实双 provider 实验已运行，也不代表任务通过；实际执行覆盖由本组独立验收记录。历史产物 continuation 仍待设计；不恢复旧 wrapper、隐式私人配置或任意宿主 env 透传。

### Spec-0076 真实 local 补记与 Spec-0077 工程 CI

Spec-0076 提交 `6a75254` 已包含真实 local 输入链路验收：run `20261003T115105Z-81ecc091` 使用转换后的两个任务包完成单轮两会话，达到 COMPLETED / collection COMPLETE，产生完整会话补丁并在独立 Docker 中复验，随后清理到 DESTROYED。此实证没有交付轮，不能作为多轮演化、E2B provider 或模型自动修复证明。原始证据和准确接受状态见[输入验收](../validation/seed-task-import.md)。

Spec-0077 为 local + localhost 迁入可选工程 CI，`runtime.local.ci_enabled=true` 沿用原 check/prepare/run/status/stop/resume/collect/destroy，不增加实验入口。默认关闭保持原语义；E2B + Gitea.com CI 仍不支持。可选 runner/job 镜像必须使用显式版本或摘要，并只在启用时允许；准备固定实际 image ID。每个 run 使用独占的 privileged Docker daemon、job 存储和工具缓存；内部 docker:27.5.1-dind 配方固定实际 image ID。runner 通过内部 DOCKER_HOST 连接，不挂宿主 Docker socket、不发布 daemon 宿主端口；job 的 host 网络模式属于私有 daemon 网络命名空间。该配置用于可信 Harness 工程代码，不提供恶意代码隔离。冻结 Harness 要有兼容 PR 工作流；后端核验注册、所有权、网络及镜像，真实 PR checkout/Python smoke 在当前 head 至少一项检查且成功后才发就绪收据。只有匹配的已核验收据能开启 OpenAgents `ci: agent`；失败或超时保留诊断，不能静默 skip。

状态与收集保存 CI 身份、就绪和 main/PR 当前提交状态，不能复用旧 head 的绿灯。stop 暂停所属 runner、处理所属 job 并停止私有 daemon，保留恢复所需存储与注册；resume 复用原 daemon/存储/注册身份、再次探测；destroy 只清理核验属于此 run 的执行资源并移除 CI job 存储，保留并列明 Gitea 和 runner 私密注册卷，注册秘密不进入普通归档。工程 CI 不调用模型、不运行 benchmark，与独立事后 SWE `grade` 及 Harness 留出评估分开。

以上记录配置与实现契约，不预先宣称真实 Docker 验收通过。双语[CI 教程](../tutorials/local-engineering-ci.zh-CN.md)提供精确命令；本组的离线回归、真实 PR 红绿和生命周期证据以[工程 CI 验收](../validation/local-engineering-ci.md)为准。人工制造红绿状态不能记为模型自动修复。当前剩余独立范围为历史产物 continuation、E2B CI 托管契约及此前明确收窄的 provider/backend 选择。

首轮真实 canary 已观察到 main 成功、人工红 PR 失败、修订 head 转绿，但也暴露 act_runner 0.2.11 的 job 名称和工具缓存会跨 run 共享，实施因此改为每 run 独立 daemon。该初步红绿结果不能代替独立 daemon 最终实现的验收；最终拓扑及生命周期实证仍以上述验收报告为准。

最终实测已完成：两个独立 daemon 同时运行相同 job/cache 名称而未冲突；完整候选通过公开 stop/resume，复用原注册与容器身份，重新得到真实 PR 红绿及固定 OpenAgents 的一致判定，最终 COMPLETED / COMPLETE / DESTROYED。归档保留当前 Harness 提交的非空 CI success，注册凭证未入归档。过程中修复 dotenv 引号造成的 reader 401、短暂 pending 和自动删容器竞态，证据及测试边界见验收报告；没有将技术红绿探针记为模型自动修复。

### Spec-0079：当前归档继承与追加

用户明确收窄范围为当前统一入口的完整归档，无需兼容旧版实验产物。此前“历史 continuation 待迁”的记录描述当时范围；本组的处置是支持带新 export 的当前 schema 2 / workload contract 1 归档，不追溯改写历史结果或升级旧冻结 controller。

当前继承输入由 `harness.source=continuation`、`workload.source=parent`、`continuation.archive/sha256` 共同声明，仍使用 check/prepare/run/status/stop/resume/collect/destroy。父来源要求 COMPLETE、实验完成和 continuation_ready；末轮精确 Git tree、材料、配对、persona、会话及报告由版本化 export 和 source validator 核验。可运行材料改变时拒绝；缺失或不能核验的 native observations 保持 unavailable。子配置显式选择模型、runtime、角色、策略及凭证，父身份、账本、资源、凭证和授权不搬入子执行身份。

子初始化通过独立 bootstrap 恢复域处理父末轮反馈并等待准入交付，再启动新增用户轮；与普通轮共用反馈 pipeline，即使只追加一轮也启用交付。count 只计新增用户，最后新增轮仍只试用。父逻辑 R5 加两轮显示子本地 R1/R2、逻辑 R6/R7；该子完整收集后再加一轮显示逻辑 R8。父会话不计入子新增指标，祖先只保留身份/hash 摘要，不递归打包完整归档。

双语[追加教程](../tutorials/experiment-continuation.zh-CN.md)提供从当前 N1 两后端模板生成完整子配置的命令、独立 profile、停止恢复及再次追加流程。此补记记录当前实现与支持边界；真实 local/E2B 非空交付、生命周期和二次追加覆盖由独立[验收记录](../validation/experiment-continuation.md)列明。离线合同通过或零准入封口不能代替真实 OpenAgents 交付证据；Spec-0077 的已完成实测记录保持原义。
