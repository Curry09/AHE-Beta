---
number: "0019"
title: launcher 非 reply 旁路放宽（progress 等）
issue: 0
slug: control-sideband-peek-wait
summary: 放宽 harness stdout 旁路协议（任意非 reply JSON 可收，写入 last_sideband/last_progress）；control() 仍支持旁路 ack 或终态 reply 两种形状（wire 兼容）。用户侧经 control 做 peek/status 的路径已由 0022 取代并 abandon（原 T2）。现行用户等待环见 0022。
tasks:
  - id: T1
    title: launcher：非 reply 旁路一律收 + control 旁路/终结分流
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to:
      - ref: 0022/T1
        type: note
    parallel: false
    files:
      - backend/auto_designer/harness/launcher.py
      - backend/tests/harness/test_launcher.py
    scope: stdout 协议放宽：一轮内可有任意多行非 reply JSON 旁路（progress/其它字段），仅含 reply 的行结束本轮；未知旁路不报协议违例。poll 累积 last_sideband/last_progress。control(name) 等到 reply 或非纯 progress 旁路 ack；暴露 in_flight。用户 sim 主路径仅 interrupt；peek-via-control 不再由用户菜单调用（见 0022）。
    acceptance: poll 对仅含未知键的旁路 JSON 不抛协议违例、写入 last_sideband；progress 映入 last_progress；control('interrupt') 返回 reply 且 in_flight 为 False。单测覆盖未知旁路、interrupt 终结；wire 上 status 旁路仍可测但不作为用户侧现行能力。
---

# 0019 · launcher 非 reply 旁路放宽（progress 等）

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

在 0013 的 `begin/poll/control` 之上，放宽 launcher 对 stdout **非 reply 旁路**的接收：任意非 reply JSON 可收，映入 `last_sideband` / `last_progress`，供心跳活动条使用。`control()` 在 wire 上仍区分「旁路 ack」与「终态 reply」。

**用户侧**不再经 `invoke_control` 做 peek/status——该路径（原本组 T2）已 abandon，由 **0022** 内外窗口（内=message）取代。本组活快照只保留 **T1（launcher 管道）**。

## Motivation

初版 `poll` 过窄时，非 `progress`/`reply` 的旁路会报协议违例，活动条与未来旁路接不住。需要管道放宽。

随后曾在用户侧用 control 做 peek；该设计与「内=message」冲突，已迁出本组。管道放宽本身仍有价值（progress 累积）。

## Guide-level explanation

- Launcher 收下一切非 reply 旁路；`in_flight` 在终态 reply 前为真。
- 用户等待环如何决策、菜单是什么 → **0022**。
- Harness 若仍实现 status 旁路 control，launcher 接得住，但种子 MANUAL 不宣称该用户能力。

## Reference-level explanation

### 锚点

- `harness/launcher.py`：`_ingest_sideband`、`last_sideband`、`control()`、`in_flight`；另有 0022 的 `emit_message`。
- 单测：`tests/harness/test_launcher.py`。

### DAG

仅 T1。

### 与相邻组

- **0013**：拆信封、interrupt、progress 发射。
- **0022**：用户侧 IO 与等待菜单；取代本组原 T2。

## Drawbacks

旁路 ack 仍用「非纯 progress」启发式；仅影响仍调用 `control(非 interrupt)` 的调用方。

## Rationale and alternatives

保留 T1、去掉用户侧 peek Task：管道与产品语义解耦。备选「整组 abandon」会丢掉仍 live 的旁路接收说明；拒绝。

## Prior art

0013 stdio JSONL；0022 内外通道。

## Unresolved questions

control 面是否最终收窄为仅 interrupt。

## Future possibilities

相关帧 `control_result`；或文档化「仅 progress 旁路、无 status ack」的短超时。
