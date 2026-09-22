---
number: "0066"
title: Provider latency 隔离与官方预算超时
issue: 0
slug: provider-latency-isolated-timeout
summary: 保留完整 wall time，同时把模型提供方等待从机制 active-time 预算中隔离，并统一官方任务内层预算与外层加 600 秒规则。
tasks:
  - id: T1
    title: 统一时间账本与 provider scope
    status: done
    priority: P0
    tags: [timeout, observability]
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/usage.py
      - backend/auto_designer/loop/live_tracer.py
      - backend/auto_designer/user/sim/persona_client.py
    scope: 记录 wall、active、provider wait、unknown 时间及模型调用事件，重叠 provider 区间按 union 计数。
    acceptance: 每次调用有可关联 call_id；记录可重放且不含凭证；旧 usage 记录保持兼容。
  - id: T2
    title: 角色超时分类与可恢复取消
    status: done
    priority: P0
    tags: [timeout, recovery]
    depends-on: [T1]
    relates-to: [0064]
    parallel: false
    files:
      - backend/auto_designer/designer/agent_runtime.py
      - backend/auto_designer/designer/grouped_designer.py
      - backend/auto_designer/loop/sim_user.py
    scope: 区分 mechanism、provider、infrastructure、controller timeout，并在恢复账本中保存截止证据。
    acceptance: provider 等待不被误报为机制失败；外层 wall guard 仍有限；完成的 operation 不被 resume 重放。
  - id: T3
    title: 官方内层预算与 E2B 配置传播
    status: done
    priority: P0
    tags: [evaluation, e2b]
    depends-on: [T1, T2]
    relates-to: [0065]
    parallel: false
    files:
      - evaluation/harness-suite-20260920/configs/scaling-e2b-20260922.json
      - evaluation/harness-suite-20260920/configs/mixed-scaling-20260922.json
      - evaluation/harness-suite-20260920/run_scaling_bundle_e2b.py
      - evaluation/harness-suite-20260920/freeze_scaling_runtime.py
    scope: 从 task metadata 读取 official agent timeout；无官方值时使用并标记 1800 秒 fallback；outer=inner+600。
    acceptance: manifest、receipt、远端 run.sh 和运行环境包含同一 timeout policy；配置漂移 fail-closed。
  - id: T4
    title: 回归验收与操作文档
    status: done
    priority: P1
    tags: [tests, docs]
    depends-on: [T1, T2, T3]
    relates-to: [0067]
    parallel: false
    files:
      - backend/tests/test_time_accounting.py
      - evaluation/harness-suite-20260920/EXPERIMENT-QUICKSTART.md
    scope: 覆盖时间分类、直接交互和 E2B 启动前检查，并给出恢复与结果解释方式。
    acceptance: 回归测试通过；quickstart 不要求把凭证写入配置或命令行。
---

# 0066 · Provider latency 隔离与官方预算超时

## Summary

评测必须同时保留原始 wall time 和可解释的 active time。模型服务排队、首 token
延迟、流式读取和重试属于 provider wait；本地工具、解析、工作区操作、检查点和
Harness 控制属于 active work。机制超时只由 active budget 判定，provider wait 和
基础设施超时单独归类，不能伪装成任务失败。

每个 task 的内层截止是官方 agent timeout；外层截止固定为
`official_agent_timeout_seconds + 600`。无官方预算时才使用 1800 秒 fallback，并在
manifest/receipt 中标记来源。该规则适用于 direct 和 simulated-user 两种交互。

## Contract

运行时为每个 role operation 保存 `wall_elapsed`、`active_elapsed`、
`provider_wait_ms`、`unknown_elapsed_ms`、调用次数和 timeout class。provider 请求有
自己的 deadline；整个 task 还有外层 wall guard。外层截止发生在 provider wait 时，结果
是 infrastructure timeout；active work 超过机制预算时才是 mechanism timeout。

`latency_isolated_timeout.enabled` 是兼容开关。正式 E2B scaling 配置启用它，并把
`wall_guard_grace_seconds=600` 传播到 controller、远端 bundle、receipt 和 run.sh。
凭证仍只能通过 `.e2b`、`.boyue` 或注入环境提供。

## Verification

变更必须通过 time-accounting、direct-session、grouped-designer、infrastructure 和
closed-loop 回归测试；启动前 receipt 还必须绑定 config/task/template/payload SHA、
canary evidence 和 timeout policy。详细实现约束见
`evaluation/harness-suite-20260920/SPEC-time-accounting-provider-latency.md`。
