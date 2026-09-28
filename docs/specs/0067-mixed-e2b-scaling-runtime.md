---
number: "0067"
title: 混合 Harness E2B Scaling 运行时
issue: 0
slug: mixed-e2b-scaling-runtime
summary: 为 N=1/4/8/16/32 建立按 receipt 冻结、可恢复、可并行启动的 E2B 混合任务运行时，并统一 direct 与 simulated-user 结果产物。
tasks:
  - id: T1
    title: 冻结任务、资源和运行身份
    status: done
    priority: P0
    tags: [evaluation, reproducibility]
    depends-on: []
    relates-to:
      - ref: 0065/T1
        type: extends
    parallel: false
    files:
      - evaluation/harness-suite-20260920/prepare_scaling_runtime_bundles.py
      - evaluation/harness-suite-20260920/freeze_scaling_runtime.py
      - evaluation/harness-suite-20260920/configs/mixed-scaling-20260922.tasks.json
    scope: 按 N 生成 agent/grader 分离的 payload inventory，并冻结任务 revision、prompt、grader、模型、资源、timeout 和 canary evidence。
    acceptance: receipt 缺字段、SHA 漂移、held-out 数据泄漏或 canary 不通过时 launch gate fail-closed。
  - id: T2
    title: E2B mixed executor 与交互边界
    status: done
    priority: P0
    tags: [e2b, interaction]
    depends-on: [T1]
    relates-to:
      - ref: 0065/T4
        type: extends
    parallel: false
    files:
      - evaluation/harness-suite-20260920/run_scaling_bundle_e2b.py
      - backend/scripts/run_mixed_closed_loop.py
      - backend/auto_designer/loop/sim_user.py
    scope: 一个 N 对应一个 sandbox、Gitea repository 和 recovery identity；simulated-user 保留 heartbeat，direct 只发一条 harness 输入并做一次终端 review。
    acceptance: 不混用 OpenRouter fallback；direct 不产生 heartbeat/follow-up；两种模式都输出 session、trace、grader 和 user outcome。
  - id: T3
    title: 单 N 启动、五轮检查点与恢复
    status: done
    priority: P0
    tags: [recovery, checkpoint]
    depends-on: [T1, T2]
    relates-to:
      - ref: 0064/T2
        type: extends
    parallel: false
    files:
      - evaluation/harness-suite-20260920/run_scaling_e2b.py
      - evaluation/harness-suite-20260920/start_scaling_n1_e2b.sh
      - evaluation/harness-suite-20260920/start_scaling_n4_e2b.sh
      - evaluation/harness-suite-20260920/start_scaling_n8_e2b.sh
      - evaluation/harness-suite-20260920/start_scaling_n16_e2b.sh
      - evaluation/harness-suite-20260920/start_scaling_n32_e2b.sh
    scope: 每个 N 在独立终端启动 5 轮；轮后和 release 后写 checkpoint；resume 复用原 sandbox、Gitea repo、run_id 和 recovery identity。
    acceptance: 启动/恢复只接受单个 N；预检先完成再创建资源；重复 controller、替换 sandbox 和已完成 operation 重放均被拒绝。
  - id: T4
    title: 结果规范和迁移手册
    status: done
    priority: P1
    tags: [reporting, docs]
    depends-on: [T1, T2, T3]
    relates-to:
      - ref: 0065/T6
        type: extends
    parallel: false
    files:
      - evaluation/harness-suite-20260920/EXPERIMENT-QUICKSTART.md
      - evaluation/harness-suite-20260920/SPEC-mixed-scaling-e2b-executor.md
      - evaluation/harness-suite-20260920/SPEC-scaling-e2b-launch.md
    scope: 统一记录 official correctness、harness completion、user acceptance、timeout class、wall/active/provider wait，并排除生成物和凭证。
    acceptance: 新执行者能按 quickstart 完成物化、冻结、check-launch、启动和 resume；结果可追溯到 receipt 与原始 artifact。
---

# 0067 · 混合 Harness E2B Scaling 运行时

## Summary

正式 scaling 使用 E2B + Boyue。N=1、4、8、16、32 是五个互相隔离的实验单元：每个单元
拥有自己的 controller、sandbox、Gitea repository、run ID 和 recovery identity，运行五轮。
物理 sandbox 直接按开发阶段峰值资源创建；用户、triage、designer/PM 和 developer 是
逻辑阶段，不在阶段之间调整 sandbox 规格。

任务 assignment 在执行前冻结。agent payload 与 grader payload 分离，receipt 绑定配置、
任务 revision、prompt/grader SHA、模型 gateway、模板 build、timeout 和 canary evidence。
launch gate 在任何凭证、网络或付费资源调用前检查这些约束。

## Interaction and lifecycle

`simulated_user` 沿用已有 persona、heartbeat、workspace/check 访问和多轮终止规则；不再
注入固定追问。`direct` 只有一条初始 harness 输入，等待 terminal result，再由用户模型做
一次有界的终端 review；它没有 heartbeat 或中途 follow-up，但仍进入同一 triage → designer/PM
→ developer → grader 管线。

每轮按 interaction、triage、designer/PM、developer、grader 的阶段顺序执行，在下一轮之前
写入原子 checkpoint。最后一轮是否 users-only 由配置决定。断连时 resume 只能连接 receipt
记录的 sandbox/repository/identity，不创建替代资源，也不重放已完成 session 或 delivery。

## Operator path

执行者应阅读 `evaluation/harness-suite-20260920/EXPERIMENT-QUICKSTART.md`，依次完成
payload materialization、receipt freeze、单 N `check-launch`，再在五个独立终端按需启动。运行
产物落在本地 controller 的 `runs/` 和远端 `/opt/hse-run/artifacts`；这些生成目录由 git
ignore 排除，不进入提交。详细运行时约束见
`evaluation/harness-suite-20260920/SPEC-mixed-scaling-e2b-executor.md`。

## Motivation

此前不同 N 的启动脚本各自管理 sandbox、Gitea、用户交互和恢复状态，容易发生身份串线、
重复 controller 或用新资源替换原资源。0067 将每个 N 固定为独立可审计的实验单元，并
把冻结、启动、检查点和恢复放进同一 receipt 驱动流程。

## Guide-level explanation

先物化并冻结 agent/grader payload，再对单个 N 执行 launch gate；通过后才创建付费资源。
每轮结束写原子 checkpoint，断连恢复只接受原 receipt 记录的 sandbox、仓库、run_id 和
recovery identity，已完成 session 或 delivery 不重放。

## Reference-level explanation

receipt 绑定 task revision、prompt/grader SHA、模型 gateway、模板 build、资源、timeout 和
canary evidence。direct 只发送一条 harness 输入并做一次终端 review；simulated-user 保留
heartbeat 和有限追问。controller、远端 run.sh 与结果报告必须输出同一 session、trace、
grader、user outcome 和 timeout class。

## Drawbacks

为每个 N 保持独立资源会增加启动成本和操作面；五轮 checkpoint、receipt 和恢复身份也会增加
磁盘与审计数据量。代价是可以避免跨实验污染并可靠重连原运行时。

## Rationale and alternatives

选择按 N 隔离而不是共享一个大 sandbox，是为了让并发扩展和故障恢复有明确边界。选择 receipt
冻结而不是仅依赖配置文件，是为了阻止任务、grader 或 timeout 在运行中漂移。共享 controller
或恢复时重建资源虽然更简单，但会破坏可追溯性并可能重复收费。

## Prior art

0065 定义评测计划、交互模式和统一结果；0064 定义阶段恢复与幂等副作用；0066 定义官方
预算与 provider latency 隔离。本 spec 将三者组合为 E2B scaling 的实际运行路径。

## Unresolved questions

N=32 以上是否需要分片 controller、跨区域资源以及更细粒度的 artifact backpressure，需由
正式 scaling 数据决定；当前先保持单 N 单 controller 约束。

## Future possibilities

可以在不改变 receipt 语义的前提下增加自动调度、跨 N 汇总和故障注入，并用同一 recovery
identity 重放基础设施无效尝试，保持业务终态不重跑。
