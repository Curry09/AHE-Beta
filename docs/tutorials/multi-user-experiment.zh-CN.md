# 运行两个任务、四位用户的实验

[English](multi-user-experiment.md) | 简体中文

本教程使用受维护的 U4 local/E2B 示例：每轮四位不同 persona、两个任务、共两轮，最多同时运行两个用户会话。每个会话在独立可写工作区试用本轮同一 Harness SHA。所有会话围绕同一份 Harness 进行迭代。

当前 checkout 的检查命令见[验证方法](../VERIFICATION.zh-CN.md)。真实 provider/模型结果应查看本次 U4 运行产物。

## 1. 安装并选择后端

使用 Linux 或 WSL2、Git、Python 3.12 与 uv。本地需要运行中的 Docker daemon 和 Compose；E2B 需要 API key，且 Gitea.com 账户要有新建仓库的容量。两种后端使用同一套生命周期命令。

```bash
git clone https://github.com/Curry09/auto-designer.git
cd auto-designer
uv sync --locked --extra experiments
cp examples/experiment.env.example .env.experiment
chmod 600 .env.experiment
CONFIG=examples/experiments/u4-local.json
# CONFIG=examples/experiments/u4-e2b.json
```

按[凭证说明](../CONFIGURATION.zh-CN.md)填写 `.env.experiment`：User、Harness、需求角色使用 OpenAI 兼容 Chat Completions，交付角色使用 Anthropic 兼容 Claude Code。E2B 还需要 `E2B_API_KEY`、`GITEA_TOKEN`；本地自动创建 localhost Gitea 凭证。密钥不放 JSON。更换模型时，在 prepare 前修改四个 `models.*.model`；复制 JSON 后必须保持材料相对路径正确。

## 2. 理解材料与计划

`workload.task_packages` 列出 `examples/tasks/pvlib-1478/task.json` 和 `examples/tasks/order-service/task.json`。每个包有自己的 kind、ID、指令、固定源码、setup 和带 hash 的依赖锁。pvlib 使用固定 Git 源码；order-service 是 MIT 的小示例项目，含可见测试和已有的商品数量计费问题。普通任务声明 `not_in_benchmark: true`。两者默认使用逐步交互的 `simulated_user`；如要直接发一次任务给 Harness、完成后再由 persona 评阅，可在 prepare 前把对应任务包设为 `interaction: "direct"`。

模拟用户画像来自 `examples/personas/library.json`，根据公开资料构建。显式计划让同轮两个 persona 试同一任务，下一轮交换任务：

| Persona | R1 | R2 |
| --- | --- | --- |
| `sr-01-willison` | `pvlib__pvlib-python-1478` | `order-service` |
| `sr-02-ronacher` | `pvlib__pvlib-python-1478` | `order-service` |
| `sr-07-baldur` | `order-service` | `pvlib__pvlib-python-1478` |
| `sr-15-swyx` | `order-service` | `pvlib__pvlib-python-1478` |

每轮四个 session，`max_parallel_users: 2`。R1 等所有用户会话终结，再运行 Triage/Synthesizer/Owner，并等待准入交付票达到终态后封口。R2 只试用已封口 Harness，不再生成交付批次。任务结果、用户满意度、基础设施失败分别记录。

创建其他实验时，选择库中存在的 persona ID 和唯一任务包 ID。`task_packages` 与旧 `kind` + `task_package` 互斥。省略 interaction_plan 时，按全局槽 k=(round_no-1)*sessions_per_round+slot，分别取第 k % P 个 persona 与第 k % T 个任务；这种简单轮转不保证覆盖全部 persona × task 组合，覆盖或固定分组请写显式计划。所选 persona ID 集合仍唯一；执行列表允许重复画像或完整配对。sessions_per_round 表示槽位数量，而非不同画像数。每个槽位都有独立对话、client、工作区及恢复身份；复用画像不代表多个独立真人样本。

## 3. 检查并冻结全部任务

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --offline
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py prepare --config "$CONFIG" --secrets-file .env.experiment
```

离线 check 检查所有本地文件、persona/task 引用及逐轮槽位，输出尚未冻结的预览；不拉取 Git，也不生成最终源码内容摘要。普通 check 检查凭证和 provider 访问，显式 `--probe-models` 才额外发送模型请求。prepare 获取固定版本 OpenAgents，核对各任务固定 Git revision，冻结源码清单、指令、setup 和锁，最后把任务摘要绑定到 SessionPlan。某个任务失败不会发布可启动的半成品。

等待 prepare 成功结束，提前打印 ID 不代表已准备好。本地构建共享 controller/交付底座和逐任务镜像；`runtime.local.seed_image` 只用于单任务覆盖，不能覆盖这两个任务。E2B 在 run 的沙箱创建阶段准备任务基线。首次下载依赖和构建镜像可能明显慢于后续缓存运行。

## 4. 启动和查看

```bash
RUN_ID=REPLACE_WITH_PRINTED_RUN_ID
uv run --locked --extra experiments python backend/scripts/experiment.py run "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py status "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py logs "$RUN_ID" --follow
```

准确复制打印出的 ID。logs 标示运行阶段，跟随日志时 Ctrl+C 只停止日志查看。status 给出任务准备情况及基于账本的逐轮已完成/运行中/待运行/失败局数；没有账本或 provider 不可达时显示 unknown，不根据配置的八局推断完成。终结结果不自动代表任务成功或用户接受。

`.experiments/$RUN_ID/` 的冻结材料包含 `manifest.json`、`materials/task-catalog.json`、`materials/session-plan.json`，及各任务 `materials/tasks/<task_id>/` 下的包、指令、setup、锁和源码 archive。`resources.json` 记录 provider 资源，`runtime/task-workspaces.json` 是 controller 使用的任务工作区映射。本地执行时，实际 session JSON 位于 run 目录内的 `data/role_runs/$RUN_ID/sessions/`，checkpoints 与轮次 seal 位于 `checkpoints/`。E2B 执行时这些路径先存在于沙箱的 run 目录；collect 后，本机副本位于 `runtime/cloud-snapshot/data/role_runs/$RUN_ID/sessions/` 和 `runtime/cloud-snapshot/checkpoints/`。审计反馈时一起核对 task ID/digest、persona、round/slot、稳定 session ID 和 Harness SHA。

## 5. 停止并恢复同一 run

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py stop "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py resume "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py status "$RUN_ID"
```

stop 保留冻结身份和 checkpoint。完整且归属匹配的 SessionStore 结果会核对后跳过，不重新运行用户或创建重复 Issue；中断且未完成的 session 使用干净 attempt。resume 校验原资源和逻辑任务/persona 绑定，不修改已终结结果、不增加轮次、不导入历史 archive，也不升级冻结代码。到期或已删除的 E2B 沙箱是 LOST，需要保留原资源才能恢复。

本教程的两个任务包使用源码配方：本地会话运行在独立容器中，E2B 在各会话目录复制源码并重新创建虚拟环境。下载和 wheel 缓存可共享，可写的源码和环境保持独立。其他实验若使用 v3 容器任务，则会通过沙箱内 Docker 创建任务容器，见[任务环境说明](../CONFIGURATION.zh-CN.md#后端边界和生命周期)。

## 6. 收集、观察和清理

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py collect "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py dashboard "$RUN_ID" --secrets-file .env.experiment
```

选定的本地看板读取实时材料；E2B 展示最近 collect 的快照和时间，再次 collect 可刷新。会话详情保留 task/persona/session/round/Harness SHA，反馈证据保留任务来源。没有 tracker token 时，已收集的本地产物仍可离线查看，但不会显示为已连接 Gitea。用 Vite 开发界面时，在另一终端执行 `cd frontend && npm ci && npm run dev`。

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py collect "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py destroy "$RUN_ID" --confirm "$RUN_ID"
```

终态收集后再销毁。destroy 释放本 run 的计算资源，保留 Gitea 仓库、已收集产物和共享构建缓存；E2B stop 进程本身仍保留沙箱。主机 monitor 只在本机在线时收集，终态收集成功前请保持在线。

## 成本与验证边界

示例运行八个用户 session 及对应 Harness 请求，另有一轮需求和交付；角色/模型调用量取决于实际 Issue。并发上限限制活跃 session，不限制总调用量或费用，两个任务的依赖构建成本也不同。COMPLETED 需要配置的两轮全部封口和 controller 完成，收集成功不等于实验成功。

用 `bash backend/scripts/e2e-spec-0073-multi-task-users.sh` 执行离线集成验收。它运行真正的材料编译、会话 runner、SessionStore、RecoveryStore 和需求 driver，在 provider/模型边界使用脚本替身；不能据此验证真实 Docker/E2B/Gitea 或模型表现。本次运行的后端与模型结果应从其实际运行记录核对，开发检查命令见[验证说明](../VERIFICATION.zh-CN.md)。
