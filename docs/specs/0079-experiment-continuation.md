---
number: "0079"
title: 当前实验归档继承与追加迭代
issue: 0
slug: experiment-continuation
summary: 当前完整归档作为冻结父输入，新run先交付末轮反馈再追加用户轮，复用统一入口与恢复机制，不兼容旧版产物。
tasks:
  - id: T1
    title: 当前归档来源与契约核验
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/experiment/continuation/__init__.py
      - backend/auto_designer/experiment/continuation/source.py
      - backend/auto_designer/experiment/schemas/continuation-export-v1.json
      - backend/tests/test_experiment_continuation_source.py
    scope: 只读解析当前归档、末轮边界、输入与文件身份；不支持历史格式
    acceptance: 只接收完整当前export；损坏/partial/身份矛盾/越界包拒绝；父配对按权威plan核验
  - id: T2
    title: 规范导出与父证据报告投影
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/experiment/continuation/export.py
      - backend/auto_designer/experiment/continuation/evidence.py
      - backend/auto_designer/experiment/continuation/forge.py
      - backend/auto_designer/experiment/collection.py
      - backend/tests/test_experiment_continuation_export.py
      - backend/tests/test_experiment_continuation_evidence.py
      - backend/tests/test_experiment_continuation_forge.py
    scope: 按commit导出精确tree；父证据只读视图、当前报告映射与脱敏来源证明
    acceptance: 旧main不能污染export；tree/mode/hash正确；报告重试唯一且不串号；父会话不计子指标、观测与授权一致
  - id: T3
    title: 共用反馈交付阶段
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/loop/feedback_pipeline.py
      - backend/auto_designer/loop/orchestrator.py
      - backend/auto_designer/demand/triage.py
      - backend/auto_designer/demand/divergent.py
      - backend/auto_designer/demand/grouped_synthesizer.py
      - backend/tests/loop/test_feedback_pipeline.py
      - backend/tests/loop/test_orchestrator.py
      - backend/tests/demand/test_triage.py
      - backend/tests/demand/test_divergent_gate.py
      - backend/tests/demand/test_grouped_synthesizer.py
    scope: 提取具体反馈pipeline；外层和角色内层共享显式前置依赖
    acceptance: 两起点依赖一致且bootstrap外部操作域不冲突；交付卡死不开用户；普通轮序/恢复/grade封口合同不变
  - id: T4
    title: 冻结继承配置及统一执行恢复
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/experiment/config.py
      - backend/auto_designer/experiment/schemas/experiment-v2.json
      - backend/auto_designer/experiment/materials.py
      - backend/auto_designer/experiment/context.py
      - backend/auto_designer/experiment/workload.py
      - backend/auto_designer/experiment/controllers/unified.py
      - backend/auto_designer/experiment/controllers/feedback.py
      - backend/auto_designer/experiment/controllers/runtime.py
      - backend/auto_designer/experiment/engine.py
      - backend/auto_designer/experiment/runtime.py
      - backend/auto_designer/experiment/backends/local.py
      - backend/tests/test_experiment_continuation_config.py
      - backend/tests/test_experiment_continuation_lifecycle.py
      - backend/tests/test_experiment_continuation_workload.py
    scope: source=parent配置、原子冻结、精确seed、阶段角色装配、独立bootstrap恢复及统一交付完成判据
    acceptance: 一轮追加仍交付；同task/persona/interaction编新绑定；不复制父ledger；恢复不重复副作用；新旧配置/两后端正常语义保持
  - id: T5
    title: 双语追加实验教程
    status: done
    priority: P1
    tags: []
    depends-on:
      - T4
    relates-to: []
    parallel: false
    files:
      - docs/tutorials/experiment-continuation.md
      - docs/tutorials/experiment-continuation.zh-CN.md
      - docs/CONFIGURATION.md
      - docs/CONFIGURATION.zh-CN.md
      - docs/audits/unified-entry-capability-migration-20261003.md
      - README.md
      - README.zh-CN.md
      - CLAUDE.md
    scope: 提供完整当前父run收集到子配置/停止恢复/再次追加教程；更新支持边界
    acceptance: 只用统一入口；中英命令一致；明确本地与逻辑轮号、旧包不支持及源事实保真
  - id: T6
    title: 合同与真实双后端验收
    status: done
    priority: P1
    tags: []
    depends-on:
      - T4
      - T5
    relates-to: []
    parallel: false
    files:
      - backend/scripts/e2e-spec-0079-experiment-continuation.sh
      - backend/tests/test_experiment_continuation_contract.py
      - backend/tests/fixtures/continuation/current-parent-v1.json
      - docs/validation/experiment-continuation.md
      - .github/workflows/experiment-contract.yml
    scope: 崩溃边界/重复继承/普通路径回归；真实local和E2B非空交付与归档清理实证
    acceptance: 两后端证实父反馈→真实交付→新增试用；当前源不变/新身份/正确累计轮号；无准入不冒充交付
---

# 0079 · 当前实验归档继承与追加迭代

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

为当前统一入口产生的完整实验归档增加继承能力：创建新 run，继承父实验最后一轮的 Harness、任务、persona 和真实用户反馈，先完成反馈处理及代码交付，再运行新增用户轮。新 run 继续使用现有 check/prepare/run/status/stop/resume/collect/destroy；父实验的身份、账本和归档保持不变。

用户已明确无需兼容旧版实验产物。本组只支持带新导出契约的当前 schema 2 / workload contract 1 归档；不增加历史布局适配器、source/replay 选择、旧脚本转调或 snapshot 补齐。归档读取、父证据投影和反馈执行分别负责自己的事情，不引入第二套监督器。

## Motivation

当前 resume 针对同一个 run 的中断恢复。COMPLETED run 直接 attach，恢复身份固定 run_id/config_hash/controller_sha/plan_hash，已完成轮直接返回 sealed_sha。普通实验最后一轮只做用户试用，不处理它产生的反馈。修改父配置的总轮数后 resume，既不能补跑末轮反馈，也违反输入冻结。

用户需要的追加流程是：父 R5 已完成用户试用→创建子 run→处理 R5 反馈并交付→子用户试用逻辑 R6。当前运行代码、模型和后端可以重新冻结，但不能把父执行记录复制成子 run 的成功记录。

还需补一项当前格式的生产端缺口：collection 排除 .git，工作区 main 可能停留在 seed，只 fetch origin/main。现有工作树与初始 materials/harness.tar.gz 不能证明最终版本。因此必须由当前控制器按最后一轮明确 SHA 导出代码，才有可核验的后续输入。

## Guide-level explanation

### 1. 父实验先完成并收集

父实验用当前统一入口正常运行到 COMPLETED，再执行 collect。新版本会把明确绑定末轮 SHA 的 Harness 导出、反馈和来源证明放进 artifacts.tar.gz，并在收集回执报告 continuation_ready。只有 COMPLETE、experiment_complete 和 continuation_ready 同时成立才可作为父来源。已销毁父计算资源不影响使用已收集的归档。

本组不追溯升级旧冻结控制器。缺少新导出契约的过去归档明确提示不支持；不靠缓存或工作树猜出最终代码。

### 2. 子实验声明继承

子配置仍是完整 schema 2 配置，runtime、models、roles、policies 和新增轮次按当前规则填写，只把输入来源改为：

```json
{
  "harness": {"source": "continuation"},
  "workload": {"source": "parent"},
  "continuation": {
    "archive": "../parent/artifacts.tar.gz",
    "sha256": "64位父归档SHA256"
  },
  "rounds": {
    "count": 1,
    "sessions_per_round": 4,
    "max_parallel_users": 4
  }
}
```

这是合入完整配置的片段，不是可直接运行的完整文件。首版固定继承父末轮的任务/persona/interaction 配对，每个新增轮重复这组配对；sessions_per_round 必须与父末轮人数一致。改变模型、后端或策略通过子配置显式声明，并记录父子差异。首版不支持借此替换任务或 persona；需要不同 workload 时使用普通新实验。

无需新的 import 启动流程，继续用现有命令：

```bash
python backend/scripts/experiment.py check --config child.json --offline
python backend/scripts/experiment.py prepare --config child.json --secrets-file .env.experiment
python backend/scripts/experiment.py run CHILD_RUN_ID --secrets-file .env.experiment
```

check 返回父身份、末轮 SHA、反馈人数/报告数、输入摘要和缺口；prepare 原子冻结继承输入；run 先交付父反馈再开始用户。凭证来自子 profile，不读父 .env、旧 token 或父 Gitea 地址。

### 3. 轮次与停止恢复

rounds.count 表示新增用户轮数。父末轮为逻辑 R5、子 base_round=5 且 count=1 时，子内部 local_round=1，对外 lineage_round=6。反馈初始化是 continuation_bootstrap 阶段，不算新增用户轮。追加多轮时，中间新增轮正常交付，最后一轮仍只试用。

子 stop/resume 沿用已有入口，恢复本次初始化和新增轮。父 run 的 COMPLETED 状态及末轮 users-only 事实不变。父会话不计入子会话数、子评分或新增模型用量。

## Reference-level explanation

### 1. 模块边界与依赖方向

```text
current archive → source validation → existing material freezing
                         ↓                        ↓
                read-only parent evidence → unified controller
                                                  ↓
                              shared feedback pipeline → ordinary user loop
```

- experiment/continuation/source.py：只理解当前归档及 export contract，验证和选择父末轮，返回数据；不 import backend/controller，不运行归档代码。
- continuation/export.py：按指定 commit 导出精确 Harness tree 和来源证明，由两后端共用的冻结 controller 调用；不通过 provider 分支猜代码。
- continuation/evidence.py、forge.py：分别提供父会话只读视图与新仓 report 映射；只依赖材料及现有 store/tracker 操作。
- loop/feedback_pipeline.py：从现有 Orchestrator 提取具体 demand→owner→delivery→seal 操作；不认识归档、lineage 或路径。
- materials/context/unified controller：分别冻结、传递非敏感上下文、装配执行。backend 继续按正常配置构建工作区、管理进程和清理资源，不增加“父实验恢复”分支。

controllers/feedback.py 是阶段角色的具体装配函数，复用现有定义与回调，并显式接收证据store、恢复域、round provider和分组产物根；不是通用agent工厂。它使bootstrap与普通阶段能够各自装配，避免unified.py复制大段角色构造或临时修改实例私有字段。

不增加 importer 插件系统、通用工作流平台、独立 launcher 或新 model 调用层。公共入口只新增配置来源，check/prepare 复用同一 source validator。

### 2. 配置、归档与材料冻结

continuation 是可选对象，仅 archive/sha256 两字段。存在时要求 harness.source=continuation、workload={source:parent}；三者必须同时出现，禁止混入另一个 Harness 或显式任务输入。省略时保持已有配置哈希、字段与行为，不增加默认 continuation。

只接受当前 collect 的单层 artifacts.tar.gz：schema_version=2、workload_contract_version=1、带版本化 continuation export、原 controller invocation/recovery/collection 身份一致。读取 collection.files 的完整性清单、对应材料及 selected sessions。拒绝未知版本、PARTIAL、停止/失败父实验、缺 export、重复/出界/链接/特殊路径及展开预算超限。不支持 tar.zst、递归完整实验包或任意包内脚本；registry 声明的 task source archive、内层 Harness export 和 observation bundle 仍属于正常材料，按各自契约和预算检查。

父边界是全部预期用户完成且已 sealed 的最后一轮；其 user_sha/sealed_sha 必须相同，用户集合由冻结 plan 与 recovery units 决定，不由文件数或可修改标签推断。完成判据读取 collection 的 controller receipt、nonce、invocation 与 recovery，不要求不可变 manifest 的初始状态字段更新为 COMPLETED。外层 archive SHA 取子配置提供的 expected SHA；包内 collection.files 验证内容，不要求归档记录自身的 hash。

需要完整 session payload、对应 task_digest/persona 以及明确报告关联。没有报告也可继承，但必须明确为零，不能生成虚构反馈。有 pending report 时要求子 triager/synthesizer 数量至少为一，不能因为角色设为零而悄悄跳过父反馈。父本身是 continuation run 时，还要核验其 bootstrap 完成且首个用户 SHA 等于 bootstrap sealed SHA，再接受它的末轮。

prepare 从父 manifest 的 material registry 复制任务原始 source archive、instruction、setup/requirements lock、persona 卡等经过核验的输入，复用正常 task catalog 与工作区准备，不依赖父宿主路径或父活沙箱。task record 与 package 保持原样，包括 source/tasks/ID 的逻辑路径；source 目录虽不在父收集包中，也能从 registry 指向的 source_archive 重建。不得重新 _freeze_task、猜宿主源目录或改 package 路径导致 task_digest 变化。

export 记录 selected persona 卡的 canonical JSON digest、原 library hash及 roster strategy；继承从冻结卡库取原卡，不用 Session 的显示 persona 替代。子可以只保存选定卡，但必须标明原库选集，不能声称整个 library 文件字节不变。只取父末轮实际配对，按子 count 编译 R1..N 新计划；复用现有 binding 校验，不把父 plan_hash 冒充子 plan_hash。

workload compiler 中新增明确的 inherited-pairs 输入路径，与普通编译共享 binding 生成/校验。父配对及摘要进入新 manifest 的 continuation 材料记录；read_session_plan 必须从这些冻结配对重新核验。配置仍保存用户声明的 source:parent，不把派生运行状态写回配置或伪造 task_package 外部路径。

继承文件登记为 materials/continuation 下的相对路径+hash；子仍冻结当前 controller/OpenAgents source 与模型策略。manifest.lineage 至少包含 parent_run_id、parent_config_hash、parent_controller_sha、parent_plan_hash、parent_archive_sha256、base_round、parent_user_sha、parent_tree_id，以及声明的模型/后端/策略差异。没有复制父 resources、checkpoint identity、授权 grants 或 secret profile。

### 3. 当前 producer 的最终 Harness 导出

新增 continuation-export-v1.json，记录末轮 SHA/tree ID、源码 archive 及 SHA-256、逐 tracked 文件内容摘要/Git mode、所选末轮与 session/material 证明。controller 只在普通循环完整结束后按账本指定 SHA 导出；不用工作区 main/HEAD或最终缓存推断。允许 Git tree 的正常文件及 executable mode，拒绝链接/submodule/特殊 mode，不静默丢文件。

导出文件放在正常收集目录，不覆盖 materials/harness.tar.gz。缺对象、私密/不支持文件或证据不一致时记录 unavailable，普通实验的已有结果保持有效；collect 可以完成，但 continuation_ready=false，后续 check 明确拒绝继承。COMPLETE 与可继承性是不同字段。

collector 保留一项明确的证据投影记录：发生已有凭证脱敏时，记录原文件 hash、归档 hash、credential_redaction 原因，不记录凭证值。父 Session 可作为已声明的脱敏证据使用，不能宣称其归档字节就是原始执行字节；task/Harness/persona 等可运行材料必须精确匹配其原 hash，脱敏改变它们则不能继承。

首版使用精确源码 tree，不携带父 Git历史。子产生新 seed commit；receipt明确 parent_commit 与 child_seed_commit 不同，child Git tree必须等于 parent_tree_id。外层 collector 使用 write_bytes，不能依赖外层 tar mode；按内层 export inventory 恢复 executable mode。建 index 必须包含父已 tracked 但被 .gitignore 忽略的文件，避免 clean filter/.gitattributes 改变 blob，逐 blob hash 与 write-tree 双重核验，不只运行 git add .。continuation seed 不重写父 .gitignore；runtime排除规则写入 .git/info/exclude，hook在 seed后安装。普通 builtin/archive seed保持既有语义。

### 4. 父证据与新仓 report 投影

子 run 创建自己所属的新仓。先完成 seed及远端初始化，再投影父末轮 pending reports，避免 _reset_to_initial 关闭已导入的报告。新建当前报告，不重放父 proposal/ready/PR/合并；父 forge 状态与评论只读归档，不继承 openagents/ready 标签。已关闭、拒绝或已交付的报告保持背景状态，不自动重新立项。

报告按 parent archive/repo identity/number 构成 source namespace，原文与哈希保留；create_issue_once 的 operation key来自子身份及源报告摘要。实际发号后保存 source→current issue_map，新号与父号相同也不能混淆。原文中的 #号/URL显示为历史引用，不在自然语言里全局替换；当前可执行 references只由结构化映射生成。

导入 receipt保留 repo ID、child seed、source report hash、新号/URL与状态。远端已创建但本地未写回时，恢复用 marker/payload对账；外部内容改变或身份冲突报错，不以另建 issue完成重试。

ContinuationEvidenceView 包装 child SessionStore与只读父材料。load/find_session_id_by_issue/load_user_feedback_envelope 根据明确 issue_map解析父SID，保留父 provenance；不调用父 save/reconcile/rebuild_index。bootstrap角色 index使用 selected父边界，派生视图的当前issue_numbers按映射生成，source refs仍单独保留；普通用户轮角色与 Metrics使用当前索引。父会话不写入子 sessions/index，不变成本次 user attempt；SID冲突拒绝覆盖。

原生 observation bundle按原字节/hash复制到子当前 observation_root/SID，保留父manifest身份，使现有 ObservationProvider和 delivery_evidence同时读取；新 grants只根据映射和授权SID创建，不复制父grants。collector 若对 bundle 内任何字节脱敏，原 manifest 的嵌套 hash 将失效，此 bundle 必须 unavailable，不能改写原 manifest 后仍称原生保真。没有有效 observation时保持 unavailable，不重建伪日志。invalid/skipped/unverified_accept、拒绝理由及脱敏声明仍保留，不将感受转成已确认技术事实。

### 5. 共享反馈阶段与 bootstrap 恢复

抽出 recoverable demand、owner、delivery wait及seal为一个具体 FeedbackPipeline。普通轮 prerequisite=users；继承初始化 prerequisite=feedback_imported。依赖角色、recovery、fetch/wait、integrity_guard与SHA解析/检查，不接收 archive或provider对象。保留原有封口前检查编排仓完整性的时序，bootstrap同样适用，不能先记成功seal再发现越界修改。

Triager和Divergent内层unit现有 users硬编码依赖要与同一显式 feedback_dependency绑定一致；正常路径仍为 users。Synthesizer/grouped/Owner复用现有恢复绑定，顺序保持 triage∥divergent→synthesizer→owner→delivery_wait→seal。不扩展 RecoveryStore为任意工作流。

bootstrap使用 checkpoints/continuation-bootstrap 的独立 RecoveryStore。身份来自子 run/config/controller及冻结初始化输入摘要；内部正 round=1只是该命名空间，不是父轮或子用户轮。起始stage为 feedback_imported，禁止伪造 users成功；receipt明确 phase、source边界、映射及input hash。

外部副作用也必须隔离：bootstrap的 operation keys/UsageContext.operation 使用显式 continuation-bootstrap 前缀，普通轮原 key 不变。仅分开 ledger 目录不足以避免同仓 bootstrap round1 和用户 round1 的 create_issue_once/model-output key 碰撞。分组产物也用独立 phase 目录。父 round-* 标签保存在 source metadata，不进入当前执行标签；bootstrap 角色 round_provider 返回 None、恢复上下文仍用其内部正 round1，普通阶段恢复实际 local round，避免 filter_current_round 误丢父报告或把 bootstrap 提案串入普通轮。

共用阶段提取保持普通持久化合同：stage=round_sealed、key=operation_key(local_round,"round_sealed","stage-marker")、input={user_sha,sealed_sha}、observed_postconditions.completed，以及原依赖关系。现有 grade 和 resume 直接核验这些字段，不能为了统一术语改成 seal 或更换普通 keys。

核验 seed/投影→父证据视图及bootstrap恢复绑定→共用pipeline→固定准入集合及交付终态→新main为child_seed后代→保存sealed SHA并原子完成。零准入也要记录no_admissions及有效seal。卡死时停止在bootstrap，不提前开始新增用户。

resume先对账初始化receipt及原有外部副作用。bootstrap已完成时，不重跑LLM、不重复建报告或交付。两个阶段经同一具体角色装配函数分别创建实例，传入对应 store/recovery/round_provider/产物根，不通过修改对象私有属性切换；随后调用现有用户循环。父已完成用户不会被复制进子ledger。

交付启用统一为 count>1 or continuation_present；角色roster、Vigil启动和两后端launch readiness使用同一语义。仅追加一轮也必须能交付父反馈。工程CI继续由子配置决定，E2B CI范围不随本组扩大。

engine._completion 对继承run增加bootstrap完整/身份一致/input及映射hash一致/sealed有效判据，并要求主ledger R1.user_sha == bootstrap.sealed_sha，证明新增用户实际试用了本次交付，再叠加现有1..N用户轮封口条件；普通run不读取此域。status/logs返回bootstrap phase与local_round/lineage_round。batch/grade仍用本次run与本地编号，仅统计新增预测。

### 6. 双后端与再次追加

两后端读取相同冻结catalog、persona、父证据与bootstrap输入；依赖安装、Git任务准备及正常任务环境验证仍由既有backend承担，本组不承诺离线安装或跨后端任意环境等价。父local→子E2B或反向时，目标后端不支持原任务必须在check/prepare明确拒绝，不用简化任务替代。

子collect保留lineage、issue_map、bootstrap receipt、必要父证据及子末轮导出。祖先记录只带hash/identity/必要引用，不递归嵌套完整父归档。export明确记录 local_round=父count、lineage_round=父base_round+父count，以及父自身该轮用户units；后继只选直接父的末轮，不重新选择祖先会话或导入已处理祖先报告。

新子 base_round = parent.lineage.base_round（无lineage为0）+ parent.config.rounds.count，并与父export.lineage_round核对；新子 lineage_round=base_round+local_round。例如父R5→子新增两轮为逻辑R6/R7→再追加一轮为R8。父材料原文/hash在重复继承中不重标为当前执行。

### 7. Task DAG与验收

T1当前归档读取/验证；T2终态导出与证据/报告投影，依赖T1；T3独立提取共用反馈pipeline及正常路径回归；T4依赖前三者接入配置/冻结/controller/生命周期；T5依赖T4写双语教程与能力审计；T6依赖T4/T5完成合同和真实双后端验收。文件互斥列表在frontmatter。端到端脚本 backend/scripts/e2e-spec-0079-experiment-continuation.sh。

| 验收 | 必须观察的结果 |
| --- | --- |
| 来源和身份 | 新导出contract匹配末轮SHA/plan/receipt；PARTIAL/FAILED/缺导出/未知版本/损坏或越界包拒绝 |
| 末轮配对 | 使用账本完成用户集，不按文件数猜；任务/persona/interaction与原内容身份保持，新增计划为1..N |
| Harness | 本地main旧也按明确末轮SHA导出；子tree精确相同，parent/child commit分清，mode/ignore不被悄改 |
| 证据映射 | 同号不串源；report重试唯一；父Session不改provenance、不进新指标；原观测同时到达需求和交付读取端 |
| 脱敏和无效评价 | 保存original/archive hashes与原因；invalid/缺日志不变valid；可运行材料改变则不能继承 |
| 恢复 | issue创建后、LLM输出保存后、交付等待和bootstrap sealed后分别中断；无重复副作用、不提前开新增用户 |
| 操作域与封口合同 | bootstrap和普通R1的远端去重键不冲突；grouping/round过滤不串源；原grade封口字段不变；新增R1确实测试bootstrap sealed SHA |
| 普通运行 | 无continuation旧hash、单轮不启Vigil、多轮末轮、resume、batch与grade行为保持原合同 |
| 双后端实际执行 | 当前父run→真实父报告处理→至少一张准入票及OpenAgents真实交付→子用户试用；不能以零准入代替非空交付 |
| 再追加与清理 | 子归档再次继承显示正确累计轮号，不递归嵌包；父字节不变、清理只针对子资源 |

小型fixture必须覆盖多个任务/persona的末轮子集、ignored tracked文件与executable mode、原生观测脱敏命中，以及父R5→子两轮→第三代一轮的R8编号。它们验证真实内容与执行归属，不能只比配置字段存在。

模型输出不能保证必然准入，验收需明确实际票与PR/sealed证据；无准入只能记为该分支验证通过。测试fixtures仅使用当前格式的脱敏小包，不提交旧实验产物或运行脚本。全仓pytest、Ruff、配置合同、spec检查及真实验收报告作为合入条件。

## Drawbacks

增加精确末轮代码导出、父证据存储和报告映射，归档体积有所增长。只携带selected末轮与必要forge背景，祖先按摘要记录，控制增长而不丢当前所需证据。

子Git提交不保留父历史，需要以tree身份记录代码等价。目标后端仍须支持父任务的正常准备条件；更换模型或后端会影响可比性，lineage展示差异而不自动得出收敛结论。

不兼容没有新export的归档，符合用户收窄范围的要求；不追溯升级已冻结旧controller。

## Rationale and alternatives

选择“当前归档+新run+独立反馈初始化”，保持父事实和现有生命周期，并允许明确换模型追加。

不改父rounds/hash后resume，也不复制users或删seal：完成轮不会补需求，且混淆执行归属。独立bootstrap域复用RecoveryStore与现有副作用对账，避免把用户计划、评分和batch全面改号。

不新增通用archive adapter或独立import命令：当前只有一个生产端和一种输入格式，现有check/prepare即可完成检查与冻结。也不在local/E2B backend恢复父进程或复活父repo；新run沿用当前资源治理。

选择源码tree snapshot而非整个Git历史；按父commit导出并核验tree，保留原源码事实，同时避免旧hooks/config/PR历史进入执行面。不同seed SHA明确映射，不作错误的SHA相同声明。

首版workload固定继承父末轮，减少任务转换与输入覆盖的歧义。将来若确需改任务，再设计明确的fork语义；不在当前接口增加一组泛化迁移开关。

## Prior art

必要背景均已就地说明。代码证据来自：Orchestrator._run_recoverable_round的完成短路和现有需求/交付恢复；RecoveryIdentity及begin_unit依赖一致性；SessionStore的provenance/索引/证据读取；prepare_materials/verify_materials的原子冻结；engine._completion封口判据；Observations grants与delivery asset读取。

现有统一controller负责两后端装配，当前task catalog和plan已经分离逻辑身份与provider坐标，可复用其原始材料注册。collector排除.git及seed工作树可能过旧的事实说明需要规范导出，不能把当前归档“看起来有代码”当成可继承证明。

## Unresolved questions

本稿已收窄为当前格式、完成末轮、新身份、固定继承workload、可显式换模型/后端、精确tree导出与独立bootstrap域；无旧格式兼容或历史场景恢复待选项。

实施必须实证父manifest的原生观测校验、tree/mode/ignore保真、实际两后端非空交付、重复继承和崩溃对账。未通过时修订设计并展示证据，不能绕过identity或伪造日志。

## Future possibilities

可后续增加UI父子对比、显式更换workload的fork、父非末轮边界及已有反馈重评。任意snapshot/活服务/private任务能力仍属于任务环境层；本组不增加旁路，也不把这些能力与当前归档追加耦合。
