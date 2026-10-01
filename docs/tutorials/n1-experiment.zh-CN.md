# 完整运行五轮 N=1 实验

[English](n1-experiment.md) | 简体中文

本教程使用仓内 pvlib 任务和 `sr-15-swyx` persona。本地与 E2B 示例的任务、persona、seed、角色、模型和五轮语义完全一致，只选一次基础设施，后续操作相同。真实验证结果单独记录在[验证报告](../validation/spec-0069-new-user.md)。

## 1. 从仓库开始
utorials
n1-experiment.zh-CN.md

```bash
git clone https://github.com/Curry09/auto-designer.git
cd auto-designer
uv sync --locked --extra experiments
```

本地先检查 `docker info`、`docker compose version`。E2B 路径准备 E2B API key 和本人 Gitea.com token。prepare 自动获取固定版本的 OpenAgents；新建的 Harness 仓库与控制器仓库、pvlib 任务仓库分别独立。

```bash
CONFIG=examples/experiments/synthesizer-n1-local.json
# 云端只替换这一选择：
# CONFIG=examples/experiments/synthesizer-n1-e2b.json
cp examples/experiment.env.example .env.experiment
chmod 600 .env.experiment
```

填写 env 中的模型地址和凭证，E2B 另填两个 provider key。JSON 默认模型是 `claude-opus-5-5`。User/Harness/需求面用 Chat Completions-compatible 地址；交付面用 Anthropic-compatible 地址。不会自动借用其他 checkout 的 `.env` 或个人 Claude 登录。

## 2. 理解输入材料

| 材料 | 本实验内容 |
| --- | --- |
| 实验 JSON | `examples/experiments/synthesizer-n1-{local,e2b}.json` |
| 任务元数据 | `examples/tasks/pvlib-1478/task.json` |
| 用户需求 | 让 ModelChain 接收 weather dataframe 中随时间变化的 albedo |
| 任务初始代码 | `pvlib/pvlib-python`，提交 `3f397ed44075b01f4ba535750356859195a51b2d` |
| 任务环境 | 仓内安装脚本、包含完整 hash 的依赖锁 |
| Persona | `examples/personas/n1.json`，选择 ID `sr-15-swyx` |
| 初始 Harness | 当前 `backend/harness_template/`，prepare 时冻结 |
| 角色 | 一个 Triage、一个 Synthesizer、机械 Owner、一个 developer；无 divergent PM |

任务只提供文本和初始代码，不给优化角色标准答案或隐藏测试。用户可以主观接受结果，但不等于官方 SWE-bench 通过，本示例不运行官方评分。

## 3. 检查并冻结

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --offline
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py prepare --config "$CONFIG" --secrets-file .env.experiment
```

离线 check 验证材料，第二条 check 验证凭证配置和 Docker/provider 访问，不发送模型请求。需要测试模型时显式加 `--probe-models`。先看到材料合法报告，再看到生成的 run ID、冻结目录与下一条命令。未知字段、不存在的 persona 或缺少本地文件在 check 时失败。prepare 下载固定 Git 源码、冻结材料 hash，并构建本地运行镜像。第一次源码、依赖、Claude、Docker 镜像下载和构建需要时间；冷准备可能明显慢于缓存运行，下载耗时取决于网络，初期等待本身不代表 controller 卡住。此阶段不发模型请求、不启动实验资源。输入冻结后，`[prepare]` 会提前输出 run ID 和冻结目录；本地构建还会给出 `logs/prepare.log` 路径，可在另一终端执行 `tail -f /printed/path/logs/prepare.log` 查看下载与构建命令。此时记录的状态为 `PREPARING`，必须等 prepare 成功结束再 run，提前出现 ID 不代表已准备好。E2B prepare 输出冻结材料目录，不产生本地镜像构建日志。

```bash
RUN_ID=REPLACE_WITH_PRINTED_RUN_ID
```

快照位于 `.experiments/$RUN_ID/`，包含 `manifest.json`、`materials/`、源码 pin、生成计划。选其他目录时，在每条命令的子命令前加全局 `--runs-dir /absolute/path/runs`。身份包括 config/controller/plan hash。之后修改原 JSON 不改变这个 run；更改配置应 prepare 新实验。

## 4. 启动完整 controller

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py run "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py status "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py logs "$RUN_ID" --follow
```

`run` 等待 provisioning、预检和 controller 启动后才输出最终结果，不会向 stdout 流式输出准备进度。启动中 runtime 会记录 `PROVISIONING`。可在另一终端执行 `status` 查看：`OPERATION_IN_PROGRESS` 表示生命周期操作仍在执行，响应包含最近记录的状态。本地 Gitea 分配动态 loopback 端口；E2B 记录实际 sandbox 身份、容量与到期时间。预检检查账户、固定版本交付 reader 和证据传输；观察到 controller 后才报告 `RUNNING`。存活期间重复 run 不会另起一个 controller。

在 `.experiments/<run_id>/resources.json` 的 `gitea` 字段查看连接信息，打开 `<url>/<owner>/<repo>`，查看反馈、proposal、Owner 准入票和 PR。如果使用其他运行根目录，查看对应的 resources 文件。本地新建账户的真实用户名和密码保存在 `.experiments/<run_id>/secrets/local-gitea-login.env`（权限 0600）；在自己的终端查看该文件，用其中的 `GITEA_USER` / `GITEA_PASSWORD` 登录上述地址，不要粘贴到 issue 或共享日志中。恢复时保留同一密码；旧实验如果没有此记录，不会自动重置密码。云端使用自己的 Gitea.com 账户。日志跟随时 Ctrl+C 只退出查看器。

## 5. 理解五轮顺序

| 轮次 | 用户交互 | 需求与交付 | 结果 |
| --- | --- | --- | --- |
| R1 | 试用 seed Harness | Triage/Synthesizer → 机械 Owner → OpenAgents | 首个 sealed Harness SHA |
| R2 | 试用 R1 封口版本 | 同一流程 | R2 封口 |
| R3 | 试用 R2 封口版本 | 同一流程 | R3 封口 |
| R4 | 试用 R3 封口版本 | 同一流程 | R4 封口 |
| R5 | 试用 R4 封口版本 | 不新增需求、不交付 | 最终用户轮封口 |

合法轮次可以没有准入票，sealed SHA 因而不变；不能看到轮次增加就推断代码有改进。已准入票被阻塞或 automation 失败时闭环停止，下一轮不能悄悄使用未封口版本。

应联合查看 session、需求/Owner 轨迹、交付记录和 recovery 封口。模型声称完成不能单独证明文件修改或 PR 合并。controller 记录每轮实际使用和最终封口的 Harness SHA。

## 6. 测试停止与恢复

controller 工作中执行：

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py stop "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py status "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py resume "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py logs "$RUN_ID" --follow
```

确认停止并保留 checkpoint。本地 stop 停止 Gitea/egress、清理执行容器，但保留仓库数据卷；Gitea 停止时浏览器地址不可用。本地 resume 恢复相同的宿主端口和仓库。resume 使用相同 run ID、Gitea 仓库、冻结输入和资源身份，核对在途交付。未封口的用户 session 可能需要重跑，恢复不能凭空制造已完成结果。重复 resume 不应产生第二个 controller，也不应重复交付已核对完的票。本次已完成的云端验证没有用户 Issue 或交付票，因此验证的是生命周期与收集，不代表实际交付去重已经实测。

E2B stop 进程后沙箱仍被分配。到期或被删除时为 `LOST`，不能重新创建后继续沿用原身份声称恢复。保持主机在线：本地 detached monitor 周期收集远程数据，不是永久云存储。

## 7. 收集证据并释放计算资源

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py collect "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py status "$RUN_ID"
```

运行中收集是 best effort，标为 `PARTIAL`；一致的终态归档标为 `COMPLETE`，包含文件 hash 和归档校验和。检查输出路径和 receipt。停止或失败的实验也可以有完整归档，实验结果仍保持停止或失败。

五轮成功要求五个 recovery seal、completed recovery 状态、成功的 controller 退出、匹配的封口 SHA。将这些记录与 Gitea 交付历史及下一轮真实使用版本核对。正常完成后完整自动收集才释放专有计算资源；否则手动收集后执行：

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py destroy "$RUN_ID" --confirm "$RUN_ID"
```

保留本地证据、Gitea 仓库、共享 cache/template。默认拒绝销毁未完整收集的结果。明确接受丢失时，额外使用 `--discard-uncollected`。之后检查 status：资源销毁不会把失败实验改成 `COMPLETED`。销毁后 collect 可再次打包保留在宿主的快照，不重新创建计算资源。本地 Gitea 仓库保留是指数据卷保留，不代表 Web 服务继续运行。

## 排查

| 情况 | 查看内容 |
| --- | --- |
| 离线 check 失败 | 错误中的 JSON 字段/文件路径，[配置格式](../CONFIGURATION.zh-CN.md) |
| prepare 失败 | 下载/构建日志、固定源码提交、依赖锁、Docker 可用性 |
| 缺凭证 | 补报错中的变量，检查显式 secrets-file 路径和 0600 权限 |
| 模型失败 | 供应商可用性、模型名、协议/URL、本地 egress；查看 controller log |
| 资源已起但不跑轮次 | controller receipt、launch/preflight 错误，基础设施启动不是成功 |
| Gitea.com 建仓返回 HTTP 403 / maximum limit | 检查账户仓库配额。保留既有实验仓库，删除不再使用的测试仓库或申请提高配额，然后重试同一个已准备的 run |
| 交付阻塞 | 准入 Issue/PR 状态与 OpenAgents 日志，不手动跳过封口 |
| Provider 不可达 | 最近观察时间、到期时间、provider 访问；UNKNOWN 不证明进程已停 |
| E2B LOST | 最近成功收集；resume 不会自动重建到期沙箱 |
| 本地 resume 报端口绑定冲突 | 从 resources.json 查原端口，用下方命令检查监听和 Docker 映射，排除冲突后重试 resume，不更改冻结 URL |
| collect 失败 | 保留的资源及旧归档，销毁前重试收集 |

本地端口冲突时，先查看宿主上的监听和映射，再处理识别出的冲突服务：

```bash
ss -ltnp
docker ps --format 'table {{.ID}}\t{{.Names}}\t{{.Ports}}'
uv run --locked --extra experiments python backend/scripts/experiment.py resume "$RUN_ID"
```

原端口释放后重试 resume，不通过编辑 manifest.json、resources.json 或冻结证据 profile 为同一 run 换端口。

没有固定完成时间保证，模型延迟、重试、用户交互、交付步骤均会变化。实际耗时与费用看时间记录和 provider 账单。本教程描述完整操作流程，验证报告逐项说明已实际执行的路径与轮次。

pvlib 配方对历史 Versioneer 使用仅构建时有效的 Python 3.12 兼容 shim，恢复已删除的 `configparser` 别名以完成 editable 安装，不修改冻结任务源码，构建后删除 shim。任务环境同时安装带 hash 的固定版本 pytest 和 pytest-mock，供用户侧检查。未修改任务基线在全新环境中验证：155 个 ModelChain 测试全部通过，其中 35 个使用 `mocker` fixture。这是任务环境验证，不是官方 SWE-bench 评分。
