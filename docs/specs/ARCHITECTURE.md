# 架构现状（ARCHITECTURE）

> 本文件由 `spec graph` 自动生成，请勿手工编辑。源 = `backend/auto_designer/` 的代码与 docstring。

## 子系统与组件

### auto_designer

_auto-designer: 自进化 harness（用户侧 a）。_

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | auto-designer: 自进化 harness（用户侧 a）。 |
| `invocation.py` | Persist one JSON file per role invocation under ROLE_RUNS_DIR. |
| `models.py` | 用户侧最小链路的公共数据结构（spec-0001/T1）。 |
| `nexau_runtime.py` | 单一 nexau 适配层（spec-0003/T2）：把一份角色定义(prompt+工具)加载成可调用 Agent。 |
| `usage.py` | Best-effort, per-call LLM usage telemetry. |

### auto_designer.demand

_Product discovery, proposal synthesis, and admission decision roles._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Product discovery, proposal synthesis, and admission decision roles. |
| `agent_contract.py` | 由 issue_schema.SCHEMAS 生成各 producer 的 submit 工具 input_schema——契约与 schema 同源， |
| `agent_runtime.py` | 四个 driver（triage / synthesize / divergent / owner）此前各抄一份的公共逻辑收拢于此： |
| `delivery_evidence.py` | Publish issue-scoped opaque evidence through the existing forge boundary. |
| `divergent.py` | Divergent（能力发现）驱动器。 |
| `evidence_contract.py` | Goal-aware evidence contracts for demand-side roles. |
| `grouped_synthesizer.py` | Group a proposal snapshot once, then give each group to one existing Synthesizer. |
| `issue_schema.py` | 标准 issue 格式的单一真源（平台层，dev 够不着——issue 格式是平台制品，不可被 harness 进化改动）。 |
| `observation_provider.py` | Spec-0059: discover and read artifact-owned diagnostic files with ordinary tools. |
| `owner.py` | Owner 驱动器：把 proposal 无损打包并交接给 OpenAgents。 |
| `proposal_view.py` | Canonical normalized proposal projection shared by all downstream roles. |
| `role_contract.py` | Spec-0043: task-independent cognitive contracts for demand-side roles. |
| `runtime_agg.py` | 运行时行为聚合：从已落盘 Session 事后扫出任务无关指标，喂结构综合作机制层判别证据。 |
| `session_timeline.py` | 结构综合按需取用：从落盘 Session 投影「使用事件时间线」。 |
| `submit_tools.py` | submit 工具的 binding。 |
| `synthesizer.py` | Synthesizer 驱动器。 |
| `triage.py` | Triage（报告规范化）驱动器。 |

### auto_designer.distill

_蒸馏侧（spec-0006）：persona 卡库读写 + 契约约束校验。_

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | 蒸馏侧（spec-0006）：persona 卡库读写 + 契约约束校验。 |
| `library.py` | PersonaLibrary（spec-0006/T1）：persona 卡库的最小读写 + 契约约束校验。 |
| `seed_adapter.py` | seed_adapter.py（spec-0010/T2）：把种子卡注入 0009 的 SeedSource 供给。 |
| `seed_library.py` | SeedLibrary（spec-0010/T1）：种子卡库的最小读写 + 契约约束校验。 |

### auto_designer.evaluation

_Objective evaluators kept separate from simulated-user judgment._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Objective evaluators kept separate from simulated-user judgment. |
| `swebench.py` | Official fresh-container SWE-bench objective evidence (spec-0051/T4). |

### auto_designer.experiment

_Frozen materials, controllers and local/E2B resource lifecycles._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Frozen materials, controllers and local/E2B resource lifecycles. |
| `batch.py` | Spec-0074/T2: foreground batches reuse single-run lifecycle and durable leases. |
| `batch_config.py` | Spec-0074/T1: strict batch inputs and identities using the existing material compiler. |
| `batch_store.py` | Spec-0074/T1: immutable batch intent, atomic receipts and owned child roots. |
| `cli.py` | Operator-facing commands with credential-free lifecycle receipts. |
| `collection.py` | Spec-0069/T5: portable, checksummed evidence collection independent of model keys. |
| `config.py` | Spec-0071/T3: strict public v2 configuration and shared identity helpers. |
| `context.py` | Spec-0069/T2: one credential-free context and model mapping for both runners. |
| `dashboard.py` | Spec-0072/T4: read-only dashboard bound to a prepared run, without provider discovery. |
| `engine.py` | Spec-0069/T2: supervise the existing controller, with owned PIDs and receipts. |
| `grading.py` | Spec-0075/T2: grade immutable collected sessions without resuming an experiment. |
| `infrastructure.py` | Provision, stop, and destroy experiment infrastructure via Compose project. |
| `manifest.py` | Spec-0071/T3: immutable input manifests and shared append-only runtime facts. |
| `materials.py` | Spec-0069/T1: compile operator inputs into a checksummed, credential-free run bundle. |
| `runtime.py` | Manage prepared experiments without rewriting their frozen identities. |
| `task_import.py` | Spec-0076/T1: offline conversion into the existing ordinary task package contract. |
| `workload.py` | Spec-0073/T1: logical task catalog and session plan, independent of providers. |

### auto_designer.experiment.backends

_Spec-0069/T2: execution adapters implement the same experiment lifecycle._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Spec-0069/T2: execution adapters implement the same experiment lifecycle. |
| `base.py` | Spec-0069/T2: provider resources are mutable facts, never frozen config fields. |
| `e2b.py` | Spec-0069/T4: identity-owned E2B execution and user-owned Gitea.com evidence. |
| `e2b_bootstrap.py` | Spec-0069/T4: portable frozen-input bootstrap, without developer home files. |
| `e2b_template.py` | Spec-0069/T4: cache a verified build identity, then inspect actual sandbox resources. |
| `local.py` | Spec-0069/T3: frozen local toolchains and an experiment-owned Docker stack. |

### auto_designer.experiment.controllers

_Spec-0073/T4: one unified controller backed by shared experiment runtime._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Spec-0073/T4: one unified controller backed by shared experiment runtime. |
| `runtime.py` | Spec-0073/T4: shared experiment runtime: repository, delivery process and round receipts. |
| `unified.py` | Spec-0073/T4: unified frozen-task experiment controller. Start through the experiment CLI. |

### auto_designer.guards

_Spec-0068/T1: repository integrity, commit boundaries and tool path checks._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Spec-0068/T1: repository integrity, commit boundaries and tool path checks. |
| `harness_boundary.py` | harness 提交边界闸：拦住密钥和 vigil 运行态，不再用顶层白名单锁死产品形状。 |
| `repo_guard.py` | repo_guard：编排仓完整性快照与校验。 |
| `workspace_jail.py` | WorkspaceJailMiddleware：dev/synthesizer 以 harness 仓为可写工作区；NexAU 源码与运行时产物只读放行。 |

### auto_designer.harness

_Evaluation harness integration and execution support._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Evaluation harness integration and execution support. |
| `connector.py` | Platform-side connector from simulated users to the harness human-facing interface. |
| `interface.py` | harness 多轮对话契约 HarnessInterface + 测试后端 FakeHarness（spec-0001/T2）。 |
| `launcher.py` | harness launcher（spec-0003/T1）：把某版 harness 程序接成 spec-0001 的 HarnessInterface。 |

### auto_designer.loop

_Conversation-loop coordination, tracing, and lifecycle management._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Conversation-loop coordination, tracing, and lifecycle management. |
| `checkpoint.py` | checkpoint 存取（spec-0004/T1）：把自包含 STATE_DIR 打包成可下载 artifact，反向还原。 |
| `live.py` | 多 agent 活动注册表（流式观测）：各 agent（用户/创新者/开发者）的实时状态写到 data/live/。 |
| `live_tracer.py` | StepTracer：把 nexau agent 运行中的过程流成看板可见的结构化事件。 |
| `metrics.py` | metrics（spec-0003/T6，曲线口径 spec-0025/T7）：统计体感与 issue backlog 随时间的曲线。 |
| `orchestrator.py` | 闭环编排 orchestrator（需求面）。 |
| `recovery.py` | Durable stage and work-item recovery ledger. |
| `roster.py` | 角色编制（roster）：各类 agent 的数量，作为「后端编排」与「前端小镇房间」的单一真源。 |
| `round_gate.py` | Wait until this round's admitted issues reach a delivery terminal state. |
| `run_state.py` | run_state（spec-0004/T1）：编排游标 + 三侧中间态标记，作为「无法从产物观测」之外的兜底。 |
| `runner.py` | 可恢复 Harbor runner（Spec-0004/T2, Spec-0064/T2）。 |
| `sim_user.py` | 把 spec-0005 控制信封 sim 用户 agent 接进 spec-0003/0007 闭环。 |

### auto_designer.observations

_Artifact-owned observations with platform-owned collection and authorization._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Artifact-owned observations with platform-owned collection and authorization. |
| `__main__.py` | Explicit recovery: python -m auto_designer.observations --root ROOT --receipt FILE. |
| `delivery_gaps.py` | Ingest only authenticated delivery requests, never arbitrary comments or logs. |
| `gaps.py` | Spec-0061: scoped maintainer diagnostic gaps with a durable outbox. |
| `grants.py` | Persist evidence authority separately from model-authored issue text. |
| `preflight.py` | Spec-0070/T3: freeze transport and verify the actual delivery reader before models run. |
| `publication.py` | Collect bounded opaque artifact files and publish immutable session evidence. |
| `transport.py` | Spec-0070/T2: freeze transport separately from the historical framework contract. |

### auto_designer.tracker

_Issue-tracker integration and proposal state management._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Issue-tracker integration and proposal state management. |
| `attachment_transport.py` | Spec-0070/T1: explicit formats and the fixed Gitea.com signed-download boundary. |
| `base.py` | IssueTracker 协议（spec-0001/T5）：issue 提交去向的抽象，用户侧不绑定具体后端。 |
| `fake.py` | FakeTracker（spec-0001/T5）：IssueTracker 的内存实现，供单测与无 Gitea 环境端到端跑通。 |
| `gitea.py` | GiteaTracker（spec-0002/T2）：spec-0001/T5 IssueTracker 接口的真后端。 |

### auto_designer.user

_User simulation, personas, and interaction evidence collection._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | User simulation, personas, and interaction evidence collection. |
| `patches.py` | Immutable full session predictions for post-run grading (Spec-0075/T1). |
| `session_store.py` | 本地 SessionStore（spec-0001/T6）：一局 Session 全量落盘 + 单一总索引。 |

### auto_designer.user.sim

_auto_designer.user.sim —— persona 驱动的 harness 用户模拟器(控制信封架构, 纯主观)。_

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | auto_designer.user.sim —— persona 驱动的 harness 用户模拟器(控制信封架构, 纯主观)。 |
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

### auto_designer.user.sim.sources

_SeedSource 实现子包（spec-0009/T1）。_

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | SeedSource 实现子包（spec-0009/T1）。 |
| `docker_seed.py` | Runnable Docker seed source (spec-0051/T2). |
| `empty.py` | empty SeedSource（spec-0009/T2）。 |
| `git.py` | git SeedSource（spec-0009/T4）。 |
| `local_fixture.py` | local-fixture SeedSource（spec-0009/T1）。 |
| `prebuilt.py` | Spec-0073/T3: copy pure task source and rebuild each managed session's venv. |

### auto_designer.web

_Web application endpoints and runtime composition._

| 组件 | 职责（文件级 docstring 首行） |
|----|----|
| `__init__.py` | Web application endpoints and runtime composition. |
| `api.py` | 前端观测看板的只读 HTTP 层（FastAPI）。 |
| `issue_timeline.py` | Spec-0039/T2：把 Gitea label timeline 折叠为可回放的 issue 状态与完整性异常。 |

## 依赖关系图（import）

```mermaid
graph LR
    nauto_designer["auto_designer"]
    nauto_designer_demand["auto_designer.demand"]
    nauto_designer_demand_agent_contract["demand.agent_contract"]
    nauto_designer_demand_agent_runtime["demand.agent_runtime"]
    nauto_designer_demand_delivery_evidence["demand.delivery_evidence"]
    nauto_designer_demand_divergent["demand.divergent"]
    nauto_designer_demand_evidence_contract["demand.evidence_contract"]
    nauto_designer_demand_grouped_synthesizer["demand.grouped_synthesizer"]
    nauto_designer_demand_issue_schema["demand.issue_schema"]
    nauto_designer_demand_observation_provider["demand.observation_provider"]
    nauto_designer_demand_owner["demand.owner"]
    nauto_designer_demand_proposal_view["demand.proposal_view"]
    nauto_designer_demand_role_contract["demand.role_contract"]
    nauto_designer_demand_runtime_agg["demand.runtime_agg"]
    nauto_designer_demand_session_timeline["demand.session_timeline"]
    nauto_designer_demand_submit_tools["demand.submit_tools"]
    nauto_designer_demand_synthesizer["demand.synthesizer"]
    nauto_designer_demand_triage["demand.triage"]
    nauto_designer_distill["auto_designer.distill"]
    nauto_designer_distill_library["distill.library"]
    nauto_designer_distill_seed_adapter["distill.seed_adapter"]
    nauto_designer_distill_seed_library["distill.seed_library"]
    nauto_designer_evaluation["auto_designer.evaluation"]
    nauto_designer_evaluation_swebench["evaluation.swebench"]
    nauto_designer_experiment["auto_designer.experiment"]
    nauto_designer_experiment_backends["experiment.backends"]
    nauto_designer_experiment_backends_base["backends.base"]
    nauto_designer_experiment_backends_e2b["backends.e2b"]
    nauto_designer_experiment_backends_e2b_bootstrap["backends.e2b_bootstrap"]
    nauto_designer_experiment_backends_e2b_template["backends.e2b_template"]
    nauto_designer_experiment_backends_local["backends.local"]
    nauto_designer_experiment_batch["experiment.batch"]
    nauto_designer_experiment_batch_config["experiment.batch_config"]
    nauto_designer_experiment_batch_store["experiment.batch_store"]
    nauto_designer_experiment_cli["experiment.cli"]
    nauto_designer_experiment_collection["experiment.collection"]
    nauto_designer_experiment_config["experiment.config"]
    nauto_designer_experiment_context["experiment.context"]
    nauto_designer_experiment_controllers["experiment.controllers"]
    nauto_designer_experiment_controllers_runtime["controllers.runtime"]
    nauto_designer_experiment_controllers_unified["controllers.unified"]
    nauto_designer_experiment_dashboard["experiment.dashboard"]
    nauto_designer_experiment_engine["experiment.engine"]
    nauto_designer_experiment_grading["experiment.grading"]
    nauto_designer_experiment_infrastructure["experiment.infrastructure"]
    nauto_designer_experiment_manifest["experiment.manifest"]
    nauto_designer_experiment_materials["experiment.materials"]
    nauto_designer_experiment_runtime["experiment.runtime"]
    nauto_designer_experiment_task_import["experiment.task_import"]
    nauto_designer_experiment_workload["experiment.workload"]
    nauto_designer_guards["auto_designer.guards"]
    nauto_designer_guards_harness_boundary["guards.harness_boundary"]
    nauto_designer_guards_repo_guard["guards.repo_guard"]
    nauto_designer_guards_workspace_jail["guards.workspace_jail"]
    nauto_designer_harness["auto_designer.harness"]
    nauto_designer_harness_connector["harness.connector"]
    nauto_designer_harness_interface["harness.interface"]
    nauto_designer_harness_launcher["harness.launcher"]
    nauto_designer_invocation["auto_designer.invocation"]
    nauto_designer_loop["auto_designer.loop"]
    nauto_designer_loop_checkpoint["loop.checkpoint"]
    nauto_designer_loop_live["loop.live"]
    nauto_designer_loop_live_tracer["loop.live_tracer"]
    nauto_designer_loop_metrics["loop.metrics"]
    nauto_designer_loop_orchestrator["loop.orchestrator"]
    nauto_designer_loop_recovery["loop.recovery"]
    nauto_designer_loop_roster["loop.roster"]
    nauto_designer_loop_round_gate["loop.round_gate"]
    nauto_designer_loop_run_state["loop.run_state"]
    nauto_designer_loop_runner["loop.runner"]
    nauto_designer_loop_sim_user["loop.sim_user"]
    nauto_designer_models["auto_designer.models"]
    nauto_designer_nexau_runtime["auto_designer.nexau_runtime"]
    nauto_designer_observations["auto_designer.observations"]
    nauto_designer_observations___main__["observations.__main__"]
    nauto_designer_observations_delivery_gaps["observations.delivery_gaps"]
    nauto_designer_observations_gaps["observations.gaps"]
    nauto_designer_observations_grants["observations.grants"]
    nauto_designer_observations_preflight["observations.preflight"]
    nauto_designer_observations_publication["observations.publication"]
    nauto_designer_observations_transport["observations.transport"]
    nauto_designer_tracker["auto_designer.tracker"]
    nauto_designer_tracker_attachment_transport["tracker.attachment_transport"]
    nauto_designer_tracker_base["tracker.base"]
    nauto_designer_tracker_fake["tracker.fake"]
    nauto_designer_tracker_gitea["tracker.gitea"]
    nauto_designer_usage["auto_designer.usage"]
    nauto_designer_user["auto_designer.user"]
    nauto_designer_user_patches["user.patches"]
    nauto_designer_user_session_store["user.session_store"]
    nauto_designer_user_sim["user.sim"]
    nauto_designer_user_sim_action_space["sim.action_space"]
    nauto_designer_user_sim_actions["sim.actions"]
    nauto_designer_user_sim_clauses["sim.clauses"]
    nauto_designer_user_sim_demo["sim.demo"]
    nauto_designer_user_sim_deps["sim.deps"]
    nauto_designer_user_sim_dimensions["sim.dimensions"]
    nauto_designer_user_sim_feeling["sim.feeling"]
    nauto_designer_user_sim_goals["sim.goals"]
    nauto_designer_user_sim_harness_adapter["sim.harness_adapter"]
    nauto_designer_user_sim_loop["sim.loop"]
    nauto_designer_user_sim_persona_client["sim.persona_client"]
    nauto_designer_user_sim_persona_io["sim.persona_io"]
    nauto_designer_user_sim_prompt["sim.prompt"]
    nauto_designer_user_sim_run_agentic["sim.run_agentic"]
    nauto_designer_user_sim_run_live["sim.run_live"]
    nauto_designer_user_sim_runtime["sim.runtime"]
    nauto_designer_user_sim_sandbox["sim.sandbox"]
    nauto_designer_user_sim_scenarios["sim.scenarios"]
    nauto_designer_user_sim_seed_source["sim.seed_source"]
    nauto_designer_user_sim_skills["sim.skills"]
    nauto_designer_user_sim_sources["sim.sources"]
    nauto_designer_user_sim_sources_docker_seed["sources.docker_seed"]
    nauto_designer_user_sim_sources_empty["sources.empty"]
    nauto_designer_user_sim_sources_git["sources.git"]
    nauto_designer_user_sim_sources_local_fixture["sources.local_fixture"]
    nauto_designer_user_sim_sources_prebuilt["sources.prebuilt"]
    nauto_designer_user_sim_state["sim.state"]
    nauto_designer_user_sim_tools["sim.tools"]
    nauto_designer_user_sim_workspace["sim.workspace"]
    nauto_designer_web["auto_designer.web"]
    nauto_designer_web_api["web.api"]
    nauto_designer_web_issue_timeline["web.issue_timeline"]
    nauto_designer_demand_agent_contract --> nauto_designer_demand_issue_schema
    nauto_designer_demand_agent_runtime --> nauto_designer_demand_observation_provider
    nauto_designer_demand_agent_runtime --> nauto_designer_demand_session_timeline
    nauto_designer_demand_agent_runtime --> nauto_designer_invocation
    nauto_designer_demand_agent_runtime --> nauto_designer_loop_live_tracer
    nauto_designer_demand_agent_runtime --> nauto_designer_observations_gaps
    nauto_designer_demand_agent_runtime --> nauto_designer_usage
    nauto_designer_demand_agent_runtime --> nauto_designer_user_session_store
    nauto_designer_demand_delivery_evidence --> nauto_designer_observations_grants
    nauto_designer_demand_delivery_evidence --> nauto_designer_observations_publication
    nauto_designer_demand_delivery_evidence --> nauto_designer_observations_transport
    nauto_designer_demand_divergent --> nauto_designer_demand_agent_runtime
    nauto_designer_demand_divergent --> nauto_designer_demand_evidence_contract
    nauto_designer_demand_divergent --> nauto_designer_demand_issue_schema
    nauto_designer_demand_divergent --> nauto_designer_demand_proposal_view
    nauto_designer_demand_divergent --> nauto_designer_demand_role_contract
    nauto_designer_demand_divergent --> nauto_designer_loop_recovery
    nauto_designer_demand_divergent --> nauto_designer_models
    nauto_designer_demand_divergent --> nauto_designer_observations_grants
    nauto_designer_demand_divergent --> nauto_designer_tracker_base
    nauto_designer_demand_divergent --> nauto_designer_usage
    nauto_designer_demand_divergent --> nauto_designer_user_session_store
    nauto_designer_demand_evidence_contract --> nauto_designer_models
    nauto_designer_demand_evidence_contract --> nauto_designer_usage
    nauto_designer_demand_grouped_synthesizer --> nauto_designer_demand_issue_schema
    nauto_designer_demand_grouped_synthesizer --> nauto_designer_demand_proposal_view
    nauto_designer_demand_grouped_synthesizer --> nauto_designer_demand_synthesizer
    nauto_designer_demand_grouped_synthesizer --> nauto_designer_loop_recovery
    nauto_designer_demand_grouped_synthesizer --> nauto_designer_models
    nauto_designer_demand_grouped_synthesizer --> nauto_designer_observations_delivery_gaps
    nauto_designer_demand_grouped_synthesizer --> nauto_designer_usage
    nauto_designer_demand_observation_provider --> nauto_designer_demand_evidence_contract
    nauto_designer_demand_observation_provider --> nauto_designer_invocation
    nauto_designer_demand_observation_provider --> nauto_designer_user_session_store
    nauto_designer_demand_owner --> nauto_designer_demand_agent_runtime
    nauto_designer_demand_owner --> nauto_designer_demand_delivery_evidence
    nauto_designer_demand_owner --> nauto_designer_demand_issue_schema
    nauto_designer_demand_owner --> nauto_designer_demand_proposal_view
    nauto_designer_demand_owner --> nauto_designer_demand_role_contract
    nauto_designer_demand_owner --> nauto_designer_loop_recovery
    nauto_designer_demand_owner --> nauto_designer_models
    nauto_designer_demand_owner --> nauto_designer_observations_grants
    nauto_designer_demand_owner --> nauto_designer_tracker_base
    nauto_designer_demand_owner --> nauto_designer_usage
    nauto_designer_demand_owner --> nauto_designer_user_session_store
    nauto_designer_demand_proposal_view --> nauto_designer_demand_issue_schema
    nauto_designer_demand_runtime_agg --> nauto_designer_models
    nauto_designer_demand_runtime_agg --> nauto_designer_user_session_store
    nauto_designer_demand_session_timeline --> nauto_designer_demand_evidence_contract
    nauto_designer_demand_session_timeline --> nauto_designer_demand_observation_provider
    nauto_designer_demand_session_timeline --> nauto_designer_models
    nauto_designer_demand_session_timeline --> nauto_designer_usage
    nauto_designer_demand_session_timeline --> nauto_designer_user_session_store
    nauto_designer_demand_synthesizer --> nauto_designer_demand_agent_runtime
    nauto_designer_demand_synthesizer --> nauto_designer_demand_issue_schema
    nauto_designer_demand_synthesizer --> nauto_designer_demand_proposal_view
    nauto_designer_demand_synthesizer --> nauto_designer_demand_role_contract
    nauto_designer_demand_synthesizer --> nauto_designer_loop_recovery
    nauto_designer_demand_synthesizer --> nauto_designer_models
    nauto_designer_demand_synthesizer --> nauto_designer_observations_delivery_gaps
    nauto_designer_demand_synthesizer --> nauto_designer_observations_grants
    nauto_designer_demand_synthesizer --> nauto_designer_tracker_base
    nauto_designer_demand_synthesizer --> nauto_designer_usage
    nauto_designer_demand_synthesizer --> nauto_designer_user_session_store
    nauto_designer_demand_triage --> nauto_designer_demand_agent_runtime
    nauto_designer_demand_triage --> nauto_designer_demand_evidence_contract
    nauto_designer_demand_triage --> nauto_designer_demand_issue_schema
    nauto_designer_demand_triage --> nauto_designer_demand_role_contract
    nauto_designer_demand_triage --> nauto_designer_loop_recovery
    nauto_designer_demand_triage --> nauto_designer_observations_grants
    nauto_designer_demand_triage --> nauto_designer_tracker_base
    nauto_designer_demand_triage --> nauto_designer_tracker_gitea
    nauto_designer_demand_triage --> nauto_designer_usage
    nauto_designer_demand_triage --> nauto_designer_user_session_store
    nauto_designer_distill --> nauto_designer_distill_library
    nauto_designer_distill_seed_adapter --> nauto_designer_distill_seed_library
    nauto_designer_distill_seed_adapter --> nauto_designer_models
    nauto_designer_evaluation --> nauto_designer_evaluation_swebench
    nauto_designer_experiment_backends --> nauto_designer_experiment_backends_base
    nauto_designer_experiment_backends_base --> nauto_designer_experiment_config
    nauto_designer_experiment_backends_e2b --> nauto_designer_demand_delivery_evidence
    nauto_designer_experiment_backends_e2b --> nauto_designer_experiment_backends_base
    nauto_designer_experiment_backends_e2b --> nauto_designer_experiment_backends_e2b_bootstrap
    nauto_designer_experiment_backends_e2b --> nauto_designer_experiment_backends_e2b_template
    nauto_designer_experiment_backends_e2b --> nauto_designer_experiment_workload
    nauto_designer_experiment_backends_e2b_bootstrap --> nauto_designer_experiment_config
    nauto_designer_experiment_backends_e2b_bootstrap --> nauto_designer_experiment_materials
    nauto_designer_experiment_backends_e2b_template --> nauto_designer_experiment_backends_base
    nauto_designer_experiment_backends_local --> nauto_designer_experiment_backends_base
    nauto_designer_experiment_backends_local --> nauto_designer_experiment_collection
    nauto_designer_experiment_backends_local --> nauto_designer_experiment_config
    nauto_designer_experiment_backends_local --> nauto_designer_experiment_context
    nauto_designer_experiment_backends_local --> nauto_designer_experiment_engine
    nauto_designer_experiment_backends_local --> nauto_designer_experiment_infrastructure
    nauto_designer_experiment_backends_local --> nauto_designer_experiment_materials
    nauto_designer_experiment_backends_local --> nauto_designer_experiment_workload
    nauto_designer_experiment_backends_local --> nauto_designer_observations_transport
    nauto_designer_experiment_batch --> nauto_designer_experiment
    nauto_designer_experiment_batch --> nauto_designer_experiment_batch_config
    nauto_designer_experiment_batch --> nauto_designer_experiment_batch_store
    nauto_designer_experiment_batch --> nauto_designer_experiment_config
    nauto_designer_experiment_batch --> nauto_designer_experiment_manifest
    nauto_designer_experiment_batch --> nauto_designer_experiment_runtime
    nauto_designer_experiment_batch_config --> nauto_designer_experiment
    nauto_designer_experiment_batch_config --> nauto_designer_experiment_config
    nauto_designer_experiment_batch_config --> nauto_designer_experiment_materials
    nauto_designer_experiment_batch_store --> nauto_designer_experiment
    nauto_designer_experiment_batch_store --> nauto_designer_experiment_config
    nauto_designer_experiment_batch_store --> nauto_designer_experiment_manifest
    nauto_designer_experiment_batch_store --> nauto_designer_experiment_materials
    nauto_designer_experiment_batch_store --> nauto_designer_experiment_runtime
    nauto_designer_experiment_batch_store --> nauto_designer_experiment_workload
    nauto_designer_experiment_cli --> nauto_designer_experiment
    nauto_designer_experiment_cli --> nauto_designer_experiment_batch
    nauto_designer_experiment_cli --> nauto_designer_experiment_config
    nauto_designer_experiment_cli --> nauto_designer_experiment_dashboard
    nauto_designer_experiment_cli --> nauto_designer_experiment_grading
    nauto_designer_experiment_cli --> nauto_designer_experiment_runtime
    nauto_designer_experiment_cli --> nauto_designer_experiment_task_import
    nauto_designer_experiment_collection --> nauto_designer_experiment_config
    nauto_designer_experiment_collection --> nauto_designer_experiment_materials
    nauto_designer_experiment_context --> nauto_designer_experiment_config
    nauto_designer_experiment_context --> nauto_designer_experiment_workload
    nauto_designer_experiment_context --> nauto_designer_models
    nauto_designer_experiment_controllers_runtime --> nauto_designer_demand_issue_schema
    nauto_designer_experiment_controllers_runtime --> nauto_designer_guards_harness_boundary
    nauto_designer_experiment_controllers_runtime --> nauto_designer_invocation
    nauto_designer_experiment_controllers_runtime --> nauto_designer_loop_live
    nauto_designer_experiment_controllers_runtime --> nauto_designer_loop_recovery
    nauto_designer_experiment_controllers_runtime --> nauto_designer_loop_sim_user
    nauto_designer_experiment_controllers_runtime --> nauto_designer_observations_preflight
    nauto_designer_experiment_controllers_runtime --> nauto_designer_observations_transport
    nauto_designer_experiment_controllers_runtime --> nauto_designer_tracker_attachment_transport
    nauto_designer_experiment_controllers_runtime --> nauto_designer_tracker_gitea
    nauto_designer_experiment_controllers_unified --> nauto_designer_demand_divergent
    nauto_designer_experiment_controllers_unified --> nauto_designer_demand_grouped_synthesizer
    nauto_designer_experiment_controllers_unified --> nauto_designer_demand_owner
    nauto_designer_experiment_controllers_unified --> nauto_designer_demand_synthesizer
    nauto_designer_experiment_controllers_unified --> nauto_designer_demand_triage
    nauto_designer_experiment_controllers_unified --> nauto_designer_distill_library
    nauto_designer_experiment_controllers_unified --> nauto_designer_experiment_context
    nauto_designer_experiment_controllers_unified --> nauto_designer_experiment_controllers
    nauto_designer_experiment_controllers_unified --> nauto_designer_experiment_controllers_runtime
    nauto_designer_experiment_controllers_unified --> nauto_designer_guards_repo_guard
    nauto_designer_experiment_controllers_unified --> nauto_designer_harness_launcher
    nauto_designer_experiment_controllers_unified --> nauto_designer_invocation
    nauto_designer_experiment_controllers_unified --> nauto_designer_loop_live
    nauto_designer_experiment_controllers_unified --> nauto_designer_loop_metrics
    nauto_designer_experiment_controllers_unified --> nauto_designer_loop_orchestrator
    nauto_designer_experiment_controllers_unified --> nauto_designer_loop_roster
    nauto_designer_experiment_controllers_unified --> nauto_designer_loop_round_gate
    nauto_designer_experiment_controllers_unified --> nauto_designer_loop_sim_user
    nauto_designer_experiment_controllers_unified --> nauto_designer_models
    nauto_designer_experiment_controllers_unified --> nauto_designer_tracker_gitea
    nauto_designer_experiment_controllers_unified --> nauto_designer_usage
    nauto_designer_experiment_controllers_unified --> nauto_designer_user_session_store
    nauto_designer_experiment_controllers_unified --> nauto_designer_user_sim_persona_client
    nauto_designer_experiment_controllers_unified --> nauto_designer_user_sim_persona_io
    nauto_designer_experiment_dashboard --> nauto_designer_experiment_config
    nauto_designer_experiment_dashboard --> nauto_designer_experiment_manifest
    nauto_designer_experiment_dashboard --> nauto_designer_experiment_materials
    nauto_designer_experiment_dashboard --> nauto_designer_experiment_runtime
    nauto_designer_experiment_dashboard --> nauto_designer_tracker_gitea
    nauto_designer_experiment_dashboard --> nauto_designer_usage
    nauto_designer_experiment_dashboard --> nauto_designer_user_session_store
    nauto_designer_experiment_dashboard --> nauto_designer_web_api
    nauto_designer_experiment_engine --> nauto_designer_experiment_config
    nauto_designer_experiment_engine --> nauto_designer_experiment_context
    nauto_designer_experiment_engine --> nauto_designer_experiment_materials
    nauto_designer_experiment_grading --> nauto_designer_evaluation_swebench
    nauto_designer_experiment_grading --> nauto_designer_experiment_config
    nauto_designer_experiment_grading --> nauto_designer_experiment_manifest
    nauto_designer_experiment_grading --> nauto_designer_experiment_materials
    nauto_designer_experiment_grading --> nauto_designer_experiment_runtime
    nauto_designer_experiment_grading --> nauto_designer_experiment_workload
    nauto_designer_experiment_grading --> nauto_designer_loop_recovery
    nauto_designer_experiment_grading --> nauto_designer_models
    nauto_designer_experiment_infrastructure --> nauto_designer_experiment_config
    nauto_designer_experiment_manifest --> nauto_designer_experiment_config
    nauto_designer_experiment_materials --> nauto_designer_distill_library
    nauto_designer_experiment_materials --> nauto_designer_experiment_config
    nauto_designer_experiment_materials --> nauto_designer_experiment_workload
    nauto_designer_experiment_materials --> nauto_designer_user_sim_persona_io
    nauto_designer_experiment_runtime --> nauto_designer_experiment_backends_e2b
    nauto_designer_experiment_runtime --> nauto_designer_experiment_backends_local
    nauto_designer_experiment_runtime --> nauto_designer_experiment_collection
    nauto_designer_experiment_runtime --> nauto_designer_experiment_config
    nauto_designer_experiment_runtime --> nauto_designer_experiment_engine
    nauto_designer_experiment_runtime --> nauto_designer_experiment_manifest
    nauto_designer_experiment_runtime --> nauto_designer_experiment_materials
    nauto_designer_experiment_runtime --> nauto_designer_experiment_workload
    nauto_designer_experiment_task_import --> nauto_designer_distill_seed_library
    nauto_designer_experiment_task_import --> nauto_designer_experiment_config
    nauto_designer_experiment_task_import --> nauto_designer_experiment_workload
    nauto_designer_experiment_workload --> nauto_designer_experiment_config
    nauto_designer_experiment_workload --> nauto_designer_experiment_context
    nauto_designer_experiment_workload --> nauto_designer_experiment_materials
    nauto_designer_guards_workspace_jail --> nauto_designer_demand_observation_provider
    nauto_designer_guards_workspace_jail --> nauto_designer_usage
    nauto_designer_harness_connector --> nauto_designer_harness_interface
    nauto_designer_harness_connector --> nauto_designer_usage
    nauto_designer_harness_launcher --> nauto_designer_harness_interface
    nauto_designer_harness_launcher --> nauto_designer_observations_publication
    nauto_designer_harness_launcher --> nauto_designer_user_sim_runtime
    nauto_designer_invocation --> nauto_designer_usage
    nauto_designer_loop_live_tracer --> nauto_designer_usage
    nauto_designer_loop_metrics --> nauto_designer_demand_issue_schema
    nauto_designer_loop_metrics --> nauto_designer_tracker_base
    nauto_designer_loop_metrics --> nauto_designer_user_session_store
    nauto_designer_loop_orchestrator --> nauto_designer_demand_divergent
    nauto_designer_loop_orchestrator --> nauto_designer_demand_synthesizer
    nauto_designer_loop_orchestrator --> nauto_designer_harness_interface
    nauto_designer_loop_orchestrator --> nauto_designer_harness_launcher
    nauto_designer_loop_orchestrator --> nauto_designer_loop_recovery
    nauto_designer_loop_orchestrator --> nauto_designer_loop_round_gate
    nauto_designer_loop_orchestrator --> nauto_designer_models
    nauto_designer_loop_orchestrator --> nauto_designer_usage
    nauto_designer_loop_orchestrator --> nauto_designer_user_sim_deps
    nauto_designer_loop_orchestrator --> nauto_designer_user_sim_runtime
    nauto_designer_loop_orchestrator --> nauto_designer_user_sim_workspace
    nauto_designer_loop_runner --> nauto_designer_loop_checkpoint
    nauto_designer_loop_runner --> nauto_designer_loop_orchestrator
    nauto_designer_loop_runner --> nauto_designer_loop_run_state
    nauto_designer_loop_sim_user --> nauto_designer_demand_evidence_contract
    nauto_designer_loop_sim_user --> nauto_designer_demand_issue_schema
    nauto_designer_loop_sim_user --> nauto_designer_evaluation_swebench
    nauto_designer_loop_sim_user --> nauto_designer_harness_connector
    nauto_designer_loop_sim_user --> nauto_designer_harness_interface
    nauto_designer_loop_sim_user --> nauto_designer_loop_recovery
    nauto_designer_loop_sim_user --> nauto_designer_models
    nauto_designer_loop_sim_user --> nauto_designer_observations_preflight
    nauto_designer_loop_sim_user --> nauto_designer_tracker_base
    nauto_designer_loop_sim_user --> nauto_designer_usage
    nauto_designer_loop_sim_user --> nauto_designer_user_patches
    nauto_designer_loop_sim_user --> nauto_designer_user_session_store
    nauto_designer_loop_sim_user --> nauto_designer_user_sim_deps
    nauto_designer_loop_sim_user --> nauto_designer_user_sim_dimensions
    nauto_designer_loop_sim_user --> nauto_designer_user_sim_loop
    nauto_designer_loop_sim_user --> nauto_designer_user_sim_persona_client
    nauto_designer_loop_sim_user --> nauto_designer_user_sim_prompt
    nauto_designer_loop_sim_user --> nauto_designer_user_sim_runtime
    nauto_designer_loop_sim_user --> nauto_designer_user_sim_workspace
    nauto_designer_models --> nauto_designer_usage
    nauto_designer_observations___main__ --> nauto_designer_observations_publication
    nauto_designer_observations_delivery_gaps --> nauto_designer_observations_gaps
    nauto_designer_observations_delivery_gaps --> nauto_designer_observations_grants
    nauto_designer_observations_gaps --> nauto_designer_demand_issue_schema
    nauto_designer_observations_gaps --> nauto_designer_invocation
    nauto_designer_observations_gaps --> nauto_designer_models
    nauto_designer_observations_gaps --> nauto_designer_observations_grants
    nauto_designer_observations_gaps --> nauto_designer_usage
    nauto_designer_observations_grants --> nauto_designer_observations_publication
    nauto_designer_observations_preflight --> nauto_designer_observations_publication
    nauto_designer_observations_preflight --> nauto_designer_observations_transport
    nauto_designer_observations_publication --> nauto_designer_invocation
    nauto_designer_tracker_base --> nauto_designer_models
    nauto_designer_tracker_fake --> nauto_designer_models
    nauto_designer_tracker_fake --> nauto_designer_tracker_base
    nauto_designer_tracker_gitea --> nauto_designer_models
    nauto_designer_tracker_gitea --> nauto_designer_observations_transport
    nauto_designer_tracker_gitea --> nauto_designer_tracker_attachment_transport
    nauto_designer_tracker_gitea --> nauto_designer_tracker_base
    nauto_designer_user_session_store --> nauto_designer_demand_evidence_contract
    nauto_designer_user_session_store --> nauto_designer_models
    nauto_designer_user_sim --> nauto_designer_user_sim_dimensions
    nauto_designer_user_sim --> nauto_designer_user_sim_feeling
    nauto_designer_user_sim --> nauto_designer_user_sim_harness_adapter
    nauto_designer_user_sim --> nauto_designer_user_sim_loop
    nauto_designer_user_sim --> nauto_designer_user_sim_persona_client
    nauto_designer_user_sim --> nauto_designer_user_sim_persona_io
    nauto_designer_user_sim_action_space --> nauto_designer_user_sim_actions
    nauto_designer_user_sim_action_space --> nauto_designer_user_sim_dimensions
    nauto_designer_user_sim_action_space --> nauto_designer_user_sim_state
    nauto_designer_user_sim_clauses --> nauto_designer_user_sim_dimensions
    nauto_designer_user_sim_demo --> nauto_designer_user_sim_dimensions
    nauto_designer_user_sim_demo --> nauto_designer_user_sim_harness_adapter
    nauto_designer_user_sim_demo --> nauto_designer_user_sim_loop
    nauto_designer_user_sim_demo --> nauto_designer_user_sim_persona_client
    nauto_designer_user_sim_demo --> nauto_designer_user_sim_state
    nauto_designer_user_sim_deps --> nauto_designer_models
    nauto_designer_user_sim_deps --> nauto_designer_user_sim_runtime
    nauto_designer_user_sim_loop --> nauto_designer_usage
    nauto_designer_user_sim_loop --> nauto_designer_user_sim_action_space
    nauto_designer_user_sim_loop --> nauto_designer_user_sim_actions
    nauto_designer_user_sim_loop --> nauto_designer_user_sim_dimensions
    nauto_designer_user_sim_loop --> nauto_designer_user_sim_feeling
    nauto_designer_user_sim_loop --> nauto_designer_user_sim_goals
    nauto_designer_user_sim_loop --> nauto_designer_user_sim_persona_client
    nauto_designer_user_sim_loop --> nauto_designer_user_sim_prompt
    nauto_designer_user_sim_loop --> nauto_designer_user_sim_state
    nauto_designer_user_sim_persona_client --> nauto_designer_usage
    nauto_designer_user_sim_persona_client --> nauto_designer_user_sim_actions
    nauto_designer_user_sim_persona_client --> nauto_designer_user_sim_prompt
    nauto_designer_user_sim_persona_client --> nauto_designer_user_sim_sandbox
    nauto_designer_user_sim_persona_client --> nauto_designer_user_sim_skills
    nauto_designer_user_sim_persona_client --> nauto_designer_user_sim_state
    nauto_designer_user_sim_persona_client --> nauto_designer_user_sim_tools
    nauto_designer_user_sim_persona_io --> nauto_designer_distill_library
    nauto_designer_user_sim_persona_io --> nauto_designer_user_sim_dimensions
    nauto_designer_user_sim_prompt --> nauto_designer_user_sim_clauses
    nauto_designer_user_sim_prompt --> nauto_designer_user_sim_dimensions
    nauto_designer_user_sim_prompt --> nauto_designer_user_sim_skills
    nauto_designer_user_sim_prompt --> nauto_designer_user_sim_state
    nauto_designer_user_sim_prompt --> nauto_designer_user_sim_tools
    nauto_designer_user_sim_run_agentic --> nauto_designer_models
    nauto_designer_user_sim_run_agentic --> nauto_designer_user_sim_demo
    nauto_designer_user_sim_run_agentic --> nauto_designer_user_sim_loop
    nauto_designer_user_sim_run_agentic --> nauto_designer_user_sim_persona_client
    nauto_designer_user_sim_run_agentic --> nauto_designer_user_sim_run_live
    nauto_designer_user_sim_run_agentic --> nauto_designer_user_sim_sandbox
    nauto_designer_user_sim_run_agentic --> nauto_designer_user_sim_scenarios
    nauto_designer_user_sim_run_agentic --> nauto_designer_user_sim_workspace
    nauto_designer_user_sim_run_live --> nauto_designer_user_sim_demo
    nauto_designer_user_sim_run_live --> nauto_designer_user_sim_dimensions
    nauto_designer_user_sim_run_live --> nauto_designer_user_sim_loop
    nauto_designer_user_sim_run_live --> nauto_designer_user_sim_persona_client
    nauto_designer_user_sim_run_live --> nauto_designer_user_sim_scenarios
    nauto_designer_user_sim_sandbox --> nauto_designer_user_sim_runtime
    nauto_designer_user_sim_seed_source --> nauto_designer_models
    nauto_designer_user_sim_seed_source --> nauto_designer_user_sim
    nauto_designer_user_sim_seed_source --> nauto_designer_user_sim_runtime
    nauto_designer_user_sim_seed_source --> nauto_designer_user_sim_sources
    nauto_designer_user_sim_skills --> nauto_designer_user_sim_dimensions
    nauto_designer_user_sim_sources_docker_seed --> nauto_designer_models
    nauto_designer_user_sim_sources_docker_seed --> nauto_designer_usage
    nauto_designer_user_sim_sources_docker_seed --> nauto_designer_user_sim_runtime
    nauto_designer_user_sim_sources_docker_seed --> nauto_designer_user_sim_seed_source
    nauto_designer_user_sim_sources_empty --> nauto_designer_models
    nauto_designer_user_sim_sources_empty --> nauto_designer_user_sim_seed_source
    nauto_designer_user_sim_sources_git --> nauto_designer_models
    nauto_designer_user_sim_sources_git --> nauto_designer_user_sim_seed_source
    nauto_designer_user_sim_sources_local_fixture --> nauto_designer_models
    nauto_designer_user_sim_sources_local_fixture --> nauto_designer_user_sim_seed_source
    nauto_designer_user_sim_sources_local_fixture --> nauto_designer_user_sim_workspace
    nauto_designer_user_sim_sources_prebuilt --> nauto_designer_models
    nauto_designer_user_sim_sources_prebuilt --> nauto_designer_usage
    nauto_designer_user_sim_sources_prebuilt --> nauto_designer_user_sim_deps
    nauto_designer_user_sim_sources_prebuilt --> nauto_designer_user_sim_runtime
    nauto_designer_user_sim_sources_prebuilt --> nauto_designer_user_sim_seed_source
    nauto_designer_user_sim_state --> nauto_designer_user_sim_dimensions
    nauto_designer_user_sim_tools --> nauto_designer_user_sim_dimensions
    nauto_designer_user_sim_tools --> nauto_designer_user_sim_sandbox
    nauto_designer_user_sim_workspace --> nauto_designer_models
    nauto_designer_user_sim_workspace --> nauto_designer_user_sim_runtime
    nauto_designer_user_sim_workspace --> nauto_designer_user_sim_seed_source
    nauto_designer_web_api --> nauto_designer_demand_issue_schema
    nauto_designer_web_api --> nauto_designer_loop_live
    nauto_designer_web_api --> nauto_designer_loop_metrics
    nauto_designer_web_api --> nauto_designer_loop_roster
    nauto_designer_web_api --> nauto_designer_tracker_base
    nauto_designer_web_api --> nauto_designer_tracker_gitea
    nauto_designer_web_api --> nauto_designer_usage
    nauto_designer_web_api --> nauto_designer_user_session_store
    nauto_designer_web_api --> nauto_designer_web_issue_timeline
    nauto_designer_web_issue_timeline --> nauto_designer_demand_issue_schema
```
