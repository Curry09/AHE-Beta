# Ordinary N=1/N=4 五轮实验迁移手册

本文是把实验迁移到另一台机器或交给另一位执行者时的操作契约。正式配置见
[`configs/ordinary-1-4-five-rounds.json`](configs/ordinary-1-4-five-rounds.json)。

## 1. 实验问题与固定变量

本实验比较两条相互独立的 harness 演化线：

| 实验 | 任务 | 每轮交互 | 轮数 |
|---|---|---|---:|
| `ordinary-1-glm53-v0-r5` | O03 | 模拟用户 | 5 |
| `ordinary-4-glm53-v0-r5` | O03、O09、O14、O18 | O03 模拟用户，O09 直出，O14 模拟用户，O18 使用 benchmark-native user | 5 |

两条线都从 `baseline-v0-cade14d` 开始，但不能共享后续 revision、Gitea、
session、checkpoint 或 artifact。这样比较的是任务规模对闭环演化的影响，而不是
两条线互相污染后的结果。

固定角色和模型：

- Harbor/Daytona 内的 harness：OpenRouter `z-ai/glm-5.3-flash`。
- Harbor/Daytona 内的历史用户模拟：OpenRouter `z-ai/glm-5.3-flash`。
- 本地 designer/developer：Boyue `glm-5.3`。
- PM/divergent：关闭，`N_DIVERGENTS=0`。
- Owner：机械验收，`review=false`，不调用 LLM。

## 2. 超时和轮次语义

每个 task 的 agent 时间预算优先取官方 task metadata；没有官方预算时使用
1800 秒。Harbor 外层 watchdog 固定为：

```text
outer_timeout = official_agent_timeout + 600 seconds
```

额外 600 秒只用于 artifact/checkpoint 落盘，不允许继续模型执行。五轮不是五次
独立 baseline：第 1 轮从 v0 开始，第 `r+1` 轮使用第 `r` 轮 owner gate 后发布的
harness revision。若某轮未发布，则沿用上一轮 revision。

每轮的边界是：

1. Harbor/Daytona 执行该轮全部 task，收集 harness transcript、用户 trace、patch 和 grader 输出。
2. 将 session、用户反馈、objective grader 结果写入本轮 checkpoint。
3. 本地 designer 只读取本轮冻结输入，生成设计交付物。
4. 本地 developer 根据设计和 trace 修改当前 harness revision。
5. mechanical owner 执行门禁；通过则发布新 revision，否则保留旧 revision。
6. 写入 `round-{r}.json` 和压缩 checkpoint，然后进入下一轮。

恢复只能从最近一个完整 checkpoint 继续；不要从半截进程内存恢复，也不要重写已
完成 trial。未完成轮次整体幂等重跑。

## 3. 机器和凭证准备

在仓库根目录准备 Python 3.12、Harbor 0.23.0、Daytona SDK 0.214.x，以及本仓库
的依赖。凭证只放在执行机环境或本地 ignored 文件中，绝不写进 JSON、日志或 git：

```bash
export DAYTONA_API_KEY='...'
export OPENROUTER_API_KEY='...'
export HARNESS_LLM_API_KEY="$OPENROUTER_API_KEY"
export USER_LLM_API_KEY="$OPENROUTER_API_KEY"
export HARNESS_LLM_BASE_URL='https://openrouter.ai/api/v1'
export USER_LLM_BASE_URL='https://openrouter.ai/api/v1'
export HARNESS_LLM_MODEL='z-ai/glm-5.3-flash'
export USER_LLM_MODEL='z-ai/glm-5.3-flash'
export PYTHONPATH="$PWD"
```

本地 design/development 使用项目既有的 Boyue credential loader；迁移时只需提供
与 `.boyue` 等价的本地凭证，不要把 Boyue key 注入 Daytona。当前 Daytona tier 已
验证的约束是：每 sandbox 最多 10 GiB 存储、聚合内存约 10 GiB。正式运行前先做
provider preflight；若仍是该 tier，默认并发设为 1，不能盲目同时创建四个 6 GiB
sandbox。

历史 v0 harness archive 需要由执行者从受控 artifact store 取回，并核对：

```text
HSE_HARNESS_ARCHIVE=.artifacts/harness-v0-cade14d.tar.gz
sha256 = dd7cdd91a4dc170af3662cdca28d2ed9fbd0dd2676e57ce9a4041146a488e011
```

`nexau==0.4.1` 和 `ag-ui-protocol==0.1.22` 会在 sandbox setup 阶段按固定版本安装。

## 4. 先做 canary，再做正式 trial

仓库中的 `harbor-ordinary-o03` 是链路 canary。它的 `tests/test.sh` 只验证
`session.json` 和 `model.patch` 存在，并写入 reward `1`；这个 reward 不是 SWE 正式
准确率，不能放进论文主表。

准备 archive 后运行：

```bash
mkdir -p .artifacts
# 从受控 artifact store 放入 .artifacts/harness-v0-cade14d.tar.gz
sha256sum .artifacts/harness-v0-cade14d.tar.gz

uvx --from harbor==0.23.0 harbor run \
  --config evaluation/harness-suite-20260920/harbor-ordinary-o03/config.json \
  --jobs-dir evaluation/harness-suite-20260920/harbor-canary-jobs \
  --job-name ordinary-1-o03-historical-user-canary \
  --env daytona --n-concurrent 1 --yes \
  --override-cpus 2 --override-memory-mb 6144 --override-storage-mb 10240 \
  --agent-env 'HSE_HARNESS_ARCHIVE=${HSE_HARNESS_ARCHIVE}' \
  --agent-env 'HARNESS_LLM_API_KEY=${HARNESS_LLM_API_KEY}' \
  --agent-env 'USER_LLM_API_KEY=${USER_LLM_API_KEY}' \
  --agent-env 'HARNESS_LLM_BASE_URL=${HARNESS_LLM_BASE_URL}' \
  --agent-env 'USER_LLM_BASE_URL=${USER_LLM_BASE_URL}' \
  --agent-env 'HARNESS_LLM_MODEL=${HARNESS_LLM_MODEL}' \
  --agent-env 'USER_LLM_MODEL=${USER_LLM_MODEL}' \
  --agent-env HSE_OFFICIAL_AGENT_TIMEOUT_SECONDS=1800 \
  --agent-env HSE_OUTER_AGENT_TIMEOUT_SECONDS=2400 \
  --agent-env HSE_PERSONA_ID=sr-01-willison \
  --agent-env HSE_TASK_INSTANCE=pvlib__pvlib-python-1478
```

通过标准是：sandbox 创建成功、model transcript 出现、用户 loop 能读写同一
`/testbed`、artifact 下载完整、无 Harbor exception。canary 通过后才允许换成正式
task package 和官方 grader。

## 5. 正式五轮执行顺序

正式执行者必须为每条实验线建立独立的以下资源：

```text
experiment process
Compose project
Gitea instance + volume
act-runner / Vigil
session store
checkpoint root
artifact root
```

不要使用 `backend/deploy/gitea/docker-compose.yml` 的固定 singleton stack；并行实验
使用 `backend/deploy/experiment/docker-compose.yml` 生成唯一 project name 和端口。

伪代码级执行顺序如下，实际 task provisioning 由 benchmark-specific Harbor
executor 完成：

```text
for experiment in [ordinary-1-glm53-v0-r5, ordinary-4-glm53-v0-r5]:
    revision = baseline-v0-cade14d
    for round in 1..5:
        freeze(round, experiment, revision, task_ids, interaction_assignment)
        run every task in fresh Daytona sandbox
        download transcript/user_trace/patch/official_grader
        checkpoint(round, inputs, outputs, revision)
        design locally with Boyue glm-5.3
        develop locally with Boyue glm-5.3
        mechanical owner gate (review=false)
        revision = released_revision or revision
        checkpoint(round, revision)
```

任务结果必须记录：task ID、benchmark、revision、model、interaction mode、persona
seed、official/outer timeout、provider、sandbox ID、grader version、reward、
end_reason、artifact hashes、infrastructure status。基础设施失败不能当作 task
failure 计入准确率，但必须单独报告。

## 6. 结果和恢复

每轮至少保存：

```text
runs/<experiment_id>/round-<r>/trials/<task_id>/result.json
runs/<experiment_id>/round-<r>/trials/<task_id>/session.json
runs/<experiment_id>/round-<r>/trials/<task_id>/trace.jsonl
runs/<experiment_id>/round-<r>/trials/<task_id>/grader.json
runs/<experiment_id>/checkpoints/round-<r>.json
runs/<experiment_id>/checkpoints/round-<r>.tar.gz
runs/<experiment_id>/summary.json
```

主表同时报告：task success、harness completion、user feeling、interaction
failure、official deadline、infrastructure failure。不能只报告 Harbor 的平均
reward，也不能把 canary reward 当 benchmark accuracy。

若进程中断：读取最近 checkpoint，确认已完成 trial 的 artifact hash 不变，只重跑
当前未完成 round；不要重新生成 manifest、换 task revision、换 persona seed 或把
另一条实验线的 release revision 回灌进来。

## 7. 迁移前检查清单

- [ ] `configs/ordinary-1-4-five-rounds.json` hash 已记录。
- [ ] O03/O09/O14/O18 的 task revision、grader 和 image digest 与 freeze record 一致。
- [ ] `baseline-v0-cade14d` archive hash 正确。
- [ ] OpenRouter `z-ai/glm-5.3-flash` chat probe 成功。
- [ ] Boyue `glm-5.3` probe 成功。
- [ ] Daytona 创建、公开镜像启动、文件上传/下载和 sandbox 删除均成功。
- [ ] PM 为关闭，Owner 为 mechanical `review=false`。
- [ ] N=1、N=4 使用不同 artifact/Gitea/revision lineage。
- [ ] official timeout 与 outer timeout 分开记录。
- [ ] canary 与正式 grader 结果分开存放、分开报告。
