> 历史研究工作流：依赖该日期套件、外部 sandbox 与对应配置。通用安装从根 README / docs/QUICKSTART.md 开始。运行前显式配置自己的 Gitea/dashboard 地址；不要复用原实验服务。

# Scaling 实验快速启动手册

本文面向第一次接手仓库的执行者。正式 scaling 使用 E2B + Boyue；每个 N 是一个
独立 controller、E2B sandbox、Gitea repository 和 recovery identity。不要把五个 N
放进同一个进程。

## 1. 凭证和前置条件

在仓库根目录准备 `.e2b`、`.boyue`，或通过环境变量注入：

```bash
export E2B_API_KEY='...'
export BOYUE_API_KEY='...'
export GITEA_TOKEN='...'
export ALLOW_INSECURE_GITEA=1       # 仅当 Gitea 使用已确认的 HTTP VPS
export PATH=/root/miniconda3/bin:$PATH
```

凭证不得写入配置、receipt、日志或 git。正式模型固定为：用户/harness 使用
`glm-5.3-flash`，triage/designer/PM/developer 使用 `glm-5.3`，owner 为机械流程。

## 2. 物化和冻结

首次运行或换机器时，从仓库源数据重新生成 N-specific payload：

```bash
python evaluation/harness-suite-20260920/prepare_scaling_runtime_bundles.py \
  --n all --materialize
```

冻结 receipt 时必须提供已经通过的全链路 canary；不能用空 receipt 绕过 gate：

```bash
python evaluation/harness-suite-20260920/freeze_scaling_runtime.py \
  --n all \
  --canary-receipt evaluation/harness-suite-20260920/prepared/scaling-e2b-20260922/existing-n1-round1-evidence.json
```

启动前逐组检查：

```bash
python evaluation/harness-suite-20260920/run_scaling_e2b.py --n 16 --check-launch
python evaluation/harness-suite-20260920/run_scaling_e2b.py --n 32 --check-launch
```

输出必须是 `launchable: true`。检查失败时先修复 receipt/config/payload，不要手动
删除 gate 或直接调用 executor。

## 3. 启动

每个 N 使用一个独立终端或 tmux session。`{n}` 是 launcher 自动替换的占位符；
`--gitea-source-sandbox-id` 只用于从已验证的 N1 sandbox relay VPS Gitea 凭据，不能
把 token 写进命令行。

```bash
cd /root/src/auto-designer
export ALLOW_INSECURE_GITEA=1
export PATH=/root/miniconda3/bin:$PATH

bash evaluation/harness-suite-20260920/start_scaling_n16_e2b.sh \
  --executor 'python evaluation/harness-suite-20260920/run_scaling_bundle_e2b.py \
    --n {n} --gitea-source-sandbox-id <verified-n1-sandbox-id>'

bash evaluation/harness-suite-20260920/start_scaling_n32_e2b.sh \
  --executor 'python evaluation/harness-suite-20260920/run_scaling_bundle_e2b.py \
    --n {n} --gitea-source-sandbox-id <verified-n1-sandbox-id>'
```

N16/N32 的当前角色规模分别是：

| N | users | triage | designer | PM | developer |
|---:|---:|---:|---:|---:|---:|
| 16 | 16 | 8 | 1 | 1 | 4 |
| 32 | 32 | 16 | 2 | 2 | 8 |

每组运行 5 轮。`latency_isolated_timeout.enabled=true`，wall guard 为 600 秒；
实际运行时由 `AUTO_DESIGNER_LATENCY_ISOLATED_TIMEOUT` 和
`AUTO_DESIGNER_LATENCY_WALL_GUARD_SECONDS` 显式导出。

## 4. 查看和恢复

本地入口只保存 controller 状态；实际闭环日志在 E2B sandbox 的
`/opt/hse-run/controller.log`。本地状态目录为：

```text
evaluation/harness-suite-20260920/runs/scaling-e2b-20260922/n{N}/<run_id>/
```

中断后只能使用对应的 resume wrapper；resume 必须复用原 sandbox、Gitea repo、run ID
和 recovery identity。wrapper 不接受 `--run-id`/`--sandbox-id` 这类本地参数；run ID
由 `--executor` 传给远端 bundle，sandbox ID 从该 run 的持久状态中读取：

```bash
bash evaluation/harness-suite-20260920/resume_scaling_n16_e2b.sh \
  --executor 'python evaluation/harness-suite-20260920/run_scaling_bundle_e2b.py \
    --n {n} --resume --run-id <run-id> \
    --gitea-source-sandbox-id <verified-n1-sandbox-id>'
```

不要用 `start` 代替 `resume`，也不要重新创建 sandbox 来“续跑”。

## 5. 结果和清理

每个 task 的 session、trace、grader 和 round checkpoint 由远端 runtime 写入
`/opt/hse-run/artifacts`，controller 通过状态 relay 更新 VPS dashboard。评分时分开报告：

- official grader correctness；
- harness/session completion；
- user acceptance/interaction outcome；
- provider/infrastructure timeout；
- 原始 wall time、active time 和 provider wait。

canary 结果不能计入正式 accuracy。实验生成的 `prepared/`、`runs/` 和
`harbor-canary-jobs/` 已加入 `.gitignore`，不要提交 payload、日志、sandbox state 或
任何凭证。
