---
number: '0083'
title: 可扩展的会话产物与独立客观验收
issue: 0
slug: extensible-session-grading
summary: 统一 direct 与模拟交互的验收产物，保留现有 SWE 评分并增加 benchmark
  与自定义评分适配；评分读取冻结归档、独立留存，缺失证据不补造。
tasks:
- id: T1
  title: 统一评分合同、注册与结果语义
  status: done
  priority: P1
  tags: []
  depends-on: []
  relates-to: []
  parallel: false
  files:
  - backend/auto_designer/evaluation/contracts.py
  - backend/auto_designer/evaluation/registry.py
  - backend/auto_designer/evaluation/results.py
  - backend/auto_designer/evaluation/acceptance.py
  - backend/tests/evaluation/test_grading_contracts.py
  scope: 定义只读评分请求、固定适配器注册、执行合同与公共结果；抽出接受关系，区分连续分数及基础设施故障。
  acceptance: 未知适配器或版本明确拒绝；completed 才可计技术成败；非 fresh 合同可严格核验；未验收或连续分数不自动成为
    valid_accept。
- id: T2
  title: 任务来源、公开产物声明与兼容身份
  status: done
  priority: P1
  tags: []
  depends-on:
  - T1
  relates-to: []
  parallel: false
  files:
  - backend/auto_designer/experiment/config.py
  - backend/auto_designer/experiment/schemas/task-package-v2.json
  - backend/auto_designer/experiment/materials.py
  - backend/auto_designer/experiment/workload.py
  - backend/auto_designer/models.py
  - backend/tests/test_experiment_grading_task_config.py
  - backend/tests/test_experiment_grading_task_materials.py
  scope: 增加 task package v2 的通用 benchmark 来源与 artifact v1 声明；冻结内容、校验路径与后端能力，保留
    schema1 原身份。
  acceptance: 旧配置、catalog 与任务 digest 不漂移；自定义来源不冒充 benchmark；管理 handle
    不接受用户路径伪造；不支持的必需采集在资源或模型操作前拒绝。
- id: T3
  title: 共用会话采集、归档与续跑边界
  status: pending
  priority: P1
  tags: []
  depends-on:
  - T1
  - T2
  - 0081/T3
  relates-to: []
  parallel: false
  files:
  - backend/auto_designer/evaluation/artifacts.py
  - backend/auto_designer/loop/sim_user.py
  - backend/auto_designer/user/sim/runtime.py
  - backend/auto_designer/experiment/context.py
  - backend/auto_designer/experiment/controllers/unified.py
  - backend/auto_designer/experiment/collection.py
  - backend/auto_designer/experiment/continuation/source.py
  - backend/auto_designer/experiment/continuation/export.py
  - backend/tests/evaluation/test_session_artifacts.py
  - backend/tests/user/test_direct_session.py
  - backend/tests/loop/test_sim_user.py
  - backend/tests/test_experiment_grading_artifact_lifecycle.py
  - backend/auto_designer/loop/orchestrator.py
  - backend/tests/test_experiment_engine.py
  - backend/tests/user/test_prediction_artifacts.py
  scope: 两种 runner 共用清理前采集，复用完整 prediction；保存 session/attempt
    receipt，接入受管环境收集且隔离私有材料、恢复与父轮证据。
  acceptance: direct/simulated 相同合同；实际 user_sha
    绑定；文件与测量来源可核验；缺失/超限/篡改不升级；父轮记录不充当子轮结果；旧 Session 不回写；受管测量前置未完成则不得标 done。
- id: T4
  title: 官方与自定义评分适配器
  status: pending
  priority: P1
  tags: []
  depends-on:
  - T1
  relates-to: []
  parallel: false
  files:
  - backend/auto_designer/evaluation/adapters/swebench.py
  - backend/auto_designer/evaluation/adapters/__init__.py
  - backend/auto_designer/evaluation/adapters/terminal_bench.py
  - backend/auto_designer/evaluation/adapters/tua_bench.py
  - backend/auto_designer/evaluation/adapters/nl2repo.py
  - backend/auto_designer/evaluation/adapters/custom.py
  - backend/tests/evaluation/test_grading_adapters.py
  - backend/tests/evaluation/test_swebench_runner.py
  - backend/auto_designer/evaluation/adapters/container.py
  - backend/auto_designer/evaluation/adapters/profiles.py
  - backend/auto_designer/evaluation/__init__.py
  scope: 包装现有 SWE evaluator；按锁定官方合同验收 Terminal/TUA/NL2Repo 产物，custom
    在独立容器执行固定脚本，移除旧在线评分入口与接受函数兼容导出。
  acceptance: 官方 grader 不重写；锁定任务、执行器、镜像及外部评分材料；SWE 官方报告保留；Terminal/TUA 读取正式
    reward；NL2Repo 保留官方通过率且不虚构二值规则；生产计划重放 SQL；KV 只消费可信原测量；无法还原的环境不可评分；custom
    与操作者阈值不冒充官方。
- id: T5
  title: 统一事后 grade 命令与原会话绑定
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
  - backend/auto_designer/experiment/grading.py
  - backend/auto_designer/experiment/grading_inputs.py
  - backend/auto_designer/experiment/cli.py
  - backend/auto_designer/experiment/schemas/grading-plan-v1.json
  - backend/tests/test_experiment_grading.py
  - backend/tests/test_experiment_grading_e2e.py
  - backend/tests/test_experiment_grading_plan.py
  - backend/tests/test_experiment_cli_v2.py
  scope: 复用归档/轮次/基线/Session/generation 校验后分发 adapter；grade 只接收必填私有 --plan，删除旧
    dataset 参数及兼容转换，保留离线模式并独立保存评分与接受关系。
  acceptance: 所有 adapter 共用 --plan；缺 plan 或使用旧 dataset 参数在评分执行前明确报错并指向新用法；direct
    SWE plan 可评分；隐藏材料不上传；评分不调用模型/provider/Issue；原实验字节与身份不变；中断及重评分独立
    attempt；新接口不得绕过旧绑定。
- id: T6
  title: 真实验收、迁移说明与双语教程
  status: pending
  priority: P1
  tags: []
  depends-on:
  - T5
  - 0081/T4
  relates-to: []
  parallel: false
  files:
  - docs/tutorials/post-run-grading.md
  - docs/tutorials/post-run-grading.zh-CN.md
  - docs/validation/extensible-session-grading.md
  - docs/specs/0051-session-container-objective-evidence.md
  - docs/specs/0075-post-run-swe-grading.md
  - docs/specs/0081-e2b-task-environments.md
  - examples/grading/swebench.json
  - examples/grading/mixed-benchmarks.json
  - examples/grading/custom.json
  - backend/scripts/e2e-spec-0083-session-grading.sh
  - backend/tests/test_experiment_grading_compatibility.py
  - README.md
  - README.zh-CN.md
  - docs/QUICKSTART.md
  - docs/QUICKSTART.zh-CN.md
  - docs/CONFIGURATION.md
  - docs/CONFIGURATION.zh-CN.md
  - CLAUDE.md
  - backend/tests/test_experiment_public_examples.py
  - backend/scripts/e2e-spec-0051-session-container.sh
  - backend/scripts/e2e-spec-0056-0057-user-semantics.sh
  - backend/scripts/e2e-spec-0075-post-run-grading.sh
  scope: 给出两后端统一事后验收材料、命令和扩展方法；核验官方正负控制与管理测量，更新旧规格边界并完成回归。
  acceptance: SWE/生产计划/Excel/TinyDB/custom 真实评分逐项报告；KV 以真实原运行受管测量验证；替身不冒充官方结果；旧
    run 不修改；前置或材料未完成时保留 pending，文档不称完整 N8 支持。
---

# 0083 · 可扩展的会话产物与独立客观验收

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

为统一实验入口增加可扩展的**已有会话客观验收**：direct 与 simulated-user 共用产物收集合同，评分只读取停止并完整收集的 run，根据独立评分计划调用 SWE、Terminal-Bench、TUA、NL2Repo 或自定义适配器。任务来源、交互模式、运行环境和验收方式分别建模；新增 benchmark 不增加会话 runner 分支。

保留 SWE 官方 evaluator，但退役公开 grade 的旧 `--dataset`／`--dataset-sha256` 参数，所有任务只使用必填 `--plan`，不提供别名、自动转换或并行兼容路径。不改用户主观结论、原 Session、反馈、交付门禁或历史归档。每次评分生成独立报告，区分真实通过、真实不通过、未配置、不支持、材料缺失和验收环境故障。独立 Harness benchmark 评测仍负责将指定 Harness 在新任务上重新运行，不由本组替换。

本组已获审阅批准并实施第一版：公共合同、任务包 v2、共用普通文件采集、首批 adapter 与统一 plan 命令已经接入。T3 的受管环境支路、T4 的完整官方核验和 T6 的完整验收仍 pending。已完成部分真实 Docker 控制，逐项结果及未完成项记录在 docs/validation/extensible-session-grading.md；离线回归不代表真实评分成功。不在本组重跑 N8 或修改旧实验结果。

## Motivation

旧 SWE 模拟会话在结束后导出补丁，调用 `SWEbenchEvaluator`，并保存 `objective_evaluation` 和 `accept_validity`。该路径由 0051 的会话隔离与双结论设计引入，已存在实际官方 CLI 调用；只有配置数据集和执行环境时才会运行。后来加入的 direct 路径未调用该 evaluator，其 `accept_validity` 直接为 `not_applicable`。

当前公开入口主动关闭演化期间的官方评分。0075 实现的事后 `grade` 校验冻结归档、完整补丁与原会话身份，并在本机 Docker 调用官方 SWE evaluator；它已经可以对 direct 的 SWE 会话评分，但按 `kind == swebench` 分流，所有评分都必须提供 SWE dataset，其他任务没有适配器。接受关系的通用判定仍放在 SWE 模块中，而且用 `fresh=true` 表达所有验收隔离，不能直接覆盖在原任务环境中验收的 TUA 或依赖独立测量的 KV。

旧混合任务执行器准备了 agent/grader 包，文档要求执行官方 grader，但准备包、用户自主检查、角色交付和官方验收是不同事实。Terminal、Excel、TinyDB 以及服务任务需要不同产物，不能只持有一个 Git diff。R6 归档中保存过工作簿和数据库，却缺少正式 KV 测量记录；新增评分器不能恢复当时未保存的事实。

0081 的完整 E2B 任务环境仍 pending：它计划提供管理侧服务、companion、就绪与 finalize、收集和隔离。本组定义它应交付的验收产物接口，不实现另一套 E2B 环境 broker，也不把旧共享快照包装成已具备可信测量隔离的当前公开环境。

## Guide-level explanation

### 操作者流程

1. 配置实验任务和交互模式。现有 schema 1 的 SWE/ordinary 任务包仍可使用；需要新 benchmark 来源或额外产物的任务使用 task package schema 2。
2. 任务包仅声明公开任务来源和需要保存的产物，不包含隐藏测试、标准答案、评分输出或私有评分路径。prepare 校验当前后端是否能保存这些材料；无法提供所需能力时在分配资源或调用模型前拒绝。
3. 正常运行实验。两种交互模式在会话结束、任务 finalize 后和工作区清理前，调用同一收集函数。捕获失败记录原因并继续必要清理，不把实验成功等同于材料完整。
4. 停止并 collect。操作者提供独立 grading plan 和所需官方材料；评分计划在验收执行前复制、校验并冻结到独立 attempt，不上传到演化运行环境。
5. 调用同一个 `experiment.py grade`，查看每个会话的技术结果、原始用户结论和二者的派生关系。该命令不启动 Harness、不调用模型、不恢复 E2B、不创建 Gitea Issue。

新功能统一使用以下调用。SWE、其他 benchmark 和自定义任务都使用 `--plan`，SWE 不需要走另一个入口：

```bash
uv run --locked --extra experiments --extra evaluation \
  python backend/scripts/experiment.py grade RUN_ID \
  --plan /path/grading-plan.json --round 6
```

这里的 plan 是评分配置，不是新的 benchmark 数据集：它说明哪些原任务使用哪个 adapter，以及 adapter 所需的官方材料在哪里。SWE 的官方 dataset 是 plan 引用的一项材料；Terminal/TUA 的测试包、NL2Repo 的任务镜像及 custom 脚本分别作为对应 adapter 的输入，不强行共用 SWE 数据集结构。

SWE plan 的配置示意如下。占位 hash 须替换为真实值，此格式已由当前 plan loader 校验：

```json
{
  "schema_version": 1,
  "materials": {
    "swe_dataset": {
      "path": "/path/official.json",
      "sha256": "<官方数据集文件的64位SHA256>"
    }
  },
  "graders": [
    {
      "adapter": "swebench",
      "contract_version": 1,
      "task_ids": ["pvlib__pvlib-python-1478"],
      "inputs": {"dataset": "swe_dataset"},
      "timeout_seconds": 1800
    }
  ]
}
```

上述配置表示：从 `RUN_ID` 的第 6 轮选取指定任务的原会话，读取已保存的完整补丁，用该官方数据集执行 SWE 验收。操作者不重新填写补丁路径、persona、Harness SHA 或原源码基线；这些事实由归档解析并校验。官方 SWE evaluator 版本保持锁定的 4.1.0，通过规则由官方 adapter 决定。

同一份 plan 可以在 `graders` 中增加 Terminal、TUA、NL2Repo 或 custom 条目，分别引用材料。多个 SWE 任务可以共享 `swe_dataset`，不需要复制 dataset 文件；通用评分入口对混合会话逐项分发，未选中项标记 not_configured。每个任务至多匹配一项，重复匹配在执行前拒绝。

旧 `--dataset`／`--dataset-sha256` 参数直接删除，不保留兼容简写或自动 plan 转换。使用旧参数或缺少 `--plan` 时，在运行验收器和写评分 attempt 前报参数错误，并指向 `grade RUN_ID --plan PATH`。迁移旧 SWE 用法时，将原 dataset 路径和 SHA 放入上述 plan 的 materials，再明确选择原 run 的 SWE task_ids；不需要更改数据集文件或重新运行实验。

`--plan` 路径支持 `--offline`：只验证可得的输入身份、合同和材料，不分配容器、不运行评分脚本、不写评分 attempt，也不把未知环境标为已就绪。缺少的材料在离线报告中明确列出。新示例与正式教程只展示 plan 调用；旧参数仅在退役说明中列出，不作为可执行示例。

### 任务来源与评分选择

task package schema 2 保留现有 `ordinary` 和 `swebench`，新增通用 `benchmark`，其中 `benchmark={suite,instance_id,revision}` 标识真实来源。ordinary 仍是明确的非 benchmark 场景，可以配置自定义验收。评分适配器由独立 plan 选择，不能通过将标准任务改成 ordinary 绕过来源校验，也不为每个新 suite 增加一种 kind。

同一评分适配器处理两种交互模式；例如同一 TinyDB 任务的 direct 和 simulated-user 交付均在同一官方环境中验收。来源标识不自动开启评分，交互模式不决定评分器，评分器也不改变任务运行环境。

### 兼容范围

| 输入 | 实施后行为 |
| --- | --- |
| 现有 schema 1 SWE 任务 | 原身份与官方验收规则保持，使用新的 --plan 评分 |
| 原 grade 的 dataset 参数 | 直接退役；改为 plan，不提供别名或自动转换 |
| 现有 ordinary 任务，未声明验收 | 可以继续运行；报告明确 not_configured，不默认通过 |
| 当前 schema 2 实验的旧完整归档 | 原生绑定校验通过且材料足够时可独立评分，不添加旧 receipt |
| schema 1 私有旧实验、缺基线或仅有截断轨迹 | 仍明确不支持或材料不足，不自动转换为当前 run |
| 新 benchmark，无注册适配器 | 可在任务环境能力允许时运行；显式评分记录 unsupported |
| 缺原运行测量的 KV 会话 | missing_artifact 或 ungradable；不能新跑负载伪装为原会话验收 |

新增评分不回填原 `accept_validity`；评分报告用 `acceptance_assessment` 展示派生关系，保留原字段和用户体感作为独立事实。

## Reference-level explanation

### 1. 分层与最小接口

执行依赖固定为：

```text
任务包的公开产物声明 → 会话公共收集 → 不可变归档
                                          ↓
原 run/round/session 绑定校验 → 评分适配器 → 独立结果与接受关系
                                 ↑
                      操作者私有 grading plan/测试材料
```

在 `auto_designer.evaluation` 内建立小型合同、注册表和结果模块。新增 adapter 只增加模块和显式注册项，不修改 direct、simulated-user、triage、OpenAgents 或 provider 的调度流程。注册表使用固定标识及合同版本；不允许配置文件任意 import Python 类，也不引入本组无需求的第三方 plugin 发现系统。

适配器只提供 `validate_inputs(request)` 和 `evaluate(request, attempt_dir)`。输入包含已经验证的 task/session 身份、只读产物集合、冻结评分配置与评分资源位置。适配器不得从在线工作区重新猜测产物，也不负责实验恢复、Session 保存、Issue 操作或主观评阅。公共层拥有原 run 绑定、评分锁、attempt 生命周期、统一报告；适配器拥有官方材料校验、环境准备、验收命令和结果解析。

官方 SWE CLI 的执行细节收至 `evaluation/adapters/swebench.py` 内的私有 `_SWEbenchRunner` 类，与公共 `SWEbenchAdapter` 共处单文件；不存在单独的 runner 模块或兼容别名。删除旧 `evaluation/swebench.py`、包级 evaluator 导出、`from_env()`、runner 的 evaluator 注入以及 `derive_accept_validity` 兼容接口；不会从宿主配置在用户会话内启动评分。历史 Session 的 objective/acceptance 字段保留用于读取既有记录，新会话仅留存交互和产物，接受关系在独立 grade 报告中判定。新报告的判定显式接收各 adapter 已验证的执行合同，不用全局 `fresh` 布尔值代替所有 benchmark 的隔离要求。

### 2. 版本化公开任务与私有评分计划

新增 `task-package-v2.json`；schema 1 的解析、字段默认值、序列化及 digest 不变，禁止为了复用解析器而改写旧冻结 package。新 package 才可添加真实 benchmark 来源与 `artifacts` 声明；它们原样进入 task catalog 和内容身份。新增 provenance kind 在模型与 catalog 校验中显式支持。

`artifacts` 使用独立版本 1 和显式导出列表。每项至少包含稳定 id、来源 `workspace`/`managed_service`、任务根内的路径或管理侧 handle、内容类型、必需性和字节上限；限制路径逃逸、重复目标、无限 glob 和非普通文件。受管服务只能引用控制器已创建、属于当前 session/attempt 的 handle，任务不能自行指定宿主绝对路径或将自己写出的文件冒充独立测量。

已有环境声明负责输入与服务部署，本组的 artifact 声明只描述验收输出。二者以 artifact id 对接，不能出现两套 source of truth。实施 0081 时应沿用 task package v2 及本组的公共收集入口；不再向旧 schema 1 隐式注入环境或评分默认字段。

私有 grading plan 版本 1 使用 `materials` 定义材料路径与 hash，使用 `graders` 定义 adapter/合同版本、task_ids、材料引用、时限和 adapter 专属配置。`task_ids` 只选择原 run 中的任务，task digest、session 和 Harness 身份从已验证归档解析并冻结到 attempt，不让操作者手抄或覆盖。每个选中任务至多一个适配器，禁止重复匹配、缺失材料引用、未知任务或与真实来源不符的映射。官方/custom 身份由 adapter 和冻结任务来源共同校验，不信任任意字符串标记。

官方材料锁定 revision 与文件 hash；必要环境由 adapter 专属配置或锁定 adapter 的固定规则确定，解析后的容器 image digest 在验收执行前冻结，禁止验收期间重新解析可变标签。custom 脚本和依赖固定 hash。数据集、测试文件和命令均由适配器专属 schema 校验，不将 SWE dataset 强制为所有 adapter 的参数。

官方二值任务保留原通过规则；连续分数任务报告原 score 及其定义。自定义阈值必须在启动评分前声明并冻结，没有二值规则时 `passed=null`，只能报告 score。阈值或测试版本改变必须形成新 attempt，报告不得将不同 plan digest 合并成相同实验条件。若评分计划是实验结束后才指定，记录该事实，不声称它是实验前预注册的标准。

评分私有文件只写入本机独立 evaluation attempt。后续 collect 明确排除 run 根下的 evaluation 目录，避免私有测试、标准答案和评分计划进入新的演化归档。只把任务运行所需的公开产物声明传给控制器，grader 文件、评分结论和受管测量的私有内容不进入用户、需求面或交付面的观测授权。评分只读本地材料和容器镜像；私有镜像登录由操作者的既有容器工具处理，不把凭证写入 plan、Session 或评分摘要。

### 3. 共用收集与生命周期

在 `evaluation/artifacts.py` 实现单一收集函数，由两种 runner 在同一生命周期边界调用。沿用现有完整 prediction 导出，不建立第二套补丁实现。新增产物 receipt 放在 `workspace_evidence.evaluation_artifacts`，数据按 session/attempt 独立落盘；receipt 记录合同版本、task digest、run/round/session/slot、试用 Harness SHA、文件 hash/bytes、采集时刻、来源与完成状态。评分绑定的是用户实际试用的 `user_sha`，不是当轮交付后的 `sealed_sha`。

必须按顺序执行：结束 Harness 和用户评阅 → 完成任务规定的 finalize → 停止或封存 companion 的测量 → 收集 → 保存 receipt → 回收资源。失败仍执行必要清理；缺文件、截断、超限、失去服务归属等分别记录，必需产物失败不得产生 complete receipt。用户自写输出与控制器采集的受管测量分开标记；KV 的可信来源要求不仅是 hash 正确，还包括管理侧身份、隔离和封存证据。

工作区文件通过现有 runtime 的读写/导出能力收集；受管服务通过 0081 的环境管理接口收集，不通过用户 shell 读取管理目录。现有后端不支持 managed_service 时 prepare 明确拒绝该声明。共用收集模块可以先实现和验证普通文件、SWE prediction；完整 KV 路径必须等待 0081 的受管环境能力，不能把一个本地 fixture 或共享可写 E2B 目录称为完整支持。

collect 校验 receipt 与实际字节，并为评分材料提供明确的收集路径。隐藏或管理侧材料保持操作者访问边界，不能因归档或 continuation 导入而自动获得需求面 observation grant。新子 run 只继承任务的公开采集声明，重新生成本轮 receipt；父轮验收记录只能引用，不能替代子轮执行。已完成恢复单元不得因缺验收材料重跑用户会话。

### 4. 首批适配器与扩展合同

| adapter | 输入及执行方式 | 真实评分所需边界 |
| --- | --- | --- |
| swebench | 基线、完整 prediction、锁定 dataset；调用现有官方 4.1.0 CLI | 官方 fresh instance 容器；读取 resolved 及官方报告分类，不以 shell 退出码判整题成功 |
| terminal-bench | 锁定 Harbor 任务包、task.toml、环境构建材料和 tests；执行官方 tests/test.sh | 遵守 verifier.environment_mode、产物来源/目标、用户及预算；读取正式 reward 与诊断，不统一猜测为 fresh |
| tua-bench | 锁定官方 task.toml/tests、环境及标准答案材料，保存任务输出 | Agent 退出后按锁定执行器语义验收；读取官方 reward/metric，不用 pytest 或进程退出码替代；不能满足环境合同则 ungradable |
| nl2repo | 锁定 test_commands/test_files/count、官方 task image 和生成仓库；遵守官方 post_process_task 的覆盖及解析语义 | 从生成副本移除官方声明的测试及包配置后覆盖官方环境，保留原测试和通过率；不把 Agent 自测或任意阈值称为官方二值成功 |
| custom | 操作者固定版本的独立脚本、输入和通过规则 | 在受限验收容器执行 argv；容器隔离是本系统合同，结果标记 custom，不存在统一的“官方 custom”评分器 |

上述表格是实施和验收必须满足的对齐要求，不能作为已完成真实评分验证或整个 benchmark 已支持的声明。首批非 SWE 对齐样本限定为下列固定任务来源；adapter 标识不是“所有历史/最新版本都兼容”的承诺。实现时锁定实际验收执行器及其依赖版本，不能只固定任务仓库而任意选择当前 Harbor。新增任务只有其元数据、环境与评分语义通过验证后才列入支持清单；未知版本或未覆盖的执行模式明确 unsupported。

| 来源 | 固定 revision / 版本 | 首批验证范围 |
| --- | --- | --- |
| SWE-bench 官方 evaluator | 4.1.0 | 当前已支持的 SWE 官方实例及其数据集身份 |
| harbor-framework/terminal-bench-1 | 452bf305c6daa62fc59061d22133a7cbc7c1572e | production-planning、kv-live-surgery 的 Harbor 格式任务 |
| facebookresearch/TUA-Bench | 3497fd320abcafaf4797424192c891a593fd7964 | 010-pivot-product-revenue |
| multimodal-art-projection/NL2RepoBench | 781a1da1ee41fb8edb0bed22f586d69111610edf | tinydb |

Terminal 的生产计划任务显式使用 separate verifier，并声明三个 SQL 产物；官方 test.sh 恢复干净数据库、重放 SQL 后执行测试及写 reward。KV 也使用 separate verifier，但产物来自 loadgen 服务：results.json、measure.log 和诊断 loadgen.log，应按官方路径重新放入验收环境；有效测量下的六项 gate 和 5 倍门槛不改写。缺记录、无效 baseline 等官方前置失败保留原 reward/日志，同时在本系统单列证据或环境问题，不能只看 reward=0 就说代码失败。[生产计划合同](https://github.com/harbor-framework/terminal-bench-1/blob/452bf305c6daa62fc59061d22133a7cbc7c1572e/tasks/production-planning/task.toml)、[官方重放与 reward](https://github.com/harbor-framework/terminal-bench-1/blob/452bf305c6daa62fc59061d22133a7cbc7c1572e/tasks/production-planning/tests/test.sh)、[KV 产物合同](https://github.com/harbor-framework/terminal-bench-1/blob/452bf305c6daa62fc59061d22133a7cbc7c1572e/tasks/kv-live-surgery/task.toml)、[KV 官方 gate](https://github.com/harbor-framework/terminal-bench-1/blob/452bf305c6daa62fc59061d22133a7cbc7c1572e/tasks/kv-live-surgery/tests/test_score.py)。

TUA 首批 Excel 的官方脚本运行 test_outputs.py 并将数值写入 reward.txt；该任务的 compare_table 给出 0/1，但不能推导其他 TUA 任务均是二值任务。验收保留官方 metric 的组合规则和原 score，不运行 --sanity/oracle 来修复提交。标准答案、sidecar 及测试内下载的外部文件也须记录内容 hash 并冻结；仅固定 tests revision 不足以锁定远程 URL 内容。[官方验收脚本](https://github.com/facebookresearch/TUA-Bench/blob/3497fd320abcafaf4797424192c891a593fd7964/tasks/010-pivot-product-revenue/tests/test.sh)、[官方 metric 和材料引用](https://github.com/facebookresearch/TUA-Bench/blob/3497fd320abcafaf4797424192c891a593fd7964/tasks/010-pivot-product-revenue/tests/test_outputs.py)。

NL2Repo 首批沿用官方 post_processor 的包配置清理、测试路径清理、镜像覆盖、命令执行和输出解析；只修改评分用生成副本，不改原归档。官方解析使用固定测试数作分母，success_rate=min(passed/total,1)，不是一条现成的整题通过规则；不得另写更方便的 pytest 统计公式冒充官方。未提供正式二值规则时 passed=null；操作者可在 plan 声明派生阈值，但须以 operator policy 单列，不能标为官方成功。[官方 post_processor](https://github.com/multimodal-art-projection/NL2RepoBench/blob/781a1da1ee41fb8edb0bed22f586d69111610edf/openhands/post_processor.py)。

Terminal adapter 根据任务声明选择 verifier mode；缺少所需环境或原测量时报告不可评分，不自行降级。生产计划按官方合同在干净数据库重放提交 SQL；数据库快照不自动替代 SQL。KV verifier 消费原运行独立负载生成器的记录，不启动新的负载以补造原测量。TUA 若只能在原任务环境验收，则其 verifier-only 材料应在用户进程退出后通过环境受管操作进入、结果作为独立验收 receipt 封存；不把这种必须在线捕获的行为塞入通用 persona runner。未提供此能力的当前 run 只能事后评分可完整重建环境的任务。

NL2Repo 的 grader 包通常只包含文件列表、命令和测试数；官方测试本体来自固定 task image，不能认为仅有这三个文本文件就已具备完整测试。通过率与二值成功均使用固定评分规则，不把任意 pytest 子集通过解释为官方全通过。

不复制 `evaluation/harness_bench` 的计划、交互或调度器。已有 budget/官方元数据解析可以通过窄函数复用；能复用的评分规则只有一份，独立 Harness 评测以后可调用相同 adapter，但这次不要求把两套入口或 manifest 合并。

### 5. 统一结果与接受关系

每个结果包含 adapter/版本、plan digest、输入与输出 hash、执行环境身份、原始报告路径、时限、状态、score/定义、passed、错误原因及执行合同证据。attempt 同时保留当前评分代码各模块的内容 hash，与原实验 controller_sha 分开，避免把实验代码版本当成事后评分器版本。执行合同至少区分 `fresh_official_instance`、`agent_stopped_task_environment`、`trusted_recorded_measurement` 和 `isolated_custom_verifier`，由 adapter 校验，不接受调用方随意填写一个 true 值。

| 状态 | 含义 | passed |
| --- | --- | --- |
| completed | 正式验收成功运行并给出有效结论 | true/false；仅连续评分且无二值规则时 null |
| not_configured / unsupported | 未指定规则／无相应 adapter | null |
| missing_artifact / ungradable | 缺产物／身份、来源或环境不能满足合同 | null |
| unavailable / crashed / timed_out | 验收基础设施、解析或运行失败 | null |
| not_evaluated | 官方 evaluator 明确跳过，例如 SWE 空预测 | null |

只在 completed、合同验证通过且原始报告有效时把 passed=false 计为正常任务失败；其他状态单列，不能混入成功或失败分母。原有 SWE JSON 输出保留原含义与字段；旧 evaluator 内部以 passed=false 表示故障时，只在新公共结果中根据 status 归一化为 null，保留原始输出，不改旧调用行为。

上述分母仅指本系统“已有效验收会话”的诊断统计，不替代 benchmark 官方汇总。官方报告的任务总数、空预测、未完成、错误及分母定义原样保留；不得删除这些项后将一个更高的条件通过率称为官方 resolved rate。报告将 official metrics 与本系统 coverage/status/acceptance 诊断分开展示。评分脚本自身规定的异常转零仍保留为原始官方输出；只有可核验的外围环境或材料故障才附加本系统分类，不改写官方脚本的结果规则。[SWE 4.1.0 官方汇总](https://github.com/SWE-bench/SWE-bench/blob/v4.1.0/swebench/harness/reporting.py)。

`acceptance_assessment` 只写在新评分报告。模拟交互读取原 accepted 结论；direct 读取原 review_verdict=accept，要求 review_status 已完成；不依据 feeling、Harness 自述或代码 diff 推测用户接受。只有有效交互、用户接受、正式 passed=true 和执行合同验证通过时派生 valid_accept；客观失败或请求超时/崩溃为 false_accept；未完成技术验收或没有二值结论为 unverified_accept；未接受为 not_applicable。该关系不覆盖原 Session.accept_validity。

### 6. 公开命令与归档绑定

`experiment/grading.py` 保留 0075 的归档完整性、RecoveryIdentity、轮次 seal、session provenance、基线与预测 hash、当前 generation 和锁校验；提取通用输入校验后才进行 adapter 分发，不允许新模式绕过其中任一检查。`--plan` 是所有 adapter 的唯一配置方式，CLI 已删除旧 dataset 参数，不设置转换逻辑；公共 grade 函数也改为接收评分 plan，dataset 只作为 SWE adapter 的材料。固定归档、任务选择、官方 dataset 与 evaluator 相同时，SWE 技术结论仍遵守原官方规则；这是评分行为回归，不是旧 CLI 兼容。

每次评分使用独立 `run_dir/evaluation/<attempt>/`，记录 plan snapshot/材料 manifest、逐 session 官方日志和归一化结果、summary。实验与评分的完成状态分开；评分中断不导致实验失败，不覆盖已有评分，下一次调用创建新 attempt。batch 的子 run 仍分别调用相同单 run 命令。新 task schema 和评分记录不能改变现有 continuation/恢复身份；冻结控制器不会因宿主升级而被自动替换。

### 7. 任务分解与验收

| Task | 实现范围 | 主要验证 |
| --- | --- | --- |
| T1 | 评分合同、注册与公共结果 | 未知版本拒绝，故障不计失败，不以 fresh 一刀切 |
| T2 | schema 2 task 来源与公开采集声明 | schema 1 身份不变，来源真实，后端能力在运行前检查 |
| T3 | 两种会话共用收集、归档及续跑边界 | 相同 receipt 合同，清理前持久化，来源/slot/attempt 不串，缺证据不升级 |
| T4 | 五类评分 adapter 与 SWE 官方实现复用 | 官方规则固定，custom 不冒充官方，KV/TUA 缺运行材料时明确不可评分 |
| T5 | 原 run 绑定、唯一 plan CLI 与独立报告 | 旧参数拒绝，SWE 新 plan 正常评分，原字节不变，无模型/provider/Issue 调用 |
| T6 | 双语文档、真实验收与完整回归 | 真实官方正负案例、环境失败与证据缺失分类，当前支持范围逐项报告 |

组内 DAG 为 T1 → T2 → T3，T1 → T4，T2/T3/T4 → T5 → T6。T3 的 managed_service 支路依赖 0081/T3；T6 的完整 E2B/受管测量实测依赖 0081/T4。这些前置尚未完成时，可以实现已具备的文件收集和事后 adapter，但不得将整个 T3/T6 标 done 或宣传完整 N8 公开路径。各 Task 的唯一文件归属以 frontmatter 为准；适配器、运行时和评分绑定各有单一维护位置。

生产验收脚本为 `backend/scripts/e2e-spec-0083-session-grading.sh`。离线回归覆盖 direct/simulated 的等价采集、超限/篡改/重复/清理竞态、恢复幂等、不同 generation、私有材料访问边界、评分结果分类、SWE plan 的官方行为，以及旧 dataset 参数和缺 plan 的拒绝。验收环境实现对单个材料/产物及 tar 展开总字节设 256 MiB 边界、tar 文件数 10000 和 verifier 日志 16 MiB 边界；这些是当前容器执行器的资源限制，不是 benchmark 官方限制，也不替代任务包显式 max_bytes。超限明确拒绝或失败，不截断后判成功。真实测试调用固定官方 grader，至少覆盖 SWE、生产计划、Excel、TinyDB 的可核验正负控制，以及一个自定义文件任务；测试控制材料只在验收边界使用，不宣称来自 Harness 的真实任务成功。KV 只有完成受管负载原运行记录采集后才做端到端实测，普通 JSON fixture 测试不替代它。模型驱动任务执行、评分器真实执行、离线替身验证分别报告。

实现阶段运行相关 pytest、ruff、spec validate/render/graph 和现有 0075/continuation/两后端回归。真实所需材料或环境缺失时保留 pending/阻塞说明，不伪造官方通过、不重写 grader，也不擅自重启历史实验来补证据。

## Drawbacks

非补丁产物会增加存储，工作簿、数据库和服务测量的保留预算需明确；必需材料超限会使会话不可验收。测试镜像与环境锁会增加可选依赖和下载成本，不应让普通无验收任务被迫安装所有 benchmark 环境。

私有 grader 与公开产物之间增加一个接口，managed_service 和原环境验收需要真实运行时支持。0081 尚未实现，因此本组不能单独交付完整 N8 场景运行及可信 KV 原测量采集。退役旧 CLI 会要求已有脚本和调用者改用 plan；更新仓内文档、示例和验收脚本是本组必要工作，历史冻结记录保持原样。

## Rationale and alternatives

选择“统一产物合同 + 独立评分计划 + 小型适配器”，因为交互、运行环境和评分规则分别变化。评分与演化隔离，既保留真实用户结论，又能在材料完整时独立复核；官方任务特有的环境和规则由专属模块维护。

备选一是在 direct runner 复制 SWE evaluate 调用，再为每个 benchmark 加 if/else。它不能保存不同交付物，还会把清理、超时、配置与验收耦合进两条会话流程，后续每增加任务都需要修改 runner，因此不采用。

备选二是将所有题都包装成 SWE 补丁或宿主 pytest。它丢失 Excel 输出、数据库重放和 KV 原测量，改变官方规则，无法支持正确结果归因，因此不采用。

备选三是把 0065 Harness 评测调度器整个嵌入自进化实验。它会重新运行任务，评测指定 Harness 的能力，不是在验收已经发生的用户会话；合并还会引入第二套 run/provider 生命周期，因此不采用。只复用纯元数据解析及评分适配。

备选四是先实现任意动态 plugin 平台和自动策略生成。当前只需显式 adapter 注册及版本化数据，没有第三方安装和远程代码加载需求，因此不采用。

## Prior art

0051 将用户接受与新鲜 SWE 官方执行结果并列保存，定义假接受与未验收接受；本组保留其双结论原则和内部 evaluator 接口，不保留旧公开 grade 参数。0056 明确目标账本、Persona 判断与技术结果不能相互覆盖，本组在独立报告中遵循同一原则。

0075 已提供严格归档绑定、完整预测、官方 SWE 执行和事后只读评分，作为本组直接基础。0065 的独立 Harness 评测已有官方预算和 grader metadata 解析，但不提供当前实验会话的产物绑定。本组不重建这两套已有能力。

0081 计划提供任务环境的就绪、服务归属、finalize、受管 companion 和输出收集；本组仅定义其验收侧消费合同，完整受管路径以对应前置实现和实测为准。

## Unresolved questions

当前方案中的接口、兼容策略与首批范围已审阅批准，不留由实现自行决定的架构分叉。0081 的任务环境还未实施是明确前置事实，不是可以静默跳过的开放问题；首批 adapter 运行环境或材料不足属于实施验收限制，应在验证报告中逐项记录。

## Future possibilities

后续可让独立 Harness 评测 executor 复用同一 adapter，并增加更多 suite 或自定义验收模块。批量评分可以调度既有单 run 命令，无须引入新评分生命周期。可信测量记录和官方产物齐备后，可以做不同轮次、交互模式和 Harness 版本的配对报告，但必须保持各评分计划与任务来源可比，不能从用户体感直接推出技术提升。
