---
number: "0024"
title: 用户 god-view 落盘 + 设计师按需取用
issue: 0
slug: designer-godview-timeline-tool
summary: Session.sim_trace 持久化用户模拟上帝视角；SessionStore index 带 issue_numbers；设计师经 get_session_timeline(issue|session_id) 按需取落盘原样 JSON；体感曲线带 session 句柄；jail 仍禁直接读 sessions/。脱敏加工与废弃 runtime_agg 另议。
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
      - backend/auto_designer/designer/designer.py
      - backend/tests/loop/test_designer.py
      - backend/tests/user/test_session_store.py
    scope: SessionStore.save 写 index.issue_numbers；_feeling_trend/_format_trend 输出 [session=…] 句柄，供设计师跟体感点查 timeline。
    acceptance: 新 index 条目含 issue_numbers；propose_once 任务消息体感行含 session=；单测覆盖 trend 四元组。
  - id: T3
    title: get_session_timeline tool（落盘原样）
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/designer/session_timeline.py
      - backend/agent_defs/designer/agent.yaml
      - backend/agent_defs/designer/tools/get_session_timeline.tool.yaml
      - backend/agent_defs/designer/systemprompt.md
      - backend/tests/designer/test_session_timeline.py
    scope: 新增 session_timeline：bind_session_store + get_session_timeline(issue_number|session_id) 返回 feeling/issue_refs/sim_trace 原样 JSON；Designer._run_agent 注入 store；agent.yaml 挂 tool；prompt 说明按需调用、禁直接读 sessions/。暂不做脱敏。
    acceptance: 按 issue/session_id 可取回与落盘一致的 sim_trace 字段；未绑定 store/找不到返回 ok=false；jail 仍拒读 sessions；单测绿。
---

# 0024 · 用户 god-view 落盘 + 设计师按需取用

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

把用户模拟的**上帝视角**（perceive / verdict / action、等待决策、persona LLM 调用链等）随 `Session` **完整落盘**为 `sim_trace`；设计师侧**不**在首轮 prompt 整包注入，而是经工具 `get_session_timeline(issue_number | session_id)` **按需**取回落盘原样 JSON。体感曲线条目附带 `session_id` 句柄，便于从分数点下钻。Jail（0015）继续禁止直接读 `sessions/`。本组**不做脱敏加工**；与既有间接信号（体感 / issue / `runtime_agg`）的并存策略见 Rationale。

## Motivation

设计师当前入口信号主要是三样（0016 等既有路径）：

1. **open issue 积压**：`propose_once` 开局调用 `tracker.list_open_issues()`，把**当前所有未关闭 issue**（含 design / bug / feature 等标签）格式化进首轮任务消息；设计师据此找跨票结构性根因并提提案，**不是**一次只领一条。
2. **体感曲线**：历轮 score + reason（短「为什么」）。
3. **`runtime_agg`**：最近 N 局机制层计数（0 步 / 超时 / 打断等），只观测不归因。

这些是**结果与机制摘要**，看不到「用户为何等、何时放弃、内心评价与外显话术如何错位」——而后者正是发现 harness **问题与潜在需求**的过程证据。

若把完整 god-view 塞进首轮 prompt：token 爆、强迫读全库、与「每轮一次 `propose_once`、全量 backlog」的激活模型冲突。若只落盘不给通路：jail 挡住 `sessions/`，设计师永远摸不到。需要「**全量持久化 + 按需工具取用**」。

## Guide-level explanation

**对用户模拟 / 编排**

1. 每局结束后，`Session` 除对话 `transcript`、feeling、issue_refs 外，多写 `sim_trace`（由内存 `TurnLog` 映射；心路与当时对话片段同条共置）。
2. `SessionStore` 的 `index.json` 条目增加 `issue_numbers`，便于按 issue 反查 session。

**对设计师**

1. `propose_once` 首轮仍只给：open issue 积压（定义见 Motivation）+ 体感曲线（带 `[session=…]`）+（若有）`runtime_agg` 摘要。
2. 需要过程证据时，调用 `get_session_timeline`：
   - `issue_number=N` → 取「含该 issue 的最新一局」；
   - 或 `session_id=…` → 直取该局。
3. 返回 JSON：`session_id` / `feeling` / `issue_refs` / `sim_trace`（与落盘字段对齐，本组为原样透传）。
4. 禁止用 `read_file` / `list_directory` 扫 `sessions/`（jail 仍生效）。

**与「间接 session 数据」的关系（产品结论）**

| 信号 | 本组态度 | 理由 |
| --- | --- | --- |
| open issue 积压（`list_open_issues` 全量） | **保留** | 设计师选题入口；开发者仍按单票 1:1 领取，分工不变 |
| 体感曲线（score+reason+session 句柄） | **保留并增强句柄** | 入口筛选「哪几局值得下钻」；reason 仍是短摘要 |
| `runtime_agg`（0016） | **本组不废弃** | 机制层计数（等待/放弃等），与定性 god-view **正交**；是否改注入形态另开议题 |
| 直接读 `sessions/` | **继续禁止** | 0015 jail；统一走 timeline tool |

「间接」指的是：设计师默认不吃 raw 轨迹，靠积压 + 体感 + agg 进场；god-view 是**可选下钻**，不是替换上述入口。

## Reference-level explanation

### Task DAG

`T1`（落盘 schema + 采集）→ `T2`（index `issue_numbers` + 体感句柄）→ `T3`（tool + agent 接线）。文件集互不相交。实现已落主路径；本组为与代码对齐的活快照。

### 数据模型

- `PersonaCallTrace`：单次 persona LLM 调用（role / system / user / response / …）。
- `SimTurn`：单拍 god-view（elapsed / phase / perceive / verdict / action / harness_output / persona_trace / …）。
- `SimTrace`：`turns: list[SimTurn]` + 可选 `persona_tail`（rate / file_issue 等局尾调用）。
- `Session.sim_trace: SimTrace | None`；旧 JSON 缺字段 → `None`。

### 采集路径

- `persona_client` 记录每次调用 → `run_session` 打 role 标签写入 `TurnLog.persona_trace` / `persona_tail`。
- `loop/sim_user.result_to_sim_trace`：`TurnLog` → `SimTrace`，写入 `Session` 后 `store.save`。

### 索引与体感句柄

- `SessionStore.save`：index 条目写 `issue_numbers`（来自 `session.issue_refs`）。
- `Designer._feeling_trend` / `_format_trend`：每行附 `[session=<id>]`。

### 工具

- 模块：`backend/auto_designer/designer/session_timeline.py`
  - `bind_session_store(store)`（`Designer._run_agent` 入口注入）
  - `get_session_timeline(issue_number=… | session_id=…)` → JSON 字符串
  - `format_session_timeline`：本组 = **passthrough**（字段原样序列化；不做 scrub / 抽象卡）
- Agent：`agent_defs/designer/tools/get_session_timeline.tool.yaml` + `agent.yaml` 注册；`systemprompt.md` 写调用约定。

### 边界（本组不做）

- 不对 `sim_trace` 做脱敏、摘要卡、跨局聚合 story。
- 不改设计师激活模型（仍每轮一次、全量 backlog）。
- 不删 `runtime_agg`、不改 0016 注入文案（除非后续单独决策）。

## Drawbacks

- 落盘体积显著增大（含完整 persona prompt/response）；磁盘与备份成本上升。
- 原样透传可能把超长轨迹直接塞进设计师上下文，依赖模型自律「按需、少次调用」。
- index 仅「按 issue → 最新含该号的 session」；一局多 issue、或同 issue 多局历史，需靠 `session_id` 或后续查询语义扩展。

## Rationale and alternatives

- **落盘全量 vs 只存摘要**：全量可事后改加工策略；摘要一旦丢细节无法回放。选全量落盘 + 工具侧再决定加工（本组工具侧暂 passthrough）。
- **工具下钻 vs 首轮注入**：与「设计师看全积压再选题」一致；避免强制吞全库。
- **透传 vs 脱敏**：产品暂不脱敏，优先保真；脱敏作为 Future。
- **是否废弃 `runtime_agg`**：**否（本组）**。它回答「机制上发生了多少次等待/放弃」，god-view 回答「那一次心里在想什么」；入口仍要轻量信号。若实测设计师只用 timeline 而从不看 agg，再开小组决定降级为看板-only 或删除注入——不在本组砍。

备选曾考虑：sidecar 文件、按 turn 分页 API、自动对低分 session 预注入——均增加面，MVP 不取。

## Prior art

- 0015：设计师 sandbox / jail（禁读 sessions 等）。
- 0016：体感 reason + `runtime_agg` 进设计师上下文。
- 0022 / 0023：用户模拟 IO 与事件驱动等待（god-view 字段语义来源）。
- 设计师 / 开发者分工：设计师每轮 `propose_once` 看全 backlog；开发者按 issue 1:1。

## Unresolved questions

1. **脱敏与加工**：何时从 passthrough 改为 scrub / 故事卡？字段白名单与长度上限？
2. **`runtime_agg` 去留**：是否在设计师 prompt 中降级或移除，仅保留观测看板？（本组明确**不砍**，留观测后再定。）
3. **多 session / 同 issue**：`issue_number` 查询是否要支持「列出全部相关 session」而非仅最新一局？

## Future possibilities

- `format_session_timeline` 增加脱敏层或「设计师可读摘要卡」，落盘仍保留 raw。
- 跨局聚合：按 gap / 放弃模式聚类，生成 harness 问题假设列表。
- 看板只读 API 复用同一 timeline 格式，供人眼调试。
- 若 token 压力大：工具支持 `turns` 切片或 `fields=` 投影。
