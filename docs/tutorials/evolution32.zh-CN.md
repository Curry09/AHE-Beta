# 四组六轮 E2B 迭代实验

[English](evolution32.md) | 简体中文

本教程介绍 U8 mixed、U8 direct、U16 mixed 和 U32 mixed 四组六轮实验。它们通过 `backend/scripts/experiment.py` 启动，从当前初始 Harness 开始，使用 32 项任务集中的指定子集。任务定义、环境配方和用户画像随仓库提供，大型材料由准备阶段获取。所有命令在仓库根目录执行。

任务内容、来源、固定版本与材料获取方式见[任务清单](../../examples/tasks/evolution32/README.zh-CN.md)。准备阶段将这些材料与当前配置、控制器和初始 Harness 一并固定，生成一次独立实验。

| 配置 | 每轮会话 | simulated_user / direct | 独立画像数 | Triager / Architect / Divergent | 用户 / Developer 并发 |
| --- | --- | --- | --- | --- | --- |
| u8-mixed-e2b.json | 8 | 6 / 2 | 5 | 4 / 1 / 1 | 4 / 4 |
| u8-direct-e2b.json | 8 | 0 / 8 | 5 | 4 / 1 / 1 | 4 / 4 |
| u16-mixed-e2b.json | 16 | 12 / 4 | 8 | 8 / 1 / 1 | 4 / 4 |
| u32-mixed-e2b.json | 32 | 25 / 7 | 15 | 16 / 1 / 1 | 4 / 4 |

每份配置均从准备时的当前 builtin seed 开始，共六轮。R1–R5 运行试用、反馈和交付，R6 仅试用最终 Harness。六轮对应五次轮间交付批次，不是六次交付。Owner 为 mechanical，architect_grouping 为 false，逐轮官方评分关闭。后者不关闭 persona 的会话反馈或终态评阅；体感接受不等于官方基准通过。

每个实验使用一个 4 CPU / 8192 MiB 的 E2B 沙箱，各会话尝试使用独立 Docker 任务环境，用户并发为 4。实际并发应结合任务的内存与服务需求选择。会话和环境相互独立，但画像可以复用，因此 U32 表示每轮 32 个会话，使用的独立画像数见上表。

U8 两组保持任务、初态、persona 配对、六轮轮序、seed、模型、角色、资源和并发一致。direct 配置仅以 interaction_overrides 将原先六个 simulated_user 任务改为 direct，另两个原 direct 任务保持不变；名称、仓库前缀和派生身份随实验区分。

## 准备材料和凭证

工作机使用 Linux 或 WSL2、Git、Python 3.12 与 uv。E2B 路径由远端模板提供 Docker，不要求工作机启动本地 Docker Desktop。任务定义和原 persona 库随仓库提供，大输入和配方附件从固定版本 Release 获取，镜像使用公开 registry digest；准备过程核对校验和，不需要个人历史 E2B 模板。

任务材料来自清单中固定版本的 Release，运行前请确认管理主机能够访问相应下载地址。准备阶段验证材料哈希；离线检查会将尚未缓存的远端材料标为待下载。

```bash
git clone https://github.com/Curry09/AHE-Beta.git
cd AHE-Beta
uv sync --locked --extra experiments
cp examples/experiment.env.example .env.experiment
chmod 600 .env.experiment
```

填写 `.env.experiment`，不要把密钥放进 JSON：

| 凭证字段 | 含义 |
| --- | --- |
| USER_LLM_BASE_URL / USER_LLM_API_KEY | 用户模拟及终态评阅，OpenAI 兼容 Chat Completions |
| HARNESS_LLM_BASE_URL / HARNESS_LLM_API_KEY | 被迭代 Harness，OpenAI 兼容 Chat Completions |
| DEMAND_LLM_BASE_URL / DEMAND_LLM_API_KEY | Triager、Architect、Divergent 等需求角色，OpenAI 兼容 Chat Completions |
| ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN | OpenAgents 的 Claude Code 交付，Anthropic 兼容协议，bearer 认证 |
| E2B_API_KEY | 有权限创建所需资源及模板的 E2B API key |
| GITEA_TOKEN | 自己 Gitea.com 账户的 token，可创建、读写实验私有仓库、Issue、评论和附件 |
| GITEA_USER | 可选，用于核对 token 对应账户 |

前三类地址应为网关的 OpenAI base URL（一般以 `/v1` 结束），不是完整 `/chat/completions` 请求地址。交付地址填写提供商为 Claude Code 指定的 Anthropic base URL，不填完整 `/v1/messages`。同一网关可分别提供两种协议；仅有 OpenAI 协议的地址不能直接作为 Claude Code 的 Anthropic 端点。

JSON 中公开模型名为用户/Harness 的 `glm-5.3-flash`、需求/交付的 `glm-5.3`。准备前可把四个 models.*.model 改为自己提供商实际接受的 ID，并保持 U8 对照两组一致。示例不包含内网服务地址、服务端思考配置或额外模型预算。

当前 User、builtin seed Harness 和需求角色的实际 `max_tokens` 都是 32768，默认输入阈值为 256000。本例不新增 limits：容量状态会标为未验证，而不是从模型名猜上下文容量。`reserved_output_tokens` 是容量计算的预留值，不会修改真实 max_tokens；也不应把它设为 128000 后声称已开启 128k 输出。演化后的 Harness 可能修改自己的配置，实际参数须查看该轮冻结版本，静态容量报告不是演化后参数的动态证明。请确认自己的提供商能容纳实际输入和输出总额。Claude Code 的输出策略由其客户端/提供商决定，不能套用前三类角色的 32768 声明。

Gitea.com 需有新建仓库名额。每个 run 使用独立仓库，destroy 默认保留该仓库；顺序批量运行也不会释放仓库名额。首次建模板、下载镜像及准备依赖可能较慢。

## 检查和启动一组

其中 8 项任务按各自的任务说明设置了 1、2 或 8 小时的执行时限。从第一条任务消息开始计时，环境准备和结束后的评阅不计入。追加消息不会重置计时。到时后，控制器停止 Harness，先保存已有产物，再发起一次最多等待 300 秒的用户评阅；没有具体问题可以不提 Issue。其余任务在这些示例中没有设置总时限。

```bash
CONFIG=examples/experiments/u8-mixed-e2b.json
# 也可选 u8-direct-e2b.json、u16-mixed-e2b.json 或 u32-mixed-e2b.json。
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --offline
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py run --config "$CONFIG" --secrets-file .env.experiment
```

离线检查不创建云资源或发送模型请求，只核对配置、画像、计划及材料声明。普通 check 检查凭证/provider；显式添加 `--probe-models` 才发送模型连通性探针。探针只说明相应协议/模型能被调用，不代表真实任务或六轮实验已经通过。

`run --config` 先 prepare 再启动，完成准备后冻结当前控制器、builtin seed、OpenAgents、任务和配置身份。也可以分步执行以便审阅：

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py prepare --config "$CONFIG" --secrets-file .env.experiment
RUN_ID=REPLACE_WITH_PRINTED_RUN_ID
uv run --locked --extra experiments python backend/scripts/experiment.py run "$RUN_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py status "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py logs "$RUN_ID" --follow
```

prepare 失败时保留已验证缓存；打印 run ID 不等于已经准备成功。模型调用前会校验实际沙箱、Docker/镜像能力，任务初始化/服务就绪发生在每个 attempt 的 Actor 启动前。材料、工具链探针通过与正式六轮完成是不同层次的验证。

启动 E2B 实验时，控制器会逐个上传准备阶段固定下来的文件，边读边传。启动日志会显示当前正在上传的文件。文件越大，上传时留给连接和读写的时间就越长。这些超时只用于单个文件的网络操作，不限制整批上传的总用时，也不影响任务或模型预算。

## 只运行一轮试用

如果只想试跑一轮 U32，可以在原目录下复制一份 `u32-mixed-e2b.json`，这样任务和用户画像的相对路径仍然有效。把副本中的 `rounds.count` 改为 `1`，并在 `workload.interaction_plan` 中只保留第一轮计划。

如果想在本地运行，用 `u4-local.json` 中的 `runtime` 段替换副本中的整个 `runtime` 段，再为本次试跑设置一个不同的仓库前缀。本地运行需要 Docker Engine 和 Compose，实验会自动启动本地 Gitea，无需配置 E2B 或 Gitea.com 凭证。选好运行方式后，把 `CONFIG` 指向副本，按上文的步骤检查配置、准备材料并启动实验。

只跑一轮，可以验证初始 Harness 能否在任务环境中完成用户会话，以及产物能否归档。这一轮也是最后一轮，因此不会进入需求处理和 OpenAgents 交付。如果还想验证交付，可以用规模较小的 U4 示例跑两轮，保留两轮的会话计划。只有首轮产生了获准交付的 Issue，OpenAgents 才会接手。

## 收集、停止和恢复

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py collect "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py stop "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py resume "$RUN_ID" --secrets-file .env.experiment
```

run 启动后，云内 supervisor/controller 独立运行；工作机还会启动后台 collector，周期收集状态和产物。退出 logs 不会停止实验。工作机关机后本机 collector 不能继续收集，云端 controller 的存活仍受实际 provider 生命周期约束。

`PARTIAL` 归档保留已收集到的记录，供查看和排查。执行 `resume` 时，程序会从原运行环境中的检查点继续实验，不会从归档恢复。要从归档创建新的续跑实验，原实验必须已完成，且[归档须符合续跑条件](experiment-continuation.zh-CN.md)。

如果本地 Docker 重启了，等 `docker info` 能正常返回后，再用 `resume` 恢复实验。控制器会复用已完成的会话，并尝试从原任务环境补齐尚未收集的产物。如果 Docker 确认原环境已丢失，只用该轮原有的输入和 Harness 版本补跑受影响的会话。如果无法核实原环境，或无法确认收尾脚本是否执行完毕，请保留实验目录和已有归档以便排查。会话结果保存后，清理失败会单独记录，不影响下一轮启动。

当前不会自动延长 E2B 沙箱租期。`runtime.e2b.timeout_seconds: 86400` 设置创建时的租期，与模型输出预算无关。`stop` 停止控制器并保留沙箱，CLI `resume` 要求原沙箱仍在运行；暂停实例需要先通过 provider 恢复，过期或已删除实例标记为 `LOST`。六轮实验可能超过一天，请关注实际 `expires_at`，保持管理主机的收集进程可用，并保留完整归档。

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py collect "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py destroy "$RUN_ID" --confirm "$RUN_ID"
```

成功终态完整收集后后台 collector 会回收计算资源；手动 destroy 仍保留 Gitea 和本机已收集产物。不要将只在云端存在的数据视为已交付归档。

## 四组批次

```bash
BATCH=examples/batches/evolution-four-e2b.json
uv run --locked --extra experiments python backend/scripts/experiment.py batch check --config "$BATCH" --offline
uv run --locked --extra experiments python backend/scripts/experiment.py batch prepare --config "$BATCH" --secrets-file .env.experiment
BATCH_ID=REPLACE_WITH_PRINTED_BATCH_ID
uv run --locked --extra experiments python backend/scripts/experiment.py batch run "$BATCH_ID" --secrets-file .env.experiment
```

批次配置 `max_parallel_runs: 1`，一次运行一组；这是实验组并发，不是用户或 Developer 并发。batch run 使用前台监督器，应保持该命令所在主机在线，或在持久终端中运行；不能把单 run 的后台 collector 行为套到 batch 上。
