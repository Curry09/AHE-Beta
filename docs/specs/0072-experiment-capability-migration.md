---
number: '0072'
title: 统一入口的既有能力迁移与执行修复
issue: 0
slug: experiment-capability-migration
summary: 补齐既有配置、交互计划和看板接线，修复单轮就绪与交付认证，并验证两后端真实消费者。
tasks:
- id: T1
  title: 配置与消费者环境、认证和 Owner 接线
  status: done
  priority: P0
  tags: []
  depends-on: []
  relates-to: []
  parallel: false
  files:
  - backend/auto_designer/experiment/config.py
  - backend/auto_designer/experiment/context.py
  - backend/auto_designer/experiment/runtime.py
  - backend/auto_designer/experiment/schemas/experiment-v2.json
  - backend/auto_designer/experiment/schemas/task-package-v1.json
  - backend/tests/test_experiment_config_v2.py
  - backend/tests/test_experiment_engine.py
  - backend/tests/test_experiment_lifecycle_v2.py
  scope: 严格 schema、冻结默认值、两后端共用环境与预检认证
  acceptance: 原配置可读，显式策略不被过滤，API key/Bearer/OAuth 名称独立，Owner llm 可启用，非法策略 check
    阶段拒绝
- id: T2
  title: 冻结显式计划和 direct 交互
  status: done
  priority: P1
  tags: []
  depends-on: []
  relates-to: []
  parallel: true
  files:
  - backend/auto_designer/experiment/materials.py
  - backend/auto_designer/experiment/controllers/ordinary.py
  - backend/auto_designer/experiment/controllers/swebench.py
  - backend/tests/test_experiment_materials.py
  - backend/tests/test_run_swebench_closed_loop.py
  - backend/tests/test_run_vigil.py
  - backend/tests/test_experiment_interactions.py
  scope: 计划校验冻结、两控制器消费与 Docker 交付参数
  acceptance: 单任务 AABB 可冻结并按计划运行，direct 与 simulated_user 被真实分派，idle timeout 透传给
    Docker，修改原材料不改变已准备实验
- id: T3
  title: 后端单轮就绪与非 root 交付执行
  status: done
  priority: P0
  tags: []
  depends-on: []
  relates-to: []
  parallel: true
  files:
  - backend/auto_designer/experiment/backends/local.py
  - backend/auto_designer/experiment/backends/e2b.py
  - backend/auto_designer/experiment/backends/e2b_bootstrap.py
  - backend/deploy/vigil/entrypoint.sh
  - backend/tests/test_experiment_local_backend.py
  - backend/tests/test_experiment_e2b_backend.py
  - backend/tests/test_experiment_e2b_bootstrap.py
  scope: 修复 local 单轮并显式隔离 E2B 管理与执行身份
  acceptance: 单轮正常完成不等待 Vigil，多轮保留 owned readiness；controller/Claude 以非 root
    运行且依赖、产物和 stop/collect 权限一致
- id: T4
  title: 绑定 run 的观测看板入口
  status: done
  priority: P1
  tags: []
  depends-on: []
  relates-to: []
  parallel: true
  files:
  - backend/auto_designer/experiment/dashboard.py
  - backend/auto_designer/experiment/cli.py
  - backend/auto_designer/web/api.py
  - backend/tests/test_experiment_dashboard.py
  - backend/tests/test_experiment_cli_v2.py
  scope: 统一命令启动显式 run 观测，避免读取旧默认数据
  acceptance: local 当前 sessions/live/usage/role_runs 正确绑定，E2B
    已收集产物可看，未收集清晰报错，token 不进入收据和 API
- id: T5
  title: 能力矩阵、示例和两后端集成验收
  status: done
  priority: P1
  tags: []
  depends-on:
  - T1
  - T2
  - T3
  - T4
  relates-to: []
  parallel: false
  files:
  - backend/scripts/e2e-spec-0072-capability-migration.sh
  - backend/scripts/check_experiment_repository.py
  - backend/tests/test_experiment_capability_migration.py
  - backend/tests/test_experiment_repository.py
  - docs/CONFIGURATION.md
  - docs/CONFIGURATION.zh-CN.md
  - docs/QUICKSTART.md
  - docs/QUICKSTART.zh-CN.md
  - docs/tutorials/u1-experiment.md
  - docs/tutorials/u1-experiment.zh-CN.md
  - docs/synthesizer-grouping.md
  - README.md
  - README.zh-CN.md
  - frontend/README.md
  - examples/experiments/u1-local.json
  - examples/experiments/u1-e2b.json
  - examples/experiment.env.example
  scope: 公开文档、真实消费者矩阵和在线证据边界
  acceptance: schema→freeze→两后端→真实消费者回归通过，文档列明已迁/待迁范围，记录实际在线覆盖而非假称完整云交付
---

# 0072 · 统一入口的既有能力迁移与执行修复

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

补齐统一实验入口中可复用、已有真实消费者的能力：分组、USER/DEMAND 推理强度、延迟隔离计时、交付等待/协作/权限/idle 参数、告警阈值、direct 交互、显式逐轮计划与当前 run 看板。修复 local 单轮 Vigil readiness 和交付认证类型映射。用户已于 2026-10-03 授权根据能力审计实施；清理基线独立提交，不将本轮业务改动混入清理提交。

## Motivation

旧启动器会导出实际开关，但统一 schema 2 没有对应字段，凭证白名单又过滤了这些设置；将历史启动器归档并不能完成能力迁移。单轮配置虽然合法，local 后端无条件等待未启动的 Vigil；delivery 将任意凭证变量名当作 Bearer，丢失显式 API key/OAuth 语义。旧 E2B 交付在非 root 下使用 bypassPermissions，新执行链改为 root 与 acceptEdits，此前五轮云实验无 issue/交付，未覆盖真实代码交付。数据迁至独立 run 后，live 看板仍读旧目录。

本组修复有明确消费者的遗漏和执行错误；此前公开契约明确暂缓的多任务/N4/N8、历史 lineage 导入、工程 CI runner 生命周期、官方评分、seed 库/纯文本输入不在本组声称完成。Owner 模型评审已有完整链路，恢复 mechanical/llm 显式选择。

## Guide-level explanation

保留 schema_version=2，新增可选 policies，各字段默认值进入 prepare 的冻结配置；env 文件只存凭证/地址，宿主同名变量仍不隐式影响实验。

- policies.synthesizer_grouping：false；models.user/demand.reasoning_effort：可选非空字符串。
- policies.timing.latency_isolated：false；wall_guard_seconds：0（采用已有默认 600 秒宽限；总墙钟上限为角色预算加宽限）。
- policies.delivery.timeout_seconds：86400；poll_seconds：15；coordination：soft/off/dependencies，默认 soft；permission_mode：bypassPermissions/acceptEdits/default，默认 bypassPermissions，执行交付的进程必须为非 root；idle_timeout_seconds：300，0 表示关闭。
- policies.alarms.proposal_depth/ready_depth：20；roles.owner_mode：mechanical/llm，默认保持现有 mechanical。
- models.delivery.auth_type：api-key/bearer/oauth，显式选择与 api_key_env 名称独立。未设置的旧 v2 配置按已有标准名称保留行为，新的示例显式使用 bearer；显式 OAuth 不再改成 Bearer。
- task package 的 interaction：simulated_user/direct，默认 simulated_user；workload.interaction_plan 可给出每轮 [[persona_id,task_id]]，当前单任务仍每轮一个 session。缺省保持轮流 persona。
- 增加 experiment dashboard RUN_ID 命令，为 local 运行或已 collect 的 E2B 产物绑定 sessions/live/usage/role_runs 和当前 Gitea，看板只启动观测服务。未收集云数据时明确提示 collect，不能读取历史默认目录冒充当前运行。

check --offline 在任何 provider 操作前拒绝非法配置/计划；prepare 固定默认值、计划和来源哈希；修改宿主 env、原始计划或配置不能改变已冻结 run。

## Reference-level explanation

### 配置与消费者

在严格 JSON schema 中添加 policies，角色推理参数、auth_type、owner_mode 和 task interaction/plan。配置加载规范化新增默认值；模型认证 helper 分离源变量名和导出的协议变量；保持读取旧 manifest 的执行默认值，不能改写旧 manifest/hash。公共 API key、Bearer、OAuth 三种分支各只导出一种凭证，模型预检使用同一认证决策。

build_controller_environment 从冻结配置导出 SYNTHESIZER_GROUPING、USER/DEMAND_LLM_REASONING_EFFORT、AUTO_DESIGNER_LATENCY_ISOLATED_TIMEOUT、AUTO_DESIGNER_LATENCY_WALL_GUARD_SECONDS、ROUND_DELIVERY_TIMEOUT_SEC/POLL_SEC、VIGIL_COORDINATION、OPENAGENTS_PERMISSION_MODE、OPENAGENTS_CLAUDE_IDLE_TIMEOUT、PROPOSAL/READY_DEPTH_ALARM、N_OWNERS。Docker 交付必须额外透传 idle timeout；禁止从凭证字典补运行策略。告警阈值必须为正整数，ordinary/SWE 共用实际背压检查；延迟墙钟保护保持旧消费者的“角色预算加宽限”语义，0 采用默认 600 秒。

计划统一校验轮数、每轮会话数、persona 是否选中、task 是否匹配与重复；规范化计划注册为冻结 material，并实际被 ordinary/SWE 消费。task interaction 写入实际 workspace，使用现有 mixed dispatcher 保留两种会话行为及恢复加载。

local launch 仅多轮等待 Vigil；single-user controller 完成不因缺少交付进程失败。E2B 保留 root 管理资源，启动前将该 run 的目录明确交给非 root user，bootstrap 中可执行依赖向该用户可读/可执行；实际 controller/OpenAgents 子进程以 user 执行。inspect/stop/collect/destroy 仍由 root 执行且保留资源身份校验。local 的交付进程也不得因挂载 role_runs 而直接用 root 执行 Claude。

看板通过 runtime 加载验证当前 manifest/materials，再按 run 路径构造显式 create_app 输入与 tracker；UI 不接触 token。E2B 绑定已收集的本地产物并明确来源，不把本地 API 当云端实时数据。服务期间再次 collect，读取数据与 runmeta 的快照时间/一致性/终态必须同步；替换中间态或校验失败返回不可用，不能显示新数据旧时间。

### DAG 与文件分配

T1 配置/环境/认证基础、T2 计划/交互、T3 后端执行、T4 看板各自实现确定的字段契约，文件互斥，可协同实现；全部完成后进入 T5 集成矩阵与文档。frontmatter 是文件分配与验收的权威数据。

e2e 脚本：backend/scripts/e2e-spec-0072-capability-migration.sh。必须覆盖配置到冻结 material 到 local/E2B 环境到真实消费者的链路；新增有意义的回归测试，不用只断言 schema 存在替代行为验收。

## Drawbacks

配置字段增加，需要完整默认值和两语文档，延迟隔离并不能取消基础设施风险。direct 复用现有行为，并不等于多任务入口已完成。非 root 执行须检查依赖目录和 run 写权限；离线 argv/所有权测试不能证明云端模型交付可用。

## Rationale and alternatives

拒绝恢复任意宿主 env 透传：无法冻结来源和确定性，也会再次泄露私人模型配置。拒绝恢复旧 runner wrapper：绕行旧配置不能让两后端获得一致能力。选择有类型、可冻结的公开字段，并直接接入已有消费者。认证类型单列，变量名称仅寻找值；只有未指定字段的旧 v2 保留已知名称默认，以免改变已冻结实验。

权限与运行身份一起处理，不向 root Claude 进程盲目设置 bypassPermissions。默认 bypass 用于已有隔离容器/沙箱的无人值守交付，保留显式 acceptEdits/default 供用户选择。

## Prior art

旧 ordinary/SWE、auditable/mixed 以及 N1/scaling 实际运行路径分别提供策略导出与消费者。现有 grouped_synthesizer、agent_runtime、round_gate、Owner、mixed dispatcher 和 OpenAgents Claude backend 是本组复用的实现。能力审计日期 2026-10-03，包含单轮误判、凭证映射和 AABB 计划的离线复现，必要背景已在本组就地说明。

## Unresolved questions

无阻止本组实施的问题。云端非空交付必须单独记录实际验收；资源/服务不可用时记录具体限制，不能用空需求闭环或 mock 宣称在线交付通过。

## Future possibilities

另行完成多任务/N4/N8、历史 continuation/new-lineage、工程 CI、入口内官方评分和 seed 输入适配。能力矩阵分别标记已迁、明确退出、待迁，不能把待迁功能重新归类成不存在。
