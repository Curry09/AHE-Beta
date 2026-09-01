---
number: "0024"
title: 用户 god-view 落盘 + 设计师按需取用
issue: 0
slug: designer-godview-timeline-tool
summary: Session.sim_trace 全量落盘上帝视角；设计师按需取证三层——使用事件时间线投影（get_session_timeline，含 utterance↔answers 请求-回复配对）→ 拍级 harness 活动（get_harness_beat）→ 单步展开（get_harness_step）；体感曲线带 session 句柄；jail 仍禁直接读 sessions/。runtime_agg 本组不废弃。
tasks:
  - id: T1
    title: Session.sim_trace 落盘（TurnLog→SimTrace）
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/models.py
      - backend/auto_designer/loop/sim_user.py
      - backend/auto_designer/user/sim/loop.py
      - backend/auto_designer/user/sim/persona_client.py
      - backend/tests/test_models.py
      - backend/tests/loop/test_sim_user.py
    scope: Session 增可选 sim_trace（SimTurn/SimTrace/PersonaCallTrace）；run_session 采集 persona_trace/persona_tail；sim_user.result_to_sim_trace 落盘。旧 JSON 无该字段兼容 None。
    acceptance: 新局 Session JSON 含 sim_trace.turns（含 perceive/verdict/action/harness_output/persona_trace）；旧 session from_dict 得 sim_trace=None；相关单测绿。
  - id: T2
    title: index 扩 issue_numbers + 体感曲线带 session_id
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/user/session_store.py
      - backend/tests/loop/test_designer.py
      - backend/tests/user/test_session_store.py
    scope: SessionStore.save 写 index.issue_numbers；_feeling_trend/_format_trend 输出 [session=…] 句柄，供设计师跟体感点查 timeline。（feeling 格式化实现现随 designer.py，归 T5 文件集。）
    acceptance: 新 index 条目含 issue_numbers；propose_once 任务消息体感行含 session=；单测覆盖 trend 四元组。
  - id: T3
    title: get_session_timeline tool 入口（按需取证通路）
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files: []
    scope: 引入 get_session_timeline(issue|session_id) 与 bind_session_store，打通 jail 下的按需取证通路。 初版工具输出曾为落盘原样透传；现行输出形态由 T4 投影、T5 注册 beat/step 承接（文件归属见 T4/T5，本 Task 保留 DAG 节点）。
    acceptance: 设计师可经 tool（而非读 sessions/）取到一局过程证据；未绑定 store/找不到返回 ok=false；jail 仍拒读 sessions。
  - id: T4
    title: get_session_timeline 使用事件投影（去仿真外壳）
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/designer/session_timeline.py
      - backend/agent_defs/designer/tools/get_session_timeline.tool.yaml
      - backend/tests/designer/test_session_timeline.py
    scope: format_session_timeline 从 passthrough 改为使用事件投影：保留 wanted/process_read/capability_gap（仅不对齐时附 available）/saw_activity/private_check/silent_stop/feeling/issue；去掉 system/user/raw、persona_id、常驻 action_space、patience/trust、role 名、tracker URL、stdout 全量。落盘 Session.sim_trace 仍全量权威。同模块实现 get_harness_beat/get_harness_step 的投影函数（tool 注册见 T5）。
    acceptance: format_session_timeline 输出无 LLM system/user/raw 与 persona_id；capability_gap 仅在 gap 时出现且含 available；beat/step 函数可按 turn/step_i 返回 stop_kind 与截断/展开正文；单测覆盖投影剥离、beat 分类、step 展开。
  - id: T5
    title: 设计师渐进下钻 tool 接线（beat/step）
    status: done
    priority: P1
    tags: []
    depends-on:
      - T4
    relates-to: []
    parallel: false
    files:
      - backend/agent_defs/designer/tools/get_harness_beat.tool.yaml
      - backend/agent_defs/designer/tools/get_harness_step.tool.yaml
      - backend/agent_defs/designer/agent.yaml
      - backend/agent_defs/designer/systemprompt.md
      - backend/auto_designer/designer/designer.py
    scope: 注册 get_harness_beat / get_harness_step；systemprompt 与 propose_once 任务文案约定渐进用法：先 get_session_timeline → 必要时 get_harness_beat(turn) → truncated 且确需时 get_harness_step(step_i)。jail 仍禁直接读 sessions/。
    acceptance: agent.yaml 含两 tool binding；prompt/任务文案写明三层取证；设计师可在 propose_once 中按需调用（探针可观测）；不要求默认每拍都下钻。
  - id: T6
    title: 请求-回复配对：heard.answers → utterance
    status: done
    priority: P1
    tags: []
    depends-on:
      - T5
    relates-to: []
    parallel: false
    files:
      - backend/tests/user/sim/test_heartbeat.py
    scope: >-
      为每条用户→harness 外发指令分配 utterance_id；begin 开启的为当前 open；等待中 emit/send_message
      标 delivery=queued + queued_behind=open；收到的 harness_output/heard 写 answers_utterance_id（及 answers_said 预览）。
      不改 harness 线协议。实现落在既有 T1/T4/T5 文件集（loop/models/session_timeline/systemprompt/tool yaml）；
      本组 files 只列新增占用的心跳单测。时间线与设计师 prompt 必须一眼能对上「这条 reply 答的是哪句」。
    acceptance: 新局 sim_trace/timeline：外发有 utterance；queued 插话带 queued_behind；heard 带 answers 指向对应 utterance；插话后仍先收到的 reply 的 answers 指向 begin 那条而非插话；旧 session 缺字段兼容；单测覆盖配对与投影。
---

# 0024 · 用户 god-view 落盘 + 设计师按需取用

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

把用户模拟的**上帝视角**随 `Session` **完整落盘**为 `sim_trace`（权威 raw，含 persona LLM 原片，供事后调试）。设计师**不**在首轮 prompt 整包注入，而是经工具**按需、渐进**取证：

1. `get_session_timeline` → **使用事件时间线投影**（意图/过程判断/能力缺口/私有核实；私有核实来自 persona 内层 tool steps，而非外层 `verify_self`；**`utterance`↔`answers` 请求–回复配对**；无 system/user/raw）；
2. `<private_evidence>` → 用户模拟自身的跨轮私有证据记忆（同样源自 persona 内层 tool steps，但只给后续 user-sim prompt，不是 timeline raw dump）；
3. `get_harness_beat(turn)` → 对准某一拍看 harness 内层 tool 序列（正文短切）与 `stop_kind`；
4. `get_harness_step(step_i)` → 单步展开（硬顶字符）。

体感曲线带 `[session=…]` 句柄。Jail（0015）继续禁止直接读 `sessions/`。`runtime_agg` 本组不废弃。

## Motivation

设计师入口信号（0016 等）主要是 open issue 积压、体感曲线、`runtime_agg`——这些是**结果与机制摘要**，看不到「用户为何等、何时放弃、内心评价与外显话术如何错位」，也难区分「撞 max_iterations」与「撞墙钟超时」时预算烧在探索还是交付前一刻。

若把完整 god-view / 全量 harness_steps 塞进首轮 prompt：token 爆（实测原样三局可至数十万 token）。若只落盘不给通路：jail 挡住 `sessions/`。需要「**全量持久化 + 工具侧投影与渐进下钻**」。

## Guide-level explanation

**对用户模拟 / 编排**

1. 每局结束后，`Session` 除对话 `transcript`、feeling、issue_refs 外，多写全量 `sim_trace`。
2. `SessionStore` 的 `index.json` 条目含 `issue_numbers`，便于按 issue 反查 session。

**对设计师（渐进取证）**

1. `propose_once` 首轮仍只给：open issue 积压 + 体感曲线（带 `[session=…]`）+（若有）`runtime_agg`。
2. 需要过程证据时：
   - `get_session_timeline(issue_number|session_id)` → 使用事件时间线（投影）；
   - 某拍 `heard` 为超时/上限或 `saw_activity` 过粗 → `get_harness_beat(turn=…)`；
   - 某步 `truncated=true` 且确需正文 → `get_harness_step(turn=…, step_i=…)`（仍有硬顶，勿把大段 stdout 写进提案）。
3. 禁止用 `read_file` / `list_directory` 扫 `sessions/`（jail 仍生效）。

**与「间接 session 数据」的关系**

| 信号 | 本组态度 | 理由 |
| --- | --- | --- |
| open issue 积压 | **保留** | 设计师选题入口 |
| 体感曲线（+session 句柄） | **保留** | 筛选「哪几局值得下钻」 |
| `runtime_agg` | **本组不废弃** | 与定性过程证据正交 |
| 直接读 `sessions/` | **继续禁止** | 0015 jail；统一走 tool |

## Reference-level explanation

### Task DAG

`T1`（落盘）→ `T2`（index + 体感句柄）→ `T3`（tool 通路节点）→ `T4`（投影 + beat/step 函数）→ `T5`（beat/step 注册与 prompt）→ `T6`（utterance↔answers 配对）。

### 数据模型（落盘权威）

| 类型 | 要点 |
| --- | --- |
| `PersonaCallTrace` | 单次 persona LLM 调用：role / system / user / raw / parsed / steps |
| `SimTurn` | 单拍：turn / phase / perceive / action / message / harness_output / harness_steps / persona_trace；T6 增 `utterance_id` / `delivery` / `queued_behind` / `answers_utterance_id` / `answers_said` |
| `SimTrace` | `turns` + 可选 `persona_tail`（rate / file_issue）+ `end_reason` / `signals` |
| `Session.sim_trace` | 全量落盘；旧 JSON 缺字段 → `None` / 空串 |

采集：`persona_client` → `run_session` 打 role → `sim_user.result_to_sim_trace` → `SessionStore.save`。

### 请求–回复配对（T6）

不改 harness 线协议。sim 侧 `_UtteranceLedger`：

| 时机 | 落盘 |
| --- | --- |
| 主环 EMIT 外发（begin） | `utterance_id=uN`，`delivery=open` |
| 等待中 `send_message` / emit | 新 `utterance_id`，`delivery=queued`，`queued_behind=<当前 open>` |
| 收到 reply / interrupt 回执 | 下一拍带 `harness_output` 的 Turn 写 `answers_utterance_id` + `answers_said`（关闭的那条 open） |

时间线投影：`utterance` / `delivery` / `queued_behind` / `answers` / `answers_said`。插话 `queued` 后先到的 reply，`answers` 仍指向当时的 open（begin 那条），而非插话。

### 使用事件投影（T4 · `format_session_timeline`）

顶层 JSON：`session_id` / `started_at` / `feeling` / `issues[{number,state}]` / `timeline{end_reason,events[]}`。

每条 `events[]` 常用字段：

| 字段 | 含义 | 何时出现 |
| --- | --- | --- |
| `t` | `SimTurn.turn`（无墙钟时用序号保序） | 回合事件 |
| `when` | `opening` / `during_wait` / `after_reply` / `closing` | 由 phase 映射 |
| `thought` | 清洗后的人话观察（去掉 `[judgment\|intent→action]` 头） | perceive 非空 |
| `process_read` | on_track / off_track / unclear | waiting 判断存在时 |
| `wanted` | 收敛前自由 intent | parsed.intent 非空 |
| `did` / `said` | 最终动作 / 发出的消息 | 有则写 |
| `utterance` | 本拍外发指令 id（`uN`） | EMIT 有正文 |
| `delivery` / `queued_behind` | `open` 或 `queued`（及排在哪条 open 后） | T6；queued 仅等待插话 |
| `heard` | harness 终态回复（限长） | harness_output 非空 |
| `answers` / `answers_said` | 本条 heard 关闭的 utterance + 预览 | T6；有 heard 且可配对时 |
| `saw_activity` | 活动条短标题（略过 tool_result 正文，最多末 8 条 tool） | 有 harness_steps |
| `capability_gap` | `{wanted,did,available,note}` | 仅 `parsed.gap==true` |
| `private_check` | 用户本机核实 steps（截断） | persona_trace 中出现 private tool/tool_result/tool_error；不依赖外层 `verify_self` |
| `silent_stop` | `true` | `did==interrupt` |
| `issue_text` / `feeling` | 局末出口 | persona_tail |

**刻意不投影**：system/user/raw、persona_id、常驻 action_space 全表、patience/trust、waiting_* role 名、fake:// URL、stdout 全量、机器信号串原样甩出。

`private_check` 与 `<private_evidence>` 源头相同但用途不同：前者是 timeline 给设计师/审计看的使用事件投影；后者是 user-sim 自己的会话内记忆，格式为 `[E# phase/stage] Private tools ... Conclusion/Observed ...`，会回灌到后续 main/waiting 的 judge/intent/act prompt。二者都不得包含完整 stdout/文件全文或 benchmark oracle；完整 raw 仍只在 `Session.sim_trace.persona_trace.steps` 中保存。

### 渐进下钻契约

**解析会话**（三 tool 共用）：`session_id` 优先，否则 `issue_number` → index.`issue_numbers` 反查，旧 index 回落扫盘；未绑定 store / 找不到 → `{ok:false,error}`。

#### `get_session_timeline`

- 入参：`issue_number?` | `session_id?`
- 出参：`{ok, session_id, timeline}`，`timeline` 为投影 JSON 字符串

#### `get_harness_beat`（T4 函数 + T5 接线）

- 入参：`turn`（必填，= 时间线 `t`）、`occurrence?`（同 turn 多拍时，默认 0；优先带 harness 输出/步骤的候选）
- 出参要点：`when` / `user_did` / `heard` / `stop_kind` / `steps[{i,kind,text,truncated?}]` / `n_steps_raw`
- `steps`：tool 标题约 220 字、result/assistant 约 280 字；超过约 80 步则头 20 + 尾部，中间 `omitted`
- **`stop_kind` ↔ harness 一级钮**（归因用，勿绑具体 SWE 任务）：

| stop_kind | 典型 heard | 对照源码 |
| --- | --- | --- |
| `max_iterations` | `Maximum iteration limit reached` | `agent.yaml` → `max_iterations` |
| `wall_timeout` | 历史 `[timeout]` / 基础设施上限 | 旧 harness deadline / launcher 绝对上限 |
| `interrupt` | `[interrupted]…` | 用户侧 interrupt / control |
| `completed` | 正常交付文案 | — |
| `empty` | 无 harness_output | 等待拍等 |

#### `get_harness_step`

- 入参：`turn` + `step_i`（= beat 的 `steps[].i`，即 raw `harness_steps` 下标）+ 同上 session 选择
- 出参：`text`（保留换行）、`n_chars_raw` / `n_chars_returned` / `truncated`；硬顶现行 **6000** 字符
- 用途：仅当 beat 中 `truncated=true` 且设计师判断该步正文仍关键；提案中仍禁焊大段 stdout

### 接线与注入（T5）

- `agent_defs/designer/agent.yaml`：注册 timeline / beat / step
- `systemprompt.md` + `Designer._run_agent` 任务文案：约定「先时间线 → 再拍 → 必要时步」
- `bind_session_store`：`ContextVar` + 模块级 `_STORE_FALLBACK`（nexau 工具回调常在别线程）
- `SANDBOX_WORK_DIR`：设计师跑时指向 harness 仓**绝对路径**（读源码 grounding）

### 验证信号（非验收门禁，供对照）

SWE-bench_Verified 真仓探针上，设计师可观测到：先读 `entry.py`/`agent.yaml`，再对 6 局 `get_session_timeline`，再对超时拍 `get_harness_beat`（`stop_kind` 区分 iteration vs wall）；`get_harness_step` 非必须（beat 已够归因时可不开）。

### 边界（本组仍不做）

- 不改设计师激活模型（仍每轮一次、全量 backlog）。
- 不删 `runtime_agg`。
- 不提供无限 raw 日志下载；硬顶后再截断只作「过大」信号。
- 用户 sim 提示去软诱导、SWE-bench 探针脚本：本组文件集之外，不纳入本 Task。

## Drawbacks

- 落盘体积仍大（全量 raw）；工具侧已控注入体积，磁盘成本仍在。
- 投影丢细节的风险：靠 beat/step 补；若设计师从不下钻，可能漏「烧在哪次 tool」。
- `issue_number` 仍指向「含该号的最新一局」；多局历史靠 `session_id`。
- 三层 tool 增加选择负担；靠 prompt 约束「默认够用就停」，依赖模型自律。

## Rationale and alternatives

- **落盘全量 vs 只存摘要**：全量可事后改加工；选全量落盘 + 工具侧投影（取代初版 passthrough）。
- **工具下钻 vs 首轮注入**：与「看全积压再选题」一致。
- **一层 timeline vs 三层渐进**：一层要么过粗要么过胖；三层默认粗、按需细。实测设计师会 timeline→beat，step 仅在正文仍关键时开。
- **扩 0024 vs 新开 0025**：同属「god-view 落盘 + 按需取证」问题面；0024 Future 已预告投影；故 `add-task` 进本组而非新号。
- **是否废弃 `runtime_agg`**：**否（本组）**。

备选曾考虑：sidecar、按 turn 分页 API、自动预注入低分 session——MVP 不取。

## Prior art

- 0015：设计师 jail。
- 0016：体感 reason + `runtime_agg`。
- 0022 / 0023：用户模拟 IO 与事件驱动等待（god-view 字段语义）。
- 本组初版 T3 passthrough：因上下文爆炸改为 T4 投影（活快照演进）。

## Unresolved questions

1. **step 硬顶与二次截断**：6000 是否合适？是否需要 `offset/limit` 分段读超长 stdout？
2. **`runtime_agg` 去留**：是否在设计师 prompt 中降级为看板-only？（本组仍不砍。）
3. **多 session / 同 issue**：是否支持列出全部相关 session？
4. **beat 步型标注**：是否在 beat 层直接标「探索/编辑/测试」占比，进一步减少 step 展开？

## Future possibilities

- beat 返回结构化「探索 vs 验证」步型占比。
- 跨局聚合：按 `stop_kind` / gap 模式聚类，生成 harness 问题假设列表。
- 看板只读 API 复用同一 timeline / beat 格式。
- step 支持字节偏移分页（仅当硬顶实测不够）。
