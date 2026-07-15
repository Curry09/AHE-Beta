---
number: "0014"
title: 开发者侧提交纪律：增量落地闸 + 收尾硬闸（含接线 AST）
issue: 0
slug: dev-commit-discipline
summary: 用机制（而非软提示）保证 dev agent 每轮产出「干净的已提交增量」：CommitCheckpointMiddleware 逐级施压逼早落已提交最小片；CompletionGateMiddleware 拦 complete_task——硬闸含工作区干净、可观察行为同步 MANUAL、以及对 entry.py 主路径（main/_run_supervised）的 AST「先用后赋」接线扫描；软闸催回归测试，并对含 heartbeat/进度符号却无短等断言的测试催补进度契约测。配套 systemprompt「一次冒烟即止，且冒烟必须覆盖真实接线/对外契约，禁止只测 helper」。落点 backend/auto_designer/dev/ + agent_defs/developer_agent/。
tasks:
  - id: T1
    title: CommitCheckpointMiddleware：逐级施压逼尽早落已提交增量
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/dev/commit_checkpoint.py
      - backend/tests/dev/test_commit_checkpoint.py
    scope: 机制保证「本轮至少落一个已提交增量」，堵 dev「贪大一口气建全套→撞满迭代/墙钟→零提交落 main、整轮白跑」。挂 dev 执行管线，before_agent 锚定 harness 仓与起始 HEAD，before_model 每次模型调用前查真实 git 状态：一旦本轮 HEAD 相对开工前移（已产生 commit）即达标、闭嘴不再打扰；否则按三档逐级施压——普通（预算过 first_commit_by_frac 或未提交改动超 big_diff_lines=正在贪大）：提醒切最小片、先落地；严重（frac>=0.66）：警告正走向零提交白跑；硬落地（remaining<=hard_commit_by_remaining）：最后窗口给不可含糊的「下一步就 commit+tag+push、其余留 follow-up」指令，逼它停止探索先落地。只在正确时机施加持续压力，绝不替模型写/提交未验证代码。仓路径取运行时 SANDBOX_WORK_DIR。
    acceptance: 本轮一旦有 commit（HEAD 前移）即不再注入任何提示；未提交且预算过 first_commit_by_frac 或 pending 行数超 big_diff_lines 时注入普通/严重档提示；remaining<=hard_commit_by_remaining 且仍零提交时注入硬落地档（含 commit+tag+push 指令）；非 git 仓/取不到状态时安全 no-op、绝不抛。单测（临时 git 仓 fixture）覆盖：已提交→静默、过线→普通、frac>=0.66→严重、末段零提交→硬落地、pending 行数计算。
  - id: T2
    title: CompletionGateMiddleware：收尾硬闸（含接线 AST）+ 软催测试/进度契约
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/dev/completion_gate.py
      - backend/tests/dev/test_completion_gate.py
    scope: 拦在 stop tool（complete_task）上。硬闸：① 工作区干净；② 改了 observable_paths（entry.py）须同步 MANUAL（或报告豁免「本次无对外可见变化」）；③ 本轮改了 entry.py 时，对 HEAD 上 main/_run_supervised 做 AST「局部先用后赋」扫描——挡住 helper 测绿但主路径 NameError 的接线事故。软闸（remaining>soft_gate_min_remaining 才催）：改了逻辑未落 tests/ 回归 → 催落库；若 entry 含 heartbeat/进度类符号而本轮测试未见 sleep/wait/heartbeat/interval 等短等断言 → 催补「等待中途有 progress」契约测。预算兜底 remaining<=1 或 blocks>=max_blocks 整体让路。
    acceptance: 脏仓/手册未同步拦；报告豁免语放行手册闸；entry 主路径先用后赋命中硬拦；无测试软催；有 heartbeat 无短等断言软催进度契约；remaining 不足或达 max_blocks 放行。单测覆盖上述分支。
  - id: T3
    title: dev agent 配置/提示对齐：迭代预算·硬落地窗口·冒烟须盖接线
    status: pending
    priority: P2
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/agent_defs/developer_agent/agent.yaml
      - backend/agent_defs/developer_agent/systemprompt.md
      - backend/agent_defs/developer_agent/MANUAL.md
    scope: 把两道闸门接线进 dev agent。agent.yaml：中间件与实测调参（max_iterations=38、hard_commit_by_remaining=8）。systemprompt：诊断型工作流 + 绝对规则 + 收尾契约。**一次冒烟即止**：只跑一种一遍；但冒烟必须覆盖本轮对外契约/真实接线（main/_run_supervised/终态 reply/进度旁路），禁止只测 helper——py_compile+纯函数断言不算过；周期性 heartbeat 须把间隔调到 ≤0.3s 并断言等待中途有 progress。机制侧接线硬闸与测试/进度软闸与 prompt 对齐。MANUAL.md 为 dev 自身操作手册。
    acceptance: agent.yaml 加载 WorkspaceJail/CommitCheckpoint/CompletionGate 与 RoundAndTokenReminder；systemprompt 含「一次冒烟即止」且明示冒烟须盖接线/契约、收尾契约含接线硬闸说明；闭环能在预算内 commit+tag+push。
---

# 0014 · 开发者侧提交纪律：增量落地闸 + 收尾硬闸（含接线 AST）

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

用机制保证 dev 每轮产出干净已提交增量：

1. **CommitCheckpoint**——预算过线/改动过大/末段零提交时逐级施压，逼早落最小片；
2. **CompletionGate**——拦 `complete_task`：硬闸=工作区干净 + MANUAL 同步 + **主路径 AST「先用后赋」接线扫描**；软闸=催 `tests/`，并对 heartbeat/进度符号催补短等契约测；
3. **systemprompt**——一次冒烟即止，且**冒烟必须覆盖真实接线/对外契约**，禁止只测 helper。

落点 `dev/` + `agent_defs/developer_agent/`。

## Motivation

纯 trunk 下 LLM dev 常见：零提交白跑、半截收尾（手册漂移）、helper 测绿但 `main` NameError、只测静态不测等待中 progress。软 prompt 不够，必须机制闸门。

## Guide-level explanation

- **早期**：CommitCheckpoint 三档施压；本轮一旦有 commit 闭嘴。
- **收尾硬闸**：脏仓 / 改 entry 未同步 MANUAL / `main`·`_run_supervised` 先用后赋 → 剔 `complete_task`。
- **收尾软闸**：无回归测试；有 heartbeat 无 sleep/wait 类断言 → 催进度契约测；预算紧让路。
- **冒烟纪律**：一种一遍即止；但必须按真实调用顺序走到本轮接线（含中途 progress）。

## Reference-level explanation

### 代码锚点

- `commit_checkpoint.py`；`completion_gate.py`（`_local_used_before_assign`、`_has_heartbeat_symbol`、`_tests_mention_timing`）；`systemprompt.md`。

### 闸门表

| 阶段 | 触发 | 动作 |
|---|---|---|
| Checkpoint 普通/严重/硬落地 | 未提交过线 | 施压直至 commit |
| Gate 硬：脏仓/手册 | complete_task | 拦截 |
| Gate 硬：接线 AST | entry 主路径先用后赋 | 拦截 |
| Gate 软：无测试 / 无进度断言 | remaining 充足 | 软催 |
| Gate 让路 | remaining≤1 或 blocks 满 | 放行 |

### DAG

```mermaid
graph LR
  T1[T1 CommitCheckpoint]
  T2[T2 CompletionGate]
  T3[T3 agent 配置/prompt]
  T1 --> T3
  T2 --> T3
```

## Drawbacks

闸门不保证增量正确；AST 扫描非全语言语义；手册同步曾有误报风险。

## Rationale and alternatives

- 只加 prompt：已被证伪。
- 加大 max_iterations：不治过度自验。
- 闸门代 commit：违反「不提交未验证」。

## Prior art

0007 纯 trunk 护栏；CI pre-commit 思想进 agent 管线。

## Unresolved questions

手册同步误报；structured tool_call 与 complete_task；参数动态化。

## Future possibilities

「已过一次 smoke 又发明第二种验证」机制收束；自适应预算。
