---
number: "0012"
title: 用户侧等待体感真实化：心跳主动权 · 进度可见 · 任务相关耐心
issue: 0
slug: user-wait-realism
summary: 把用户 agent 面对慢/卡 harness 时的「干等」升级为可感知的真实体感：等待中心跳唤醒后经 judge→intent→act 决策；等待条展示 live progress 与 prior_activity；keep_waiting 仅在无新进度时耗耐心；WAIT_GAP 与 ATTRIBUTION。起始耐心随任务量浮动。等待菜单与内外 IO 语义以 0022 为准（本组不再定义 invoke_control）。
tasks:
  - id: T1
    title: 等待中主动权：心跳唤醒 + 进度可见 + 等待衰减口径统一
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to:
      - ref: 0022/T1
        type: note
    parallel: false
    files:
      - backend/tests/user/sim/test_loop.py
    scope: 真实子进程经 begin/poll 心跳唤醒；等待上下文喂 progress/prior_activity；keep_waiting 仅无 new_progress 时按 patience_decay 耗心；_MAX_HEARTBEATS 兜底；评分 ATTRIBUTION。菜单形状、emit_message、开放 intent/gap、interrupt 归因文案的现行定义见 0022（本组不再维护 invoke_control）。本 Task 文件列表仅保留未被 0022 独占声明的 test_loop；实现主体在 0022/T1 与本组 T2。
    acceptance: 真实子进程才 supervised；无新进度 keep_waiting 扣心、有进度不扣；耐心耗尽/心跳上限可转 give_up；等待 prompt 含 progress/prior_activity；评分含 ATTRIBUTION。与 0022 菜单单测一并覆盖。
  - id: T2
    title: 状态耐心模型：任务量起始浮动 + 性格衰减系数
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/user/sim/state.py
      - backend/tests/user/sim/test_state.py
    scope: 把跨轮耐心从固定基线升级为「性格档位 + 任务量微浮动」两级：init_state 由 D4.3 给耐心基线；开局 OPENING 据 task_load 经 apply_task_load 叠加 TASK_LOAD_DELTA，钳到 >=1。Coef.patience_decay 由性格派生，供 apply_verdict 与心跳 keep_waiting 共用。
    acceptance: 同一 persona 面对 quick 的起始耐心严格低于 epic；浮动只在 OPENING 一次、钳位 >=1；patience_decay 急躁=2 否则 1；apply_verdict 规则单测覆盖。
---

# 0012 · 用户侧等待体感真实化：心跳主动权 · 进度可见 · 任务相关耐心

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

把用户 agent 面对慢/卡 harness 时的行为，从「静默干等到超时」升级为拟真机制：

1. **等待中的主动权**——心跳唤醒后走 **judge → intent → act**。
2. **可见进度**——等待 prompt 喂 `last_progress` 与跨轮 `prior_activity`。
3. **有条件耗心**——`keep_waiting` **仅当本心跳无 new_progress** 才扣耐心。
4. **WAIT_GAP + ATTRIBUTION**——意愿未兑现记 gap；用户自打断不归咎 harness。
5. **任务相关起始耐心**——性格档位 + 任务量微浮动。

**等待菜单、内外通道、开放 intent、`emit_message`、interrupt 归因的现行定义见 0022**（本组不再描述 `invoke_control` / 封闭 intent 枚举）。

## Motivation

0005 回合制把慢 harness 压成「最终一次判断」，丢掉等待过程体感；起始耐心与任务量无关。本组引入心跳、进度可见、有条件耗心与任务量浮动。菜单与 IO 边界的换代由 0022 完成。

## Guide-level explanation

- 真实子进程才心跳；Fake/Scripted 否。
- 决策三跳（或 two 合并）；上下文含秒数、history、MANUAL、progress、prior_activity。
- `keep_waiting`：无新进度才耗心；触顶或耐心耗尽 → 放弃（具体动作 ID 见 0022）。
- 起始耐心：OPENING `task_load` 微浮动。
- ATTRIBUTION：自 interrupt 勿怪 harness。

## Reference-level explanation

### 锚点

- 心跳编排与菜单现行代码：见 **0022/T1**（`loop.py` / `prompt.py` / `launcher.py`）。
- 耐心模型：`state.py`（本组 T2）。

### DAG

```mermaid
graph LR
  T1[T1 心跳与衰减口径]
  T2[T2 耐心模型]
```

### 与相邻组

- **0022**：内外窗口、等待菜单、开放 intent、`report_issue`、slash。
- **0013 / 0019/T1**：progress 发射与旁路接收。

## Drawbacks

只对真实子进程生效；three 模式 LLM 调用多；常量经验值。

## Rationale and alternatives

心跳 + 有条件耗心优于「超时直接放弃」或「每次 keep 都扣心」。菜单换代不在本组重复设计，交给 0022。

## Prior art

0005；长运行 agent heartbeat；0022 IO 边界。

## Unresolved questions

阈值与 `TASK_LOAD_DELTA` 是否重标。

## Future possibilities

等待序列结构化喂 0016；按情绪调心跳频率。
