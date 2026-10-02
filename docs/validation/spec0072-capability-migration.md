# Spec-0072 能力迁移验收

日期：2026-10-03。工作树：`feat/unified-experiment-entry`。清理基线已独立提交为 `81b3f56`；本报告记录本组提交前的验收结果；提交与推送状态以 Git 记录为准。

## 已实现的能力矩阵

| 旧能力／问题 | 新入口 | 实际接线与验证 |
| --- | --- | --- |
| Synthesizer 分组 | `policies.synthesizer_grouping` | prepare 冻结 → 两后端 context → `group_synthesizer_stage` 确实选择 GroupedSynthesizer |
| USER 推理强度 | `models.user.reasoning_effort` | 两后端冻结环境 → 实际 ApiPersonaClient chat 请求 |
| DEMAND 推理强度 | `models.demand.reasoning_effort` | 两后端环境 → 实际 AgentConfig.llm_config.extra_params；与 Owner 共用模型 |
| 延迟隔离／墙钟保护 | `policies.timing` | 环境 → 实际 run_agent_def 的 accounting/run_with_timeout 参数；0 保留角色预算加 600 秒宽限，正值覆盖额外宽限；受控时钟验证默认/指定上限 |
| 交付等待与轮询 | `policies.delivery.timeout_seconds/poll_seconds` | 真 round_gate 用受控时钟读票、轮询并按指定边界报 timeout |
| 协作策略 | `policies.delivery.coordination` | 实际 OpenAgents config writer 生成 dependencies，而非固定 soft |
| 权限和 idle 超时 | `policies.delivery.permission_mode/idle_timeout_seconds` | 两后端导出；Docker 透传 idle=0；新云执行与容器交付均设置非 root 身份 |
| proposal/ready 告警阈值 | `policies.alarms` | 两控制器共用实际轮末检查，FakeTracker 验证计数、等于阈值不告警、超过才告警；schema 拒绝 0，不改变准入或扩容 |
| Owner 模型评审 | `roles.owner_mode: llm` | N_OWNERS=1 到已有 Owner(review=True) 调度；默认 mechanical 保留 |
| 任意名字的显式 API key、Bearer、OAuth | `models.delivery.auth_type` | 三种协议分别只导出一种凭证；SDK预检使用相同 API key/Bearer 决策且排除宿主另一凭证；OAuth SDK探针显式拒绝，实际Claude路径保留 |
| 单轮 local readiness | `rounds.count: 1` | 真实 supervisor 正常完成封存，不等待不会启动的 Vigil；多轮保留 owned ready/非root检查 |
| direct 交互 | 任务包 `interaction: direct` | ordinary/SWE 共用 mixed dispatcher，执行 direct/simulated 真会话、终端 review、反馈建票与 SessionStore |
| 自定义逐轮计划 | `workload.interaction_plan` | 校验轮数、会话数、persona/task；冻结 AABB；两控制器的计划 callable 驱动真四轮 Orchestrator |
| 看板绑定 run | `dashboard RUN_ID` | TestClient 读指定 sessions/live/history/usage/roster；local 当前数据与 E2B collected-snapshot 分开；未 collect 云数据报错；再次 collect 同步快照元信息，半发布/请求期间变化/损坏刷新返回 503 |
| 已有 v2 恢复 | 原 manifest/frozen source | 不重写旧身份或哈希；无 policies/无执行身份的旧云 run 保留原 root/环境路径；新 run 缺非root身份拒绝 |

新增策略写入 JSON，默认值在 prepare 前规范化并进入 config hash。env 文件只提供显式凭证/地址，宿主或 profile 的同名控制变量仍被过滤。准备后的原配置、persona 和任务文件变更不会改写 plan/hash。

## 自动验证

| 检查 | 结果 |
| --- | --- |
| 完整 pytest（最终变更） | 1396 passed，2 skipped |
| Spec-0072 集成脚本 | 目录检查通过，332 passed |
| Ruff | check 与 format --check 全仓通过，486 文件 |
| 前端 | 15 tests passed；构建通过 |
| 两仓配置合同 | OpenAgents a752e8830a13f44d97a3043d1f3e8dd16bd8d8aa，通过 |
| 两仓证据合同 | 同一版本：gzip/ZIP、14 类拒绝、retry reuse、legacy recovery，通过 |
| Spec | validate 通过；render/graph 已重生成 |
| Shell/工作树 | bash -n、git diff --check 通过 |

两项 pytest skipped 仍来自可选 `tau2` 未安装，不是断言失败。

新增 `backend/scripts/e2e-spec-0072-capability-migration.sh` 组合严格配置、冻结材料、监督器、两后端、真实消费者、交互计划、看板、公开目录和示例验收。此脚本不调用真实模型/forge/cloud。

身份验证执行了真实 bootstrap Python 逻辑、隔离 Git/setup、实际本地 supervisor/worker 写文件与进程终止；SDK 模拟器记录 root 管理和 user 启动参数。Docker entrypoint 的脚本测试使用受控系统命令，不能将它包装成真实容器 UID 切换。E2B collection 排除 runtime/home、python、uv-cache，保留 bootstrap 及执行/收集收据，避免依赖包膨胀或登录缓存进入证据包。

## 在线覆盖与复核步骤

本次没有创建云资源、Gitea issue/PR 或运行真实模型。当前 WSL 的 Docker CLI 报告缺少 Docker Desktop WSL integration，因此无法执行真实 local 容器验收。E2B 没有执行在线验收；Docker 不可用不是 E2B 的技术阻碍，两者须分开表述。

之前 E2B N1 五轮为空需求闭环，不能替代本组非空交付验证。后续在线验收至少应在新 run 完成：issue → 代码修改 → commit/push → PR → merge → 下一轮使用新 SHA，并核对实际 `id -u`、OpenAgents/Claude UID、产物可读与 stop/resume/collect。旧 run 使用冻结版本，不能拿旧 run 的结果冒充新实现验收。

在仓库根复核离线结果：

```bash
bash backend/scripts/e2e-spec-0072-capability-migration.sh
uv run --locked --extra experiments python backend/scripts/experiment.py check --config examples/experiments/synthesizer-n1-local.json --offline
uv run --locked --extra experiments python backend/scripts/experiment.py check --config examples/experiments/synthesizer-n1-e2b.json --offline
```

实际环境可用后按 [N1 教程](../tutorials/n1-experiment.zh-CN.md) prepare 新 run。观察入口：

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py dashboard "$RUN_ID" --secrets-file .env.experiment
```

local 读取实时本地产物；E2B 先 collect，显示快照来源和时间。缺 Gitea token 仍可读产物，不伪称已连接。`/api/runmeta` 不含凭证或宿主绝对目录。

## 尚未迁入的范围

工程 CI runner、入口内官方 SWE 评分、N4/N8/多任务/批量实验、历史产物追加轮与重放起始轮、旧 seed 库/纯文本输入仍待实现。自定义自建 Gitea 不在本次两套公开后端选择内。独立 OpenAgents 的 alternative backend 不等于旧 auto-designer controller 曾支持任意 backend。

本组只完成上表能力的实现及离线验收，不能据此宣称全部历史运行形态已迁入。[初次审计](../audits/unified-entry-capability-migration-20261003.md)保留当时的缺口和证据，后续状态以本报告为准。
