# 快速开始

[English](QUICKSTART.md) | 简体中文

以下命令全部在 auto-designer 仓库根目录执行。完整实验的统一入口是 `backend/scripts/experiment.py`，选好后端后，两条路径使用相同的操作命令。

| 后端 | 执行环境 | Git 托管 | 用户需要提供 |
| --- | --- | --- | --- |
| `local` | 本机 Docker 容器 | 程序自动启动独立的 localhost Gitea | 可用的 Docker 服务、模型凭证 |
| `e2b` | 每个实验一个 E2B 沙箱 | 用户自己的 Gitea.com 账户 | 模型凭证、`E2B_API_KEY`、`GITEA_TOKEN` |

可选 N1：每轮一位用户试用一个任务；或 N4：每轮四位用户试用两个任务，并发上限为二。N4 共两轮，首轮包含交付，末轮只试用。任务包列表和显式 persona/任务计划使用同一入口。历史结果导入后追加一轮仍不支持。N1 示例是每轮一位模拟用户、共五轮：R1–R4 包含需求处理与 OpenAgents 交付，R5 仅试用最终 Harness。被进化的对象是 Harness；pvlib 是用户的试用任务，auto-designer 是实验控制器。官方 SWE-bench 评分是独立的事后步骤。

## 1. 安装

使用 Linux 或 WSL2，准备 Git、Python 3.12 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。本地路径还需要 Docker Engine 和 Compose；也可以用开启 WSL 集成的 Docker Desktop。

```bash
git clone https://github.com/Curry09/auto-designer.git
cd auto-designer
uv sync --locked --extra experiments
```

运行环境配方固定 uv 0.11.28、Python 3.12.13 和 Claude Code 2.1.284。OpenAgents、NexAU 的版本来自[兼容清单](../release/compatibility.json)，prepare 自动获取 OpenAgents，不需要提前放置 sibling checkout 或上传个人 Claude 程序。

## 2. 选择示例，填写凭证

```bash
# 本地 Docker + localhost Gitea：
CONFIG=examples/experiments/synthesizer-n1-local.json
# 或者 E2B + 用户自己的 Gitea.com：
# CONFIG=examples/experiments/synthesizer-n1-e2b.json
# 四位用户、两个任务：选择对应后端。
# CONFIG=examples/experiments/synthesizer-n4-local.json
# CONFIG=examples/experiments/synthesizer-n4-e2b.json
cp examples/experiment.env.example .env.experiment
chmod 600 .env.experiment
```

编辑 `.env.experiment`，填写 User、Harness、需求面的 OpenAI-compatible base URL/key，以及交付角色的 Anthropic-compatible base URL/token。示例模型为 `claude-opus-5-5`；供应商模型名不同时，复制 JSON 后修改四个 `models.*.model`。Triage、Synthesizer、PM 共用需求模型，Owner 准入是机械规则。

E2B 路径还要填写 `E2B_API_KEY` 和 Gitea.com token，授权创建、读写本人的私有仓库、Issue、评论、附件。可选的 `GITEA_USER` 用于校验 token 实际对应的账号。本地 Gitea 账户和 token 自动生成；新建账户的网页登录信息保存在对应 run 的 `secrets/local-gitea-login.env`（权限 0600）。具体格式见[配置说明](CONFIGURATION.zh-CN.md)。

## 3. 检查、准备、启动

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --offline
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py prepare --config "$CONFIG" --secrets-file .env.experiment
```

离线检查验证 JSON 和本地材料，不调用模型、不创建云资源。第二条 check 检查凭证配置和 Docker/provider 访问，除非显式加 `--probe-models`，否则不发送模型请求。prepare 生成唯一 run ID，冻结输入，下载固定版本源码，并构建所需本地镜像；不调用模型，也不启动实验资源。冻结后 `[prepare]` 会先输出 run ID，本地构建还会输出日志路径；可在另一终端执行 `tail -f /printed/path/logs/prepare.log` 查看首次镜像构建进度。首次需要下载源码、依赖、Claude 和 Docker 镜像，冷构建可能明显慢于后续使用缓存的准备。等 prepare 成功结束再启动实验，提前出现 ID 不代表已准备好。复制 run ID：

```bash
RUN_ID=REPLACE_WITH_PRINTED_RUN_ID
uv run --locked --extra experiments python backend/scripts/experiment.py run "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py status "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py logs "$RUN_ID" --follow
```

run 创建资源、预检实际交付 reader，启动 controller 后才输出结果。启动中可在另一终端用 status 查看最近记录的状态；`OPERATION_IN_PROGRESS` 表示启动操作仍在执行。资源启动不等于实验进入 `RUNNING`。查看日志时 Ctrl+C 只结束日志跟随，不停止实验。首次 E2B 运行可能需要构建模板。

## 4. 停止、继续、收集

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py stop "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py resume "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py collect "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py destroy "$RUN_ID" --confirm "$RUN_ID"
```

stop 保留实验身份、仓库与 recovery checkpoint。本地会停止 Gitea/egress、清理执行容器并保留 Gitea 数据；resume 恢复原 loopback 端口和仓库。原端口被占用时，应排除冲突后重试 resume，不修改冻结地址。E2B 停进程后沙箱仍被分配，仍可能计费。resume 使用同一份冻结输入和仍存活的资源；到期或被删除的沙箱会标为 `LOST`，不会悄悄新建后声称续跑。destroy 保留已收集产物、Gitea 仓库和共享构建缓存；没有完整收集时默认拒绝删除。

默认目录为 `.experiments/<run_id>/`。实验结果、资源状态、收集状态分别记录：配置的轮次全部封口和 controller 完成才是 `COMPLETED`；收集的 `COMPLETE` 不代表实验成功。主机在线时后台 monitor 周期收集。终态收集完成前应保持主机在线，云沙箱到期可能丢失尚未收集的数据。

[完整 N=1 教程](tutorials/n1-experiment.zh-CN.md)说明所有输入、预期结果、中断边界和证据；[多用户教程](tutorials/multi-user-experiment.zh-CN.md)提供两个任务、固定跨轮计划和停止/恢复的 N4 流程；实际验证结果见[N1 报告](validation/spec-0069-new-user.md)和[多用户报告](validation/spec0073-multi-task-users.md)。

## 对已保存的 SWE 任务补丁评分

终态完整收集后，安装 evaluation extra，独立提供经过核验的本地官方数据集。local 与 E2B 归档都在本机用 Docker 评分；`grade` 不需要模型或 provider 凭证。

```bash
uv sync --locked --extra experiments --extra dev --extra evaluation
DATASET=/absolute/path/to/official-dataset.parquet
DATASET_SHA256=REPLACE_WITH_VERIFIED_SHA256
uv run --locked --extra experiments --extra evaluation python backend/scripts/experiment.py grade "$RUN_ID" --dataset "$DATASET" --dataset-sha256 "$DATASET_SHA256" --offline
```

删除同一命令的 `--offline` 即执行官方新容器评分。默认选择配置的末轮；`--round 1` 可选择更早的已封口轮次。它评的是用户任务补丁，不是新的 Harness 留出测试，结果不进入演化循环。每次评分保留原实验产物；没有完整预测回执的旧控制器需新跑实验。数据集格式、哈希、输出和失败状态见[评分教程](tutorials/post-run-grading.zh-CN.md)。

## 运行一组实验

填好同一份 `.env.experiment` 后，选择批次列表，替代单个实验配置：

```bash
BATCH_CONFIG=examples/batches/n1-n4-local.json
# BATCH_CONFIG=examples/batches/n1-n4-e2b.json
uv run --locked --extra experiments python backend/scripts/experiment.py batch check --config "$BATCH_CONFIG" --offline
uv run --locked --extra experiments python backend/scripts/experiment.py batch prepare --config "$BATCH_CONFIG" --secrets-file .env.experiment
BATCH_ID=REPLACE_WITH_PRINTED_BATCH_ID
uv run --locked --extra experiments python backend/scripts/experiment.py batch run "$BATCH_ID" --secrets-file .env.experiment
```

示例每次只运行一个活动实验。`batch run` 在前台监督到终态收集；Ctrl+C 退出监督，已启动成员继续运行。停止成员用 `batch stop`，接回原成员用 `batch resume`。N1 为五轮、N4 为两轮，因此这些列表演示调度，不构成公平的因果对照。状态、子实验专属 `--runs-dir`、收集、成本和显式清理见[完整批次教程](tutorials/batch-experiment.zh-CN.md)。批次管理不自动销毁计算资源或删除仓库；E2B stop 后沙箱仍保留。


## 离线演示和开发

只查看一次不调用模型、不使用 Docker 的脚本交互：

```bash
uv run --locked python backend/scripts/offline_demo.py
```

开发控制器时：

```bash
uv sync --locked --extra experiments --extra dev
uv run --locked --extra experiments --extra dev pytest -q
```

公开 examples 目录只放当前 v2 实验定义。[开发维护工具](../tools/dev/README.md)用于独立诊断，不是另一套实验入口。[历史研究](../research/README.zh-CN.md)集中归档并记录源码版本和迁移清单，复现时使用对应版本的独立 checkout。新实验走上述统一入口。可选前端见 [README](../README.zh-CN.md)。

## 指定实验的观测看板

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py dashboard "$RUN_ID" --secrets-file .env.experiment
```

local 看板读取该 run 的实时产物。E2B 先执行 collect，再启动 dashboard；显示最后一次收集快照，云端继续运行时需重新 collect 刷新。若前端未构建，在另一个终端运行 `cd frontend && npm ci && npm run dev`；构建前端后可直接访问 `http://127.0.0.1:8000`。默认开发 API 不会自动选择实验，建议使用此命令。

分组、推理强度、延迟隔离、交付参数、Owner 模型评审、direct 与显式逐轮计划见[配置说明](CONFIGURATION.zh-CN.md)。改变这些设置后需 prepare 新实验，已有 run 不升级。
