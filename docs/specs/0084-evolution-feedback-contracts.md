---
number: "0084"
title: 自主与交互演化的反馈、执行合同及逐轮验收
issue: 0
slug: evolution-feedback-contracts
summary: 校准双模式反馈，贯穿执行条件，修正 Seed 基础运行边界并在每轮反馈前独立验收；保留跨轮纠错，不增加候选淘汰门。
tasks:
  - id: T1
    title: 规范反馈、执行合同与缺测读模型
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/models.py
      - backend/auto_designer/execution_contract.py
      - backend/auto_designer/user/session_store.py
      - backend/tests/web/test_api.py
      - backend/auto_designer/web/api.py
      - backend/auto_designer/loop/metrics.py
      - backend/auto_designer/evaluation/acceptance.py
      - backend/tests/user/test_session_store.py
      - backend/tests/loop/test_metrics.py
      - backend/tests/evaluation/test_grading_contracts.py
      - backend/tests/test_experiment_grading_compatibility.py
      - backend/tests/test_execution_contract.py
      - frontend/src/types.ts
      - frontend/src/components/detail/SessionDetail.tsx
      - frontend/src/components/detail/SessionDetail.test.tsx
      - frontend/src/components/Charts.tsx
    scope: 建立单一规范反馈与执行合同，评分可空且带来源，贯穿索引、统计、接受关系和界面。
    acceptance: 四轴互不替代；严格整数评分、缺测不补分；旧记录只读；缺测会话仍可取证，前端不空引用。
  - id: T2
    title: 双模式评阅、产物归属与报告恢复
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/loop/sim_user.py
      - backend/auto_designer/user/sim/loop.py
      - backend/auto_designer/user/sim/feeling.py
      - backend/auto_designer/user/sim/prompt.py
      - backend/auto_designer/user/sim/persona_client.py
      - backend/auto_designer/user/sim/clauses.py
      - backend/auto_designer/user/sim/runtime.py
      - backend/tests/user/test_direct_session.py
      - backend/tests/loop/test_sim_user.py
      - backend/tests/user/sim/test_feeling.py
      - backend/tests/user/sim/test_loop.py
      - backend/tests/user/sim/test_prompt.py
      - backend/tests/user/sim/test_workspace.py
      - backend/tests/user/sim/test_feedback.py
      - backend/tests/user/sim/test_persona_client_agentic.py
      - backend/tests/user/sim/test_inner_prompt.py
      - backend/tests/user/sim/test_persona_usage.py
      - backend/tests/test_feedback_runtime_integrity.py
      - backend/tests/test_experiment_grading_artifact_lifecycle.py
      - backend/tests/user/test_prediction_artifacts.py
      - backend/auto_designer/user/sim/tools.py
      - backend/auto_designer/user/sim/sandbox.py
      - backend/auto_designer/user/sim/sources/docker_seed.py
      - backend/tests/user/sim/test_docker_seed_source.py
    scope: 保留交互用户按persona核实、运行测试与写入的能力；共用量表与规范反馈，终态先冻结产物再只读评阅；按冻结报告计划幂等发布0到多票。
    acceptance: 交互judge/final-check可按能力读跑写且保留用户贡献轨迹；仅终态Reviewer禁写与shell；成功零票、归因不明不造结论，恢复不重复Actor/Reviewer及Issue，冻结后评分字节不变。
  - id: T3
    title: Seed请求合同、预算与容量边界
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/harness/budget.py
      - backend/auto_designer/harness/launcher.py
      - backend/auto_designer/experiment/config.py
      - backend/auto_designer/experiment/context.py
      - backend/auto_designer/experiment/workload.py
      - backend/auto_designer/experiment/model_limits.py
      - backend/auto_designer/experiment/schemas/experiment-v2.json
      - backend/auto_designer/experiment/schemas/task-package-v2.json
      - backend/harness_template/entry.py
      - backend/harness_template/agent.yaml
      - backend/harness_template/agents/main.md
      - backend/harness_template/META_SPEC.md
      - backend/auto_designer/harness/INTERFACE.md
      - backend/tests/harness/test_seed_terminal_status.py
      - backend/tests/harness/test_seed_execution_contract.py
      - backend/tests/harness/test_launcher_budget.py
      - backend/tests/test_experiment_config_v2.py
      - backend/tests/test_experiment_workload.py
      - backend/tests/test_experiment_model_limits.py
      - backend/harness_template/.env.example
      - backend/harness_template/params.yaml
      - backend/tests/harness/test_launcher.py
      - backend/tests/harness/test_interface.py
      - backend/tests/harness/test_template_entry.py
    scope: 冻结任务总预算和输入可用性，修队列字段与任务期限、终态解码；统一容量静态校验和确定性超限分类。
    acceptance: 7200秒无隐藏1800截断；control不续租；宽限不解题；缺状态不成功；容量冲突拒绝且不破坏原生异步取消，不新增恢复策略。
  - id: T4
    title: 需求与交付链保留可信使用条件
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
      - backend/auto_designer/demand/evidence_contract.py
      - backend/auto_designer/demand/session_timeline.py
      - backend/auto_designer/demand/agent_runtime.py
      - backend/auto_designer/demand/triage.py
      - backend/auto_designer/demand/divergent.py
      - backend/auto_designer/demand/synthesizer.py
      - backend/auto_designer/demand/grouped_synthesizer.py
      - backend/auto_designer/demand/owner.py
      - backend/auto_designer/demand/proposal_view.py
      - backend/auto_designer/demand/delivery_evidence.py
      - backend/agent_defs/triage_agent/systemprompt.md
      - backend/agent_defs/divergent_pm/systemprompt.md
      - backend/agent_defs/synthesizer/systemprompt.md
      - backend/agent_defs/owner/systemprompt.md
      - backend/tests/demand/test_evidence_contract.py
      - backend/tests/demand/test_proposal_view.py
      - backend/tests/demand/test_triage.py
      - backend/tests/demand/test_divergent_gate.py
      - backend/tests/demand/test_owner.py
      - backend/tests/demand/test_grouped_synthesizer.py
      - backend/tests/demand/test_delivery_evidence.py
    scope: 使用现有grants关联执行合同与安全验收摘要，贯穿角色投影、提案聚合、准入及交付发布，不靠模型复述。
    acceptance: 裁剪和合并不丢输入条件；多个来源保留适用范围；归因不明不抹去未交付；无隐藏grader泄露，新旧reader不静默错配。
  - id: T5
    title: 逐轮独立验收与外部评分端
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/evaluation/service.py
      - backend/auto_designer/evaluation/contracts.py
      - backend/auto_designer/evaluation/adapters/custom.py
      - backend/auto_designer/evaluation/adapters/swebench.py
      - backend/auto_designer/evaluation/adapters/terminal_bench.py
      - backend/auto_designer/evaluation/adapters/tua_bench.py
      - backend/auto_designer/evaluation/adapters/nl2repo.py
      - backend/auto_designer/evaluation/artifacts.py
      - backend/auto_designer/experiment/assessment_worker.py
      - backend/auto_designer/loop/round_assessment.py
      - backend/auto_designer/experiment/grading.py
      - backend/auto_designer/experiment/continuation/evidence.py
      - backend/auto_designer/experiment/grading_inputs.py
      - backend/auto_designer/experiment/materials.py
      - backend/auto_designer/experiment/runtime.py
      - backend/auto_designer/experiment/cli.py
      - backend/auto_designer/experiment/controllers/unified.py
      - backend/auto_designer/experiment/collection.py
      - backend/auto_designer/experiment/manifest.py
      - backend/auto_designer/experiment/backends/base.py
      - backend/auto_designer/experiment/backends/local.py
      - backend/auto_designer/experiment/backends/e2b.py
      - backend/auto_designer/loop/orchestrator.py
      - backend/auto_designer/loop/feedback_pipeline.py
      - backend/auto_designer/loop/recovery.py
      - backend/tests/test_experiment_round_grading.py
      - backend/tests/test_assessment_plan_preflight.py
      - backend/tests/test_experiment_continuation_evidence.py
      - backend/tests/test_unified_assessment_recovery.py
      - backend/tests/test_assessment_receipt_recovery.py
      - backend/tests/test_experiment_local_backend.py
      - backend/tests/test_experiment_assessment_worker.py
      - backend/tests/test_experiment_grading.py
      - backend/tests/test_experiment_grading_plan.py
      - backend/tests/loop/test_feedback_pipeline.py
      - backend/tests/loop/test_recovery.py
      - backend/tests/test_experiment_engine.py
      - backend/tests/test_experiment_lifecycle_v2.py
      - pyproject.toml
      - uv.lock
    scope: 抽取共同评分服务，增加封存会话请求、可信外部worker及每轮评分恢复；私有plan不进入任务侧。
    acceptance: local/E2B共用请求；末轮亦验收；失败不淘汰候选；缺worker显示等待且可恢复；线上/事后同结果，旧grade校验不放宽，故障不记0。
  - id: T6
    title: 联合验收、配置示例与双语说明
    status: in-progress
    priority: P1
    tags: []
    depends-on:
      - T4
      - T5
    relates-to: []
    parallel: false
    files:
      - backend/scripts/e2e-spec-0084-evolution-feedback.sh
      - backend/scripts/check_observation_contract.py
      - backend/scripts/check_experiment_repository.py
      - backend/tests/test_evolution_feedback_e2e.py
      - backend/tests/test_experiment_public_examples.py
      - backend/tests/test_experiment_repository.py
      - release/compatibility.json
      - .github/workflows/ci.yml
      - examples/experiments/evolution-feedback-local.json
      - examples/experiments/evolution-feedback-e2b.json
      - docs/tutorials/evolution-feedback.md
      - docs/tutorials/evolution-feedback.zh-CN.md
      - docs/validation/evolution-feedback-contracts.md
      - docs/ARCHITECTURE.md
      - docs/specs/0048-user-sim-final-check-convergence.md
      - docs/CONFIGURATION.md
      - docs/CONFIGURATION.zh-CN.md
      - docs/QUICKSTART.md
      - docs/QUICKSTART.zh-CN.md
      - CLAUDE.md
      - backend/tests/fixtures/execution_evidence_contract.json
      - tools/dev/delivery/__init__.py
      - tools/dev/delivery/run_openagents_validation.py
      - backend/tests/test_run_openagents_validation.py
      - backend/auto_designer/experiment/controllers/runtime.py
      - tools/dev/delivery/prepare_openagents_from_summary.py
      - tools/dev/delivery/prepare_openagents_validation.py
      - backend/tests/test_prepare_openagents_from_summary.py
      - backend/tests/test_prepare_openagents_validation.py
    scope: 验证真实reader、模型边界与两后端评分canary，说明支持范围、worker依赖、历史只读及研究指标。
    acceptance: 离线合同和真实执行分别留证；真实正负控制、worker断连恢复、零跟进Direct均通过；未支持受管任务明确拒绝；全部Task未经实测不得标done。
---

# 0084 · 自主与交互演化的反馈、执行合同及逐轮验收

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

修正演化实验的测量和运行前提，使同一份 Harness 产物既能自主处理明确目标，也能接受用户后续控制。改动分为四项：

| 项目 | 本次修正 | 验收结果 |
| --- | --- | --- |
| 1. 反馈测量 | 将任务判断、体验、归因和改进机会分开；两种交互共用评分量表；终态评审只读 | 完成却未评分不再自动变成低分或中等分，成功会话允许零 Issue |
| 2. 执行合同贯穿 | 将后续输入可用性、目标、预算和交付前提作为可信结构化事实传到所有需求与交付角色 | Direct 的恢复方案不能依赖不存在的第二条用户消息 |
| 3. Seed 基础边界 | 消费结构化预算和输入条件，区分任务总期限与消息活动边界，补齐终态解码及模型容量预检 | 不靠自然语言猜预算，不因控制消息续租，不把缺失状态默认为成功 |
| 4. 逐轮独立验收 | 冻结实际 Actor 产物，在需求生成前通过既有评分适配器验收，并校验实验材料一致性 | 每轮提供可核验的任务结果，基础设施故障与未验收不记作任务失败 |

保留“用户试用 → 反馈 → 需求与交付 → 下一轮纠错”的流程。任务不通过仍允许进入后续轮次发现和修复；本组不增加候选淘汰、自动回滚或发布前能力门禁，不给最终演化产物打评测专用补丁，不预先实现完整自动续跑、上下文压缩或看门狗策略。

设计基线为 auto-designer `5cccb3642c04bf278ae44e5dba9691dfb68ddf11`。本文及配套 OpenAgents 合同设计已获审阅批准，按任务验收记录更新实施状态；仅运行开发验收 canary，不重启已归档或暂停的大规模实验。

## Motivation

一次全 Direct 六轮实验的 48 个会话中，有 42 个 feeling 为 1，31 个评审 accept，其中 26 个同时为 accept 和 1 分，正式客观任务验收为零。它们不足以证明实际任务成功率：Direct 提示词示例固定 `score:1`，accept 又混合了“任务完成”和“无需归因成 Harness bug”。有会话承认未交付，却以“诚实报告失败、用户下一条消息再处理”为由 accept。

新 main 仍可定位到以下问题，而不是仅依赖历史实验推测：

- `loop/sim_user.py::make_direct_run_session_fn` 包含固定评分示例、评分缺失回落 3、无条件建立 bug Issue，并在 Reviewer 使用工作区之后才最终采集产物。
- `user/sim/loop.py` 在评阅非法时构造 2 分或派生分；适配器还会将派生分写入正式 feeling。缺测不是评分。
- `demand/evidence_contract.py::build_l1_summary` 未固定保留输入可用性等执行前提；`proposal_view.py` 的正文会截断，属性标签也不能承担合同传递。
- Launcher 已发送 `budget_seconds`，Seed 的队列仅保存 text/queued；Launcher 在新消息和 control 时重置计时，读取任务 reply 时仍可能将缺失 status 默认 completed。
- 公开实验 schema 将 `evaluation.official_grading` 固定为 false。现有事后评分必须等实验终态及完整归档，不能直接在运行中调用。其适配器依赖 Docker，E2B 控制器没有相同执行能力。

提示文件加载、NexAU provider SDK 兼容、Seed 的完成工具判定、源码 SHA 绑定、Direct 执行证据、分诊提交与恢复已在基线修复，本组保留其回归，不重复重写。对演化后早停的观察只能支持具体控制路径分析，不能在不同 Seed、模型后端和资源条件下直接推导总体因果。

问题的关键是错误设计没有收到稳定、忠实的纠错信号。工程测试可以证明代码符合一个 Spec，但 Spec 若已把“等待用户继续”当成无人任务的恢复方式，局部实现正确也不能证明原任务完成。因此先修研究仪器与合同，再观察后续轮次是否自然纠正策略。

## Guide-level explanation

### 使用与结果阅读

操作者仍通过 `backend/scripts/experiment.py` 准备并启动实验。任务包声明公开目标、交付物及执行预算，交互计划选择 direct 或 simulated_user；私有 grading plan 独立提供，不能放进任务目录或发送给角色。

新增以下配置片段，未声明逐轮验收的现有配置继续明确标为未配置验收，不补默认成功率：

```json
{
  "evaluation": {
    "session_grading": {
      "plan_sha256": "<64 位摘要>",
      "worker_key_sha256": "<评分机 Ed25519 验证公钥的摘要>",
      "runner": "external"
    }
  }
}
```

`check/prepare` 在开启逐轮验收时接收 `--grading-plan /private/plan.json` 与 `--grading-worker-public-key /path/worker.pub`，冻结 plan 与验签身份并逐任务检查覆盖、产物和执行能力。已有 `official_grading:false` 配置保持原身份；新旧形状互斥，不引入另一套评分语义。完整私有 plan 只保存在可信评分端，控制器只知道摘要、覆盖与安全合同，公钥不是秘密。

可信评分机运行拟新增的命令：

```bash
uv run --locked --extra experiments --extra evaluation \
  python backend/scripts/experiment.py assessment-worker RUN_ID \
  --plan /private/plan.json --signing-key /private/worker.key --follow
```

该命令只领取已封存的评分请求、调用既有 adapter 并回传安全收据，不启动或重跑 Harness，不承担新的实验调度器职责。local 与 E2B 使用同一请求格式；评分机需要 Docker，E2B 不运行嵌套 Docker。评分进程可部署在长期运行的操作者服务器；若只在个人电脑运行，关机会暂停此评分端，实验将显示等待验收，不能宣称脱离该机器仍可全流程推进。

每轮会话先结束 Actor 并封存产物，Reviewer 只能读取快照。随后独立评分完成，安全摘要进入需求阶段；最后一轮即使不再交付，也执行采集、评阅和验收。正式结果不回填修改原 Session。

结果按轴显示：

- 用户任务判断：fulfilled、unfulfilled 或 unknown，附判断来源和依据。
- 体验：有效的 1–4 自评分或缺测原因；1=bad、2=poor、3=ok、4=good。派生分单列，不能替代自评分。
- 组件归因：有证据等级和不确定性的主张，不自动等于已确认 bug。
- 改进机会：零到多项建议、能力缺口或待调查问题。
- 独立验收：沿用评分服务的状态、原始 metric、passed 和执行合同。它与用户判断并列，不由 Reviewer 填写。

例如“API 停滞后诚实退出、没有交付”：任务判断可为 unfulfilled，诚实性可获正面体验评价，根因可暂不确定，也可提出恢复能力探索。不能因为诚实就记为任务完成，也不能因为任务失败就断言 Harness 有已证实代码缺陷。

### 保留自主与交互的共同核心

Harness 只收到通用运行事实，例如“本任务后续用户输入不可用”“剩余预算 7200 秒”，不收到 benchmark 名、评分答案、轮次或实验组名称。有人时后续消息是控制或补充信息；无人时不能假设会收到继续指令。缺必要授权、缺关键事实、不可恢复错误或总预算耗尽仍可诚实结束，不要求永远执行。

本组修正的是合同和测量，不承诺提高任意模型的任务分数。不会给 Direct 配一个帮助解题的用户，不强制规定应采用何种自动恢复算法。

## Reference-level explanation

### 1. 单一反馈事实源与缺测

在 `models.py` 定义有版本的规范化 `Session.feedback`，不要增加多套互相竞争的 accept/result/pass。其四个分量为 `task_assessment`、`experience`、`attribution`、`opportunities`。每个分量带来源、证据引用和有效性；用户任务判断不具有官方验收权威。

`experience` 的状态区分 rated、missing、invalid、unavailable，score 为严格整数 1–4 或 null；拒绝布尔值、浮点截断和字符串数字。Direct 与模拟交互复用同一量表和校验函数。协议失败、模型调用失败、缺字段均保存真实原因，不能默认 1、2 或 3。行为推导的 feeling 可保留在独立 derived 诊断中，不进入自评分均值。

`Session.feeling` 改为可空展示投影，由新反馈一致生成；旧记录按其已有字段只读解释，不在加载时重写。SessionStore 的索引、重建、Metrics、需求趋势、控制器 live 元数据以及前端类型和详情同步支持缺测。统计同时给出有效样本数和缺测数，按交互条件分组，不用一个均分抵消另一种能力的退化。

正式验收继续使用既有评分结果模型与独立 receipt。接受关系派生读取明确的任务接受判断；新记录不再以 Direct 的“无需提 bug”当作用户确认完成。旧含混 accept 标明旧来源和未核实，不倒填历史成功。Reviewer 服务失败不应单独阻止可信 Actor 产物接受客观评分；执行协议或产物本身不可信则仍单独拒绝评分。

### 2. 冻结 Actor 输出、只读评阅和报告发布

会话顺序固定为：

```text
Actor 结束 → 停止并确认不再写入 → finalize → 冻结完整 patch/声明产物及 hash
          → 只读终态评阅 → 保存 Session 与报告发布计划 → 幂等发布 0..n 个报告
```

两种 runner 共用已有产物采集器，不在 Direct 里复制一套收集逻辑。用于验收的字节必须来自 Actor 结束时的封存；Reviewer 不能在评阅后重新导出补丁并把自身修改算入交付。

为 Direct 明确注册终态评阅阶段。模拟交互中的 `main_final_check` 发生在用户决定接受或继续之前，属于仍在使用工具的模拟用户：保持实时工作区和persona的工具能力，不提前关闭Actor。普通main/waiting judge同样按D1暴露能力，competent/expert可写测试、运行命令，或按协作/接手倾向修改代码；是否采取这些操作由persona决定，不能强制每个用户自己完成任务。开场不开放私有工具，intent/rejudge/reintent/act继续无工具；final-check仍每周期最多一次、最多四次工具调用且不在该检查中发布报告。

只有会话真正结束后，才停止Actor及写进程、冻结协作工作区产物，终态Reviewer只获得快照read/list/diff，不暴露write_file、任意shell、实时工作区或私有评分材料。独立grader承担正式测试。交互用户与终态Reviewer不共用权限政策；终态如需自由执行检查，仍须另行设计隔离副本。交互中的用户测试、命令、写入、补充信息及授权保存在sim_trace；冻结产物可能包含用户贡献，独立验收衡量这一最终任务产物，不自动等于Harness独立求解成绩。现有轨迹提供操作依据，但不宣称已完成逐文件或逐行的完整贡献归因。

用户模型客户端对GLM的显式不关闭思考路径同时识别provider/model、glm-5.3与glm53等部署名，实际模型ID原样发送；未配置reasoning_effort时沿用服务端默认，不因部署别名重新注入enable_thinking=false。此名称兼容不推断上下文容量，也不改变32768输出预算。

Direct 不再无条件建 bug。可靠成功且无问题时零票；非阻塞建议以 feature/建议表述；任务失败且归因未知可形成诊断或通用能力机会报告，正文明确不是已确认根因。Triage 仍自主调查，不把客观失败自动变成已批准需求。成功样本保留为后续能力对照证据，不为此创建第二套任务池管理器。

在调用 tracker 前持久化确定的发布计划，包含稳定 operation key 及完整 IssueDraft，或其不可变载荷引用和 hash；仅保存正文摘要不足以恢复。逐票发布进度落在独立 receipt，全部完成后才一次性按 SessionStore 现有规则附加 issue_refs，不逐票改写 Session。恢复只重试未完成发布，不重新调用 Actor 或 Reviewer，不重新生成正文。零报告计划也显式完成。沿用 `create_issue_once` 和允许的 handoff enrichment，不为回填评分放宽 Session 不可变性。

### 3. 可信执行合同与角色传递

以一个纯数据模块 `execution_contract.py` 定义合同及安全投影；实验配置、Launcher、Session 与需求面复用，模块不依赖 provider、模型客户端或 grader。稳定部分至少包含：

| 字段 | 来源与用途 |
| --- | --- |
| task_id / task_digest / contract_id | 冻结任务与使用条件身份，不由模型生成 |
| original_goal_ref / public_deliverables / public_acceptance | 公开目标与交付前提；保留可读取的引用，不混入隐藏测试 |
| followup_input | unavailable、possible 或 unknown；不能将 possible 当作必定回复 |
| task_budget_seconds / budget_source | 总活动预算及来源，区别官方元数据与操作者实验定额 |
| user_assistance | 控制、授权、事实、偏好及解题贡献等已发生帮助的引用，不凭猜测补造 |
| runtime_facts_ref | 实际 task/message 身份、期限、时长和终态收据的引用 |

合同本体仅包含起跑前冻结的声明；已发生用户帮助及 runtime_facts 由 Session 的执行收据关联，不回写合同或改变其身份。

Session 可另存实验交互模式作分析标签，但给 Harness 的运行上下文只发送通用输入可用性和公开目标等事实。既不注入 benchmark 特征，也不修改原任务正文来规避解析问题。

合同作为 L1 固定区保留；普通事件裁剪不能将其删除。Direct 的目标摘要从真实 SeedScenario 与执行收据构建，不伪造 SimTrace 或模拟用户 goal ledger。原始目标过长时使用有 hash 的引用与有界摘要，不让大合同突破既有证据访问边界。

Triage 原报告、规范化提案、PM `evidence_sessions`、Synthesizer `source_proposals/covers`、Owner 合并及准入沿用现有可信 grants 取来源并集。由框架生成独立机器合同段和有界摘要，不让模型手写来源或从正文尾部重新解析。`ProposalView` 将合同置于独立字段，不受 3000 字正文裁剪或 direct 标签过滤影响。Mixed 来源同时保留各自适用条件，不能概括成“用户可以继续”。

角色仍各司其职：PM 读取用户层目标、体验和使用条件；Triage/Owner 等按原授权读取客观证据。向全角色暴露执行前提不等于放开全部验证日志。安全评分摘要通过明确证据通道提供；具体隐藏断言、expected output、标准答案与原始 verifier 日志不进入需求模型。

提案和 Spec 可以改变现有停止策略，但不能把原始目标、用户取消语义或无人输入条件放进 non-goals 后宣称解决。符合旧 Spec 只能说明实现一致，不能自动消除持续未交付的能力缺口。允许 reject 某次无据归因，同时保留 task_assessment 与真实验收事实供后续分析。

交付证据发布复用现有 gzip/ZIP、hash 和授权包，只新增带版本的安全合同块与结果引用。OpenAgents 配套读取端须核验来源和版本，并在 Spec Writer、Architect、Implementer、Reviewer 的实际上下文中直接给出有界条件，而不只给附件路径。其独立设计位于 OpenAgents 仓库；本组的跨仓联合验收在该 reader 可用前不得标完成。`release/compatibility.json`、预检能力和固定 reader SHA 一起更新，不允许新发布端配旧 reader 静默丢字段。

两仓共同 wire 合同为原观测包内的 `execution_evidence` 对象，必需字段为 `schema_version:1`、`issue`、`execution_contracts`、`assessment_summaries`、`payload_sha256`。contract 必需字段为 `contract_id`、`session_id`、`task_id`、`task_digest`、`followup_input`、`task_budget_seconds`（允许 null）、`budget_source`、`public_refs`；公开引用逐项为 kind/path/sha256。summary 必需字段为 `receipt_id`、`session_id`、`contract_id`、`status`、`passed`、可空 score/metric 定义、验收种类和来源摘要。数组允许为空，但开启 required 时必须覆盖该票全部授权来源，不能用空数组绕过。

payload 摘要对移除 `payload_sha256` 后的对象计算：UTF-8、`ensure_ascii=false`、键排序、无多余空白、拒绝非有限数；契约数组按稳定 ID 排序。contract_id 使用相同正规化规则计算不含 contract_id 的声明内容摘要，实际执行事实另附，不参与重定义原始合同。公开目标、产物和运行事实引用均为授权包内的 relative path + SHA256，禁止宿主绝对路径或私有 evaluation 路径。私有评分只给不透明 receipt ID 和白名单摘要，reader 不追取私有日志。两仓各保存同一份协议 fixture，并通过联合检查校验一致。

required 预期还必须由准备阶段协商的项目交付配置带到受信任 dispatch，不能仅存在于可被删掉的附件或 Issue marker 中。声明 required 的任务缺 marker/附件时应失败；无该协商声明的普通 Issue 才可按无合同处理。实施时使用 OpenAgents 的固定配置/dispatch 接缝，不依据历史轨迹内容决定信任级别。

### 4. Seed、Launcher 与预算一致性

沿用 `harness/budget.py`，增加明确的任务总截止与消息活动边界，不建立平行计时器。任务时钟从环境准备就绪后的首次目标投递开始，按墙钟流逝；同一任务的 queued、control、心跳与后续消息不能续租总期限。每条消息的可用活动预算不超过任务剩余时间。显式预算变更须经过当前操作者授权策略并留收据，不因文本中出现 wait 自动延期。

任务包 schema 2 可提供结构化 `execution`：预算来源、秒数及公开交付前提；现有 runtime 预算作为操作者 fallback，优先级和实际选值写入冻结合同。结构化官方时限与操作者定额不同必须明确标为定额实验，不冒称官方预算。对已知任务包的指令时限进行一致性预检：冲突在调用模型前报告并要求修改材料或显式登记 override；不静默改写任务文本，不根据自然语言正则自动决定运行期限。共享计算资源的 CPU、内存、任务并发与环境身份也冻结；不把目录隔离称为资源隔离。

公开字段固定为 `execution.budget_seconds`、`budget_source`（task_metadata/operator_quota）及可选 `quota_override_reason`。优先使用任务预算，未声明时才使用 `runtime.harness.request_budget_seconds`；同一请求的消息活动上限另由可选 `runtime.harness.message_activity_seconds` 限制。已知来源以其锁定元数据校验时限；任意自由文本不能自动证明一致，记录为 instruction_budget_unverified，常见显式时限冲突可作 lint 报错但不作为预算来源。模型容量字段为 `models.<role>.limits.context_window_tokens`、`reserved_output_tokens` 和 `input_headroom_tokens`，以及可选 `max_context_tokens`（有效输入阈值，默认保持 256000，可显式下调）；它们是声明值及静态检查输入，不是假定可硬拦截的实际 token 计数。

协议 message 保留稳定 task/message ID、输入条件、任务截止和剩余预算。Seed 的消息队列保存并消费这些结构化字段。跨主机 wall timestamp 仅作审计；Runner 是期限权威，Seed 在入队时用剩余时间锚定本机 monotonic deadline，同任务后续帧只能取 `min(existing_deadline, now + remaining)`。出队、重连和重新包装消息不能退款或重新分配完整预算；缺字段、未知身份不能暗中开新任务或回落为 1800 秒。连接延迟不延长 Runner 的权威期限。

基础设施强停期限为任务期限加独立 termination grace；宽限只做取消、终态说明和留档，不能开始新解题调用。7200 秒任务的期限不被内部 fallback 1800/1860 覆盖。没有显式合同的人工交互保留明确的 unknown/未声明语义，不猜测总预算；新的研究实验在 prepare 时冻结完整合同。

Seed 主提示与 META_SPEC 改为“收到明确目标后自主推进，用户输入是可选控制通道”；不预置具体看门狗阈值或自动恢复实现。有限迭代、输出截断、缺必要信息等仍可产生 incomplete，它是待改善的任务结局，不是完成证明。保留现有 `max_iterations=100` 与 `max_tokens=32768`；本组不因为任务有 7200 秒就承诺一定持续计算两小时。

公共任务 reply 必须有合法 status 和 termination_reason 并关联身份；Launcher 不再默认缺失 status 为 completed。内部 slash 命令使用明确的 builtin_command/确认语义，只确认该条命令，不结束活动任务、不清除其 deadline。task/message ID 不匹配的回复不能被当前任务消费。原始 reason 进入 request outcome，平台强停和 Harness 正常回复保留不同来源。沿用已修正的完成工具 hook 和取消路径。

为 user/harness/demand 的直接模型配置增加可声明的总上下文容量、保留输出和输入余量，保留既有输出默认值。预检只在有明确容量时校验有效输入阈值 + 输出保留 + 余量不超过总容量；未知容量标未核实，不能从模型名字推断。例：容量 262144 时，256000+32768 必须拒绝，不能把该组合记作验证通过。

固定 NexAU 的上下文计数/超限目前不能提供可靠动态硬保证：部分 hook 吞异常，默认 token counter 是估算，模型包装还可能改变原生异步取消。因此本组不 fork NexAU、不引入此包装，不承诺动态压缩。仅静态纠正配置，并将可识别的确定性 context overflow 记为 incomplete，阻止 Seed 再次追加相同规模的完整 Agent.run。NexAU 内部 HTTP 重试与外层 attempt 分别记录；不能声称真实 HTTP 只发生一次。

### 5. 逐轮验收服务和可信执行端

新增 `evaluation/service.py`，提取构建/验证 `GradingRequest`、调用注册 adapter 和规范化结果的共同逻辑。事后 `experiment/grading.py` 保留其“终态 run、完整归档、generation、seal、hash”的校验，不为了在线路径放宽这些要求。在线评分只读取另一种明确封存的 session artifact bundle，并验证相同等级的任务、会话、来源和字节身份；不传一个跳过校验的布尔开关。

新增 `loop/round_assessment.py` 负责控制器侧恢复单元，`experiment/assessment_worker.py` 负责可信评分机领取与执行；provider 仅增加受所有权约束的请求/产物下载与收据上传能力。它们不包含评分规则、不调度新 Actor、不负责交付。外部 worker 可在 local 与 E2B 场景复用；任务输出和管理目录不能暴露私有 plan。worker 端用现有 Docker adapter，不把 Docker socket 或私有 grader 挂到 E2B 用户环境。

```text
users（含冻结产物和主观评阅）
  → objective_grading（请求 → 外部 worker → 验证结果收据）
  → 安全反馈投影
  → triage ∥ PM → synth → owner → 交付 → 下一轮
```

恢复操作身份至少绑定 run、round、slot/session、实际试用 user_sha、task_digest、artifact_digest、plan_digest、adapter 版本与评分实现摘要。先落结果和 hash，再完成单元；重复领取复用已验证的结果，不重跑 Actor，不改旧 Session，不用交付后的 sealed_sha 替换试用 SHA。

评分请求采用有版本的 JSON 信封，固定包含上述身份、controller generation/nonce、request_digest 和产物清单；请求目录不允许携带任意 shell 命令。worker 领取采用原子 claim，形成单调递增 claim_epoch、worker_nonce 和租约。每次回传绑定 request_digest、当前 claim_epoch、worker_nonce、私有原始结果摘要及 safe_summary_digest；控制器仅 accept-once 接受当前 generation 的有效 claim。旧 worker、过期 epoch、重复不同结果和来源错误均不能覆盖已接受的 receipt 或反馈投影。

worker 身份由 prepare 注册的验签公钥校验，私钥仅留在可信评分机；结果信封由 worker 签名，不能把内容 hash 或随机 nonce 当身份认证。传输仍复用 provider 的所有权验证和管理通道，不新建公共 HTTP 评分服务器。受管控制状态的隔离仍遵守当前后端边界，不把工作区目录隔离宣传为恶意代码安全沙箱。新评分规则必须使用独立 attempt，不能借 resume 换规则。

配置开启验收时，prepare 验证私有 plan 覆盖和后端能力，正式用户运行前验证 worker 的可用身份、plan digest 和执行能力。worker 中断或传输未知时显示 assessment_pending，阻止假装已有评分而进入依赖阶段；恢复只接续评分，不重跑会话。操作者可终止该实验或在显式审计后记录本项 unavailable，不暗中转为 0。它是测量完备性约束，不是因为任务分数低而拒绝版本。

等待验收是现有运行中的阶段事实：保持 experiment_state=RUNNING，phase=objective_grading，单列 assessment_state=PENDING；不为了等评分另建一套实验顶层状态机。

合法结果的语义复用现有 adapter：completed 且验证合同有效才有技术结论；false 是真实失败，仍进入后续轮次；unsupported、missing_artifact、ungradable、unavailable、crashed、timed_out 保持 passed=null。只有连续 metric 的任务保留原 score，未定义二值规则时不造 passed。未配置逐轮验收写明确 not_configured，不能把 Reviewer 判断换名为官方通过率。

私有评分结果留在可信评分端和私有 evaluation 存储，不进入公开归档、可读源码快照、模型 Prompt 或 Issue 附件。控制器只接收来源可校验的白名单摘要及不透明引用。结果摘要本身不泄露具体隐藏断言或正确答案。首次反馈消费前冻结该轮投影 digest；事后补评分仍为独立记录，不静默改掉角色当时看到的证据。

首批真实验收限于现有已核验 adapter/profile 和可完整封存的产物。机制任务使用明确 custom verifier，不冒称官方。依赖原环境或受管 KV 测量的任务，只有满足已有环境与可信采集合同才可开启；当前缺能力的任务在 prepare 拒绝，不能因此宣布完整 N8 E2B 路径已补齐。独立 Harness→Harbor 研究评测入口不变，本组不复制它的任务重跑、资源调度或 manifest。

### 6. Task DAG、文件归属和验证

实施调度细化：T2 的只读评阅/报告恢复与 T5 的纯评分服务/worker 可在 T1 后并行开发；它们的 Runner 接线和整体验收仍等待 T3 的预算接口，T6 验证完整链路。

| Task | 职责 | 主要依赖 |
| --- | --- | --- |
| T1 | 规范反馈、执行合同纯数据、缺测存储/统计/界面和接受关系 | 无 |
| T2 | 双模式会话、先冻结后只读评阅、0..n 报告与幂等恢复 | T1、T3 |
| T3 | Seed/Launcher、公共配置、任务预算与模型容量预检 | T1 |
| T4 | 需求角色、提案、授权证据和交付合同传递 | T1、T2、T3 |
| T5 | 共用评分服务、外部 worker、逐轮恢复和私有材料生命周期 | T1、T2、T3 |
| T6 | 跨仓合同与真实后端验收、文档和迁移边界 | T4、T5 |

精确文件归属由 frontmatter 给出，组内不交叉。OpenAgents 的 reader/context/角色检查在它自己的仓库分配，不把外部源码列为本仓文件。T6 是联合接口验收，不能用发布者单方 fixture 代替真实 reader。

端到端脚本为 `backend/scripts/e2e-spec-0084-evolution-feedback.sh`，支持离线确定性合同测试及显式启用的真实 local/E2B 路径。验收至少覆盖：

1. 正常交付零 Issue；建议与未知归因失败分别报告；缺失、布尔、字符串、非法评分不制造分数；前端不空引用。
2. Reviewer 写入和 shell 工具不可达，评阅前后用于评分的字节/hash 相同；Reviewer API 失败仍可验收有效 Actor 产物。
3. Direct 从首次消息到最终协议回复没有第二条用户消息；交互控制可用；合同经过 triage、PM、synth、合并准入和实际 OpenAgents 角色上下文后仍保留输入不可用条件。
4. “停止后请用户继续”的无人恢复验收被架构/代码审查指出；“符合旧 Spec”不得被当作完成证据。测试不向评测任务提供隐藏答案。
5. 注入时钟验证 7200 秒、排队、控制、预算到期及独立收尾余量；不真的耗时两小时。缺终态不计成功，内置命令不误判。
6. 静态容量冲突被拒、未知容量如实呈现、确定性超限不追加同规模外层 attempt；保持原生异步取消和真实 SDK 构造回归。
7. 同一冻结产物经在线与事后服务获得相同 adapter 结果；真实正/负控制、连续分数、产物缺失、verifier 故障分别分类；测试控制材料不冒称 Harness 成功样本。
8. 在 Actor 已完成、报告待发布、评分结果已写但 ledger 未完成、worker 断连、重复领取时分别中断恢复；不重复 Actor/Reviewer、已完成判分和 Issue。
9. 最后一轮只试用仍验收；低分不触发候选淘汰；旧归档字节、Session hash 和恢复身份保持不变；私有材料不出现在角色输入和公开归档。

真实验收先跑最小 local custom/SWE 或文件任务及 E2B+外部评分机 canary，保留实际收据。之后才冻结同 Seed、SDK、模型服务、预算与任务资源的小规模配对 pilot：全 Direct 与 Mixed 分别报告技术结果、体验、缺测和用户帮助。新大规模六轮实验需要操作者另行启动，本组不自动重跑历史实验，不把一两道题变化当作已证明的泛化提升。

## Drawbacks

可空评分会触及存储、趋势、角色和前端，单改 Prompt 不足以交付。固定产物先于评阅会减少 Reviewer 的自由检查能力，需要用独立 grader 补足技术验收，而非让 Reviewer 修任务。

逐轮评分增加运行成本、时长和一个长期可信执行端；E2B 实验不能只依赖没有 Docker 的控制器自给自足。该依赖必须被显式部署和监控，不能伪装为免费能力。完整 KV 等环境合同尚未具备时支持范围仍有限。

合同和结果摘要增加角色上下文占用；应有界、按来源去重并保留引用。测量变准不保证模型立即学出更好的恢复机制，早期也可能出现更多被诚实记录的失败。

## Rationale and alternatives

采用“一个反馈事实源、一个执行合同、既有 adapter 服务、一个窄评分 worker”。数据、会话、Seed、需求与交付、评分执行各有单一维护位置，不新增第二套用户循环、benchmark 框架或实验调度器。

备选一是只给 Direct Prompt 补充“不要早停”。它不能修正评分缺测、预算丢失、成功强制建票、评审改产物和交付条件丢失，故不采用。

备选二是给 Harness 的所有提前退出自动发送“继续”，或给 Direct 加一个解题用户。它改变自主能力测量和产物行为，可能把用户调试贡献计为 Harness 提升，故不采用。

备选三是每次交付后必须跑过所有能力题，否则拒绝合并或回滚。本次保留允许后续轮次纠错的实验设计，不把它混入同一变量；独立验收提供反馈，不作候选淘汰门。

备选四是在 E2B 内挂 Docker socket、评分 plan 或标准答案，或者为在线评分重新实现官方 tests。这会扩大任务可见材料并制造两套评分规则，故使用外部可信评分机及共用 adapter。

备选五是立即实现完整环境 broker、通用插件平台、动态硬 token 管理和自动恢复。它们不是修测量及合同的必要前置；本组只声明能力并拒绝不支持路径，后续可以按真实反馈分别演化。

## Prior art

本仓已有用户目标账本、用户/客观证据分层、只读 SHA 源码快照、不可变 Session、幂等 Issue 发布、RecoveryStore、公开产物声明及独立评分 adapter，可直接复用。已有事后评分和独立 Harness 研究评测分别负责“验收已发生的会话”和“在新任务重跑指定 Harness”，本组保留该区别。

配套 OpenAgents 已通过统一 runtime engine 注入观测上下文，能够继续以窄的安全合同扩展；不要求它理解实验组、私有 grading plan 或 benchmark 专属规则。

## Unresolved questions

方案已获审阅批准，按本文边界实施。外部评分机是显式依赖，Reviewer 只读、任务总预算和消息活动预算分离，保留跨轮纠错。配套 reader 已推送为不可变审阅候选并回填 compatibility，正式发布仍需联合审阅合并。早期未发布的本地快照仅用于开发验收，不充当发布 pin。

## Future possibilities

在忠实反馈和合同下观察新演化，再单独评估自动恢复、上下文压缩、独立任务沙箱、父版本配对复查或候选选择机制。成功/失败样本可以用于分层能力趋势，但不将已进入反馈的研究题继续称作未见测试。

未来可为可信评分服务增加其他执行后端；它应实现同一评分服务合同，不要求给每个新 benchmark 再写 runner 或改用户会话循环。
