# 四组六轮 E2B 迭代实验

[English](evolution32.md) | 简体中文

本教程使用 `examples/experiments/` 中四份配置。它们通过同一个 `backend/scripts/experiment.py` 入口，从当前 builtin seed 运行原32任务集的指定子集；材料、环境和画像不需要从旧实验目录手动复制。所有命令在仓库根目录执行。

任务内容、来源和发布材料见[任务清单](../../examples/tasks/evolution32/README.zh-CN.md)。这里的配置是新实验示例，不宣称逐字节重现某次历史运行，也不把材料检查或工具探针当成正式六轮已完成。

| 配置 | 每轮会话 | simulated_user / direct | 不重复的 persona | Triager / Synthesizer / Divergent | 用户 / Developer 并发 |
| --- | --- | --- | --- | --- | --- |
| u8-mixed-e2b.json | 8 | 6 / 2 | 5 | 4 / 1 / 1 | 4 / 4 |
| u8-direct-e2b.json | 8 | 0 / 8 | 5 | 4 / 1 / 1 | 4 / 4 |
| u16-mixed-e2b.json | 16 | 12 / 4 | 8 | 8 / 1 / 1 | 4 / 4 |
| u32-mixed-e2b.json | 32 | 25 / 7 | 15 | 16 / 1 / 1 | 4 / 4 |

每份配置均从准备时的当前 builtin seed 开始，共六轮。R1–R5 运行试用、反馈和交付，R6 仅试用最终 Harness。六轮对应五次轮间交付批次，不是六次交付。Owner 为 mechanical，synthesizer_grouping 为 false，逐轮官方评分关闭。后者不关闭 persona 的会话反馈或终态评阅；体感接受不等于官方基准通过。

一个实验使用一个 4 CPU / 8192 MiB 的 E2B 沙箱，各 session/attempt 使用独立 Docker 任务环境。公开示例的用户并发统一为 4，它不同于部分历史运行的初始并发，也不是所有任务同时达到资源峰值的总容量保证。每个槽位有独立会话和环境；相同 persona 可以复用，因此 U32 不应描述成 32 个独立真人画像。

U8 两组保持任务、初态、persona 配对、六轮轮序、seed、模型、角色、资源和并发一致。direct 配置仅以 interaction_overrides 将原先六个 simulated_user 任务改为 direct，另两个原 direct 任务保持不变；名称、仓库前缀和派生身份随实验区分。

## 准备材料和凭证

工作机使用 Linux 或 WSL2、Git、Python 3.12 与 uv。E2B 路径由远端模板提供 Docker，不要求工作机启动本地 Docker Desktop。任务定义和原 persona 库随仓库提供，大输入和配方附件从固定版本 Release 获取，镜像使用公开 registry digest；准备过程核对校验和，不需要个人历史 E2B 模板。

主仓目前仍为私有仓库；材料 Release 的匿名下载需要等仓库公开后补验。当前使用登录身份完成的 Release 校验不能等同于匿名可下载。

```bash
git clone https://github.com/Curry09/auto-designer.git
cd auto-designer
uv sync --locked --extra experiments
cp examples/experiment.env.example .env.experiment
chmod 600 .env.experiment
```

填写 `.env.experiment`，不要把密钥放进 JSON：

| 凭证字段 | 含义 |
| --- | --- |
| USER_LLM_BASE_URL / USER_LLM_API_KEY | 用户模拟及终态评阅，OpenAI 兼容 Chat Completions |
| HARNESS_LLM_BASE_URL / HARNESS_LLM_API_KEY | 被迭代 Harness，OpenAI 兼容 Chat Completions |
| DEMAND_LLM_BASE_URL / DEMAND_LLM_API_KEY | Triager、Synthesizer、Divergent 等需求角色，OpenAI 兼容 Chat Completions |
| ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN | OpenAgents 的 Claude Code 交付，Anthropic 兼容协议，bearer 认证 |
| E2B_API_KEY | 有权限创建所需资源及模板的 E2B API key |
| GITEA_TOKEN | 自己 Gitea.com 账户的 token，可创建、读写实验私有仓库、Issue、评论和附件 |
| GITEA_USER | 可选，用于核对 token 对应账户 |

前三类地址应为网关的 OpenAI base URL（一般以 `/v1` 结束），不是完整 `/chat/completions` 请求地址。交付地址填写提供商为 Claude Code 指定的 Anthropic base URL，不填完整 `/v1/messages`。同一网关可分别提供两种协议；仅有 OpenAI 协议的地址不能直接作为 Claude Code 的 Anthropic 端点。

JSON 中公开模型名为用户/Harness 的 `glm-5.3-flash`、需求/交付的 `glm-5.3`。准备前可把四个 models.*.model 改为自己提供商实际接受的 ID，并保持 U8 对照两组一致。示例不包含内网服务地址、服务端思考配置或额外模型预算。

当前 User、builtin seed Harness 和需求角色的实际 `max_tokens` 都是 32768，默认输入阈值为 256000。本例不新增 limits：容量状态会标为未验证，而不是从模型名猜上下文容量。`reserved_output_tokens` 是容量计算的预留值，不会修改真实 max_tokens；也不应把它设为 128000 后声称已开启 128k 输出。演化后的 Harness 可能修改自己的配置，实际参数须查看该轮冻结版本，静态容量报告不是演化后参数的动态证明。请确认自己的提供商能容纳实际输入和输出总额。Claude Code 的输出策略由其客户端/提供商决定，不能套用前三类角色的 32768 声明。

Gitea.com 需有新建仓库名额。每个 run 使用独立仓库，destroy 默认保留该仓库；顺序批量运行也不会释放仓库名额。首次建模板、下载镜像及准备依赖可能较慢。

## 检查和启动一组

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

准备阶段以文件流上传冻结材料，不会把整个归档读进内存；连接、读写等待时间随文件大小增加。这是有限的 I/O 等待，不是整次上传的严格总时限，也不会改变任务或模型预算。启动进度会显示当前传输的文件。

## 收集、停止和恢复

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py collect "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py stop "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py resume "$RUN_ID" --secrets-file .env.experiment
```

run 启动后，云内 supervisor/controller 独立运行；工作机还会启动后台 collector，周期收集状态和产物。退出 logs 不会停止实验。工作机关机后本机 collector 不能继续收集，云端 controller 的存活仍受实际 provider 生命周期约束。

当前代码没有自动续租循环。`runtime.e2b.timeout_seconds: 86400` 是创建沙箱时设置的 provider 租期，不是无限存活承诺，也不是模型输出预算。stop 停止 controller 并保留运行中的沙箱；CLI resume 连接同一仍在运行的沙箱并恢复检查点，不是 provider auto-pause/auto-resume。paused 沙箱需要显式 provider 恢复；已过期/删除实例报告 LOST，不能用一台新实例冒充无损续跑。长六轮运行可能超过一天，请关注实际 expires_at、保留工作机采集和完整归档；此处不提供不存在的自动续租指令。

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
