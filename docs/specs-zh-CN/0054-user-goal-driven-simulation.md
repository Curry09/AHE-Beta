---
number: "0054"
title: 用户模拟目标驱动与可修订目标账本
issue: 0
slug: user-goal-driven-simulation
summary: 为用户模拟增加显式、可修订且可审计的目标账本：以不可删除的 B0 保留原始任务身份，允许用户根据交互重新表述目标并记录理由；每轮通过目标感知、目标指向、预期进展和目标效果影响动作决策，但不把目标状态或主观 accept 冒充客观验收。
tasks:
  - id: T1
    title: 目标账本与修订事件模型
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/user/sim/goals.py
      - backend/tests/user/sim/test_goals.py
    scope: 定义 Goal、GoalLedger、GoalEvent、GoalStatus、GoalKind 以及 B0 初始化、add/status/focus/revise/relax/withdraw 操作；B0 不得删除或 withdraw，但允许带 reason 修订 text/done_if；每次修订保存 before/after、版本和 evidence_refs。
    acceptance: 任意任务初始化一个 B0；B0 的 initial_text/initial_done_if 永久保留；无 reason 或无实际变化的 revise 不生效；relax/withdraw 必须有 reason 且不能作用于 B0；事件 seq 连续；snapshot 与 audit 可独立还原当前状态和原始状态。
  - id: T2
    title: 目标进入用户感知与动作决策
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/user/sim/loop.py
      - backend/ahe_beta/user/sim/prompt.py
      - backend/ahe_beta/user/sim/persona_client.py
      - backend/tests/user/sim/test_loop.py
      - backend/tests/user/sim/test_persona_client_agentic.py
    scope: 将当前目标快照注入 judge/intent/act/waiting 决策上下文；各轮输出 goal_reading、target_goal_ids、expected_progress、goal_updates 和 goal_effect；目标改变时以结构化 revise 重新构造后续决策上下文，不用关键词推断用户是否应 accept。
    acceptance: 用户每轮能基于当前目标选择 send_message、keep_waiting、interrupt、accept 等动作；目标更新会影响后续 prompt；target_goal_ids 只能引用已知目标；动作/目标字段异常只产生可审计 warning，不把普通格式噪声改成 evaluator_invalid；B0 变化不会丢失原始任务。
  - id: T3
    title: 目标结果与主客观结论分离
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/models.py
      - backend/ahe_beta/user/session_store.py
      - backend/tests/test_models.py
      - backend/tests/user/test_session_store.py
    scope: 在 Session/SimTrace/SimTurn 中保存 goal ledger、goal acceptance 和每轮目标字段；goal terminal check 只报告用户主观目标是否闭合，不覆盖 interaction_status、objective_status 或 lifecycle_status。
    acceptance: 新字段 JSON 可往返序列化；旧 session 缺字段时安全读取为空/不可用；accept 与未闭合目标产生 subjective_accept_unverified 而不强行阻止用户动作；objective failed/unverified 与用户 accepted 可同时存在且可区分。
  - id: T4
    title: 时间线投影与目标账本完整审计
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/session_timeline.py
      - backend/tests/demand/test_session_timeline.py
    scope: 将目标摘要、目标变更事件、每轮 target/effect 和 goal_audit 投影到设计面 timeline；保留完整 sim_trace 作为权威落盘，但默认投影只提供有界、可读、带来源的目标证据，不提供完整 persona raw。
    acceptance: timeline 能区分 B0 初始文本、当前文本和每次 revision reason；每轮目标指向与动作可追溯到 turn；goal audit 能报告未知目标、effect mismatch、缺 reason 等问题；旧 timeline 无目标字段时保持兼容并标记 unavailable。
---

# 0054 · 用户模拟目标驱动与可修订目标账本

<!-- 本文件为用户目标机制的基础契约；需求面角色如何消费这些证据由 0055 定义。 -->

## Summary

用户模拟过去主要根据当前聊天内容和 harness 回复判断下一步动作。这样的机制有两个缺陷：

1. 用户到底想完成什么只能从自然语言中事后猜测；
2. 用户改变请求、等待、打断或接受时，没有稳定的决策依据。

本 spec 把“目标”作为用户模拟内部的显式状态，但不把它做成僵硬的任务清单。每局从原始任务初始化一个不可
删除的目标身份 `B0`；B0 的文字和完成条件可以根据用户的新理解修订，但每次修订都必须留下原因和 before/after。
每轮用户先在当前目标下形成感知和意图，再决定动作；动作结果和目标状态独立落盘。

```text
原始任务
  ↓ initialize B0
当前目标快照
  ↓ perceive / intent
target_goal_ids + expected_progress
  ↓ act / wait / interrupt / accept
goal_effect + optional goal_update
  ↓ append-only audit
```

这个机制是解释和记录用户行为的控制层，不是客观验收器，也不是强迫用户一定走到实现或 accept 的状态机。

## Motivation

旧机制的 `issue_artifact`、`verdict` 和 `action` 能记录用户说了什么以及最后做了什么，却不能稳定表达“用户认为
什么进展才算有价值”。结果是同一个 `accept` 既可能表示“核心需求真的满足”，也可能只是“我不想再等了”；
设计师和审计者只能从长段对话猜测。

直接增加硬规则也不是解决方案。若规定“目标没有证据就不能 accept”，用户模拟会被验收逻辑反向塑形，重新出现
过于保守、只做 toy 操作和大量提前退出的问题。目标机制应该让用户的决策更可解释，而不是替用户做技术裁决。

因此本 spec 选择三条原则：

- **原始目标可追溯**：B0 作为身份不可删除，避免改写历史后看不出用户最初要什么；
- **当前目标可演化**：用户可以在真实交互中重新理解和修订目标，但必须记录理由；
- **主客观分离**：用户目标闭合和主观 accept 是用户证据，代码是否通过由独立 evaluator 决定。

## Guide-level explanation

### B0 不是不可改变的任务锁

B0 的“不可删除”只针对身份和历史，不针对文字。初始任务是：

```json
{"goal_id": "B0", "text": "修复 apply_voi_lut 的问题", "status": "open"}
```

用户在交互中发现原 issue 过于模糊，可以修订为：

```json
{
  "op": "revise",
  "goal_id": "B0",
  "text": "修复 Rescale 元数据为空和损坏 LUTDescriptor 两个 bug，并补测试",
  "reason": "原始报告混合了问题咨询和实现请求，现在明确要交付补丁"
}
```

旧文本仍保留在 revision 事件中。修订不是自动放宽验收；它只是把用户当前真正要推进的目标说清楚。

### 每轮如何影响动作

每轮的最小决策链是：

1. `goal_reading`：用户根据当前观察判断目标是 unchanged、advancing、blocked、unclear 或 complete，并说明原因；
2. `target_goal_ids`：用户声明本轮想推进哪些目标；
3. `expected_progress`：用户认为哪种进展会改善这些目标；
4. `goal_updates`：若理解发生变化，带 reason 修订/新增/放松/撤回目标；
5. `goal_effect`：本轮动作对目标的效果是 advance、wait、close、close_with_reservations、abandon 或 abandon_and_report。

这些字段影响 persona 的下一轮上下文和动作选择，但不会替换动作契约。`keep_waiting` 仍然是等待，`interrupt`
仍然是打断，`accept` 仍然是用户主观接受；目标字段不能把一个动作伪装成另一个动作。

### 多目标与锚定风险

B0 是原始任务锚点，但不是唯一永远优先的内容。用户可以通过 `add` 创建 `G1/G2` 等 request/core/optional
目标，并用 `focus` 表明当前注意力；可以带理由 `relax` 或 `withdraw` 非 B0 目标。这样可以表达“先澄清问题、
再修复 bug、最后补测试”等自然转移。

为防止 B0 锚定：

- prompt 只反复放当前目标快照，不反复塞完整原始文本；
- 原始 B0 和 revision 历史只在审计/回放中完整保留；
- `focus_goal_id` 和 `target_goal_ids` 可以暂时指向新目标；
- B0 被修订时必须记录 reason，不允许静默覆盖。

## Reference-level explanation

### 数据模型

`GoalLedger` 保存当前目标集合和 append-only `GoalEvent`：

```text
Goal
  goal_id / text / kind / done_if / status / evidence_refs / version

GoalEvent
  seq / turn / op / goal_id / actor / reason / before / after / evidence_refs

GoalLedger
  baseline_id / focus_goal_id / goals / events
```

目标状态为 `open`、`partial`、`met`、`dropped`；目标类型为 `baseline`、`core`、`request`、`optional`。
正常 accept 的目标检查只把尚未闭合的 baseline/core/request 列为 unresolved；optional 目标不会阻止用户完成。

### 更新操作

| 操作 | 作用 | 限制 |
|---|---|---|
| `add` | 新增目标 | 必须有非空 text；重复 id 忽略 |
| `status` | 更新 open/partial/met | 保存 before/after 和 evidence |
| `focus` | 改变当前关注目标 | 目标必须存在 |
| `revise` | 修改 text/done_if 的含义 | 必须有 reason 且必须实际变化；B0 允许 |
| `relax` | 降低非 B0 目标要求 | 必须有 reason；可改 done_if |
| `withdraw` | 放弃非 B0 目标 | 必须有 reason；变为 dropped |

`relax` 与 `withdraw` 是可观察的用户取舍，不是框架替用户降低验收门槛。`B0` 永远存在，必要时只能 revise。

### 与用户模拟阶段的接线

目标快照进入 judge/intent/act 和 waiting 路径，但不同阶段的字段仍遵守阶段局部 schema：

```text
judge：读取当前目标，输出 goal_reading
intent：输出目标指向和 expected_progress，必要时提出 goal_update
act：输出 action、target_goal_ids、goal_effect，必要时提交 goal_update
waiting：基于当前目标决定 wait、interrupt 或继续沟通
terminal：记录 goal_acceptance，但不改写 objective evaluator
```

模型输出中缺失目标注释不应自动构造“已完成”结论。框架可以记录 warning 或使用空值兼容旧模型，但动作越权、
未知目标 id 和 revision 无理由等问题必须可审计。

### 目标接受与客观验收

目标账本提供 `terminal_check`，它回答“用户在自己的当前目标下是否认为目标已经闭合”，不回答“代码是否正确”。
因此以下组合都合法：

```text
user_goal_status = met
user_verdict = accepted
objective_status = failed
```

或：

```text
user_goal_status = partial
user_verdict = accepted_with_reservations
objective_status = passed
```

下游 triage/PM 可以使用这些组合解释用户体验，但不得把 `goal_acceptance` 当作 evaluator 结果。

### 持久化与审计

`SimTurn` 至少记录：

```text
goal_before
goal_reading
target_goal_ids
expected_progress
goal_updates
goal_after
goal_effect
goal_field_audit
```

`SimTrace` 和 `Session` 保存最终 `goal_ledger`、`goal_acceptance`、`goal_audit`。`goal_audit` 是观察性完整性检查，
报告缺失 B0、非法 focus、非连续 seq、未知目标、effect 与 target 不一致、revision 缺 reason 等问题；除动作越权
外，不把这些 annotation warning 直接变成 `evaluator_invalid`。

完整 raw persona trace 仍是事后调试权威，但后续设计角色使用的 timeline 只应投影有限目标证据。需求面角色的
分层可见性和 handoff 由 Spec-0055 约束。

## Rationale and alternatives

### 为什么要有不可删除的 B0

如果只保存当前目标，用户改口后原始任务会消失，审计者无法判断这是合理的需求澄清、用户被系统诱导，还是 persona
为了结束而降低了目标。B0 保留身份和 initial snapshot，使“目标改变”成为可检查事件。

### 为什么 B0 必须可修订

真实用户经常在看到仓库结构或助手反馈后才理解原问题。禁止修订会把真实澄清误判为偏离，迫使 persona 继续围绕
不再准确的文本行动。可修订不等于无约束：必须有 reason、before/after 和版本。

### 为什么不让目标直接成为硬验收门

硬门会把用户模拟变成“满足字段才能 accept”的测试脚本，重新制造假性保守和提前放弃。目标是显式决策依据，
而不是客观质量判定；objective evaluator 仍负责代码结果。

### 为什么不只保存最终目标

最终目标能解释当前动作，却解释不了用户为什么改目标。append-only revision 事件既保留用户当前自由度，也让
设计端知道目标漂移是否来自真实新信息、助手行为还是 persona 自我放宽。

### 备选方案

- **只把 goal 写进 prompt，不落盘**：不可审计，否决。
- **每轮复制完整目标历史到 prompt**：上下文线性膨胀，且会锚定用户，否决；prompt 只放当前快照，历史在 trace。
- **B0 永不可变**：无法表达自然的需求澄清，否决。
- **由框架根据聊天关键词自动判断目标完成**：会把语义猜测硬编码成验收，否决。
- **用目标状态覆盖 objective status**：会把主观 accept 伪装成技术通过，否决。

## Drawbacks

目标字段增加了每轮结构化输出和 trace 体积；模型可能给出空泛的 `expected_progress` 或无效 revision。缓解方式
是阶段局部 schema、确定性字段审计、固定长度投影和离线回放，而不是用关键词规则强行替模型完成认知。

B0 及其 revision 也可能让用户过度围绕原始任务，尤其是长期任务。prompt 只放当前快照、允许 focus/add/relax
非基线目标，并在 audit 中暴露 revision，降低锚定但不声称彻底消除。

## Prior art

本机制复用现有 user-sim 的 judge → intent → act 阶段和 Session.sim_trace 落盘；动作语义、客观 evaluator 与
生命周期的独立性沿用 Spec-0053；角色专属 artifact 和证据边界由 Spec-0043/0055 负责。这里新增的是用户目标
状态的语义与事件模型，而不是新的执行 runtime 或验收器。

## Validation plan

离线回放和真实小闭环至少验证：

1. 原始任务总能初始化 B0，B0 revision 后 initial_text 仍可恢复；
2. 用户可以从模糊目标转为明确请求，也可以在没有新信息时保持目标不变；
3. wait/interrupt/accept 的选择能引用目标和预期进展，但不被目标字段强制为某个动作；
4. 用户 accept 不覆盖 objective failed/unverified；
5. revision、focus、relax、withdraw 的原因和 before/after 都可追溯；
6. 旧 session 无 goal 字段时兼容读取并明确标记 unavailable；
7. 目标 trace 交给需求面角色后不会携带完整 persona raw 或目标项目答案。

## Unresolved questions

- 是否在未来把长期目标和当前目标拆成两个实体，还是继续以 B0 + 子目标表达；首版保持单 ledger，避免过早增加层级；
- `goal_reading` 是否继续由 persona 自报，还是在离线评测中增加独立观察者；首版保留自报，但不授予客观验收权；
- 目标字段的 L1 摘要上限由 Spec-0055 的真实 session 分布校准；不能删除 revision reason 来换 token。

## Future possibilities

积累足够的目标 revision 和用户行为后，可以统计“模糊 issue → 明确请求”的收敛率、目标变更触发原因、wait/interrupt
的目标推进率，以及主观 accept 与 objective evaluator 的分离矩阵。这些指标用于评估用户模拟和需求面质量，不应
反过来变成 prompt 中的固定计数或硬编码验收规则。
