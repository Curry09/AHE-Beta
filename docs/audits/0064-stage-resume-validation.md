# Spec 0064 阶段恢复验收

日期：2026-09-15

## 验收对象

本次验收覆盖同一 `experiment_id` 下的稳定 `run_id`、配置摘要、controller SHA、交互计划摘要，
以及 `users → triage/divergent → designer → owner → delivery_wait → round_sealed` 的恢复链。
`SessionStore`、Gitea 和 git 仍是各自业务事实的权威来源，`checkpoints/recovery.json` 只保存冻结输入、
模型输出回执、工作项状态与对账结果。

## 入口结论

- `runtime.create` 一次性生成 `run_id`，并把 `config_hash`、`controller_sha`、`plan_hash` 和 runner
  写入不可变 manifest。
- 审计 controller 的 fresh 路径拒绝已有 recovery state；resume 路径要求 recovery state 存在且
  五项身份完全一致。
- `experiment resume <id>` 对审计实验调用带 `--resume` 的真实需求 controller。controller 先恢复
  Compose 基础设施，再以同一 `run_id` 启动 SWE-bench 闭环，并在 journal 记录 reconcile 和 resume。
- 两个闭环入口只有 fresh 会种 harness、强推远端 main、关闭遗留 issue 和清空 live。resume 会复用
  harness、Gitea、role run、SessionStore 与 live/history，并把遗留 running 槽标为等待恢复。
- controller 当前 HEAD 必须等于冻结的 `source.auto_designer_sha`。配置、计划、controller 或 recovery
  identity 漂移均在模型调用和业务副作用前失败。

## 故障矩阵

| 故障位置 | 恢复断言 | 覆盖测试 |
|---|---|---|
| 用户会话副作用后、完成标记前 | SessionStore/稳定 session id 对账；只补缺失会话 | `test_stage_resume_e2e.py`、`test_sim_user.py`、`test_session_store.py` |
| Triage 输出或评论应用后 | 复用输出回执；不重复模型调用或评论 | `test_stage_resume_e2e.py`、`test_triage.py` |
| Divergent proposal 创建后 | 按 operation key 找回原票；不重复建票 | `test_stage_resume_e2e.py`、`test_divergent_gate.py` |
| Designer grouping/batch/proposal 后 | 复用冻结分组及 batch 输出；补齐未完成来源迁移 | `test_stage_resume_e2e.py`、`test_designer.py`、`test_grouped_designer.py` |
| Owner 标签或评论后 | 重放冻结决策；admitted 集合保持不变 | `test_stage_resume_e2e.py`、`test_owner.py` |
| Delivery inflight/timeout | 不重跑上游；重新读取完整固定 admitted 集并逐票对账终态；已完成票不能被同批其他超时票误标失败 | `test_stage_resume_e2e.py`、`test_orchestrator.py`、`test_round_gate.py` |
| Delivery 业务失败 | 先完成全 admitted 集合对账，再只报告 `automation-failed`/`needs-human` 的真实 blocker；不得让列表中较早的失败票阻止后续票补记完成 | `test_stage_resume_e2e.py`、`test_orchestrator.py` |
| 身份、输入、输出或 revision 漂移 | fail-closed，不覆盖旧状态 | `test_recovery.py`、`test_run_auditable_experiment.py` |

`backend/scripts/e2e-stage-resume.sh` 汇总运行上述阶段、角色和副作用测试。故障用例在副作用写入后抛出
进程级等价异常，重新打开磁盘 recovery store 并重建 Orchestrator；恢复结果与无故障基线比较 session、
issue 后置条件、admitted 集、全部阶段终态和 sealed SHA。角色级用例另覆盖“模型输出已保存”和
“Gitea 副作用已提交但 recovery 完成标记未保存”的窗口。

## 已执行验证

```text
backend/scripts/e2e-stage-resume.sh
197 passed

pytest（实验 runtime/CLI、live、审计 controller、SWE-bench 入口及 E2E）
36 passed

backend 全量 pytest
940 passed
```

## 2026-09-18 Delivery 对账回归

修复恢复流程在遇到首个 delivery 失败票时立即抛错的问题。恢复器现在会先遍历完整的冻结 admitted
集合，把 forge 中已经完成的票补记为 `completed`，收集全部真实 blocker 后再 fail-closed。等待过程
返回 timeout/blocked 时也会重新读取每张 inflight 票的 forge 终态，只给实际受影响的票写入失败，
避免已合并票或无关在途票被批量误标，从而使后续 resume 反复卡在同一张旧票。

新增 `test_delivery_reconciles_every_ticket_before_reporting_blockers` 和
`test_delivery_timeout_rechecks_forge_before_marking_units_failed` 两项端到端回归测试。

阶段恢复不尝试续接进行中的 token stream 或容器内线程。未完整保存输出的最小工作项会重新调用模型；
已经完整保存的角色输出与已经满足的外部后置条件不会重复执行。
