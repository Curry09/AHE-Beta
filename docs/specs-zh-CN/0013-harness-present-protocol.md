---
number: "0013"
title: Harness 呈现与交互协议：拆信封 · 过程流分层 · 打断/心跳
issue: 0
slug: harness-present-protocol
summary: 把 harness 的对用户呈现与内层过程彻底分层，并补齐慢会话的交互协议：拆 complete_task 信封；内层过程经 steps 只吐观测层；进行中可发 mid-flight {"progress":…} 活动条（stdout 可多行旁路，终态仍为一行含 reply）；control:interrupt 回 [interrupted]；launcher begin/poll/control 分片轮询不盲杀。落点 harness_template + harness/launcher。旁路放宽与 peek 续等见 0019。
tasks:
  - id: T1
    title: 拆 complete_task 信封 + 过程流分层 + begin/poll/control 心跳协议
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/harness_template/entry.py
      - backend/ahe_beta/harness/launcher.py
      - backend/ahe_beta/harness/interface.py
      - backend/ahe_beta/loop/sim_user.py
      - backend/ahe_beta/models.py
      - backend/tests/harness/test_template_entry.py
      - backend/tests/harness/test_launcher.py
    scope: entry.py：stdin 逐行 JSON（message/control）；一轮内可先吐零或多行 {"progress":{kind,text}} 活动条（_emit_progress，与终态 reply 共用 _stdout_lock 防交错），终态一行 {"reply", "steps"?}。拆信封 _unwrap_reply；steps 只给观测；interrupt→[interrupted]。预算钮注释。launcher begin/poll/control：进程活着返回 pending；last_steps/last_progress 旁路（progress 接收与未知旁路放宽见 0019）。models/sim_user 落 steps。
    acceptance: 终态 reply 非空且拆信封；进行中可发 progress 行且不替代 reply；steps 不入 reply；interrupt→[interrupted]；poll 存活 pending。单测覆盖信封、steps、打断；progress 发射与接收对齐 0019。
  - id: T2
    title: v0 种子自测 smoke + MANUAL 呈现契约
    status: pending
    priority: P2
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/harness_template/tests/test_smoke.py
      - backend/harness_template/MANUAL.md
    scope: tests/test_smoke.py 最小冒烟；MANUAL.md 记录呈现契约——终态一次 reply、等待中可见 activity strip（progress）、[interrupted]/超时语义、控制面；与 entry 一致。tests/ 只放 harness 本体测试（见 0015）。
    acceptance: smoke 通过；MANUAL 含 activity strip / 终态 reply 分工，与 entry 行为一致。
---

# 0013 · Harness 呈现与交互协议：拆信封 · 过程流分层 · 打断/心跳

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

规范 harness 作为「可启动程序 + 黑盒对话契约」对用户的呈现与交互协议：

1. **拆信封**——`complete_task` 信封剥到 `output.result`，用户只看最终答案；
2. **过程流分层**——内层 `steps` 只吐观测层，persona 只吃 `reply`；
3. **进行中活动条**——一轮内可先发零或多行 `{"progress":{kind,text}}`（与终态 reply 共用 stdout 锁），终态仍为一行含 `reply`；
4. **打断/分片轮询**——`control:interrupt` → `[interrupted]`；launcher `begin/poll/control` 对活进程返回 pending、不盲杀。

旁路键放宽与 peek 续等见 **0019**。落点 `harness_template/` + `harness/launcher.py`。

## Motivation

harness 是黑盒对话契约：stdin 收消息、stdout 回复。需要根治信封泄漏、过程流污染体感、慢会话无协议；并让等待中有可见活动条，供 0012 心跳决策。

## Guide-level explanation

- **协议帧。** stdin：`{"message"}` / `{"control"}`。stdout：进行中可多行 `progress`；终态一行 `{"reply", "steps"?}`。
- **reply 给人看**；`steps` 观测旁路；`progress` 是活状态不是终答（MANUAL activity strip）。
- **打断** → `[interrupted]`，保留会话。
- **长任务不盲杀**：`poll` 活进程 → pending。
- **预算钮可见**（`_RUN_RETRIES` / `max_iterations`）；harness 不设整轮墙钟上限。

## Reference-level explanation

### 代码锚点

- `harness_template/entry.py`：`_emit_progress`、`_stdout_lock`、拆信封、interrupt、tracer→steps。
- `harness/launcher.py`：`begin`/`poll`/`control`、`last_steps`/`last_progress`（接收放宽见 0019）。
- `MANUAL.md`：activity strip + 终态 reply 分工。

### 契约表

| 关注点 | 本组契约 |
|---|---|
| 收尾 | 拆到 `output.result` |
| 内层过程 | `steps` 只观测 |
| 进行中 | 多行 `progress`，不替代 reply |
| 慢会话 | begin/poll/control，活进程 pending |
| 打断 | `[interrupted]` |

### DAG

```mermaid
graph LR
  T1[T1 协议与拆分]
  T2[T2 smoke + MANUAL]
```

### 接缝

0012 消费 progress/poll；0019 放宽未知旁路与 peek；0014 改对外行为须同步 MANUAL。

## Drawbacks

信封拆解启发式；progress 与 steps 可能重复信息；打断依赖 nexau `force_stop` 检查点。

## Rationale and alternatives

- 墙钟盲杀会误杀合法长任务。
- 把 progress 拼进 reply 会污染体感。
- 未知旁路接收归 0019，本组负责种子发射契约。

## Prior art

CLAUDE.md 黑盒契约；stdio JSONL；长任务 poll/heartbeat。

## Unresolved questions

超时是否种子内建「部分结果」？progress 粒度与截断？

## Future possibilities

种子「超时即回进行中」；观测层按 progress/steps 重建时间线。
