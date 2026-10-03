# Spec-0074 批量实验验收

本报告将离线生产链路验收与真实 provider 试验分开。离线测试通过不代表 Docker、E2B、Gitea.com 或模型网关已被实际调用。

## 可重复执行的离线验收

```bash
bash backend/scripts/e2e-spec-0074-batch-experiments.sh
```

`backend/tests/test_experiment_batch_e2e.py` 保留真实的批次配置/冻结材料/账本/调度，以及单 run 的 `check_v2`、`prepare_v2`、`run_v2`、`status_v2`、`stop_v2`、`collect_v2`。测试没有替换这些生命周期函数。

边界替身负责 Docker 可用性检查和镜像准备、资源 adapter、模型回复和交付角色。adapter 使用生产 `engine` 启动真实 supervisor 和 controller 子进程；子进程从该 run 的冻结源码导入生产 Orchestrator、会话执行、SessionStore 和 RecoveryStore。每个成员执行两轮；第一轮含非空 admitted Issue、真实 Git 提交和生产交付闸，第二轮仅用户试用。模型和准入决策为脚本化输出，不能据此评价模型质量或 Owner 的真实决策质量。

测试同时检查两个成员的封口 SHA、恢复账本、终态归档内容和凭证排除。provider 无真实 Gitea 服务，归档将 Gitea 远端快照明确视为不适用；这不替代 live 的建仓、Issue/PR 拉取和远端认证验收。

| 场景 | 实际验收边界 |
| --- | --- |
| 活动上限 1 / 2 | 计算真实 engine 子进程的峰值活动数；启动确认不释放 lease，终态 collect 后才调度下一项 |
| 启动后、ack 落账前崩溃 | provider 已启动实际子进程；恢复重新观察同一 run，未再次 provision / fresh launch |
| UNKNOWN | 活跃实际子进程的 observation 不可得；保留 lease，第二成员 pending，恢复后接回原 run |
| PARTIAL collection | 真实 archive 生成 PARTIAL，名额保留；显式 terminal collect 重试后继续 |
| Ctrl+C / stop / resume | Ctrl+C 只 detach scheduler；stop 给实际进程发送信号；resume 保留 run ID 和 RecoveryIdentity |
| 模型传输失败 | 子进程在模型边界异常退出，实验 FAILED，终态归档 COMPLETE；下一成员不启动 |
| 配额失败 | 资源 provision 边界抛错，保存意图且不创建替代 run / 不启动下一成员 |
| 重复调用 / 材料篡改 | 已完成 run 不重复 provision / launch；子 manifest 身份改变在启动前拒绝 |

2026-10-03 执行上述脚本：**97 passed，94.16 秒**。其中新增生产链路集成为 **11 个测试用例**；其余覆盖批次配置、账本、调度和公开示例。新增测试的 Ruff lint / format、脚本 `bash -n` 和 `git diff --check` 均通过。脚本自身不调用真实云资源或模型。

随后全仓后端/评测测试结果为 **1593 passed，2 skipped，206.93 秒**（记录：`/home/wydlinux/spec0074-live-20261003/full-pytest.log`）；全仓 Ruff lint / format 通过，format 检查共 510 个文件，`git diff --check` 通过。这是整个测试套件的回归结果，不代表新增真实云批次验收。

额外的 generation 反例将真实单 run collect 产生的 COMPLETE receipt 标为另一 nonce；批次拒绝释放原 generation 的 lease，保持 pending。只有与最新 observation 匹配的 nonce/state 和已停止 controller，才允许 terminal collection 完成。停止恢复反例在第一轮已交付并封口后执行 stop；resume 后保留第一轮 SHA，Git 仓仍只有 baseline 与交付两个提交，会话索引仍为两条。

## 真实 provider 验收

2026-10-03 已完成真实 Local 批次 `batch-20261003T055525Z-92ebe50b`：两个成员、活动上限 1、各一轮 direct 普通任务，使用真实 Docker、本地 Gitea 和模型调用。材料与操作证据位于 `/home/wydlinux/spec0074-live-20261003/`；`check-offline.json`、`check-online.json` 均为 `ok:true`，`prepare.json` 为 READY，`status-final.json`、`collect-final.json`、`resume.json` 均为 COMPLETED / COMPLETE，最终 `counts.active=0`、`counts.pending=0`、`counts.completed=2`。

| 成员 | 冻结 run ID | 实际会话 | 最终归档 SHA-256 |
| --- | --- | --- | --- |
| first | `20261003T055525Z-37242b99` | 1 个 direct 会话，attempt 1 | `8c10d1351d15e26d8dc9d1bd5f129a355a9027b1372a6ae8d6c12cb091ef436a` |
| second | `20261003T055858Z-dbcfdb1b` | 1 个 direct 会话，attempt 1 | `d8ae8326910cde40c66ed6c17b71dabbc684fcbce9439c973eaa170e5cbb889b` |

`final-proof.json` 与两个 child 的 `journal.jsonl` 核对了真实限流顺序：第一项终态收集完成于 **06:03:44.778943 UTC**，第二项第一次 provision intent 为 **06:03:45.093290 UTC**；最大 active lease 为 1。第一项仅一次 fresh provision；第二项 fresh 启动后，经 stop/resume 在同一 run 下恢复，未新建批次成员。

`stop.json` 确认 PAUSED；恢复保持相同 batch/run IDs，intent 与 manifest hash 不变，先前已完成的 first 会话文件字节不变。必须限定该 live 恢复证据的含义：stop 确认时 second 已有完整用户会话结果，resume 接回该结果并完成 controller 封口，两个用户 unit 最终仍均为 attempt 1。本次没有实际验证 **batch 层尚未完成用户会话的重试**；也因为各成员只有末轮用户阶段，没有 live 非空需求/交付。非空交付及 R1 已封口后的恢复由上面的两轮离线测试覆盖，不能写成此次 live 完成了这些路径。

随后通过单 run 的显式 destroy 清理两项 owned Local compute；`destroy-final.json` 中两者均为 `resource_state:DESTROYED`，保留 `experiment_state:COMPLETED`、`collection_state:COMPLETE`。这是运行者显式清理，批次没有自动销毁或删除仓库。

当前没有真实 E2B **批次**验收证据：测试账号的五个 Gitea.com 仓库名额已满。此前 Spec-0073 N4 的真实 E2B 单 run 完成、8 个会话、归档 COMPLETE 与 destroy DONE，只能作为单 run 的证据，不能算作 Spec-0074 的云批次验证。
