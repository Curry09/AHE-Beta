---
number: "0062"
title: 交付失败终态协议兼容
issue: 0
slug: delivery-failure-terminal
summary: 本轮交付闸识别 automation-failed，保留 needs-human 兼容并禁止失败轮推进。
tasks:
  - id: T1
    title: 当前与历史失败终态及闭环回归
    status: done
    priority: P1
    depends-on: []
    files:
      - CLAUDE.md
      - backend/ahe_beta/loop/round_gate.py
      - backend/tests/loop/test_round_gate.py
      - backend/tests/loop/test_orchestrator.py
    scope: 代码修改完毕。automation-failed 与 needs-human 均优先于 closed，异常保留准确失败原因和票号。
    acceptance: 两类失败均即时停轮，闭票失败不算成功，不开下一轮；正常交付和超时路径不变。
---

# 0062 · 交付失败终态协议兼容

## Summary

代码修改完毕。修复框架本轮交付闸仅识别旧 needs-human 标签的问题。
2026-09-09 全量测试 856 passed；针对性终态闸与编排回归 38 passed。
测试入口：`.venv/bin/python -m pytest backend/tests/loop/test_round_gate.py backend/tests/loop/test_orchestrator.py -q`。
原实验结果可从 Git 历史查看；当前可复现检查见 `docs/VERIFICATION.zh-CN.md`。

## Motivation

Spec61 双用户实验中 OpenAgents 将 issue #8 标为 automation-failed，而本框架仍当成
inflight 等待四小时上限。实验经一次人工核验恢复后已归档，本修复不改变原运行的审计归因。

## Guide-level explanation

任何准入票出现 automation-failed 或 needs-human，本轮立即报 RoundDeliveryBlocked，
不得封口为成功或启动下一轮用户。停止是显式失败，不是静默卡顿。

## Reference-level explanation

classify_issue 在 closed 判断前检查两种失败标签。wait_round_delivery 保留去重票号，
原因按本次快照实际失败标签确定；混合失败稳定列出两种原因，不误报旧标签。
不直接读取交付运行器数据库，双方仍只通过 forge 状态和主干 SHA 解耦。

## Drawbacks

短暂出现终态也会停止本次实验，这是终态契约的保守选择；交付侧须避免虚假失败/复活震荡。

## Rationale and alternatives

不拉长超时掩盖失败，不把 closed 盖过失败标签，不在本框架内修复交付工作树。

## Prior art

本仓 Spec-0050 终态闸；OpenAgents Spec-0081 机器失败投影和 Spec-0088 收敛修复。
证据见 ahe-beta-experiments/spec61-two-user-glm53-glm52-20260908 的归档和人工干预记录。

## Unresolved questions

真实双用户实验有一次人工纠正，不能宣称全自主成功。修复后的新镜像需另起实验验证。

## Future possibilities

若跨框架终态协议增加状态，先扩充契约回归，再冻结下一场实验的框架版本。
