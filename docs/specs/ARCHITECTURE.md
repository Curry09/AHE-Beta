# 架构现状（ARCHITECTURE）

> 本文件由 `spec graph` 自动生成，请勿手工编辑。源 = `backend/ahe_beta/` 的代码与 docstring。

## 子系统与组件

### ahe_beta

_ahe-beta: 自进化 harness（用户侧 a）。_

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | ahe-beta: 自进化 harness（用户侧 a）。 |
| `execution_contract.py` | Immutable execution declarations and public evidence wire (Spec-0084/T1). |
| `invocation.py` | Persist one JSON file per role invocation under ROLE_RUNS_DIR. |
| `models.py` | 用户侧最小链路的公共数据结构（spec-0001/T1）。 |
| `nexau_runtime.py` | 单一 nexau 适配层（spec-0003/T2）：把一份角色定义(prompt+工具)加载成可调用 Agent。 |
| `usage.py` | Best-effort, per-call LLM usage telemetry. |

### ahe_beta.demand

_Product discovery, proposal synthesis, and admission decision roles._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Product discovery, proposal synthesis, and admission decision roles. |
| `agent_contract.py` | 由 issue_schema.SCHEMAS 生成各 producer 的 submit 工具 input_schema——契约与 schema 同源， |
| `agent_runtime.py` | 四个 driver（triage / architect / divergent / owner）此前各抄一份的公共逻辑收拢于此： |
| `architect.py` | Architect 驱动器。 |
| `delivery_evidence.py` | Publish issue-scoped opaque evidence through the existing forge boundary. |
| `divergent.py` | Divergent（能力发现）驱动器。 |
| `evidence_contract.py` | Goal-aware evidence contracts for demand-side roles. |
| `grouped_architect.py` | Group a proposal snapshot once, then give each group to one existing Architect. |
| `issue_schema.py` | 标准 issue 格式的单一真源（平台层，dev 够不着——issue 格式是平台制品，不可被 harness 进化改动）。 |
| `observation_provider.py` | Spec-0059: discover and read artifact-owned diagnostic files with ordinary tools. |
| `owner.py` | Owner 驱动器：把 proposal 无损打包并交接给 OpenAgents。 |
| `proposal_view.py` | Canonical normalized proposal projection shared by all downstream roles. |
| `role_contract.py` | Spec-0043: task-independent cognitive contracts for demand-side roles. |
| `runtime_agg.py` | 运行时行为聚合：从已落盘 Session 事后扫出任务无关指标，喂结构综合作机制层判别证据。 |
| `session_timeline.py` | 结构综合按需取用：从落盘 Session 投影「使用事件时间线」。 |
| `source.py` | Spec-0082/T1: demand reads a commit snapshot rather than a moving checkout. |
| `submit_tools.py` | submit 工具的 binding。 |
| `triage.py` | Triage（报告规范化）驱动器。 |

### ahe_beta.distill

_蒸馏侧（spec-0006）：persona 卡库读写 + 契约约束校验。_

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | 蒸馏侧（spec-0006）：persona 卡库读写 + 契约约束校验。 |
| `library.py` | PersonaLibrary（spec-0006/T1）：persona 卡库的最小读写 + 契约约束校验。 |
| `seed_adapter.py` | seed_adapter.py（spec-0010/T2）：把种子卡注入 0009 的 SeedSource 供给。 |
| `seed_library.py` | SeedLibrary（spec-0010/T1）：种子卡库的最小读写 + 契约约束校验。 |

### ahe_beta.evaluation

_Spec-0083: session artifact collection and independent post-run grading._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Spec-0083: session artifact collection and independent post-run grading. |
| `acceptance.py` | Keep original acceptance distinct from technical evidence (Spec-0083/T1). |
| `artifacts.py` | Spec-0083/T3: one bounded, binary artifact collector for both interactions. |
| `contracts.py` | Read-only requests for independent session grading (Spec-0083/T1). |
| `registry.py` | Explicit versioned built-ins; no runtime Python plugins (Spec-0083/T1). |
| `results.py` | Normalized grading results, separate from official reports (Spec-0083/T1). |
| `service.py` | Shared request construction and verified result normalization (Spec-0084/T5). |

### ahe_beta.evaluation.adapters

_Fixed official and custom grading adapters (Spec-0083/T4)._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Fixed official and custom grading adapters (Spec-0083/T4). |
| `container.py` | Bounded staging and isolated Docker execution (Spec-0083/T4). |
| `custom.py` | Execute an operator-fixed custom verifier in isolation (Spec-0083/T4). |
| `nl2repo.py` | Pinned TinyDB post-processing and official score parser (Spec-0083/T4). |
| `profiles.py` | Verified Git subtree identities for the first official tasks (Spec-0083/T4). |
| `swebench.py` | Spec-0083/T4: SWE adapter with a private official CLI executor. |
| `terminal_bench.py` | Run exact pinned separate Terminal-Bench verifiers (Spec-0083/T4). |
| `tua_bench.py` | Reconstruct the first pinned Excel verifier without altering it (Spec-0083/T4). |

### ahe_beta.experiment

_Frozen materials, controllers and local/E2B resource lifecycles._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Frozen materials, controllers and local/E2B resource lifecycles. |
| `assessment_worker.py` | Trusted external Docker grading worker (Spec-0084/T5). |
| `batch.py` | Spec-0074/T2: foreground batches reuse single-run lifecycle and durable leases. |
| `batch_config.py` | Spec-0074/T1: strict batch inputs and identities using the existing material compiler. |
| `batch_store.py` | Spec-0074/T1: immutable batch intent, atomic receipts and owned child roots. |
| `cli.py` | Operator-facing commands with credential-free lifecycle receipts. |
| `collection.py` | Spec-0069/T5: portable, checksummed evidence collection independent of model keys. |
| `config.py` | Spec-0071/T3: strict public v2 configuration and shared identity helpers. |
| `context.py` | Spec-0069/T2: one credential-free context and model mapping for both runners. |
| `dashboard.py` | Spec-0072/T4: read-only dashboard bound to a prepared run, without provider discovery. |
| `engine.py` | Spec-0069/T2: supervise the existing controller, with owned PIDs and receipts. |
| `grading.py` | Spec-0083/T5: grade immutable collected sessions without resuming an experiment. |
| `grading_inputs.py` | Spec-0083/T5: freeze private grading plans before dispatch or allocation. |
| `infrastructure.py` | Provision, stop, and destroy experiment infrastructure via Compose project. |
| `manifest.py` | Spec-0071/T3: immutable input manifests and shared append-only runtime facts. |
| `materials.py` | Spec-0069/T1: compile operator inputs into a checksummed, credential-free run bundle. |
| `model_limits.py` | Explicit model capacity declarations and static checks (Spec-0084/T3). |
| `runtime.py` | Manage prepared experiments without rewriting their frozen identities. |
| `task_import.py` | Spec-0076/T1: offline conversion into the existing ordinary task package contract. |
| `workload.py` | Spec-0073/T1: logical task catalog and session plan, independent of providers. |

### ahe_beta.experiment.backends

_Spec-0069/T2: execution adapters implement the same experiment lifecycle._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Spec-0069/T2: execution adapters implement the same experiment lifecycle. |
| `base.py` | Spec-0069/T2: provider resources are mutable facts, never frozen config fields. |
| `e2b.py` | Spec-0069/T4: identity-owned E2B execution and user-owned Gitea.com evidence. |
| `e2b_bootstrap.py` | Spec-0069/T4: portable frozen-input bootstrap, without developer home files. |
| `e2b_template.py` | Spec-0069/T4: cache a verified build identity, then inspect actual sandbox resources. |
| `local.py` | Spec-0069/T3: frozen local toolchains and an experiment-owned Docker stack. |
| `local_ci.py` | Spec-0077/T2: private registration and real PR readiness for an owned runner. |

### ahe_beta.experiment.continuation

_Current, frozen experiment archive continuation contracts._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Current, frozen experiment archive continuation contracts. |
| `evidence.py` | Spec-0079/T2: parent evidence stays read-only and outside child session metrics. |
| `export.py` | Spec-0079/T2: export the ledger-selected final Git tree and evidence boundary. |
| `forge.py` | Spec-0079/T2: project only selected pending reports into the child's fresh forge. |
| `source.py` | Read and validate current collect archives without executing their contents. |

### ahe_beta.experiment.controllers

_Spec-0073/T4: one unified controller backed by shared experiment runtime._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Spec-0073/T4: one unified controller backed by shared experiment runtime. |
| `feedback.py` | Spec-0079/T4: concrete phase role assembly and inherited feedback initialization. |
| `runtime.py` | Spec-0073/T4: shared experiment runtime: repository, delivery process and round receipts. |
| `unified.py` | Spec-0073/T4: unified frozen-task experiment controller. Start through the experiment CLI. |

### ahe_beta.experiment.task_environments

_Spec-0081: frozen task material and Docker execution capabilities._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Spec-0081: frozen task material and Docker execution capabilities. |
| `contract.py` | Spec-0081/T1: container task declarations independent of execution providers. |
| `docker.py` | Spec-0081/T3: owned Docker task containers and finite companion services. |
| `materials.py` | Spec-0081/T2: verified task inputs; no provider or experiment orchestration. |

### ahe_beta.guards

_Spec-0068/T1: repository integrity, commit boundaries and tool path checks._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Spec-0068/T1: repository integrity, commit boundaries and tool path checks. |
| `harness_boundary.py` | harness 提交边界闸：拦住密钥和 vigil 运行态，不再用顶层白名单锁死产品形状。 |
| `repo_guard.py` | repo_guard：编排仓完整性快照与校验。 |
| `workspace_jail.py` | WorkspaceJailMiddleware：dev/architect 以 harness 仓为可写工作区；NexAU 源码与运行时产物只读放行。 |

### ahe_beta.harness

_Evaluation harness integration and execution support._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Evaluation harness integration and execution support. |
| `budget.py` | Spec-0082/T2: request budgets and infrastructure termination are separate limits. |
| `connector.py` | Platform-side connector from simulated users to the harness human-facing interface. |
| `interface.py` | harness 多轮对话契约 HarnessInterface + 测试后端 FakeHarness（spec-0001/T2）。 |
| `launcher.py` | harness launcher（spec-0003/T1）：把某版 harness 程序接成 spec-0001 的 HarnessInterface。 |

### ahe_beta.loop

_Conversation-loop coordination, tracing, and lifecycle management._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Conversation-loop coordination, tracing, and lifecycle management. |
| `checkpoint.py` | checkpoint 存取（spec-0004/T1）：把自包含 STATE_DIR 打包成可下载 artifact，反向还原。 |
| `feedback_pipeline.py` | Spec-0079/T3: one recoverable feedback and delivery cycle. |
| `live.py` | 多 agent 活动注册表（流式观测）：各 agent（用户/创新者/开发者）的实时状态写到 data/live/。 |
| `live_tracer.py` | StepTracer：把 nexau agent 运行中的过程流成看板可见的结构化事件。 |
| `metrics.py` | metrics（spec-0003/T6，曲线口径 spec-0025/T7）：统计体感与 issue backlog 随时间的曲线。 |
| `orchestrator.py` | 闭环编排 orchestrator（需求面）。 |
| `recovery.py` | Durable stage and work-item recovery ledger. |
| `roster.py` | 角色编制（roster）：各类 agent 的数量，作为「后端编排」与「前端小镇房间」的单一真源。 |
| `round_assessment.py` | Sealed-session grading exchange and round recovery (Spec-0084/T5). |
| `round_gate.py` | Wait until this round's admitted issues reach a delivery terminal state. |
| `run_state.py` | run_state（spec-0004/T1）：编排游标 + 三侧中间态标记，作为「无法从产物观测」之外的兜底。 |
| `runner.py` | 可恢复 Harbor runner（Spec-0004/T2, Spec-0064/T2）。 |
| `sim_user.py` | 把 spec-0005 控制信封 sim 用户 agent 接进 spec-0003/0007 闭环。 |

### ahe_beta.observations

_Artifact-owned observations with platform-owned collection and authorization._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Artifact-owned observations with platform-owned collection and authorization. |
| `__main__.py` | Explicit recovery: python -m ahe_beta.observations --root ROOT --receipt FILE. |
| `delivery_gaps.py` | Ingest only authenticated delivery requests, never arbitrary comments or logs. |
| `gaps.py` | Spec-0061: scoped maintainer diagnostic gaps with a durable outbox. |
| `grants.py` | Persist evidence authority separately from model-authored issue text. |
| `preflight.py` | Spec-0070/T3: freeze transport and verify the actual delivery reader before models run. |
| `publication.py` | Collect bounded opaque artifact files and publish immutable session evidence. |
| `transport.py` | Spec-0070/T2: freeze transport separately from the historical framework contract. |

### ahe_beta.tracker

_Issue-tracker integration and proposal state management._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Issue-tracker integration and proposal state management. |
| `attachment_transport.py` | Spec-0070/T1: explicit formats and the fixed Gitea.com signed-download boundary. |
| `base.py` | IssueTracker 协议（spec-0001/T5）：issue 提交去向的抽象，用户侧不绑定具体后端。 |
| `fake.py` | FakeTracker（spec-0001/T5）：IssueTracker 的内存实现，供单测与无 Gitea 环境端到端跑通。 |
| `gitea.py` | GiteaTracker（spec-0002/T2）：spec-0001/T5 IssueTracker 接口的真后端。 |

### ahe_beta.user

_User simulation, personas, and interaction evidence collection._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | User simulation, personas, and interaction evidence collection. |
| `patches.py` | Immutable full session predictions for post-run grading (Spec-0075/T1). |
| `session_store.py` | 本地 SessionStore（spec-0001/T6）：一局 Session 全量落盘 + 单一总索引。 |

### ahe_beta.user.sim

_ahe_beta.user.sim —— persona 驱动的 harness 用户模拟器(控制信封架构, 纯主观)。_

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | ahe_beta.user.sim —— persona 驱动的 harness 用户模拟器(控制信封架构, 纯主观)。 |
| `action_space.py` | action_space.py |
| `actions.py` | actions.py |
| `clauses.py` | clauses.py |
| `demo.py` | demo.py |
| `deps.py` | 依赖供给：执行 WorkspaceSpec.setup 在工作区里备好依赖环境（spec-0009/T3）。 |
| `dimensions.py` | dimensions.py |
| `feeling.py` | feeling.py |
| `goals.py` | Explicit, append-only user goals for the persona control loop. |
| `harness_adapter.py` | harness_adapter.py |
| `loop.py` | loop.py |
| `persona_client.py` | persona_client.py |
| `persona_io.py` | persona_io.py（spec-0006/T2 + Spec-0037/T4）：把 persona 卡注入控制信封 sim。 |
| `prompt.py` | prompt.py |
| `run_agentic.py` | run_agentic.py — 实测内层 tool-using 用户 agent 是否真去操作工作区（spec-0008）。 |
| `run_live.py` | run_live.py |
| `runtime.py` | Workspace execution boundaries for simulated-user sessions (spec-0051/T2). |
| `sandbox.py` | 内层用户 agent 的最小执行 sandbox（spec-0008/T2）。 |
| `scenarios.py` | scenarios.py |
| `seed_source.py` | 可插拔的种子工作区供给接缝（spec-0009/T1）。 |
| `skills.py` | skill 占位接口（spec-0008/T3）。 |
| `state.py` | state.py |
| `tools.py` | 内层用户 agent 的原子工具 + D1 能力门控（spec-0008/T2）。 |
| `workspace.py` | seed 工作区落地（spec-0008/T1 → spec-0009/T1）。 |

### ahe_beta.user.sim.sources

_SeedSource 实现子包（spec-0009/T1）。_

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | SeedSource 实现子包（spec-0009/T1）。 |
| `container.py` | Spec-0081/T3: bind a frozen container recipe to a concrete session attempt. |
| `docker_seed.py` | Runnable Docker seed source (spec-0051/T2). |
| `empty.py` | empty SeedSource（spec-0009/T2）。 |
| `git.py` | git SeedSource（spec-0009/T4）。 |
| `local_fixture.py` | local-fixture SeedSource（spec-0009/T1）。 |
| `prebuilt.py` | Spec-0073/T3: copy pure task source and rebuild each managed session's venv. |

### ahe_beta.web

_Web application endpoints and runtime composition._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Web application endpoints and runtime composition. |
| `api.py` | 前端观测看板的只读 HTTP 层（FastAPI）。 |
| `issue_timeline.py` | Spec-0039/T2：把 Gitea label timeline 折叠为可回放的 issue 状态与完整性异常。 |

## 依赖关系图（import）

```mermaid
graph LR
    nahe_beta["ahe_beta"]
    nahe_beta_demand["ahe_beta.demand"]
    nahe_beta_demand_agent_contract["demand.agent_contract"]
    nahe_beta_demand_agent_runtime["demand.agent_runtime"]
    nahe_beta_demand_architect["demand.architect"]
    nahe_beta_demand_delivery_evidence["demand.delivery_evidence"]
    nahe_beta_demand_divergent["demand.divergent"]
    nahe_beta_demand_evidence_contract["demand.evidence_contract"]
    nahe_beta_demand_grouped_architect["demand.grouped_architect"]
    nahe_beta_demand_issue_schema["demand.issue_schema"]
    nahe_beta_demand_observation_provider["demand.observation_provider"]
    nahe_beta_demand_owner["demand.owner"]
    nahe_beta_demand_proposal_view["demand.proposal_view"]
    nahe_beta_demand_role_contract["demand.role_contract"]
    nahe_beta_demand_runtime_agg["demand.runtime_agg"]
    nahe_beta_demand_session_timeline["demand.session_timeline"]
    nahe_beta_demand_source["demand.source"]
    nahe_beta_demand_submit_tools["demand.submit_tools"]
    nahe_beta_demand_triage["demand.triage"]
    nahe_beta_distill["ahe_beta.distill"]
    nahe_beta_distill_library["distill.library"]
    nahe_beta_distill_seed_adapter["distill.seed_adapter"]
    nahe_beta_distill_seed_library["distill.seed_library"]
    nahe_beta_evaluation["ahe_beta.evaluation"]
    nahe_beta_evaluation_acceptance["evaluation.acceptance"]
    nahe_beta_evaluation_adapters["evaluation.adapters"]
    nahe_beta_evaluation_adapters_container["adapters.container"]
    nahe_beta_evaluation_adapters_custom["adapters.custom"]
    nahe_beta_evaluation_adapters_nl2repo["adapters.nl2repo"]
    nahe_beta_evaluation_adapters_profiles["adapters.profiles"]
    nahe_beta_evaluation_adapters_swebench["adapters.swebench"]
    nahe_beta_evaluation_adapters_terminal_bench["adapters.terminal_bench"]
    nahe_beta_evaluation_adapters_tua_bench["adapters.tua_bench"]
    nahe_beta_evaluation_artifacts["evaluation.artifacts"]
    nahe_beta_evaluation_contracts["evaluation.contracts"]
    nahe_beta_evaluation_registry["evaluation.registry"]
    nahe_beta_evaluation_results["evaluation.results"]
    nahe_beta_evaluation_service["evaluation.service"]
    nahe_beta_execution_contract["ahe_beta.execution_contract"]
    nahe_beta_experiment["ahe_beta.experiment"]
    nahe_beta_experiment_assessment_worker["experiment.assessment_worker"]
    nahe_beta_experiment_backends["experiment.backends"]
    nahe_beta_experiment_backends_base["backends.base"]
    nahe_beta_experiment_backends_e2b["backends.e2b"]
    nahe_beta_experiment_backends_e2b_bootstrap["backends.e2b_bootstrap"]
    nahe_beta_experiment_backends_e2b_template["backends.e2b_template"]
    nahe_beta_experiment_backends_local["backends.local"]
    nahe_beta_experiment_backends_local_ci["backends.local_ci"]
    nahe_beta_experiment_batch["experiment.batch"]
    nahe_beta_experiment_batch_config["experiment.batch_config"]
    nahe_beta_experiment_batch_store["experiment.batch_store"]
    nahe_beta_experiment_cli["experiment.cli"]
    nahe_beta_experiment_collection["experiment.collection"]
    nahe_beta_experiment_config["experiment.config"]
    nahe_beta_experiment_context["experiment.context"]
    nahe_beta_experiment_continuation["experiment.continuation"]
    nahe_beta_experiment_continuation_evidence["continuation.evidence"]
    nahe_beta_experiment_continuation_export["continuation.export"]
    nahe_beta_experiment_continuation_forge["continuation.forge"]
    nahe_beta_experiment_continuation_source["continuation.source"]
    nahe_beta_experiment_controllers["experiment.controllers"]
    nahe_beta_experiment_controllers_feedback["controllers.feedback"]
    nahe_beta_experiment_controllers_runtime["controllers.runtime"]
    nahe_beta_experiment_controllers_unified["controllers.unified"]
    nahe_beta_experiment_dashboard["experiment.dashboard"]
    nahe_beta_experiment_engine["experiment.engine"]
    nahe_beta_experiment_grading["experiment.grading"]
    nahe_beta_experiment_grading_inputs["experiment.grading_inputs"]
    nahe_beta_experiment_infrastructure["experiment.infrastructure"]
    nahe_beta_experiment_manifest["experiment.manifest"]
    nahe_beta_experiment_materials["experiment.materials"]
    nahe_beta_experiment_model_limits["experiment.model_limits"]
    nahe_beta_experiment_runtime["experiment.runtime"]
    nahe_beta_experiment_task_environments["experiment.task_environments"]
    nahe_beta_experiment_task_environments_contract["task_environments.contract"]
    nahe_beta_experiment_task_environments_docker["task_environments.docker"]
    nahe_beta_experiment_task_environments_materials["task_environments.materials"]
    nahe_beta_experiment_task_import["experiment.task_import"]
    nahe_beta_experiment_workload["experiment.workload"]
    nahe_beta_guards["ahe_beta.guards"]
    nahe_beta_guards_harness_boundary["guards.harness_boundary"]
    nahe_beta_guards_repo_guard["guards.repo_guard"]
    nahe_beta_guards_workspace_jail["guards.workspace_jail"]
    nahe_beta_harness["ahe_beta.harness"]
    nahe_beta_harness_budget["harness.budget"]
    nahe_beta_harness_connector["harness.connector"]
    nahe_beta_harness_interface["harness.interface"]
    nahe_beta_harness_launcher["harness.launcher"]
    nahe_beta_invocation["ahe_beta.invocation"]
    nahe_beta_loop["ahe_beta.loop"]
    nahe_beta_loop_checkpoint["loop.checkpoint"]
    nahe_beta_loop_feedback_pipeline["loop.feedback_pipeline"]
    nahe_beta_loop_live["loop.live"]
    nahe_beta_loop_live_tracer["loop.live_tracer"]
    nahe_beta_loop_metrics["loop.metrics"]
    nahe_beta_loop_orchestrator["loop.orchestrator"]
    nahe_beta_loop_recovery["loop.recovery"]
    nahe_beta_loop_roster["loop.roster"]
    nahe_beta_loop_round_assessment["loop.round_assessment"]
    nahe_beta_loop_round_gate["loop.round_gate"]
    nahe_beta_loop_run_state["loop.run_state"]
    nahe_beta_loop_runner["loop.runner"]
    nahe_beta_loop_sim_user["loop.sim_user"]
    nahe_beta_models["ahe_beta.models"]
    nahe_beta_nexau_runtime["ahe_beta.nexau_runtime"]
    nahe_beta_observations["ahe_beta.observations"]
    nahe_beta_observations___main__["observations.__main__"]
    nahe_beta_observations_delivery_gaps["observations.delivery_gaps"]
    nahe_beta_observations_gaps["observations.gaps"]
    nahe_beta_observations_grants["observations.grants"]
    nahe_beta_observations_preflight["observations.preflight"]
    nahe_beta_observations_publication["observations.publication"]
    nahe_beta_observations_transport["observations.transport"]
    nahe_beta_tracker["ahe_beta.tracker"]
    nahe_beta_tracker_attachment_transport["tracker.attachment_transport"]
    nahe_beta_tracker_base["tracker.base"]
    nahe_beta_tracker_fake["tracker.fake"]
    nahe_beta_tracker_gitea["tracker.gitea"]
    nahe_beta_usage["ahe_beta.usage"]
    nahe_beta_user["ahe_beta.user"]
    nahe_beta_user_patches["user.patches"]
    nahe_beta_user_session_store["user.session_store"]
    nahe_beta_user_sim["user.sim"]
    nahe_beta_user_sim_action_space["sim.action_space"]
    nahe_beta_user_sim_actions["sim.actions"]
    nahe_beta_user_sim_clauses["sim.clauses"]
    nahe_beta_user_sim_demo["sim.demo"]
    nahe_beta_user_sim_deps["sim.deps"]
    nahe_beta_user_sim_dimensions["sim.dimensions"]
    nahe_beta_user_sim_feeling["sim.feeling"]
    nahe_beta_user_sim_goals["sim.goals"]
    nahe_beta_user_sim_harness_adapter["sim.harness_adapter"]
    nahe_beta_user_sim_loop["sim.loop"]
    nahe_beta_user_sim_persona_client["sim.persona_client"]
    nahe_beta_user_sim_persona_io["sim.persona_io"]
    nahe_beta_user_sim_prompt["sim.prompt"]
    nahe_beta_user_sim_run_agentic["sim.run_agentic"]
    nahe_beta_user_sim_run_live["sim.run_live"]
    nahe_beta_user_sim_runtime["sim.runtime"]
    nahe_beta_user_sim_sandbox["sim.sandbox"]
    nahe_beta_user_sim_scenarios["sim.scenarios"]
    nahe_beta_user_sim_seed_source["sim.seed_source"]
    nahe_beta_user_sim_skills["sim.skills"]
    nahe_beta_user_sim_sources["sim.sources"]
    nahe_beta_user_sim_sources_container["sources.container"]
    nahe_beta_user_sim_sources_docker_seed["sources.docker_seed"]
    nahe_beta_user_sim_sources_empty["sources.empty"]
    nahe_beta_user_sim_sources_git["sources.git"]
    nahe_beta_user_sim_sources_local_fixture["sources.local_fixture"]
    nahe_beta_user_sim_sources_prebuilt["sources.prebuilt"]
    nahe_beta_user_sim_state["sim.state"]
    nahe_beta_user_sim_tools["sim.tools"]
    nahe_beta_user_sim_workspace["sim.workspace"]
    nahe_beta_web["ahe_beta.web"]
    nahe_beta_web_api["web.api"]
    nahe_beta_web_issue_timeline["web.issue_timeline"]
    nahe_beta_demand_agent_contract --> nahe_beta_demand_issue_schema
    nahe_beta_demand_agent_runtime --> nahe_beta_demand_evidence_contract
    nahe_beta_demand_agent_runtime --> nahe_beta_demand_observation_provider
    nahe_beta_demand_agent_runtime --> nahe_beta_demand_session_timeline
    nahe_beta_demand_agent_runtime --> nahe_beta_demand_source
    nahe_beta_demand_agent_runtime --> nahe_beta_invocation
    nahe_beta_demand_agent_runtime --> nahe_beta_loop_live_tracer
    nahe_beta_demand_agent_runtime --> nahe_beta_observations_gaps
    nahe_beta_demand_agent_runtime --> nahe_beta_observations_grants
    nahe_beta_demand_agent_runtime --> nahe_beta_usage
    nahe_beta_demand_agent_runtime --> nahe_beta_user_session_store
    nahe_beta_demand_architect --> nahe_beta_demand_agent_runtime
    nahe_beta_demand_architect --> nahe_beta_demand_issue_schema
    nahe_beta_demand_architect --> nahe_beta_demand_proposal_view
    nahe_beta_demand_architect --> nahe_beta_demand_role_contract
    nahe_beta_demand_architect --> nahe_beta_loop_recovery
    nahe_beta_demand_architect --> nahe_beta_models
    nahe_beta_demand_architect --> nahe_beta_observations_delivery_gaps
    nahe_beta_demand_architect --> nahe_beta_observations_grants
    nahe_beta_demand_architect --> nahe_beta_tracker_base
    nahe_beta_demand_architect --> nahe_beta_usage
    nahe_beta_demand_architect --> nahe_beta_user_session_store
    nahe_beta_demand_delivery_evidence --> nahe_beta_demand_evidence_contract
    nahe_beta_demand_delivery_evidence --> nahe_beta_execution_contract
    nahe_beta_demand_delivery_evidence --> nahe_beta_observations_grants
    nahe_beta_demand_delivery_evidence --> nahe_beta_observations_publication
    nahe_beta_demand_delivery_evidence --> nahe_beta_observations_transport
    nahe_beta_demand_divergent --> nahe_beta_demand_agent_runtime
    nahe_beta_demand_divergent --> nahe_beta_demand_evidence_contract
    nahe_beta_demand_divergent --> nahe_beta_demand_issue_schema
    nahe_beta_demand_divergent --> nahe_beta_demand_proposal_view
    nahe_beta_demand_divergent --> nahe_beta_demand_role_contract
    nahe_beta_demand_divergent --> nahe_beta_loop_recovery
    nahe_beta_demand_divergent --> nahe_beta_models
    nahe_beta_demand_divergent --> nahe_beta_observations_grants
    nahe_beta_demand_divergent --> nahe_beta_tracker_base
    nahe_beta_demand_divergent --> nahe_beta_usage
    nahe_beta_demand_divergent --> nahe_beta_user_session_store
    nahe_beta_demand_evidence_contract --> nahe_beta_execution_contract
    nahe_beta_demand_evidence_contract --> nahe_beta_models
    nahe_beta_demand_evidence_contract --> nahe_beta_usage
    nahe_beta_demand_grouped_architect --> nahe_beta_demand_architect
    nahe_beta_demand_grouped_architect --> nahe_beta_demand_issue_schema
    nahe_beta_demand_grouped_architect --> nahe_beta_demand_proposal_view
    nahe_beta_demand_grouped_architect --> nahe_beta_loop_recovery
    nahe_beta_demand_grouped_architect --> nahe_beta_models
    nahe_beta_demand_grouped_architect --> nahe_beta_observations_delivery_gaps
    nahe_beta_demand_grouped_architect --> nahe_beta_usage
    nahe_beta_demand_observation_provider --> nahe_beta_demand_evidence_contract
    nahe_beta_demand_observation_provider --> nahe_beta_invocation
    nahe_beta_demand_observation_provider --> nahe_beta_user_session_store
    nahe_beta_demand_owner --> nahe_beta_demand_agent_runtime
    nahe_beta_demand_owner --> nahe_beta_demand_delivery_evidence
    nahe_beta_demand_owner --> nahe_beta_demand_issue_schema
    nahe_beta_demand_owner --> nahe_beta_demand_proposal_view
    nahe_beta_demand_owner --> nahe_beta_demand_role_contract
    nahe_beta_demand_owner --> nahe_beta_loop_recovery
    nahe_beta_demand_owner --> nahe_beta_models
    nahe_beta_demand_owner --> nahe_beta_observations_grants
    nahe_beta_demand_owner --> nahe_beta_tracker_base
    nahe_beta_demand_owner --> nahe_beta_usage
    nahe_beta_demand_owner --> nahe_beta_user_session_store
    nahe_beta_demand_proposal_view --> nahe_beta_demand_evidence_contract
    nahe_beta_demand_proposal_view --> nahe_beta_demand_issue_schema
    nahe_beta_demand_proposal_view --> nahe_beta_observations_grants
    nahe_beta_demand_runtime_agg --> nahe_beta_models
    nahe_beta_demand_runtime_agg --> nahe_beta_user_session_store
    nahe_beta_demand_session_timeline --> nahe_beta_demand_evidence_contract
    nahe_beta_demand_session_timeline --> nahe_beta_demand_observation_provider
    nahe_beta_demand_session_timeline --> nahe_beta_models
    nahe_beta_demand_session_timeline --> nahe_beta_usage
    nahe_beta_demand_session_timeline --> nahe_beta_user_session_store
    nahe_beta_demand_triage --> nahe_beta_demand_agent_runtime
    nahe_beta_demand_triage --> nahe_beta_demand_evidence_contract
    nahe_beta_demand_triage --> nahe_beta_demand_issue_schema
    nahe_beta_demand_triage --> nahe_beta_demand_role_contract
    nahe_beta_demand_triage --> nahe_beta_demand_source
    nahe_beta_demand_triage --> nahe_beta_loop_recovery
    nahe_beta_demand_triage --> nahe_beta_observations_grants
    nahe_beta_demand_triage --> nahe_beta_tracker_base
    nahe_beta_demand_triage --> nahe_beta_tracker_gitea
    nahe_beta_demand_triage --> nahe_beta_usage
    nahe_beta_demand_triage --> nahe_beta_user_session_store
    nahe_beta_distill --> nahe_beta_distill_library
    nahe_beta_distill_seed_adapter --> nahe_beta_distill_seed_library
    nahe_beta_distill_seed_adapter --> nahe_beta_models
    nahe_beta_evaluation_acceptance --> nahe_beta_evaluation_results
    nahe_beta_evaluation_adapters_container --> nahe_beta_evaluation_contracts
    nahe_beta_evaluation_adapters_custom --> nahe_beta_evaluation_adapters_container
    nahe_beta_evaluation_adapters_custom --> nahe_beta_evaluation_adapters_terminal_bench
    nahe_beta_evaluation_adapters_custom --> nahe_beta_evaluation_contracts
    nahe_beta_evaluation_adapters_custom --> nahe_beta_evaluation_results
    nahe_beta_evaluation_adapters_nl2repo --> nahe_beta_evaluation_adapters_container
    nahe_beta_evaluation_adapters_nl2repo --> nahe_beta_evaluation_adapters_terminal_bench
    nahe_beta_evaluation_adapters_nl2repo --> nahe_beta_evaluation_contracts
    nahe_beta_evaluation_adapters_nl2repo --> nahe_beta_evaluation_results
    nahe_beta_evaluation_adapters_profiles --> nahe_beta_evaluation_adapters_container
    nahe_beta_evaluation_adapters_profiles --> nahe_beta_evaluation_contracts
    nahe_beta_evaluation_adapters_swebench --> nahe_beta_evaluation_adapters_container
    nahe_beta_evaluation_adapters_swebench --> nahe_beta_evaluation_contracts
    nahe_beta_evaluation_adapters_swebench --> nahe_beta_evaluation_results
    nahe_beta_evaluation_adapters_terminal_bench --> nahe_beta_evaluation_adapters_container
    nahe_beta_evaluation_adapters_terminal_bench --> nahe_beta_evaluation_adapters_profiles
    nahe_beta_evaluation_adapters_terminal_bench --> nahe_beta_evaluation_contracts
    nahe_beta_evaluation_adapters_terminal_bench --> nahe_beta_evaluation_results
    nahe_beta_evaluation_adapters_tua_bench --> nahe_beta_evaluation_adapters_container
    nahe_beta_evaluation_adapters_tua_bench --> nahe_beta_evaluation_adapters_profiles
    nahe_beta_evaluation_adapters_tua_bench --> nahe_beta_evaluation_adapters_terminal_bench
    nahe_beta_evaluation_adapters_tua_bench --> nahe_beta_evaluation_contracts
    nahe_beta_evaluation_adapters_tua_bench --> nahe_beta_evaluation_results
    nahe_beta_evaluation_artifacts --> nahe_beta_user_sim_runtime
    nahe_beta_evaluation_registry --> nahe_beta_evaluation_adapters_custom
    nahe_beta_evaluation_registry --> nahe_beta_evaluation_adapters_nl2repo
    nahe_beta_evaluation_registry --> nahe_beta_evaluation_adapters_swebench
    nahe_beta_evaluation_registry --> nahe_beta_evaluation_adapters_terminal_bench
    nahe_beta_evaluation_registry --> nahe_beta_evaluation_adapters_tua_bench
    nahe_beta_evaluation_registry --> nahe_beta_evaluation_contracts
    nahe_beta_evaluation_results --> nahe_beta_evaluation_contracts
    nahe_beta_evaluation_service --> nahe_beta_evaluation_contracts
    nahe_beta_evaluation_service --> nahe_beta_evaluation_registry
    nahe_beta_evaluation_service --> nahe_beta_evaluation_results
    nahe_beta_evaluation_service --> nahe_beta_execution_contract
    nahe_beta_evaluation_service --> nahe_beta_experiment_config
    nahe_beta_experiment_assessment_worker --> nahe_beta_evaluation_contracts
    nahe_beta_experiment_assessment_worker --> nahe_beta_evaluation_service
    nahe_beta_experiment_assessment_worker --> nahe_beta_execution_contract
    nahe_beta_experiment_assessment_worker --> nahe_beta_experiment_config
    nahe_beta_experiment_assessment_worker --> nahe_beta_experiment_grading
    nahe_beta_experiment_assessment_worker --> nahe_beta_experiment_grading_inputs
    nahe_beta_experiment_assessment_worker --> nahe_beta_experiment_runtime
    nahe_beta_experiment_assessment_worker --> nahe_beta_loop_round_assessment
    nahe_beta_experiment_backends --> nahe_beta_experiment_backends_base
    nahe_beta_experiment_backends_base --> nahe_beta_experiment_config
    nahe_beta_experiment_backends_e2b --> nahe_beta_demand_delivery_evidence
    nahe_beta_experiment_backends_e2b --> nahe_beta_experiment_backends_base
    nahe_beta_experiment_backends_e2b --> nahe_beta_experiment_backends_e2b_bootstrap
    nahe_beta_experiment_backends_e2b --> nahe_beta_experiment_backends_e2b_template
    nahe_beta_experiment_backends_e2b --> nahe_beta_experiment_workload
    nahe_beta_experiment_backends_e2b --> nahe_beta_loop_round_assessment
    nahe_beta_experiment_backends_e2b_bootstrap --> nahe_beta_experiment_backends_base
    nahe_beta_experiment_backends_e2b_bootstrap --> nahe_beta_experiment_config
    nahe_beta_experiment_backends_e2b_bootstrap --> nahe_beta_experiment_materials
    nahe_beta_experiment_backends_e2b_bootstrap --> nahe_beta_experiment_task_environments_contract
    nahe_beta_experiment_backends_e2b_bootstrap --> nahe_beta_experiment_task_environments_docker
    nahe_beta_experiment_backends_e2b_bootstrap --> nahe_beta_experiment_task_environments_materials
    nahe_beta_experiment_backends_e2b_template --> nahe_beta_experiment_backends_base
    nahe_beta_experiment_backends_e2b_template --> nahe_beta_experiment_workload
    nahe_beta_experiment_backends_local --> nahe_beta_experiment_backends
    nahe_beta_experiment_backends_local --> nahe_beta_experiment_backends_base
    nahe_beta_experiment_backends_local --> nahe_beta_experiment_backends_e2b_bootstrap
    nahe_beta_experiment_backends_local --> nahe_beta_experiment_backends_local_ci
    nahe_beta_experiment_backends_local --> nahe_beta_experiment_collection
    nahe_beta_experiment_backends_local --> nahe_beta_experiment_config
    nahe_beta_experiment_backends_local --> nahe_beta_experiment_context
    nahe_beta_experiment_backends_local --> nahe_beta_experiment_engine
    nahe_beta_experiment_backends_local --> nahe_beta_experiment_infrastructure
    nahe_beta_experiment_backends_local --> nahe_beta_experiment_materials
    nahe_beta_experiment_backends_local --> nahe_beta_experiment_task_environments
    nahe_beta_experiment_backends_local --> nahe_beta_experiment_task_environments_contract
    nahe_beta_experiment_backends_local --> nahe_beta_experiment_task_environments_docker
    nahe_beta_experiment_backends_local --> nahe_beta_experiment_workload
    nahe_beta_experiment_backends_local --> nahe_beta_loop_round_assessment
    nahe_beta_experiment_backends_local --> nahe_beta_observations_transport
    nahe_beta_experiment_backends_local_ci --> nahe_beta_experiment_backends_base
    nahe_beta_experiment_backends_local_ci --> nahe_beta_experiment_infrastructure
    nahe_beta_experiment_batch --> nahe_beta_experiment
    nahe_beta_experiment_batch --> nahe_beta_experiment_batch_config
    nahe_beta_experiment_batch --> nahe_beta_experiment_batch_store
    nahe_beta_experiment_batch --> nahe_beta_experiment_config
    nahe_beta_experiment_batch --> nahe_beta_experiment_manifest
    nahe_beta_experiment_batch --> nahe_beta_experiment_runtime
    nahe_beta_experiment_batch_config --> nahe_beta_experiment
    nahe_beta_experiment_batch_config --> nahe_beta_experiment_config
    nahe_beta_experiment_batch_config --> nahe_beta_experiment_materials
    nahe_beta_experiment_batch_config --> nahe_beta_experiment_task_environments_contract
    nahe_beta_experiment_batch_store --> nahe_beta_experiment
    nahe_beta_experiment_batch_store --> nahe_beta_experiment_batch_config
    nahe_beta_experiment_batch_store --> nahe_beta_experiment_config
    nahe_beta_experiment_batch_store --> nahe_beta_experiment_manifest
    nahe_beta_experiment_batch_store --> nahe_beta_experiment_materials
    nahe_beta_experiment_batch_store --> nahe_beta_experiment_runtime
    nahe_beta_experiment_batch_store --> nahe_beta_experiment_workload
    nahe_beta_experiment_cli --> nahe_beta_experiment
    nahe_beta_experiment_cli --> nahe_beta_experiment_assessment_worker
    nahe_beta_experiment_cli --> nahe_beta_experiment_batch
    nahe_beta_experiment_cli --> nahe_beta_experiment_config
    nahe_beta_experiment_cli --> nahe_beta_experiment_dashboard
    nahe_beta_experiment_cli --> nahe_beta_experiment_grading
    nahe_beta_experiment_cli --> nahe_beta_experiment_runtime
    nahe_beta_experiment_cli --> nahe_beta_experiment_task_import
    nahe_beta_experiment_collection --> nahe_beta_experiment_config
    nahe_beta_experiment_collection --> nahe_beta_experiment_continuation_export
    nahe_beta_experiment_collection --> nahe_beta_experiment_materials
    nahe_beta_experiment_config --> nahe_beta_experiment_model_limits
    nahe_beta_experiment_config --> nahe_beta_experiment_task_environments_contract
    nahe_beta_experiment_config --> nahe_beta_experiment_workload
    nahe_beta_experiment_context --> nahe_beta_execution_contract
    nahe_beta_experiment_context --> nahe_beta_experiment_config
    nahe_beta_experiment_context --> nahe_beta_experiment_workload
    nahe_beta_experiment_context --> nahe_beta_models
    nahe_beta_experiment_continuation_evidence --> nahe_beta_demand_evidence_contract
    nahe_beta_experiment_continuation_evidence --> nahe_beta_experiment_config
    nahe_beta_experiment_continuation_evidence --> nahe_beta_models
    nahe_beta_experiment_continuation_evidence --> nahe_beta_observations_grants
    nahe_beta_experiment_continuation_evidence --> nahe_beta_observations_publication
    nahe_beta_experiment_continuation_evidence --> nahe_beta_user_session_store
    nahe_beta_experiment_continuation_export --> nahe_beta_demand_issue_schema
    nahe_beta_experiment_continuation_export --> nahe_beta_experiment_config
    nahe_beta_experiment_continuation_export --> nahe_beta_experiment_materials
    nahe_beta_experiment_continuation_export --> nahe_beta_experiment_workload
    nahe_beta_experiment_continuation_export --> nahe_beta_loop_recovery
    nahe_beta_experiment_continuation_forge --> nahe_beta_demand_issue_schema
    nahe_beta_experiment_continuation_forge --> nahe_beta_experiment_config
    nahe_beta_experiment_continuation_forge --> nahe_beta_loop_recovery
    nahe_beta_experiment_continuation_forge --> nahe_beta_models
    nahe_beta_experiment_continuation_forge --> nahe_beta_tracker_base
    nahe_beta_experiment_continuation_source --> nahe_beta_demand_issue_schema
    nahe_beta_experiment_continuation_source --> nahe_beta_experiment_config
    nahe_beta_experiment_continuation_source --> nahe_beta_experiment_task_environments_contract
    nahe_beta_experiment_continuation_source --> nahe_beta_experiment_workload
    nahe_beta_experiment_controllers_feedback --> nahe_beta_demand_architect
    nahe_beta_experiment_controllers_feedback --> nahe_beta_demand_divergent
    nahe_beta_experiment_controllers_feedback --> nahe_beta_demand_grouped_architect
    nahe_beta_experiment_controllers_feedback --> nahe_beta_demand_owner
    nahe_beta_experiment_controllers_feedback --> nahe_beta_demand_triage
    nahe_beta_experiment_controllers_feedback --> nahe_beta_experiment_config
    nahe_beta_experiment_controllers_feedback --> nahe_beta_experiment_context
    nahe_beta_experiment_controllers_feedback --> nahe_beta_experiment_continuation_evidence
    nahe_beta_experiment_controllers_feedback --> nahe_beta_experiment_continuation_forge
    nahe_beta_experiment_controllers_feedback --> nahe_beta_experiment_materials
    nahe_beta_experiment_controllers_feedback --> nahe_beta_loop_feedback_pipeline
    nahe_beta_experiment_controllers_feedback --> nahe_beta_loop_recovery
    nahe_beta_experiment_controllers_feedback --> nahe_beta_observations_grants
    nahe_beta_experiment_controllers_runtime --> nahe_beta_demand_issue_schema
    nahe_beta_experiment_controllers_runtime --> nahe_beta_guards_harness_boundary
    nahe_beta_experiment_controllers_runtime --> nahe_beta_invocation
    nahe_beta_experiment_controllers_runtime --> nahe_beta_loop_live
    nahe_beta_experiment_controllers_runtime --> nahe_beta_loop_recovery
    nahe_beta_experiment_controllers_runtime --> nahe_beta_loop_sim_user
    nahe_beta_experiment_controllers_runtime --> nahe_beta_observations_preflight
    nahe_beta_experiment_controllers_runtime --> nahe_beta_observations_transport
    nahe_beta_experiment_controllers_runtime --> nahe_beta_tracker_attachment_transport
    nahe_beta_experiment_controllers_runtime --> nahe_beta_tracker_gitea
    nahe_beta_experiment_controllers_unified --> nahe_beta_distill_library
    nahe_beta_experiment_controllers_unified --> nahe_beta_experiment_collection
    nahe_beta_experiment_controllers_unified --> nahe_beta_experiment_config
    nahe_beta_experiment_controllers_unified --> nahe_beta_experiment_context
    nahe_beta_experiment_controllers_unified --> nahe_beta_experiment_continuation_export
    nahe_beta_experiment_controllers_unified --> nahe_beta_experiment_controllers
    nahe_beta_experiment_controllers_unified --> nahe_beta_experiment_controllers_feedback
    nahe_beta_experiment_controllers_unified --> nahe_beta_experiment_controllers_runtime
    nahe_beta_experiment_controllers_unified --> nahe_beta_guards_repo_guard
    nahe_beta_experiment_controllers_unified --> nahe_beta_harness_launcher
    nahe_beta_experiment_controllers_unified --> nahe_beta_invocation
    nahe_beta_experiment_controllers_unified --> nahe_beta_loop_live
    nahe_beta_experiment_controllers_unified --> nahe_beta_loop_metrics
    nahe_beta_experiment_controllers_unified --> nahe_beta_loop_orchestrator
    nahe_beta_experiment_controllers_unified --> nahe_beta_loop_roster
    nahe_beta_experiment_controllers_unified --> nahe_beta_loop_round_assessment
    nahe_beta_experiment_controllers_unified --> nahe_beta_loop_round_gate
    nahe_beta_experiment_controllers_unified --> nahe_beta_loop_sim_user
    nahe_beta_experiment_controllers_unified --> nahe_beta_models
    nahe_beta_experiment_controllers_unified --> nahe_beta_tracker_gitea
    nahe_beta_experiment_controllers_unified --> nahe_beta_usage
    nahe_beta_experiment_controllers_unified --> nahe_beta_user_session_store
    nahe_beta_experiment_controllers_unified --> nahe_beta_user_sim_persona_client
    nahe_beta_experiment_controllers_unified --> nahe_beta_user_sim_persona_io
    nahe_beta_experiment_dashboard --> nahe_beta_experiment_config
    nahe_beta_experiment_dashboard --> nahe_beta_experiment_manifest
    nahe_beta_experiment_dashboard --> nahe_beta_experiment_materials
    nahe_beta_experiment_dashboard --> nahe_beta_experiment_runtime
    nahe_beta_experiment_dashboard --> nahe_beta_tracker_gitea
    nahe_beta_experiment_dashboard --> nahe_beta_usage
    nahe_beta_experiment_dashboard --> nahe_beta_user_session_store
    nahe_beta_experiment_dashboard --> nahe_beta_web_api
    nahe_beta_experiment_engine --> nahe_beta_experiment_config
    nahe_beta_experiment_engine --> nahe_beta_experiment_context
    nahe_beta_experiment_engine --> nahe_beta_experiment_materials
    nahe_beta_experiment_grading --> nahe_beta_evaluation_acceptance
    nahe_beta_experiment_grading --> nahe_beta_evaluation_contracts
    nahe_beta_experiment_grading --> nahe_beta_evaluation_registry
    nahe_beta_experiment_grading --> nahe_beta_evaluation_service
    nahe_beta_experiment_grading --> nahe_beta_experiment_config
    nahe_beta_experiment_grading --> nahe_beta_experiment_grading_inputs
    nahe_beta_experiment_grading --> nahe_beta_experiment_manifest
    nahe_beta_experiment_grading --> nahe_beta_experiment_materials
    nahe_beta_experiment_grading --> nahe_beta_experiment_runtime
    nahe_beta_experiment_grading --> nahe_beta_experiment_workload
    nahe_beta_experiment_grading --> nahe_beta_loop_recovery
    nahe_beta_experiment_grading --> nahe_beta_models
    nahe_beta_experiment_grading_inputs --> nahe_beta_evaluation_contracts
    nahe_beta_experiment_grading_inputs --> nahe_beta_experiment_config
    nahe_beta_experiment_grading_inputs --> nahe_beta_experiment_task_environments_contract
    nahe_beta_experiment_infrastructure --> nahe_beta_experiment_backends_local_ci
    nahe_beta_experiment_infrastructure --> nahe_beta_experiment_config
    nahe_beta_experiment_manifest --> nahe_beta_experiment_config
    nahe_beta_experiment_materials --> nahe_beta_distill_library
    nahe_beta_experiment_materials --> nahe_beta_experiment_assessment_worker
    nahe_beta_experiment_materials --> nahe_beta_experiment_config
    nahe_beta_experiment_materials --> nahe_beta_experiment_continuation_forge
    nahe_beta_experiment_materials --> nahe_beta_experiment_continuation_source
    nahe_beta_experiment_materials --> nahe_beta_experiment_task_environments_materials
    nahe_beta_experiment_materials --> nahe_beta_experiment_workload
    nahe_beta_experiment_materials --> nahe_beta_user_sim_persona_io
    nahe_beta_experiment_model_limits --> nahe_beta_experiment_config
    nahe_beta_experiment_runtime --> nahe_beta_experiment_assessment_worker
    nahe_beta_experiment_runtime --> nahe_beta_experiment_backends_e2b
    nahe_beta_experiment_runtime --> nahe_beta_experiment_backends_local
    nahe_beta_experiment_runtime --> nahe_beta_experiment_collection
    nahe_beta_experiment_runtime --> nahe_beta_experiment_config
    nahe_beta_experiment_runtime --> nahe_beta_experiment_engine
    nahe_beta_experiment_runtime --> nahe_beta_experiment_manifest
    nahe_beta_experiment_runtime --> nahe_beta_experiment_materials
    nahe_beta_experiment_runtime --> nahe_beta_experiment_workload
    nahe_beta_experiment_task_environments_docker --> nahe_beta_experiment_task_environments_contract
    nahe_beta_experiment_task_environments_docker --> nahe_beta_experiment_task_environments_materials
    nahe_beta_experiment_task_environments_docker --> nahe_beta_observations_publication
    nahe_beta_experiment_task_environments_docker --> nahe_beta_user_sim_runtime
    nahe_beta_experiment_task_environments_materials --> nahe_beta_experiment_task_environments_contract
    nahe_beta_experiment_task_import --> nahe_beta_distill_seed_library
    nahe_beta_experiment_task_import --> nahe_beta_experiment_config
    nahe_beta_experiment_task_import --> nahe_beta_experiment_workload
    nahe_beta_experiment_workload --> nahe_beta_experiment_config
    nahe_beta_experiment_workload --> nahe_beta_experiment_context
    nahe_beta_experiment_workload --> nahe_beta_experiment_materials
    nahe_beta_experiment_workload --> nahe_beta_experiment_task_environments_contract
    nahe_beta_guards_workspace_jail --> nahe_beta_demand_observation_provider
    nahe_beta_guards_workspace_jail --> nahe_beta_usage
    nahe_beta_harness_connector --> nahe_beta_harness_interface
    nahe_beta_harness_connector --> nahe_beta_usage
    nahe_beta_harness_launcher --> nahe_beta_execution_contract
    nahe_beta_harness_launcher --> nahe_beta_harness_budget
    nahe_beta_harness_launcher --> nahe_beta_harness_interface
    nahe_beta_harness_launcher --> nahe_beta_observations_publication
    nahe_beta_harness_launcher --> nahe_beta_user_sim_runtime
    nahe_beta_invocation --> nahe_beta_usage
    nahe_beta_loop_feedback_pipeline --> nahe_beta_demand_source
    nahe_beta_loop_feedback_pipeline --> nahe_beta_loop_recovery
    nahe_beta_loop_feedback_pipeline --> nahe_beta_loop_round_gate
    nahe_beta_loop_feedback_pipeline --> nahe_beta_models
    nahe_beta_loop_feedback_pipeline --> nahe_beta_usage
    nahe_beta_loop_live_tracer --> nahe_beta_usage
    nahe_beta_loop_metrics --> nahe_beta_demand_issue_schema
    nahe_beta_loop_metrics --> nahe_beta_tracker_base
    nahe_beta_loop_metrics --> nahe_beta_user_session_store
    nahe_beta_loop_orchestrator --> nahe_beta_demand_architect
    nahe_beta_loop_orchestrator --> nahe_beta_demand_divergent
    nahe_beta_loop_orchestrator --> nahe_beta_demand_source
    nahe_beta_loop_orchestrator --> nahe_beta_harness_interface
    nahe_beta_loop_orchestrator --> nahe_beta_harness_launcher
    nahe_beta_loop_orchestrator --> nahe_beta_loop_feedback_pipeline
    nahe_beta_loop_orchestrator --> nahe_beta_loop_recovery
    nahe_beta_loop_orchestrator --> nahe_beta_loop_round_gate
    nahe_beta_loop_orchestrator --> nahe_beta_models
    nahe_beta_loop_orchestrator --> nahe_beta_usage
    nahe_beta_loop_orchestrator --> nahe_beta_user_sim_deps
    nahe_beta_loop_orchestrator --> nahe_beta_user_sim_runtime
    nahe_beta_loop_orchestrator --> nahe_beta_user_sim_workspace
    nahe_beta_loop_round_assessment --> nahe_beta_execution_contract
    nahe_beta_loop_round_assessment --> nahe_beta_experiment_config
    nahe_beta_loop_round_assessment --> nahe_beta_experiment_workload
    nahe_beta_loop_round_assessment --> nahe_beta_loop_recovery
    nahe_beta_loop_runner --> nahe_beta_loop_checkpoint
    nahe_beta_loop_runner --> nahe_beta_loop_orchestrator
    nahe_beta_loop_runner --> nahe_beta_loop_run_state
    nahe_beta_loop_sim_user --> nahe_beta_demand_evidence_contract
    nahe_beta_loop_sim_user --> nahe_beta_demand_issue_schema
    nahe_beta_loop_sim_user --> nahe_beta_evaluation_artifacts
    nahe_beta_loop_sim_user --> nahe_beta_execution_contract
    nahe_beta_loop_sim_user --> nahe_beta_harness_connector
    nahe_beta_loop_sim_user --> nahe_beta_harness_interface
    nahe_beta_loop_sim_user --> nahe_beta_loop_recovery
    nahe_beta_loop_sim_user --> nahe_beta_models
    nahe_beta_loop_sim_user --> nahe_beta_observations_preflight
    nahe_beta_loop_sim_user --> nahe_beta_observations_publication
    nahe_beta_loop_sim_user --> nahe_beta_tracker_base
    nahe_beta_loop_sim_user --> nahe_beta_usage
    nahe_beta_loop_sim_user --> nahe_beta_user_patches
    nahe_beta_loop_sim_user --> nahe_beta_user_session_store
    nahe_beta_loop_sim_user --> nahe_beta_user_sim_deps
    nahe_beta_loop_sim_user --> nahe_beta_user_sim_dimensions
    nahe_beta_loop_sim_user --> nahe_beta_user_sim_feeling
    nahe_beta_loop_sim_user --> nahe_beta_user_sim_loop
    nahe_beta_loop_sim_user --> nahe_beta_user_sim_persona_client
    nahe_beta_loop_sim_user --> nahe_beta_user_sim_prompt
    nahe_beta_loop_sim_user --> nahe_beta_user_sim_runtime
    nahe_beta_loop_sim_user --> nahe_beta_user_sim_seed_source
    nahe_beta_loop_sim_user --> nahe_beta_user_sim_workspace
    nahe_beta_models --> nahe_beta_execution_contract
    nahe_beta_models --> nahe_beta_usage
    nahe_beta_observations___main__ --> nahe_beta_observations_publication
    nahe_beta_observations_delivery_gaps --> nahe_beta_observations_gaps
    nahe_beta_observations_delivery_gaps --> nahe_beta_observations_grants
    nahe_beta_observations_gaps --> nahe_beta_demand_issue_schema
    nahe_beta_observations_gaps --> nahe_beta_invocation
    nahe_beta_observations_gaps --> nahe_beta_models
    nahe_beta_observations_gaps --> nahe_beta_observations_grants
    nahe_beta_observations_gaps --> nahe_beta_usage
    nahe_beta_observations_grants --> nahe_beta_observations_publication
    nahe_beta_observations_preflight --> nahe_beta_observations_publication
    nahe_beta_observations_preflight --> nahe_beta_observations_transport
    nahe_beta_observations_publication --> nahe_beta_invocation
    nahe_beta_tracker_base --> nahe_beta_models
    nahe_beta_tracker_fake --> nahe_beta_models
    nahe_beta_tracker_fake --> nahe_beta_tracker_base
    nahe_beta_tracker_gitea --> nahe_beta_models
    nahe_beta_tracker_gitea --> nahe_beta_observations_transport
    nahe_beta_tracker_gitea --> nahe_beta_tracker_attachment_transport
    nahe_beta_tracker_gitea --> nahe_beta_tracker_base
    nahe_beta_user_session_store --> nahe_beta_demand_evidence_contract
    nahe_beta_user_session_store --> nahe_beta_execution_contract
    nahe_beta_user_session_store --> nahe_beta_models
    nahe_beta_user_sim --> nahe_beta_user_sim_dimensions
    nahe_beta_user_sim --> nahe_beta_user_sim_feeling
    nahe_beta_user_sim --> nahe_beta_user_sim_harness_adapter
    nahe_beta_user_sim --> nahe_beta_user_sim_loop
    nahe_beta_user_sim --> nahe_beta_user_sim_persona_client
    nahe_beta_user_sim --> nahe_beta_user_sim_persona_io
    nahe_beta_user_sim_action_space --> nahe_beta_user_sim_actions
    nahe_beta_user_sim_action_space --> nahe_beta_user_sim_dimensions
    nahe_beta_user_sim_action_space --> nahe_beta_user_sim_state
    nahe_beta_user_sim_clauses --> nahe_beta_user_sim_dimensions
    nahe_beta_user_sim_demo --> nahe_beta_user_sim_dimensions
    nahe_beta_user_sim_demo --> nahe_beta_user_sim_harness_adapter
    nahe_beta_user_sim_demo --> nahe_beta_user_sim_loop
    nahe_beta_user_sim_demo --> nahe_beta_user_sim_persona_client
    nahe_beta_user_sim_demo --> nahe_beta_user_sim_state
    nahe_beta_user_sim_deps --> nahe_beta_models
    nahe_beta_user_sim_deps --> nahe_beta_user_sim_runtime
    nahe_beta_user_sim_loop --> nahe_beta_usage
    nahe_beta_user_sim_loop --> nahe_beta_user_sim_action_space
    nahe_beta_user_sim_loop --> nahe_beta_user_sim_actions
    nahe_beta_user_sim_loop --> nahe_beta_user_sim_dimensions
    nahe_beta_user_sim_loop --> nahe_beta_user_sim_feeling
    nahe_beta_user_sim_loop --> nahe_beta_user_sim_goals
    nahe_beta_user_sim_loop --> nahe_beta_user_sim_persona_client
    nahe_beta_user_sim_loop --> nahe_beta_user_sim_prompt
    nahe_beta_user_sim_loop --> nahe_beta_user_sim_state
    nahe_beta_user_sim_persona_client --> nahe_beta_usage
    nahe_beta_user_sim_persona_client --> nahe_beta_user_sim_actions
    nahe_beta_user_sim_persona_client --> nahe_beta_user_sim_prompt
    nahe_beta_user_sim_persona_client --> nahe_beta_user_sim_runtime
    nahe_beta_user_sim_persona_client --> nahe_beta_user_sim_sandbox
    nahe_beta_user_sim_persona_client --> nahe_beta_user_sim_skills
    nahe_beta_user_sim_persona_client --> nahe_beta_user_sim_state
    nahe_beta_user_sim_persona_client --> nahe_beta_user_sim_tools
    nahe_beta_user_sim_persona_io --> nahe_beta_distill_library
    nahe_beta_user_sim_persona_io --> nahe_beta_user_sim_dimensions
    nahe_beta_user_sim_prompt --> nahe_beta_user_sim_clauses
    nahe_beta_user_sim_prompt --> nahe_beta_user_sim_dimensions
    nahe_beta_user_sim_prompt --> nahe_beta_user_sim_skills
    nahe_beta_user_sim_prompt --> nahe_beta_user_sim_state
    nahe_beta_user_sim_prompt --> nahe_beta_user_sim_tools
    nahe_beta_user_sim_run_agentic --> nahe_beta_models
    nahe_beta_user_sim_run_agentic --> nahe_beta_user_sim_demo
    nahe_beta_user_sim_run_agentic --> nahe_beta_user_sim_loop
    nahe_beta_user_sim_run_agentic --> nahe_beta_user_sim_persona_client
    nahe_beta_user_sim_run_agentic --> nahe_beta_user_sim_run_live
    nahe_beta_user_sim_run_agentic --> nahe_beta_user_sim_sandbox
    nahe_beta_user_sim_run_agentic --> nahe_beta_user_sim_scenarios
    nahe_beta_user_sim_run_agentic --> nahe_beta_user_sim_workspace
    nahe_beta_user_sim_run_live --> nahe_beta_user_sim_demo
    nahe_beta_user_sim_run_live --> nahe_beta_user_sim_dimensions
    nahe_beta_user_sim_run_live --> nahe_beta_user_sim_loop
    nahe_beta_user_sim_run_live --> nahe_beta_user_sim_persona_client
    nahe_beta_user_sim_run_live --> nahe_beta_user_sim_scenarios
    nahe_beta_user_sim_sandbox --> nahe_beta_user_sim_runtime
    nahe_beta_user_sim_seed_source --> nahe_beta_models
    nahe_beta_user_sim_seed_source --> nahe_beta_user_sim
    nahe_beta_user_sim_seed_source --> nahe_beta_user_sim_runtime
    nahe_beta_user_sim_seed_source --> nahe_beta_user_sim_sources
    nahe_beta_user_sim_skills --> nahe_beta_user_sim_dimensions
    nahe_beta_user_sim_sources_container --> nahe_beta_experiment_task_environments_contract
    nahe_beta_user_sim_sources_container --> nahe_beta_experiment_task_environments_docker
    nahe_beta_user_sim_sources_container --> nahe_beta_models
    nahe_beta_user_sim_sources_container --> nahe_beta_usage
    nahe_beta_user_sim_sources_container --> nahe_beta_user_sim_seed_source
    nahe_beta_user_sim_sources_docker_seed --> nahe_beta_models
    nahe_beta_user_sim_sources_docker_seed --> nahe_beta_usage
    nahe_beta_user_sim_sources_docker_seed --> nahe_beta_user_sim_runtime
    nahe_beta_user_sim_sources_docker_seed --> nahe_beta_user_sim_seed_source
    nahe_beta_user_sim_sources_empty --> nahe_beta_models
    nahe_beta_user_sim_sources_empty --> nahe_beta_user_sim_runtime
    nahe_beta_user_sim_sources_empty --> nahe_beta_user_sim_seed_source
    nahe_beta_user_sim_sources_git --> nahe_beta_models
    nahe_beta_user_sim_sources_git --> nahe_beta_user_sim_seed_source
    nahe_beta_user_sim_sources_local_fixture --> nahe_beta_models
    nahe_beta_user_sim_sources_local_fixture --> nahe_beta_user_sim_runtime
    nahe_beta_user_sim_sources_local_fixture --> nahe_beta_user_sim_seed_source
    nahe_beta_user_sim_sources_local_fixture --> nahe_beta_user_sim_workspace
    nahe_beta_user_sim_sources_prebuilt --> nahe_beta_models
    nahe_beta_user_sim_sources_prebuilt --> nahe_beta_usage
    nahe_beta_user_sim_sources_prebuilt --> nahe_beta_user_sim_deps
    nahe_beta_user_sim_sources_prebuilt --> nahe_beta_user_sim_runtime
    nahe_beta_user_sim_sources_prebuilt --> nahe_beta_user_sim_seed_source
    nahe_beta_user_sim_state --> nahe_beta_user_sim_dimensions
    nahe_beta_user_sim_tools --> nahe_beta_user_sim_dimensions
    nahe_beta_user_sim_tools --> nahe_beta_user_sim_sandbox
    nahe_beta_user_sim_workspace --> nahe_beta_models
    nahe_beta_user_sim_workspace --> nahe_beta_user_sim_runtime
    nahe_beta_user_sim_workspace --> nahe_beta_user_sim_seed_source
    nahe_beta_web_api --> nahe_beta_demand_issue_schema
    nahe_beta_web_api --> nahe_beta_loop_live
    nahe_beta_web_api --> nahe_beta_loop_metrics
    nahe_beta_web_api --> nahe_beta_loop_roster
    nahe_beta_web_api --> nahe_beta_tracker_base
    nahe_beta_web_api --> nahe_beta_tracker_gitea
    nahe_beta_web_api --> nahe_beta_usage
    nahe_beta_web_api --> nahe_beta_user_session_store
    nahe_beta_web_api --> nahe_beta_web_issue_timeline
    nahe_beta_web_issue_timeline --> nahe_beta_demand_issue_schema
```
