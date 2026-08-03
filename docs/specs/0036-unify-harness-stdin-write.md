---
number: "0036"
title: 接缝层统一 stdin 写入口：去 begin/emit 二分，reply 软唤醒
issue: 0
slug: unify-harness-stdin-write
summary: 接缝层 begin/emit_message 二分泄漏「正式轮次 vs 加塞」语义，并把读 stdout 绑在 in_flight 上，导致 reply 后 keep_waiting 空转。本组改为：用户消息统一一个写入口（始终写 stdin，类 CC 输入框）；堵/排队由 harness 决定；平台以 type=reply 为软唤醒（等下一条 reply 或超时），poll 不依赖写路径旗标；interrupt 仍为外通道。改动面集中在 launcher/loop/connector 与测试，不改 harness 线协议形状。
tasks:
  - id: T1
    title: 写 0036 活快照
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - docs/specs/0036-unify-harness-stdin-write.md
    scope: 写清动机：begin/emit 二分与 in_flight 挡读的问题；选定统一写入口 + reply 软唤醒；划清与 0022/0035 边界；明确不把 utterance FIFO 账本当设计约束。
    acceptance: spec validate 通过；正文含 Summary/Motivation/Reference-level explanation/Rationale and alternatives；DAG 与文件分配清楚。
  - id: T2
    title: launcher：统一写入口 + poll 不绑写旗标
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/harness/launcher.py
      - backend/tests/harness/test_launcher.py
    scope: 用户消息统一 write_message（或等价单一 API）：始终写 stdin message 帧，不区分 begin/emit；去掉「必须/禁止 in_flight 才能写」的分叉。poll(timeout) 只读 stdout 等下一条 type=reply（progress/status 照记并继续等），不要求写旗标；超时返回 pending。保留 interrupt/shutdown 外通道。阻塞 send() 改为「写 + poll 直到 reply」。删除实验性平行等待 API（若有）。
    acceptance: 单测：连续两次写 message 无需中间虚构轮次锁；reply 后再 poll 能拿到后续 reply；空闲 poll 超时 pending；progress/status 在等 reply 期间被记录；interrupt 路径不回归。
  - id: T3
    title: loop：主/心跳发消息走统一写；keep_waiting→poll
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/user/sim/loop.py
      - backend/tests/user/sim/test_loop.py
      - backend/tests/user/sim/test_heartbeat.py
    scope: 主 loop 与心跳的 send_message 都走统一写入口；等待环以 reply 软唤醒（写后 poll 直到 reply 或心跳定时）。主 loop keep_waiting：poll 等下一条 reply，超时 None，无 reply 时仍 drain 旁路事件。不把 utterance FIFO 账本当唤醒/写路径前提。heartbeat 菜单本轮不强制加 accept（可列 Unresolved）。
    acceptance: route/集成测：reply 后 keep_waiting 能拿到后续 reply；心跳插话与主发消息均走同一写；空闲 keep_waiting 安全 no-op；既有心跳路径绿。
  - id: T4
    title: connector 与 INTERFACE 对齐统一写
    status: done
    priority: P2
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/harness/connector.py
      - backend/auto_designer/harness/INTERFACE.md
      - backend/tests/harness/test_connector.py
    scope: connector 暴露统一写与 poll/drain；文档写明：stdin 消息统一、reply 为软唤醒标签、interrupt 外通道；兼容层可保留旧方法名作别名但语义指向统一写。
    acceptance: connector 单测覆盖统一写与 poll；INTERFACE.md 与实现一致；无 begin/emit 语义分叉描述残留（或明确标为 deprecated 别名）。
---

# 0036 · 接缝层统一 stdin 写入口：去 begin/emit 二分，reply 软唤醒

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

本组收敛接缝层对 harness 的 I/O 模型，使其更接近真人 CLI（输入框常在）：**用户消息统一一个 stdin 写入口**；**堵/排队由 harness 决定**；平台以 stdout 上的 `type=reply` 为**软唤醒**（用户再 decide），不以平台私有的「正式轮次 / 加塞」语义约束 harness。

同时收掉现行实现的一个具体缺口：`reply` 之后主 loop `keep_waiting` 因写路径旗标而空转——读 stdout（`poll`）不再依赖该旗标。不改 harness 线协议形状（仍为 message / progress / status / reply / interrupt），不把 TurnLog utterance 账本当设计约束。

## Motivation

### 二分写入口泄漏产品语义

现行 launcher 提供 `begin` 与 `emit_message`：

- `begin`：平台「正式开一轮」，置内部旗标，后续用 `poll` 等对应 `reply`
- `emit_message`：仅在旗标为真时允许再写，称为「轮次中加塞」

对 harness 而言两者都是同一类 stdin message。分叉是接缝层为等待环记账发明的，把「正式轮次 vs 加塞」泄漏进了平台 API，不利于 harness 按 CC 式「输入框一直可用」进化。

### 读路径绑在写旗标上

旗标在收到 `reply` 后清除；主 loop `keep_waiting` 若要求旗标为真才能 `poll`，则 **reply 之后无法再等下一条 reply**（例如 queued 工作的后续输出）。0035 已写明 reply ≠ idle 与 `keep_waiting` 语义，但未钉死读路径与写旗标解耦；本组一并落地。

## Guide-level explanation

对用户模拟：

```text
发消息 → 统一写入 stdin
        → poll / 心跳：progress、status 可见，继续等
        → 见到 type=reply → 软唤醒，主 loop 再 decide
        → 可再发消息 / keep_waiting（再 poll）/ interrupt / 终止
```

对 harness：只看到连续的 message 与可选 interrupt；如何排队、何时吐 reply，由它自己决定。

## Reference-level explanation

### 写

- 单一 API（名可 `write_message`；旧 `begin`/`emit_message` 可作 deprecated 别名，语义均为写 stdin message 帧）。
- **不**再要求「无进行中轮次才能写」或「必须有进行中轮次才能写」。
- 连续多次写合法；是否排队/丢弃/并行处理属 harness 行为，经 stdout 可见事件表达。

### 读与软唤醒

- `poll(timeout)`：读 stdout；`progress`/`status` 等记入可见事件并继续等；`type=reply`（及 legacy `reply` 字段）→ 返回该文本；超时 → `pending`。
- **不**以写路径旗标作为 `poll` 前置条件。
- 主 loop `keep_waiting`：调用 `poll`；有 reply → 作为下一轮 `harness_output`；超时 → `None`，仍可 `drain_visible_events`。
- 等待环（写后至下一条 reply）：仍可用定时心跳；心跳内 `send_message` 走同一写入口。

### 外通道

- `interrupt` / `shutdown` 仍为外通道（0022），不是普通 message。

### 非目标

- 不改为「每条 progress 都唤醒主 decide」（成本过高）。
- 本轮不强制心跳菜单增加 `accept`（可后续开组）。
- 不要求删除 TurnLog 观测字段；也不以之为写/读前提。
- 不改 v0 harness 的 queued/status 产品行为（0035/T4 已落地）。

### DAG 与文件分配

```text
T1 活快照
 ├→ T2 launcher 统一写 + poll
 │    ├→ T3 loop 接线
 │    └→ T4 connector / INTERFACE
```

| Task | 文件 |
|---|---|
| T1 | `docs/specs/0036-unify-harness-stdin-write.md` |
| T2 | `harness/launcher.py`, `tests/harness/test_launcher.py` |
| T3 | `user/sim/loop.py`, `tests/user/sim/test_loop.py`, `test_heartbeat.py` |
| T4 | `harness/connector.py`, `INTERFACE.md`, `tests/harness/test_connector.py` |

## Drawbacks

- 去掉「单 begin 在飞」后，平台不再用旗标防止「逻辑上的双轮次」；若调用方误连写，依赖 harness 与用户行为消化（与真人 CLI 一致）。
- 旧测试/探针若断言「不可并发 begin」或「emit 必须 in_flight」需改写。
- 兼容别名短期存在时，文档须避免继续传播二分语义。

## Rationale and alternatives

### 为什么统一写，而不是只放宽 poll

只放宽 `poll` 能修 `keep_waiting` 空转，但留下 begin/emit 二分，进化时仍要解释「加塞」。统一写一次收掉泄漏语义，并自然包含读路径解耦。

### 为什么软唤醒选 type=reply

与现行 harness 线协议一致，控制 decide 频率；progress/status 仍进入感知，但不每次触发完整主决定。若将来需要「任意可见事件唤醒」，再扩展 `poll` 返回 kind，而非第三套写 API。

### 为什么保留 interrupt 外通道

真人 CLI 中 Ctrl+C 与打字不是同一通道；0022 内外窗口仍然成立。

## Prior art

- 0022：内外通道；本组保留 interrupt，收紧的是普通 message 写路径。
- 0035：stdout 可见事件、`keep_waiting`、reply ≠ idle；本组落实读路径并去掉写二分。
- Claude Code / Codex：输入框常在；忙时输入由产品侧反馈，非客户端伪造「加塞类型」。

## Unresolved questions

- 心跳等待菜单是否补 `accept` / 与主 loop 动作空间完全对齐。
- 内部是否仍保留只读的「距上次 reply 的期望」计数器供观测，还是完全删除写旗标。
- Fake/Scripted harness 的最小表面：是否只实现统一写 + 阻塞 `send`。

## Future possibilities

- 事件合并窗口：短时间多条 progress 合并后再决定，进一步降本。
- harness 自愿输出 `reply_to` 时仅作展示，不作平台推断。
- 主/心跳环进一步合并为单一事件环（本组不强制）。

