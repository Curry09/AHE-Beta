---
number: "0018"
title: 设计师提案拆信封：complete_task 交付不再被静默丢弃
issue: 0
slug: designer-proposal-envelope
summary: '设计师用 complete_task 交回提案时，nexau 把结果套进 tool 信封（{success,status,output:{result:"[...]"}}），而 _parse_proposals 的平衡括号扫描刻意不进字符串内部，扫不到顶层数组 → 静默返回「本轮无提案」。实测 8 轮长跑 6 条结构性提案 0 条进 backlog；且该缺陷非确定性——agent 听话调 complete_task 就被丢，不听话直接吐裸数组反而入库（第 6 轮侥幸入库的 #6/#7/#8 使 dev 立刻去改 entry.py 与 tools/，证明结构性进化通道本身是通的、只是被这里堵死）。落点：designer/_run_agent 出口拆信封 + 单测覆盖两条路径（带信封 / 裸数组）。'
tasks:
  - id: T1
    title: _run_agent 出口拆 complete_task 信封
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/designer/designer.py
      - backend/tests/loop/test_designer.py
    scope: designer/_run_agent 拿到 agent.run() 返回值后先拆 nexau 的 complete_task 信封再交给 _parse_proposals：新增 _unwrap_result()——把形如 {success,status,output:{result:<str|list>}} 的信封剥到 output.result（result 已是数组/对象则 json.dumps 回字符串，是字符串则原样透传）；非信封（裸 JSON 数组 / 散文 / 非 JSON）一律原样返回，不改既有行为。_parse_proposals 的平衡括号扫描保持不动（它拒进字符串内部是对的设计，不该为了兼容信封而放宽）。堵住「agent 听话用 complete_task 交付反而被丢」的反向激励。
    acceptance: 带信封的返回（output.result 为 JSON 数组字符串）能解析出提案；裸 JSON 数组、json 围栏代码块、散文夹数组三条既有路径行为不变；信封里 result 为空数组 → 0 条提案（而非报错）；畸形/非 JSON 信封回落原文、不抛错。单测覆盖以上五条；用 8 轮长跑里真实的 detail 原文作回归夹具。
---

# 0018 · 设计师提案拆信封：complete_task 交付不再被静默丢弃

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

设计师**产出了**结构性提案，但提案在解析层被**静默丢弃**：nexau 的 `complete_task` 把结果套进
tool 信封（`{success, status, output:{result:"[...]"}}`），真正的 JSON 数组成了信封里的一个**字符串**；
而 `_parse_proposals` 的平衡括号扫描**刻意不进字符串内部**，于是扫不到顶层数组 → 返回 `[]` → 记为
「本轮无结构性提案」。本组在 `_run_agent` 出口加一层拆信封（T1），把这条通道接回去。

## Motivation

**这不是一个观测瑕疵，是整个实验前提的失效。**

设计流程本设计为「用户产 bug → 设计师从 bug 里提炼跨 issue 的结构性根因 → 开发者据此做机制改动」。
中间一环断了，闭环退化成「用户产 bug → 开发者打补丁式改 prompt」——正是长跑里实际观察到、
且与「自进化出新工具 / 新编排」预期相悖的那个结果。

实测证据（8 轮长跑，真模型 + 真 Gitea）：

- 前 5 轮设计师每轮都显示「本轮无结构性提案」，Gitea 里 **0 条 `design` 标签 issue**；
- 从 `data/live/history.json` 的 designer 归档 `detail` 里，**能把提案原文拆出来**——它们一直都在：

  ```
  Designer._parse_proposals(detail)  →  []                                   # 现状：丢光
  拆掉信封后再解析                     →  ['缺少面向小任务的延迟预算与验证强度控制']    # 提案其实在
  ```

- 代价可度量：**6 条结构性提案 → 0 条进入 backlog**。

### 这个 bug 是非确定性的，且**惩罚正确行为**

第 6 轮的提案**成功入库**了（issue #6/#7/#8）。差别只在于 agent 那一轮**有没有真的去调
`complete_task`**：

| 轮 | designer 返回 | 结果 |
| --- | --- | --- |
| 1–5 | `{"success": true, "status": "TASK_COMPLETED", "output": {"result": "[...]"}}`（**信封**） | 解析失败，6 条全丢 |
| 6 | `[ { "title": "首轮预算拖垮可用交付", ... } ]`（**裸数组**） | 解析成功 → #6/#7/#8 |

即：**agent 听 prompt 的话用 `complete_task` 交付，提案反而被丢；不听话直接吐数组，反而入库。**
能否进 backlog 取决于模型当轮的随机选择——这是一个反向激励，必须堵掉。

### 通道打通后，开发者行为立刻改变（因果直接可证）

| commit | 来源 issue | 改了什么 |
| --- | --- | --- |
| `fix: issue #2~#5` | 用户 bug | 只改 `agents/main.md`（prompt）+ 断言 prompt 内容的水测试 |
| **`fix: issue #6`** | **design 提案** | **`entry.py` +63 行（机制本体）** + MANUAL + 41 行真测试 |
| **`fix: issue #7`** | **design 提案** | **`tools/complete_task.tool.yaml`（工具定义）** + prompt + MANUAL + 测试 |

**开发者不是不会做机制改动，是之前压根没收到过机制类任务。** 结构性进化通道本身是通的，只是被这里堵死。

## Guide-level explanation

`_run_agent` 现在在把文本交给 `_parse_proposals` 之前，先过一道 `_unwrap_result()`：

- 返回值若是 `complete_task` 信封 → 剥到 `output.result`（提案数组的原文）；
- 返回值若是**裸 JSON 数组 / ```json 围栏 / 散文夹数组** → **原样透传**，行为一字不变。

对设计师 agent 来说没有任何行为要求变化：它照旧被要求用 `complete_task` 交回一个 JSON 数组。
区别只是——现在它**照做也能成功**。

## Reference-level explanation

**DAG**：单 Task，无依赖。

**T1**（`designer.py` + `test_designer.py`）：

```python
def _unwrap_result(out: object) -> str:
    """拆 nexau complete_task 信封 → output.result；非信封原样返回。"""
```

- 输入非 `str` → `str(out)`（保持既有兜底）；
- 尝试 `json.loads`；不是 JSON、或不是 dict、或没有 `output.result` → **原样返回原文**；
- `output.result` 是 `str` → 直接返回；是 `list`/`dict` → `json.dumps` 回字符串（agent 有时把数组
  直接放进 result 而非其字符串形式，两种都要接）。

**`_parse_proposals` 不动**。它「尊重字符串转义、拒进字符串内部」的平衡括号扫描是**对的设计**
（防被散文里的 `[]` 带偏），不该为了兼容信封而放宽——那会把一个正确的解析器改成一个宽松的解析器，
用错误的地方修错误。信封该在**信封层**拆。

**测试**（`test_designer.py`）覆盖五条：带信封（result 为数组字符串）、带信封（result 为数组本体）、
裸数组、围栏代码块、畸形信封回落原文不抛错；并用 8 轮长跑里**真实的 detail 原文**作回归夹具。

## Drawbacks

- 多一层解析。但成本极小（一次 `json.loads` try），且失败即回落原文，不改变既有路径。
- 信封形状由 nexau 决定，nexau 若改信封 schema，此处需跟进。已用「取不到就回落原文」把风险降为
  「退回今天的行为」而非「炸」。

## Rationale and alternatives

1. **放宽 `_parse_proposals` 的扫描，让它进字符串内部找数组** —— 拒绝。这会重新引入它当初刻意
   避免的坑（被散文/字符串里的 `[]` 带偏），且在错误的层次修问题。
2. **改 prompt，要求设计师别用 `complete_task`、直接吐裸数组** —— 拒绝。这是让 agent 迁就框架的
   bug，且不可靠（模型仍会调工具）；正确方向恰恰相反：agent 听话应当被奖励。
3. **在 `nexau_runtime` 统一拆信封** —— 暂不做。目前只有 designer 需要解析 agent 的结构化返回
   （dev 不解析、user 侧走自己的 persona_io）；提前抽公共层属于「增加实体」。若第二个消费者出现，
   再上提到 `nexau_runtime`（见 Future possibilities）。

## Prior art

**同一个坑在本仓修过一次**：`backend/harness_template/entry.py` 的 `_unwrap_reply()` 专门拆同一层
信封（注释写着「拆信封：用户只看最终答案」）。harness 侧记得拆，编排侧的 designer 漏了。本组是把
那次的教训补到 designer 上。

`persona_io._parse_json` 也踩过同源的「粗暴 find/rfind 抠 JSON」坑并已改为稳健解析——本仓对
「LLM 返回值解析」这一类问题已有一致的处置立场：**解析器要严，信封要在信封层拆**。

## Unresolved questions

- designer 归档里 `round_no` 为 `None`（`history.json` 显示 `round None | proposals: None`），
  轮次游标没落到归档上、看板按轮分组会失准。属观测层问题，不在本组范围，另开。

## Future possibilities

- 若 dev / 其它角色也开始解析 agent 的结构化返回，把 `_unwrap_result` 上提到 `nexau_runtime`
  作为单一 nexau 适配层的公共出口。
- 更进一步：让 `complete_task` 的 result 直接以结构化对象（而非字符串）回传，从源头免掉这层拆封。
