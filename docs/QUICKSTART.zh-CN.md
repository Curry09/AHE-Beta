# 快速开始

[English](QUICKSTART.md) | 简体中文

本指南从示例配置启动一次完整的 Harness 迭代实验。所有命令均在仓库根目录执行，统一入口为 `backend/scripts/experiment.py`。

| 后端 | 运行环境 | 仓库托管 | 所需准备 |
| --- | --- | --- | --- |
| `local` | 本地 Docker 容器 | 自动启动的本地 Gitea | Docker Engine、Compose 和模型凭证 |
| `e2b` | 每个实验一个 E2B 沙箱 | 自己的 Gitea.com 账户 | 模型凭证、`E2B_API_KEY`、`GITEA_TOKEN` |

首次运行可选择 U1：每轮一位模拟用户试用 pvlib 任务，共五轮。R1–R4 包含需求处理与交付，R5 只试用最终 Harness。U4 则在两项任务上安排四个用户会话，共两轮，用户并发为二。两类示例均迭代 Harness，任务源码用于模拟使用。

U8 mixed/direct、U16 和 U32 的六轮实验使用容器任务包，材料和启动步骤见[六轮教程](tutorials/evolution32.zh-CN.md)。以下先以 U1 为例介绍共同流程。

## 1. 安装

使用 Linux 或 WSL2，安装 Git、Python 3.12 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。本地运行还需要已启动的 Docker Engine 和 Compose，也可使用开启 WSL 集成的 Docker Desktop。

```bash
git clone https://github.com/Curry09/AHE-Beta.git
cd AHE-Beta
uv sync --locked --extra experiments
```

运行环境配方固定 Python、uv 和 Claude Code 的版本，具体值见[兼容清单](../release/compatibility.json)。准备阶段会获取固定版本的 OpenAgents 和 NexAU，无需另行克隆 OpenAgents 或安装个人版 Claude Code。

## 2. 选择示例，填写凭证

```bash
CONFIG=examples/experiments/u1-local.json
# E2B：
# CONFIG=examples/experiments/u1-e2b.json
# U4：
# CONFIG=examples/experiments/u4-local.json
# CONFIG=examples/experiments/u4-e2b.json
cp examples/experiment.env.example .env.experiment
chmod 600 .env.experiment
```

在 `.env.experiment` 中填写模拟用户、Harness 和需求角色的 OpenAI 兼容接口地址与密钥，以及交付角色的 Anthropic 兼容接口地址与凭证。OpenAgents 通过 Claude Code 交付，需要支持 Anthropic 协议的接口。

U1/U4 默认选择 `claude-opus-5-5`；六轮示例的用户与 Harness 使用 `glm-5.3-flash`，需求与交付使用 `glm-5.3`。根据供应商支持的名称，在准备前修改 JSON 中的四个 `models.*.model` 字段。Triage、Architect 和 PM 共用需求模型，示例中的 Owner 使用规则准入。

E2B 还需要沙箱 API 密钥，以及有权创建和读写本人仓库、Issue、评论及附件的 Gitea.com Token。可选 `GITEA_USER` 用于校验 Token 所属账户。本地 Gitea 凭证自动生成，网页登录信息保存在 run 目录的 `secrets/local-gitea-login.env`。完整字段见[配置说明](CONFIGURATION.zh-CN.md)。

## 3. 检查、准备、启动

先检查配置，再准备实验材料：

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --offline
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py prepare --config "$CONFIG" --secrets-file .env.experiment
```

`check --offline` 验证配置、本地材料和会话计划，尚未缓存的远端材料列为待下载。在线 `check` 还检查凭证及后端访问；只有显式添加 `--probe-models` 时才发送模型请求。

`prepare` 固定控制器、Harness、任务及依赖，下载所需源码，并为本地后端构建镜像。首次下载和构建通常比缓存后的运行更慢。准备过程中会提前输出 run ID，本地构建也会提供 `logs/prepare.log` 路径；等待命令成功结束后再启动实验。

准备成功后，将输出的 ID 填入 `RUN_ID`：

```bash
RUN_ID=REPLACE_WITH_PRINTED_RUN_ID
uv run --locked --extra experiments python backend/scripts/experiment.py run "$RUN_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py status "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py logs "$RUN_ID" --follow
```

`run` 完成资源创建、交付接口预检及控制器启动后返回。启动期间可在另一终端查询 `status`；`OPERATION_IN_PROGRESS` 表示操作仍在进行，`RUNNING` 表示已观察到控制器运行。日志跟随时按 Ctrl+C 只退出日志查看。

也可直接使用下面的命令连续完成准备与启动，无需重复执行上述 `prepare` 和 `run RUN_ID`：

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py run --config "$CONFIG" --secrets-file .env.experiment
```

## 4. 停止、继续、收集

使用同一个 run ID 管理实验：

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py stop "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py resume "$RUN_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py collect "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py destroy "$RUN_ID" --confirm "$RUN_ID"
```

`stop` 保留恢复记录。`resume` 使用原配置、仓库和资源继续运行；本地 Gitea 恢复原端口，端口冲突时应先排除冲突再重试。追加新轮次则需要从完整归档创建子实验，详见[追加教程](tutorials/experiment-continuation.zh-CN.md)。

默认输出位于 `.experiments/<run_id>/`。实验状态、资源状态和收集状态分别记录：`COMPLETED` 表示所有配置轮次完成；收集 `COMPLETE` 表示产物完整，不代表任务或实验成功。`destroy` 释放计算资源，保留收集产物、Gitea 仓库及共享构建缓存，默认拒绝销毁尚未完整收集的实验。

单实验的后台监控会定期收集产物；实验正常完成且收集完整后，自动释放计算资源。停止或失败的实验需要显式清理。E2B 的 `stop` 只停止进程，沙箱仍可能计费。

E2B 控制器可在本地 CLI 退出后继续运行，但后台收集依赖管理主机在线，且当前不会自动延长沙箱租期。示例 `runtime.e2b.timeout_seconds` 为 86400 秒；长实验应关注 `expires_at` 并定期收集。CLI `resume` 要求原沙箱仍在运行；暂停实例需先由操作者恢复，过期或已删除的沙箱标记为 `LOST`。详见[六轮教程](tutorials/evolution32.zh-CN.md#收集停止和恢复)。

## 指定实验的观测接口

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py dashboard "$RUN_ID" --secrets-file .env.experiment
```

`dashboard` 命令提供只读 JSON 观测 API。在另一终端运行 `curl http://127.0.0.1:8000/api/overview` 查询汇总，或通过 `/api/sessions` 查询会话。本地实验读取实时产物；E2B 读取最近一次 `collect` 的快照及采集时间，再次收集可刷新数据。

## 在每轮反馈前启用客观验收

普通示例默认不配置客观评分。需要向后续需求处理提供独立任务结果时，按[逐轮验收教程](tutorials/evolution-feedback.zh-CN.md)配置 `evaluation.session_grading`，准备私有评分计划及 worker 密钥。

local 和 E2B 都通过可信 Docker 主机上的 `assessment-worker` 验收冻结产物。先启动 run，再启动 worker；worker 未就绪时，控制器等待于 `objective_grading / PENDING`。末轮也会执行已配置的验收。体验评分、任务结果、归因和改进建议分别保存。

## 对已保存的会话产物评分

也可以在实验终态完整收集后，通过私有评分计划对原会话产物评分：

```bash
uv sync --locked --extra experiments --extra dev --extra evaluation
GRADING_PLAN=/absolute/path/to/grading-plan.json
uv run --locked --extra experiments --extra evaluation python backend/scripts/experiment.py grade "$RUN_ID" --plan "$GRADING_PLAN" --offline
```

`--offline` 仅检查计划和证据绑定，删除该参数后执行评分器。默认选择末轮，可用 `--round` 指定其他已完成并封存的轮次。local 和 E2B 归档均在 Docker 主机上评分，不需要模型凭证。材料格式和支持范围见[事后评分教程](tutorials/post-run-grading.zh-CN.md)。

评测已有 Harness 在新任务上的表现，则使用独立的 `evaluation.yaml` 入口，见[Harbor 评测指南](../evaluation/docs/harbor.zh-CN.md)。

## 运行一组实验

批次列表引用完整的单实验配置：

```bash
BATCH_CONFIG=examples/batches/u1-u4-local.json
# BATCH_CONFIG=examples/batches/u1-u4-e2b.json
# 四组六轮 E2B 实验：
# BATCH_CONFIG=examples/batches/evolution-four-e2b.json
uv run --locked --extra experiments python backend/scripts/experiment.py batch check --config "$BATCH_CONFIG" --offline
uv run --locked --extra experiments python backend/scripts/experiment.py batch prepare --config "$BATCH_CONFIG" --secrets-file .env.experiment
BATCH_ID=REPLACE_WITH_PRINTED_BATCH_ID
uv run --locked --extra experiments python backend/scripts/experiment.py batch run "$BATCH_ID" --secrets-file .env.experiment
```

示例每次运行一个活动实验。`batch run` 在前台持续监督到终态收集；Ctrl+C 退出监督，已启动的成员继续运行。`batch stop` 停止成员，`batch resume` 接回同一批次。批次不会自动销毁计算资源或删除仓库，收集和清理方式见[批量实验教程](tutorials/batch-experiment.zh-CN.md)。

## 离线演示和开发

离线交互演示：

```bash
uv run --locked python backend/scripts/offline_demo.py
```

开发检查：

```bash
uv sync --locked --extra experiments --extra dev --extra harbor-evaluation
uv run --locked --extra experiments --extra dev --extra harbor-evaluation pytest -q
```

[完整 U1 教程](tutorials/u1-experiment.zh-CN.md)进一步说明预期产物和排查方法，[配置说明](CONFIGURATION.zh-CN.md)介绍模型、预算、分组和交付策略。开发贡献见[贡献指南](../CONTRIBUTING.zh-CN.md)。历史实验按[研究索引](../research/README.zh-CN.md)记录的源码版本复现。
