---
number: "0028"
title: divergent PM + gate：产品候选并行通道与晋升评审
issue: 0
slug: divergent-pm-gate
summary: 在 0025 triage 漏斗旁并行一条产品候选通道：divergent PM 与 architect 同信号并行落 divergent 不可领候选；Architect.gate_once 做语义晋升（promote→feature+triaged / hold / drop）。默认 N_DIVERGENTS=0 关闭；dev 领取硬排除 divergent。
tasks:
  - id: T1
    title: issue_schema：divergent/gate-dropped 标签与可执行 backlog 口径
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/issue_schema.py
      - backend/tests/demand/test_issue_schema.py
    scope: 新增 DIVERGENT / GATE_DROPPED 常量。triage_status 优先级插入 GATE_DROPPED（终态）与 DIVERGENT（候选不可领）。is_backlog_by_labels / is_executable_backlog 排除 divergent 与 gate-dropped，避免候选灌进可执行 backlog 曲线。
    acceptance: 常量可导入；triage_status 对含 divergent/gate-dropped 的标签返回正确单值；可执行 backlog 判定对 divergent 与 promote 后 feature+triaged 正确；单测覆盖。
  - id: T2
    title: Divergent 驱动器 + agent_defs/divergent_pm：落不可领产品候选
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/divergent.py
      - backend/agent_defs/divergent_pm/
      - backend/scripts/preview_divergent_pm_rounds.py
      - backend/scripts/preview_gate_on_divergent.py
      - backend/tests/demand/test_divergent_gate.py
    scope: 新建 Divergent.propose_once：与 architect 同构输入（triaged/RFC/积压候选/体感/runtime_agg），跑 divergent_pm agent，校验 RFC 字段后 create_issue(labels=[divergent, round-N])，每轮硬顶 3 条。不打 triaged/RFC。agent_defs 含 jail+timeline 工具；prompt 强调产品面挖掘、禁题面过拟合。附预览脚本（FakeTracker / 真 LLM）便于离线验 gate。
    acceptance: 候选带 divergent、无 triaged；超顶截断；字段非法不入库；dev 不可领；stub 单测覆盖创建/截断/不可领。
  - id: T3
    title: Architect.gate_once：promote/hold/drop 语义晋升
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: true
    files:
      - backend/ahe_beta/demand/architect.py
    scope: Architect 增 gate_once：无候选跳过；有则短预算跑晋升任务（候选+RFC+体感，可按需 timeline）。解析 disposition：promote→去 divergent 加 feature+triaged；hold 保持；drop→gate-dropped 关闭。未出现在决策中的候选默认 hold。复用同一 agent_defs/architect，不新建第四角色定义。
    acceptance: promote 进可领；hold 仍 divergent；drop 关闭带 gate-dropped；空候选不调 LLM；解析失败默认 hold；单测（见 T2 测试文件）覆盖三路。
  - id: T4
    title: 编排接线：d2 architect∥divergent → d3 gate；roster/run 默认关
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/loop/orchestrator.py
      - backend/ahe_beta/loop/roster.py
      - backend/ahe_beta/loop/live.py
      - backend/ahe_beta/experiment/controllers/ordinary.py
      - backend/ahe_beta/experiment/controllers/swebench.py
      - backend/tests/loop/test_roster.py
    scope: orchestrator：triage 后 ThreadPool 并行 architect∥divergent，再对每个 architect 调 gate_once（无 architect 则候选积压）。roster 增 divergent 键，DEFAULT=0，N_DIVERGENTS 覆盖。run.py 与 SWE 脚本按编制构造 Divergent 注入。live ROLE_ORDER 插入 divergent。默认关闭不改现有闭环成本。
    acceptance: 顺序 triage→(architect∥divergent)→gate→dev；N_DIVERGENTS=0 无 divergent 实例；=1 注入并跑；roster 单测覆盖；live 排序含 divergent。
  - id: T5
    title: dev 领取硬排除 divergent 候选
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: true
    files:
      - backend/ahe_beta/dev/agentic_developer.py
      - backend/tests/dev/test_agentic_developer.py
    scope: AgenticDeveloper._eligible 增加 DIVERGENT not in labels，即使误打 triaged 也不领候选。与 schema 口径双保险。
    acceptance: 仅 divergent 的 open issue 不进 eligible；promote 后 feature+triaged 可领；单测断言排除。
---

# 0028 · divergent PM + gate：产品候选并行通道与晋升评审

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

在 0025 的 triage→architect→dev 漏斗旁，增加一条**可选**的产品候选通道：

1. **divergent PM**（新 agent 定义）：与 architect **同信号、并行**，从交互挖「用户可感知」的产品面机会，落 `divergent` 标签的 open 候选（**不可领**）。
2. **gate**（逻辑 Promoter，实现为 `Architect.gate_once`）：对 open divergent 做语义晋升——`promote`→去 `divergent`、加 `feature`+`triaged`；`hold` 积压；`drop`→`gate-dropped` 关闭。

默认 `N_DIVERGENTS=0`（零额外成本）；开启后才跑发散与晋升。dev 领取集合硬排除 `divergent`，避免未评审候选直进主干改动。

## Motivation

实测 SWE 闭环里，用户侧几乎不主动报 `feature`，architect 与 dev 被 reliability 债（超时软收口、continuation、BrokenPipe）占满，产品面机会即使在对话里以「用户自拟规程」反复出现，也进不了可领 backlog。把「挖产品候选」绑进 architect 会破坏其宁缺毋滥的根因综合职责。需要一条**并行、默认可关、经门控才可领**的通道：发散允许外推「反复自拟规程→产品契约」；晋升负责去重与带宽筛选。

## Guide-level explanation

一轮 d 段变为：

```
a(用户) → d1 triage → d2 (architect ∥ divergent) → d3 gate → b(dev) → c
```

- 关（默认）：`N_DIVERGENTS=0`，行为与 0025 等价（仍跑 gate，但无候选则立即跳过）。
- 开：`N_DIVERGENTS=1`（通常配 `N_ARCHITECTS≥1`，否则候选只能积压等下轮有 architect 的 gate）。

观测上：`divergent` 不计入可执行 backlog 曲线；promote 后进入与普通 feature 相同的可领集合。

## Reference-level explanation

### 标签与口径（T1）

| 标签 | 含义 |
|------|------|
| `divergent` | 产品候选，open 但不可领 |
| `gate-dropped` | gate 丢弃（关闭） |
| promote 后 | 去掉 `divergent`，加 `feature` + `triaged`（保留 `round-*`） |

`triage_status` 优先级：`rejected` / `needs-info` / `gate-dropped` / `superseded` / `divergent` / `triaged` / `needs-triage`。  
`is_backlog_by_labels` 排除 `DIVERGENT` 与 `GATE_DROPPED`。

### Divergent（T2）

- 驱动：`backend/ahe_beta/demand/divergent.py`
- 定义：`backend/agent_defs/divergent_pm/`（jail + timeline/beat/step，与 architect 同工具面）
- 每轮硬顶 3 条；body 走 RFC 五门字段校验；标签仅 `[divergent, round-N?]`
- 离线预览：`preview_divergent_pm_rounds.py` / `preview_gate_on_divergent.py`

### Gate（T3）

- `Architect.gate_once`：注入候选全文 + open RFC + 体感曲线；提示可按需 `get_session_timeline`
- `complete_task` 交 `[{issue, disposition, note}]`；未列出的候选默认 hold
- 短 `max_iterations`（≤80）；无候选不调 LLM

### 编排（T4）

- `Orchestrator`：`ThreadPoolExecutor` 并行 `propose_once`（architect∥divergent），再串行 `gate_once`
- `roster`：`divergent` 键，env `N_DIVERGENTS`
- `live._ROLE_ORDER`：user < triager < architect < divergent < developer

### Dev（T5）

- `_eligible`：`DIVERGENT not in labels`（与 schema 双保险）

### DAG

```
T1 → T2 ─┐
T1 → T3 ─┼→ T4
T1 → T5 ─┘
```

## Drawbacks

- 多一次 LLM 调用（divergent）+ 每 architect 一次 gate；默认关闭可规避。
- architect∥divergent 并行写同一 Fake/Gitea tracker，依赖 tracker 线程安全（现有 Fake/Gitea 调用面短，接受）。
- gate 复用 architect 定义，systemprompt 仍偏 architect；靠任务消息覆盖角色，极端情况下模型可能混淆职责。

## Rationale and alternatives

| 方案 | 取舍 |
|------|------|
| **本方案：并行 divergent + Architect.gate_once** | 不污染 architect；晋升不新建完整 agent 定义（奥卡姆）；默认可关 |
| 把产品挖掘塞进 architect | 破坏宁缺毋滥；实测产品面仍会被 reliability 淹没 |
| 第四个完整 Promoter agent_defs | 多一套 prompt/工具/编制；与 gate「同工具面换任务」收益不成比例 |
| divergent 直接打 triaged | 无去重/带宽门控，易灌单占满 N_DEVELOPERS |
| 机制规则晋升（关键词/频次） | 无法区分「纯 runtime 重叠」与「用户可感知产品面」 |

## Prior art

- 0025：triage 漏斗与 RFC 可领集合——本组在其旁路扩展，不改 raw→triage→RFC 主链语义。
- 0024：god-view timeline——divergent/gate 按需取证，jail 仍禁直接读 sessions/。
- 真实软件团队：PM 提案看板 → Promoter/TL 评审进 sprint backlog。

## Unresolved questions

- gate 是否应强制至少一次 timeline 抽样（现为「可按需」）。
- 多 architect 时 gate 是否应只跑一次（现：每个 architect 各跑一次；N_ARCHITECTS=1 时无歧义）。
- 前端 AgentBoard 是否要为 divergent 单独房间色（roster 已有键；UI 可后续跟）。

## Future possibilities

- 把 gate 决策 note 投影到观测看板。
- divergent 产出 kind 从 RFC 五门演进为更轻的「产品机会」字段集。
- 与 0026 前端联调：divergent / gate-dropped 徽标。
