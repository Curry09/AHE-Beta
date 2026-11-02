# 迭代任务材料

[English](README.md)

这套材料提供 U8 mixed/direct、U16 mixed、U32 mixed 示例所用的 32 个场景。前 8 项和前 16 项组成较小的实验组。实验配置负责选择任务包和交互方式；本清单只记录材料身份与来源。

示例从当前 seed 开始新的运行。准备阶段冻结输入、配方和镜像身份，分别记录历史原始 payload 与明确重建的上游源码。这里的场景用于 Harness 迭代；导出的 Harness 可通过独立的 `evaluation.yaml` 参加评测。

## 文件组成

- `manifest.json`：任务顺序、原 benchmark 标识、指令 hash、persona 绑定和材料发布状态。
- `<task-key>/instruction.md`：原始任务请求；缺少文件末尾换行时只补一个换行。
- `<task-key>/task.json`：可执行的 schema 3 环境与产物声明，固定镜像 digest 和输入校验和。
- `recipes/initialize.py`：恢复真实的初始 Git 版本，并补入已校验、原本被 Git 忽略的输入文件。
- `recipes/verify.py`：在 Actor 启动前检查材料及运行环境是否可用。
- `recipes/finalize.py`：在 Actor 退出后收取独立的 KV 测量，并生成单独的公开摘要。
- `recipes/collect_directory.py` 及任务专用收集器：在 Actor 退出后保存实际文件和产物。
- `recipes/freeze_initial_git.py`：在执行前，将声明的初始文件记录进准备版 Git 基线。

发布和验证状态以 `manifest.json` 为准。[固定版本材料 Release](https://github.com/Curry09/AHE-Beta/releases/tag/evolution32-task-materials-v1) 包含 37 项输入资产，以及 `materials.lock.json`、`SHA256SUMS` 和 README。准备阶段只下载所选任务需要的资产，逐项检查哈希及文件清单。主仓当前仍为私有，带身份下载单独验证；匿名材料下载待主仓公开后再验证，通用材料下载器不加入 GitHub 身份认证逻辑。

32 项任务镜像统一使用 `ghcr.io/mmjzmy/auto-designer-tasks:<任务 key 小写>-v<version>`，例如 `m04-v1`、`o03-v1`、`kv-live-surgery-v1`。实际任务定义锁定镜像 digest；源码、依赖版本与构建配方记录在清单中。

32 项任务镜像和 4 项配套服务镜像均已公开，逐项通过干净 E2B 环境中的匿名下载、镜像身份校验和工具启动。32 项最终任务配方还通过了真实本地 Docker 初始化、就绪、收尾及收集检查，检查时未启动 Actor。[清单](manifest.json)记录材料身份与验证凭据；[验证方法](../../../docs/VERIFICATION.zh-CN.md)提供当前 checkout 可复现的检查命令。

## 材料边界

原始构建输入留在管理侧。KV 服务端源码和 benchmark 作者的 README 用来构建删除源码、去除符号的二进制，不会整包放进 Actor 工作区。负载发生器在独立配套容器中运行，原始测量和日志属于管理侧证据；公开摘要仅展示任务已经公开要求的加速、正确性和存活性观测。

有原始 Git 基线的场景据此审查实际补丁。M01、M03 和 Pretrain 另以确定性准备提交记录全部已提供的初始文件；来源记录同时保留前后版本，源码与数据字节不变。原本没有 Git 的任务保留原环境，使用源码归档或声明产物；工作簿和服务结果也使用明确声明的产物。每次尝试创建新环境，测量收尾和产物收集完成后才清理服务。

场景准备逻辑位于固定任务配方中。实验控制器、E2B 提供方和 Docker 驱动统一消费环境合同，无须按任务 key 分支。新增任务可自行声明材料、镜像、命令、服务和产物。

模型与提供方配置、四组实验的启动方法见[完整教程](../../../docs/tutorials/evolution32.zh-CN.md)。

## 任务顺序

| Key | 来源类别 | 原始任务标识 |
| --- | --- | --- |
| O03 | SWE-bench | `pvlib__pvlib-python-1478` |
| O09 | Terminal-Bench | `production-planning` |
| O14 | TUA-Bench | `010-pivot-product-revenue` |
| M03 | mechanism | `superset-goal-discovery` |
| O01 | SWE-bench | `pylint-dev__astroid-2240` |
| kv-live-surgery | Terminal-Bench | `kv-live-surgery` |
| tinydb | NL2Repo | `tinydb` |
| M01 | mechanism | `sqlfluff-subagent-review` |
| O05 | SWE-bench | `marshmallow-code__marshmallow-1229` |
| O06 | SWE-bench | `sqlfluff__sqlfluff-2336` |
| vf2-speedup-networkx | Terminal-Bench | `vf2-speedup-networkx` |
| pretrain-shard-corruption | Terminal-Bench | `pretrain-shard-corruption` |
| 091-add-receipts-bookkeeping | TUA-Bench | `091-add-receipts-bookkeeping` |
| flask-restful | NL2Repo | `flask-restful` |
| M05 | mechanism | `permission-schema-migration` |
| M09 | mechanism | `plan-blocked-dependency` |
| O02 | SWE-bench | `pydicom__pydicom-1334` |
| O04 | SWE-bench | `pyvista__pyvista-3750` |
| astroid-1030 | SWE-bench | `astroid-1030` |
| sqlfluff-3608 | SWE-bench | `sqlfluff-3608` |
| marshmallow-2123 | SWE-bench | `marshmallow-2123` |
| payments-pipeline-fix | Terminal-Bench | `payments-pipeline-fix` |
| wal-recovery-ordering | Terminal-Bench | `wal-recovery-ordering` |
| vba-userform-port | Terminal-Bench | `vba-userform-port` |
| react-lead-form | Terminal-Bench | `react-lead-form` |
| 080-convert-novel-epub | TUA-Bench | `080-convert-novel-epub` |
| cookiecutter | NL2Repo | `cookiecutter` |
| tqdm | NL2Repo | `tqdm` |
| M02 | mechanism | `superset-ci-loop` |
| M04 | mechanism | `dbt-direction-negotiation` |
| M07 | mechanism | `memory-project-constraints` |
| M10 | mechanism | `review-verifier-catches-regression` |
