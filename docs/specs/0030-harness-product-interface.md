---
number: "0030"
title: harness 产品化边界：/help 用户说明、平台侧接口与 connector 适配
issue: 0
slug: harness-product-interface
summary: 把 harness 收敛为真人可运行产品：harness 模板内只保留 HELP.md 作为 /help 内容源、RUNTIME.md 作为维护说明；README/USER/MANUAL 不再作为模板文档，INTERFACE 归 AHE-Beta 平台侧；connector 适配 sim-user 到真人接口；launcher/template 支持 stdio-jsonl-v1 并兼容 legacy。
tasks:
  - id: T1
    title: 写 0030 活快照
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - docs/specs/0030-harness-product-interface.md
    scope: 明确 harness=真人可运行产品、ahe-beta=训练/观测平台、connector=sim-user 到 human-facing interface adapter；用户帮助由 /help 读取 HELP.md；平台接口文档归 ahe-beta；不把 persona/feeling/issue/round/triage/sim_trace/user simulator 放进 harness。
    acceptance: spec validate 通过；正文含 Summary/Motivation/Reference-level explanation/Rationale and alternatives；任务按 HELP/RUNTIME、平台侧接口、connector/protocol、边界分配清楚。
  - id: T2
    title: harness_template 精简为 HELP/RUNTIME/scripts/deps
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/harness_template/LICENSE
      - backend/harness_template/HELP.md
      - backend/harness_template/RUNTIME.md
      - backend/harness_template/.env.example
      - backend/harness_template/requirements.txt
      - backend/harness_template/scripts/run.sh
      - backend/harness_template/scripts/smoke.sh
      - backend/harness_template/scripts/check.sh
    scope: harness 模板内只保留 HELP.md 作为 /help 内容源、RUNTIME.md 作为维护说明、env/deps/scripts 作为自包含运行套件；不保留 README.md、USER.md、MANUAL.md、INTERFACE.md。
    acceptance: 新模板 checkout 后可通过 HELP/RUNTIME/scripts/env/deps 理解和运行；HELP 与 RUNTIME 分工清晰；模板文档不出现 persona/feeling/issue/round/triage/sim_trace/user simulator 等平台概念。
  - id: T3
    title: /help slash 与模板自测
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/harness_template/entry.py
      - backend/harness_template/agents/main.md
      - backend/harness_template/tests/test_smoke.py
    scope: 新增 /help slash：读取 HELP.md、返回帮助文本且不结束会话；/exit 和 /quit 仍结束会话；清理 entry.py / agents/main.md 平台词；模板自测覆盖 HELP 存在、/help 行为、scripts shebang、禁入平台词。
    acceptance: 在 backend/harness_template 根下运行 python3 -m unittest discover -s tests -p 'test_*.py' 通过；/help 返回 HELP.md 内容且会话继续；/exit|/quit 仍退出；默认自测不依赖真实 LLM 网络。
  - id: T4
    title: 产品提交边界：拒绝密钥与运行态
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/guards/harness_boundary.py
      - backend/tests/guards/test_harness_boundary.py
    scope: guards/harness_boundary 使用产品提交拒绝清单：拒绝 .env、.env.*（.env.example 例外）和顶层 .openagents；正常产品代码、文档与配置可提交。
    acceptance: HELP/RUNTIME/docs/src 与 .env.example 可提交；.env、.env.local 和 .openagents 被拒；本地钩子与 seed smoke 规则一致。
  - id: T6
    title: connector 与 stdio-jsonl-v1 协议适配
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/harness/connector.py
      - backend/tests/harness/test_connector.py
      - backend/ahe_beta/loop/sim_user.py
      - backend/tests/loop/test_sim_user.py
      - backend/ahe_beta/user/sim/loop.py
      - backend/tests/user/sim/test_heartbeat.py
      - backend/ahe_beta/harness/launcher.py
      - backend/tests/harness/test_launcher.py
      - backend/harness_template/params.yaml
      - backend/ahe_beta/harness/INTERFACE.md
    scope: connector 作为平台侧 adapter，把 sim-user 的 send/interrupt/shutdown 映射到真人接口；launcher 根据 params.yaml protocol/interface 选择 stdio-jsonl-v1 或 legacy wire；模板声明 v1 并双读 legacy/v1；平台侧 INTERFACE.md 记录 connector/launcher 协议。
    acceptance: connector 满足 HarnessInterface；interrupt/give_up 走 connector 命名 API；launcher v1 fake entry 的 message/progress/reply/error/interrupt 测试通过且 legacy 继续通过；sim_user 离线跑通；平台侧 INTERFACE.md 存在并记录 v1/legacy。
---

# 0030 · harness 产品化边界：/help 用户说明、平台侧接口与 connector 适配

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

旧内置 Developer 收尾中间件及其配置接线（原 T5）已退役；HELP.md 的平台读取行为仍由 T6 的 launcher 与接口测试覆盖。

本组把 harness 从“ahe-beta 闭环里的被测对象片段”收敛为“真人可运行产品”的种子：harness 模板内只保留 `HELP.md` 作为 `/help` 内容源、`RUNTIME.md` 作为维护者说明，配合 `.env.example` / `requirements.txt` / `scripts/` / `tests/` 支撑独立运行和自测；`README.md`、`USER.md`、`MANUAL.md` 不再作为模板文档，`INTERFACE.md` 归 AHE-Beta 平台侧。

同时，平台侧新增 `HarnessConnector` 作为 sim-user 到真人接口的 adapter，并让 launcher/template 支持 `stdio-jsonl-v1`：新模板通过 `params.yaml` 声明 v1，旧 wire 仍兼容。harness 不接收 persona、feeling、issue、round、triage、sim_trace 等训练/观测概念。

## Motivation

“自包含 harness”的重点不是堆文档，而是让真人或维护者只看 harness 仓就知道如何使用和维护这个产品，同时让 AHE-Beta 平台通过 connector 适配它。此前 README / USER / MANUAL / INTERFACE 同时存在，职责重叠且容易把平台接缝文档塞进 harness 本体；这会让被进化目标混入训练平台概念，削弱边界。

本组将用户帮助收敛到产品内 `/help`，将协议说明移到平台侧，并用 connector 把模拟用户动作适配成人类会对 harness 做的动作。这样 harness 是产品，ahe-beta 是训练/观测平台，connector/launcher 是接缝。

## Guide-level explanation

```text
AHE-Beta
  user simulator / feeling / issue / triage / metrics / orchestrator
          │
          ▼
  HarnessConnector + HarnessLauncher（平台侧接缝）
          │  stdio-jsonl-v1 / legacy
          ▼
harness repo
  entry.py + HELP.md + RUNTIME.md + agents/tools/scripts/tests
```

harness repo 内只有两类文字说明：

- `HELP.md`：给真人用户看的 `/help` 内容源，说明能做什么、怎么退出、怎么打断、工作区语义。
- `RUNTIME.md`：给维护者看的运行边界，说明 harness 仓、workspace、NexAU、session/timeout/interrupt 等维护约束。

程序接口说明不放在 harness 模板内，放在 `backend/ahe_beta/harness/INTERFACE.md`，因为它服务 connector/launcher 维护者。

## Reference-level explanation

### Harness template 文件职责

`LICENSE` 随独立 seed Harness 分发，保留项目 MIT 许可；它不作为 `/help` 内容。

| 文件 | 职责 |
|------|------|
| `backend/harness_template/HELP.md` | `/help` 返回内容，用户能力说明 |
| `backend/harness_template/RUNTIME.md` | 维护者 runtime 边界 |
| `backend/harness_template/.env.example` | `LLM_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY` / `SANDBOX_WORK_DIR` 模板 |
| `backend/harness_template/requirements.txt` | harness 自身最小依赖清单 |
| `backend/harness_template/scripts/*.sh` | 运行、自测、统一 check |
| `backend/harness_template/tests/*` | harness 自身自测，不放任务项目测试 |

模板不再包含 `README.md`、`USER.md`、`MANUAL.md`、`INTERFACE.md`。

### Slash help

`/help` 是普通 message 内的产品命令：

```text
message: /help
→ entry.py 读取 HELP.md
→ 输出 reply
→ 会话继续
```

`/exit` 和 `/quit` 仍输出 reply 后结束会话。未知 slash 仍交给 agent 作为普通用户消息处理。

### Connector 与协议

`HarnessConnector` 提供平台侧语义 API：

- `send_user_message(text)` / `send(text)`：只转发人类可输入文本。
- `interrupt()`：打断当前请求。
- `shutdown()`：结束当前 harness 过程。

训练/观测数据不穿过 connector 进入 harness。

`HarnessLauncher` 根据 `params.yaml`：

- `protocol: stdio-jsonl-v1` → 发送 `{"type":"message","text":...}` / `{"type":"interrupt"}` / `{"type":"shutdown"}`，读取 `type=progress/reply/error`。
- 缺失或 `legacy` → 旧 `{"message"}` / `{"control"}` 与 `{"reply"}` / `{"progress"}`。

### Boundary

当前提交边界采用拒绝清单：正常产品代码、文档和配置可提交；拒绝 `.env`、`.env.*`（`.env.example` 例外）及顶层 `.openagents`。不再按固定产品文件名限制合法扩展。

### DAG / file allocation

```text
T1 ─┬→ T2 ─┬→ T3
    │      ├→ T4
    │      └→ T6
```

- T1 写 spec。
- T2 收敛模板文档/脚本/依赖。
- T3 实现 `/help` 并加自测。
- T4 维护产品提交拒绝清单。
- 原 T5 的旧收尾检查接线已退役；平台读取 HELP.md 由 T6 维护。
- T6 connector 与 v1/legacy 协议适配。

### E2E 验证路径

```bash
./tools/spec-driven-development/spec validate
python backend/scripts/check-spec-number-conflicts.py
uv run pytest backend/tests/user/sim/test_heartbeat.py backend/tests/harness/test_connector.py backend/tests/loop/test_sim_user.py backend/tests/harness/test_launcher.py backend/tests/guards/test_harness_boundary.py backend/tests/test_bootstrap_harness.py
(cd backend/harness_template && python3 -m unittest discover -s tests -p 'test_*.py')
```

## Drawbacks

- v1 与 legacy 双栈会短期共存，直到确认不需要旧 wire。
- 删除 README/USER/MANUAL 会让人类直接浏览仓时入口更少，依赖 `/help` 与 `RUNTIME.md` 的分工。

## Rationale and alternatives

### 为什么用 HELP.md 而不是 USER.md / MANUAL.md

用户帮助是产品能力，最自然的入口是 `/help`。`HELP.md` 作为 `/help` 内容源比 `USER.md` / `MANUAL.md` 更贴近 CLI 产品习惯，也避免旧文档名和平台读取属性混淆。

### 为什么 INTERFACE 不在 harness_template

协议细节服务 AHE-Beta connector/launcher 维护者，不是给真人用户看的能力说明。把它放在平台侧能避免 harness 模板承担接缝文档职责。

### 为什么不保留 README

当前 seed 已由 `HELP.md`、`RUNTIME.md`、scripts 和 tests 提供使用/维护入口。README 会与 HELP 重叠，增加模板重量。若未来需要独立发行，可另开 spec 重新引入极薄 README。

### 为什么保留 legacy

历史 harness refs 与现有测试仍使用 legacy wire。v1 通过 `params.yaml` 显式启用，旧 ref 默认 legacy，降低迁移风险。

## Prior art

- 0013：harness present protocol，reply/progress/steps/interrupt 基础语义。
- 0019：launcher 接受非 reply sideband。
- 0022：内外通道、interrupt 与 slash 语义。
- 0023：事件化等待环与 try_reply。
- 0014：dev 侧提交纪律与用户可见帮助同步硬闸。
- 0015：harness 提交边界与过拟合泄漏隔离。

## Unresolved questions

- legacy wire 何时退场。
- 是否未来允许 `harness/` 作为产品源码生长目录；本组不处理。

## Future possibilities

- launcher 进一步拆成 protocol codec + process transport + connector factory。
- connector 成为 `HarnessLauncher.launch()` 的默认返回对象，避免上层重复 wrap。
- legacy wire 退场后删除 `control()` 公共方法，只保留 `interrupt()/shutdown()` 语义 API。
- 如果未来证明需要独立发行，再引入极薄 README 或 package manifest。
