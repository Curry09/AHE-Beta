---
number: "0016"
title: 设计师根因信号 + 读码效率 + 运行时聚合
issue: 0
slug: synthesizer-rootcause-signal
summary: 补上设计师的「为什么差」根因信号、机制层对照数字与读码效率：① 体感 reason 随分数落 index 并喂设计师；② search_file_content + 先搜后读；③ runtime_agg 事后扫最近 N 局 Session 聚合 0 步/超时/打断/错误占比与预算钮，注入 propose_once（只观测不归因）。落点 synthesizer/ + user/session_store.py + agent_defs/synthesizer/。
tasks:
  - id: T1
    title: 体感 reason 作根因信号喂设计师
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/demand/synthesizer.py
      - backend/auto_designer/user/session_store.py
      - backend/tests/loop/test_synthesizer.py
    scope: 补上设计师诊断根因所缺的定性信号。SessionStore：save() 写 index.json 时把 FeelingScore.reason（用户打分背后那句「为什么」）随 score/created_at 一起落库。synthesizer：_feeling_trend 从 index 读出 (created_at, score, reason) 三元组、_format_trend 把 reason 拼进体感曲线喂给设计师——分数只告诉「差」，reason 才告诉「差在哪」。尤其「延迟/等待本身」这类痛点（等很久才失败/半天没动静/等到弃坑）是体感杀手，且只会出现在 reason 里、绝不体现在分数高低上；设计师须据 reason 先判是 bug 还是 feature、再把需求动作给 dev，别把「延迟」误读成「没交付」而去加恢复逻辑（反面教材）。设计师站位是产品+架构：以为用户解决问题为前提，看体感（分数+reason）→ 分析根因 → 提需求给 dev。
    acceptance: SessionStore.save 后 index.json 每条含 reason 字段；_feeling_trend 返回含 reason 的三元组、_format_trend 输出把每个分数带上其 reason；设计师输入里能看到每轮分数对应的「为什么」。单测覆盖：index 落 reason、trend 读回三元组、格式化含 reason、缺省 reason 兼容。
  - id: T2
    title: 设计师 grep + 先搜后读，降低读码开销
    status: pending
    priority: P2
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/agent_defs/synthesizer/agent.yaml
      - backend/agent_defs/synthesizer/systemprompt.md
      - backend/agent_defs/synthesizer/tools/search_file_content.tool.yaml
    scope: 设计师此前无 shell、只能 read_file 整篇通读大文件（entry.py 数百行），瞬间烧光迭代预算（曾撞满 max-iter）。给它 search_file_content(grep) 工具，并在 systemprompt 立「先搜后读」纪律：entry.py 这类大文件先用 search_file_content 按关键词（如 timeout|retry|_CALL_TIMEOUT|_RUN_RETRIES|max_iter）跳到相关处，命中后只 read_file 那一段（带 offset/limit）精读；agents/main.md 通常短可直接读。读系统时先判根因在行为层（main.md）还是机制层（entry.py/agent.yaml），没读机制源码就别断言机制根因。search_file_content.tool.yaml 从 dev 工具定义复用。
    acceptance: synthesizer/agent.yaml 挂载 read_file/list_directory/search_file_content；systemprompt 含「先搜后读、别整篇通读」纪律与关键词示例；search_file_content.tool.yaml schema 合法可加载。模拟中设计师对大文件走 grep→精读而非整篇通读，不再因通读烧满迭代。
  - id: T3
    title: 运行时行为聚合 runtime_agg：机制层观测数字喂设计师
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/demand/runtime_agg.py
      - backend/tests/loop/test_runtime_agg.py
    scope: 补上设计师 prompt 宣称却从未注入的机制层对照数字。新增 synthesizer/runtime_agg.py：事后扫 SessionStore 最近 N 局（默认 50）的 harness 轮，聚合任务无关指标——0 步轮占比、timeout/interrupted/harness_error 回复占比、tool_error 步占比、中位 steps、以及 harness 仓预算钮（_CALL_TIMEOUT/_RUN_RETRIES/max_iterations，只读常量/配置、不 import harness）。format_runtime_agg 把 RuntimeAgg 拼成可读块；由 synthesizer.propose_once（归 T1 的 synthesizer.py）在体感曲线旁注入。只做观测聚合、不做归因（归因留给设计师读 reason）。不改 Session schema、不改协议、不碰用户侧模拟路径。
    acceptance: aggregate_runtime 对空仓返回零计数；有 sessions 时正确统计 0 步/timeout/interrupted/error/tool_error 与 median_steps；能从 harness 仓读出预算钮（缺省则 None）。format_runtime_agg 输出含占比与预算行。propose_once 输入含该块。单测覆盖：空仓、混合 reply 归类、预算解析、格式化。
---

# 0016 · 设计师根因信号 + 读码效率 + 运行时聚合

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

补上设计师诊断所需信号与读码效率：

1. **体感 reason**——随分数落 index，喂曲线（延迟类痛点只在 reason 里）；
2. **先搜后读**——`search_file_content` + 纪律，避免整篇烧迭代；
3. **runtime_agg**——事后扫最近 N 局 Session，聚合 0 步/超时/打断/错误占比、中位 steps、预算钮，注入 `propose_once`（**只观测、不归因**）。

落点 `synthesizer/` + `session_store` + `agent_defs/synthesizer/`。

## Motivation

只看分数会漏延迟根因、误提恢复逻辑；无 grep 会通读烧预算；prompt 宣称有「0 步占比/超时占比」却从未注入数字，reason 压成「又超时」时分不清失忆与预算太紧——故补 runtime_agg。

## Guide-level explanation

- 曲线带 reason；延迟先判根因再提需求。
- 大文件先搜后精读。
- 旁路一块**机制层对照数字**（runtime_agg），设计师自行归因。

## Reference-level explanation

### 代码锚点

- `session_store` index 含 reason；`synthesizer.py` trend + 注入 `format_runtime_agg(aggregate_runtime(...))`。
- `runtime_agg.py`：`RuntimeAgg`、最近 N=50、reply 粗标签、读仓内 `_CALL_TIMEOUT`/`_RUN_RETRIES`/`max_iterations`。
- synthesizer agent.yaml / systemprompt / search_file_content。

### 信号流

```
FeelingScore{score,reason} → index
Turn.steps + reply + 预算钮 → runtime_agg
        ↓
propose_once：曲线(reason) + 运行时块 → 判 bug/feature → 提需求
```

### DAG

```mermaid
graph LR
  T1[T1 reason 喂设计师]
  T2[T2 grep + 先搜后读]
  T3[T3 runtime_agg]
  T1 --> T3
```

### 文件分配

- **T1**：`synthesizer.py`、`session_store.py`、`test_synthesizer.py`（含 propose 注入调用点）
- **T2**：synthesizer agent 定义与 grep 工具
- **T3**：`runtime_agg.py`、`test_runtime_agg.py`

## Drawbacks

reason 噪声；runtime_agg 粗标签非任务语义；grep 仍依赖关键词选择。

## Rationale and alternatives

- 只看分数：延迟不可见。
- 结构化打标 reason：MVP 先喂原文。
- 不注入数字、靠 prompt 假装有指标：已证伪。

## Prior art

0005 FeelingScore；0012/0013 延迟与 steps 旁路。

## Unresolved questions

reason 是否打标；是否把等待序列结构化并入 agg。

## Future possibilities

看板展示 agg；按标签聚合痛点。
