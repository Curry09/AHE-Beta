# 演化过程中的反馈与客观验收

[English](evolution-feedback.md) | 简体中文

本教程启动一个带逐轮独立验收的小实验：Harness 计算总额并生成 `answer.json`，私有 custom verifier 检查冻结后的文件。示例用于演示公开任务、私有验收规则与反馈处理之间的完整流程。

## 循环中的变化

两种交互模式共用四轴反馈：

| 维度 | 含义 |
| --- | --- |
| `task_assessment` | Reviewer 的 `fulfilled`、`unfulfilled` 或 `unknown` 观察，带来源和证据引用；独立 grader 收据另存 |
| `experience` | `rated` 时为整数 1–4；或 `missing` / `invalid` / `unavailable`，此时 `score: null` 并保留原因 |
| `attribution` | 原因已确认、不确定或未知；任务失败不自动证明是 Harness 缺陷 |
| `opportunities` | 零到多个建议；成功会话不必发 Issue |

`direct` 模式下，解题 Agent（Actor）只收到一次任务，不会有用户追加消息。`simulated_user` 模式下，模拟用户可以按画像能力访问实时工作区，在等待或决定接受／继续之前进行检查。`competent` 和 `expert` 画像可写测试、运行命令，并按协作方式修改代码；这些检查是可选行为。`main_final_check` 每个决策周期最多执行一次，包含最多四次工具调用，之后由模拟用户重新判断下一步动作。

会话终止后，系统停止 Actor 及相关写入进程，冻结任务产物，再由终态 Reviewer 进行只读复核。Reviewer 能读取快照文件和 diff，不能写文件、执行 shell 或追加任务消息。用户的操作保存在 `sim_trace` 中；若最终工作区包含用户贡献，验收通过代表该协作产物通过，不自动等于 Harness 独立完成。现有记录不提供完整的逐行贡献归因，缺失体验评分也不会用诊断分数补齐。

系统先保存完整报告计划，再逐条发布 Issue 并保存收据。恢复时继续发布原计划中未完成的 Issue，不重跑 Actor 或 Reviewer；没有 Issue 的空计划也是正常结果。每轮的客观验收都在需求处理前执行，末轮只试用也包括在内。安全摘要支持后续纠错，不会因一次验收失败自动淘汰或回退已交付候选。

## 1. 安装并固定评分镜像

在可信、已启动 Docker 的主机上，从仓库根目录执行：

```bash
uv sync --locked --extra experiments --extra evaluation --extra dev
docker info
# 解析本机 worker 实际要使用的 registry 镜像 digest：
docker pull python:3.12-slim
GRADER_IMAGE=$(docker image inspect python:3.12-slim --format '{{index .RepoDigests 0}}')
test -n "$GRADER_IMAGE"
```

此镜像仅用于隔离执行 custom verifier，任务和 controller 镜像仍使用正常后端配置。同一 worker 主机也可使用已有镜像的不可变 `sha256:...` ID；需要其他主机获取镜像时使用 registry digest。

## 2. 生成公开与私有材料

在仓库外选择一个尚不存在的目录：

```bash
CASE_DIR="$HOME/evolution-feedback-local"
bash backend/scripts/e2e-spec-0084-evolution-feedback.sh \
  --prepare-example "$CASE_DIR" --backend local --grader-image "$GRADER_IMAGE"
# 测 E2B 时，换一个新的 CASE_DIR，并改成 --backend e2b。
```

生成器不创建资源、不调用模型，输出如下：

| `CASE_DIR` 下的路径 | 用途 |
| --- | --- |
| `experiment.json` | 已开启 `evaluation.session_grading`，填入真实摘要的完整实验定义 |
| `public/task/` | 公开指令、源码、setup、任务合同及 `answer.json` 导出声明 |
| `private/grading-plan.json`、`private/verifier.py` | 固定的 custom 规则与镜像，不属于任务材料 |
| `private/worker.key`、`private/worker.pub` | 新生成的 Ed25519 签名私钥、公钥；私钥权限为 0600 |
| `private/controls.json`、`private/positive.json`、`private/negative.json` | 操作者的验收正负控制，不是 Harness 生成的答案 |

仓内 `examples/experiments/evolution-feedback-local.json` 和 `evolution-feedback-e2b.json` 是未开启验收的基础模板。生成器替换任务、计算真实 hash 后启用验收，不使用占位摘要，也不分发通用私钥。

按供应商实际模型名修改 `experiment.json` 中四个角色的模型选择。复制 `examples/experiment.env.example` 到 `"$CASE_DIR/secrets.env"`，权限设为 0600，填写各角色凭证；E2B 还需 `E2B_API_KEY` 和 Gitea.com token。协议与显式上下文限制见[配置说明](../CONFIGURATION.zh-CN.md)。私有文件不要放进 `public/task/` 或任务源码。

生成任务使用 600 秒操作者配额，便于小规模验证。真实任务可以声明 `execution.budget_seconds: 7200`、`budget_source: task_metadata`。总时钟从首次目标发出开始，消息不续租；7200 秒优先于运行时的 1800 秒 fallback。可选 `runtime.harness.message_activity_seconds` 会增加更短的单消息边界，默认不设置。收尾余量只用于清理。Seed 默认仍为 100 次迭代、32768 输出 tokens，因此预算不保证一定完成或运行满时长。

## 3. 检查并准备

准备阶段根据[兼容清单](../../release/compatibility.json)固定 OpenAgents 的执行证据 reader 版本，优先使用 `execution_evidence.reader_release_commit`，未设置时使用 `reader_candidate_commit`。显式 `source.openagents` 也必须指向支持同一执行证据合同的不可变提交。预检会核验实际读取能力；配套版本更新见[发布指南](../RELEASING.md)。

```bash
CONFIG="$CASE_DIR/experiment.json"
PLAN="$CASE_DIR/private/grading-plan.json"
PUBLIC_KEY="$CASE_DIR/private/worker.pub"
SECRETS="$CASE_DIR/secrets.env"

uv run --locked --extra experiments --extra evaluation python backend/scripts/experiment.py \
  check --config "$CONFIG" --grading-plan "$PLAN" \
  --grading-worker-public-key "$PUBLIC_KEY" --offline
uv run --locked --extra experiments --extra evaluation python backend/scripts/experiment.py \
  check --config "$CONFIG" --grading-plan "$PLAN" \
  --grading-worker-public-key "$PUBLIC_KEY" --secrets-file "$SECRETS"
uv run --locked --extra experiments --extra evaluation python backend/scripts/experiment.py \
  prepare --config "$CONFIG" --grading-plan "$PLAN" \
  --grading-worker-public-key "$PUBLIC_KEY" --secrets-file "$SECRETS"
```

`check --offline` 验证配置与材料，不调用模型或 provider。`prepare` 冻结任务、Harness、执行/反馈条件、worker 公钥身份及评分实现，私有计划和密钥不复制进任务材料。成功准备后再复制 run ID；准备后修改评分文件或实现会被拒绝，改变输入需重新 prepare。

`plan_sha256` 是 grading-plan 文件原始字节的摘要，`worker_key_sha256` 是 Ed25519 公钥原始 32 字节的摘要，不是 PEM 文本摘要。生成器自动计算两者，不要用 `sha256sum worker.pub` 代替 worker 身份。

可先只检查 verifier：

```bash
bash backend/scripts/e2e-spec-0084-evolution-feedback.sh --grader-controls "$CASE_DIR"
```

该命令需要 Docker，经过共用的生产评分服务执行正负控制。`verifier-controls/summary.json` 应分别显示 `completed / true` 和 `completed / false`。这一步不运行 Actor、实验后端或 worker 交换链路。

## 4. 先启动实验，再启动 worker

```bash
RUN_ID=REPLACE_WITH_PREPARED_RUN_ID
uv run --locked --extra experiments --extra evaluation python backend/scripts/experiment.py \
  run "$RUN_ID" --secrets-file "$SECRETS"
```

在同一可信主机的另一终端恢复 `RUN_ID`、`CASE_DIR`、`PLAN`、`SECRETS` 变量，再执行：

```bash
uv run --locked --extra experiments --extra evaluation python backend/scripts/experiment.py \
  assessment-worker "$RUN_ID" --plan "$PLAN" \
  --signing-key "$CASE_DIR/private/worker.key" --secrets-file "$SECRETS" --follow
```

这是前台进程，local 和 E2B **都需要**该 worker 的 Docker。E2B 不接收评分主机的 Docker socket 或私有 verifier；worker 使用同一准备目录和 provider 凭证交换封存请求、签名结果。如果自定义了全局 `--runs-dir`，每个子命令前（包括 worker）都要填写同一值。换用另一台 worker 主机时，必须具备相同准备状态、兼容 checkout 和凭证；这个命令不是远程 worker 注册服务。

worker 就绪前出现 `objective_grading / PENDING / worker_not_ready` 属于预期，启动 worker 即可继续。实验期间保持它运行，`--follow` 持续轮询，controller 为 `EXITED` 或 `STOPPED` 且没有待办时会自动退出，途中也可 Ctrl+C 停止；不带该参数只处理当前待办后退出。中断后用相同计划、私钥重启，已接受收据会复用；过期 generation 和冲突重复结果会被拒绝，恢复不会产生新的用户试用。

## 5. 查看、收集与解释

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py status "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py logs "$RUN_ID" --follow
uv run --locked --extra experiments python backend/scripts/experiment.py collect "$RUN_ID"
```

停止、恢复和清理继续使用[快速开始](../QUICKSTART.zh-CN.md#4-停止继续收集)的命令。保持主机和 worker 在线直到末轮验收及完整收集完成。之后用 Ctrl+C 停 worker；只停 worker 不会销毁实验资源。

| 观察 | 解释 |
| --- | --- |
| `completed`、`passed: true/false` | 声明的独立规则已执行，产生有效任务结果 |
| `ungradable`、`unavailable`、`crashed`、`timed_out` | 无有效二值结论，`passed` 保持 null |
| `not_configured` | 未要求客观验收 |
| 体验 `missing`、`invalid`、`unavailable` | 无有效主观评分，不计入有效评分统计 |
| 验收 `PENDING` | 阶段仍在等待，既不是成功也不是失败 |

实验保留执行合同、完整 Actor 产物和报告收据。controller 侧 `assessment/` 保存请求、已接受签名收据和安全轮次反馈；worker 本地 run 的 `evaluation/online/` 保存私有执行细节，排除于收集包及 Issue/需求证据。安全摘要只有结果、身份和摘要字段，不带 verifier 断言、隐藏测试或 stdout。Reviewer 的观察与独立验收可以不一致，二者不会互相覆盖。

在线合同支持从保存的工作区产物重建验收；依赖仍存活的原任务环境或受管服务可信测量的 profile 会被拒绝，不猜环境后继续评分。[事后评分](post-run-grading.zh-CN.md)在收集后复用同一评分服务，仍是独立操作；`evaluation/` 下的 Harness 留出 benchmark 也保持独立。当前 checkout 的检查命令见[验证方法](../VERIFICATION.zh-CN.md)。
