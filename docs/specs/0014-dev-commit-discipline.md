---
number: "0014"
title: 旧内置 Developer 提交纪律（已退役）
issue: 0
slug: dev-commit-discipline
summary: 旧内置 Developer 的两个提交中间件及其装配任务已退役，不再作为当前运行保障；历史设计与实现保留在 Git 历史。
tasks: []
---

# 0014 · 旧内置 Developer 提交纪律（已退役）

## Summary

本组无现役任务。旧内置 Developer 的增量提交催促、收尾检查和对应配置接线已经退役。此次清理删除未被当前运行时加载的两个中间件与专属测试，原任务通过 `spec abandon` 移出活快照。

## Motivation

需求面和交付面已经分离，代码实现由独立 OpenAgents CLI 执行。保留未接线的旧中间件，会使维护者误以为阶段性提交、手册同步和主入口 AST 检查仍在运行。

## Guide-level explanation

当前不配置这组旧中间件。仍有效的需求 Agent 文件访问检查、编排仓完整性检查和 Harness 提交钩子位于 `backend/auto_designer/guards/`，它们不等同于旧 Developer 的提交纪律。

## Reference-level explanation

T1、T2 及专门装配它们的 T3 已退役；本组不再拥有代码文件。过去的源文件、参数、测试与实现可通过 Git 历史追溯。当前 `guards/` 仅包含 `workspace_jail.py`、`repo_guard.py`、`harness_boundary.py` 与包入口，没有旧模块的转发导出。

## Drawbacks

当前发布不再提供这两份旧中间件的可导入入口；依赖旧内置 Developer 的实验需使用原版本。

## Rationale and alternatives

不把无运行时引用的中间件一起搬入 `guards/`，因为这会继续混淆现役保障与历史实现；也不将它们移植到 OpenAgents，因为这涉及独立的执行协议和质量门设计。

## Prior art

旧设计试图在 Agent 内施加增量提交与收尾约束。当前 OpenAgents 按自身配置执行工程交付，本组不宣称它等价实现旧中间件的全部检查。

## Unresolved questions

无。退役范围限定为旧提交中间件及其配置接线，有效边界检查保留。

## Future possibilities

若需要在交付面恢复特定提交纪律，应单独提出需求，并在 OpenAgents 仓验证实际装配与效果。
