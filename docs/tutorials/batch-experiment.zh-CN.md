# 批量运行完整实验

[English](batch-experiment.md) | 简体中文

批次冻结一份现有实验配置列表，监督各成员跑完自己的完整闭环。每个成员有独立的冻结输入、Harness 仓库、资源、checkpoint 和结果。批次与单实验共用 `backend/scripts/experiment.py`，不增加另一套 controller。

公开示例在同一后端列出 N1 和 N4。**它们演示批量执行，不构成公平的因果对照：**N1 是一个任务、五轮；N4 是两个任务、两轮，批次不改这些设置。完整流程见 [N1](n1-experiment.zh-CN.md)和 [N4](multi-user-experiment.zh-CN.md)教程。需要受控对照时，先分别准备完整配置，并明确需要比较的因素。

## 1. 安装，选择列表

按[快速开始](../QUICKSTART.zh-CN.md)安装依赖和填写凭证。本地需要 Docker 和 Compose；E2B 需要沙箱容量及自己的 Gitea.com 账户。以下命令都在仓库根目录执行。

```bash
uv sync --locked --extra experiments
cp examples/experiment.env.example .env.experiment
chmod 600 .env.experiment
RUNS_DIR=.experiments
BATCH_CONFIG=examples/batches/n1-n4-local.json
# BATCH_CONFIG=examples/batches/n1-n4-e2b.json
```

在线检查前填好 `.env.experiment`。修改模型、轮次或 persona 时，先复制和修改各实验 JSON，保持相对材料路径有效，再让批次引用这些完整配置。凭证只放受保护的 env 文件，不写入两种 JSON。

批次使用 `schema_version: 1`，包含名称、`max_parallel_runs`（默认 `1`）及非空的 `entries`；每项包含唯一 `id` 和 `config`。配置路径相对批次 JSON 解析。同一批所有成员须使用同一后端；不支持局部覆盖、参数矩阵、任意 shell 命令或混合后端批次。详见[配置说明](../CONFIGURATION.zh-CN.md#批次配置)。

## 2. 检查，冻结所有成员

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" batch check --config "$BATCH_CONFIG" --offline
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" batch check --config "$BATCH_CONFIG" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" batch prepare --config "$BATCH_CONFIG" --secrets-file .env.experiment
BATCH_ID=REPLACE_WITH_PRINTED_BATCH_ID
```

离线检查逐项验证本地材料，不读凭证、不获取 Git、不调用 provider。在线检查复用单实验的凭证和 provider 检查。无法由 provider 确认剩余仓库配额时明确报告容量未知，未知不代表名额足够。

prepare 顺序冻结成员并记录各自唯一的 run ID，不启动实验资源、不调用模型。所有成员准备成功后才可启动批次；准备失败会阻塞，不能让半成品运行。准备途中中断时，`batch resume` 核对该批次已有子实验；不会为已存在但准备失败的成员悄悄新建替代实验。

## 3. 前台监督运行

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" batch run "$BATCH_ID" --secrets-file .env.experiment
```

保持该命令运行。单实验的 `run` 返回启动确认；`batch run` 持续监督到终态收集。成员启动后仍占用名额；活动未知、操作仍在进行或终态收集未完整时也保留名额，避免超额派发。某个成员失败或丢失后停止启动其余排队成员，已有活动成员继续观测和收集。

Ctrl+C 退出批次监督、停止后续排队启动，**不会停止已经启动的实验**。用 `batch resume` 接回监督；需要停止子实验进程时用 `batch stop`。另一终端可查看状态：

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" batch status "$BATCH_ID" --secrets-file .env.experiment
```

`max_parallel_runs` 限制本批次的活动或不确定运行租约，不是整个账户的上限，也不是已分配沙箱数或模型调用数上限。各子实验保留自己的 `max_parallel_users`，N4 为两个并发用户会话。停止或完成后的资源可能仍被分配，独立实验及其他批次不受本批上限管理。

## 4. 停止、续跑、收集原成员

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" batch stop "$BATCH_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" batch resume "$BATCH_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" batch collect "$BATCH_ID" --secrets-file .env.experiment
```

stop 先持久保存暂停请求，再停止已启动成员；正在停止或无法访问的成员不会立即被宣称为已暂停。resume 接回活动成员，从原 checkpoint 恢复已停止成员，只对从未启动的成员执行 fresh run。冻结模型、任务和计划不变，不升级源码，也不替换 LOST 沙箱。

collect 逐项报告完整、部分或失败。整个批次成功要求所有实验为 `COMPLETED`，且所有终态收集为 `COMPLETE`。收集成功不等于实验成功或 benchmark 通过。终态收集完成前保持主机在线。

## 5. 查看单个成员，清理保留资源

批次目录为 `$RUNS_DIR/.batches/$BATCH_ID/`。`intent.json`、`manifest.json` 固定所选成员，`runtime.json`、`journal.jsonl` 记录调度观测。每个子实验位于 `children/<entry_id>/<run_id>/`，沿用单实验的正常产物结构。从 batch status 的 `entries[entry_id].run_id` 复制子实验 ID，从 `child_roots[entry_id]` 复制目录，再按下面的命令管理。

以下以 `n1` 成员为例，替换打印出的 run ID；另一成员使用 `children/n4`：

```bash
CHILD_RUNS_DIR="$RUNS_DIR/.batches/$BATCH_ID/children/n1"
RUN_ID=REPLACE_WITH_PRINTED_CHILD_RUN_ID
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$CHILD_RUNS_DIR" status "$RUN_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$CHILD_RUNS_DIR" logs "$RUN_ID" --follow --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$CHILD_RUNS_DIR" dashboard "$RUN_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$CHILD_RUNS_DIR" collect "$RUN_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$CHILD_RUNS_DIR" destroy "$RUN_ID" --confirm "$RUN_ID" --secrets-file .env.experiment
```

管理成员必须指定其 `--runs-dir`，不能拿子 run ID 到外层根目录找。E2B 看板显示已收集快照，先 collect 再查看；完整收集后再 destroy。批次管理不自动销毁计算资源或删除仓库。E2B 停进程后沙箱仍被分配，应核对资源状态并用显式清理命令。销毁计算不会删除 Gitea 仓库；需要删旧仓时，先自行保存需要的记录。

这两个示例通常需要两个独立 Harness 仓库。顺序执行也可能耗尽仓库配额，因为先前成员结束后仓库仍保留。N1/N4 列表共安排十三个用户会话，另有 Harness 请求及需求/交付工作；降低并发不减少总调用或费用。云资源分配、依赖构建和模型生成各有成本。容量未知的检查结果和本教程都不证明账户配额足够。

[单实验多用户验收报告](../validation/spec0073-multi-task-users.md)对应独立 N4 运行，不证明 local/E2B 批次已经真实跑通。使用脚本化 provider/model 边界的批次测试应与真实执行分开记录。
