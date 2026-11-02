---
number: "0065"
title: 标准化 Harness 评测框架
issue: 0
slug: standardized-harness-evaluation
summary: 以不可变计划驱动隔离沙盒中的 Harness 评测，统一官方时间预算、直出与带心跳 LLM 用户模拟、官方 grader、失败分类、恢复和可复现实验报告。
tasks:
  - id: T1
    title: 版本化评测计划与不可变清单
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - evaluation/harness_bench/schema.py
      - evaluation/harness_bench/config.py
      - evaluation/harness_bench/manifest.py
      - evaluation/harness_bench/cli.py
      - evaluation/tests/harness_bench/test_config.py
      - evaluation/tests/harness_bench/test_manifest.py
    scope: 定义 suite、case、Harness、模型、交互模式、官方预算、沙盒资源、重复次数与随机种子的版本化 schema；预检后冻结可散列 run manifest，并提供 validate/plan CLI。
    acceptance: 缺少 pin、预算来源、模式兼容性或隐藏数据边界的计划 fail-closed；同一输入生成稳定摘要；manifest 不含密钥且能完整解释每个 trial 的变量。
  - id: T2
    title: 可插拔沙盒提供方与隔离生命周期
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - evaluation/harness_bench/providers/base.py
      - evaluation/harness_bench/providers/daytona.py
      - evaluation/harness_bench/providers/local.py
      - evaluation/harness_bench/sandbox.py
      - evaluation/tests/harness_bench/test_sandbox.py
    scope: 建立 provider-neutral sandbox 接口，首个实现支持 Daytona；负责镜像 pin、资源配额、文件注入、长命令会话、日志回收、并发调度和 finally 清理。
    acceptance: agent 与 grader 默认物理隔离，controller-private 数据不能进入 agent；网络、资源和镜像 digest 入清单；创建、断连、恢复与删除均可审计且不把基础设施故障计为任务失败。
  - id: T3
    title: Harness 持久会话与流式控制协议
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - evaluation/harness_bench/harness/protocol.py
      - evaluation/harness_bench/harness/session.py
      - evaluation/harness_bench/harness/adapters.py
      - evaluation/tests/harness_bench/test_harness_session.py
    scope: 定义持久消息、progress、usage、reply、error、interrupt 和 shutdown 协议；支持非阻塞 poll、终态配对、在途消息和 Harness 自有超时识别。
    acceptance: 同一 trial 只建一个持久会话；progress 不被误判成 reply；心跳期间可追加消息或中断；迟到 reply 竞态确定处理；Harness 自停、评测截止、崩溃和协议错误可区分。
  - id: T4
    title: 直出与带心跳 LLM 用户模拟策略
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
      - T3
    relates-to: []
    parallel: false
    files:
      - evaluation/harness_bench/interactions/base.py
      - evaluation/harness_bench/interactions/direct.py
      - evaluation/harness_bench/interactions/simulated_user.py
      - evaluation/harness_bench/interactions/native_user.py
      - evaluation/tests/harness_bench/test_interactions.py
    scope: 实现 direct 单消息策略，以及位于 agent 沙盒外、可观察公开进度并在运行中 keep_waiting/send_message/interrupt/give_up 的 LLM 用户监督器；兼容 benchmark-native 用户模拟。
    acceptance: direct 绝不生成第二条用户消息；simulated_user 按冻结 persona/model/seed/heartbeat/turn 配置运行且看不到 grader；reply 与心跳决策竞态时不发送过期动作；一次回复后才生成单次追问不得冒充心跳模式。
  - id: T5
    title: Benchmark 插件、官方预算与隐藏 grader
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - evaluation/harness_bench/benchmarks/base.py
      - evaluation/harness_bench/benchmarks/swebench.py
      - evaluation/harness_bench/benchmarks/terminal_bench.py
      - evaluation/harness_bench/benchmarks/tua_bench.py
      - evaluation/harness_bench/benchmarks/tau3.py
      - evaluation/tests/harness_bench/test_benchmarks.py
    scope: 为 SWE-bench Verified、Terminal-Bench、TUA-Bench 和 tau3 提供任务准备、模式能力、官方 agent/verifier 预算解析、产物导出和官方 grader 适配。
    acceptance: 从锁定 task metadata 读取官方时限，无官方 agent 时限统一使用并标记 1800 秒 fallback；外层截止不得短于选定任务预算；隐藏测试、gold、solution 与 grader 输出不进入 agent 或通用用户模拟上下文。
  - id: T6
    title: 可恢复编排、统一结果与配对报告
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
      - T2
      - T3
      - T4
      - T5
    relates-to: []
    parallel: false
    files:
      - evaluation/harness_bench/orchestrator.py
      - evaluation/harness_bench/state.py
      - evaluation/harness_bench/outcomes.py
      - evaluation/harness_bench/report.py
      - evaluation/tests/harness_bench/test_orchestrator.py
      - evaluation/tests/harness_bench/test_reporting.py
    scope: 按 trial 状态机执行、断点恢复和精确重试，归一化任务、Harness、模拟用户、grader 与基础设施终态，并生成分 benchmark、分模式和配对 A/B 报告。
    acceptance: 业务失败不重跑，基础设施无效尝试可在同一 manifest 下补跑；pass、终态回复、非超时回复、grader reach、延迟和三类成本分别报告；不同计划摘要不可合并，报告可追溯到原始轨迹和清理状态。
---

# 0065 · 标准化 Harness 评测框架

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

建立一个独立于具体 Harness、沙盒厂商和 benchmark 的标准化评测控制面。操作者用版本化
evaluation plan 声明任务集、Harness 制品、模型、交互模式、预算来源、重复次数和隔离策略；框架
解析各 benchmark 的官方元数据，冻结不可变 run manifest，再在临时沙盒中执行持久 Harness
会话、收集公开轨迹并调用隐藏 grader。所有结果都能回溯到输入、制品摘要、协议事件、成本和清理
状态。

首期正式支持两种互斥的交互模式：

- `direct`：只发送一次官方任务输入，不产生追加用户消息，等待正常终态、Harness 自有终态或
  已解析的任务截止时间。
- `simulated_user`：LLM 用户监督器位于 agent 沙盒外，既能在 Harness 工作期间按心跳读取公开
  进度并选择继续等待、追加消息、中断或放弃，也能在 Harness 回复后继续多轮对话。benchmark
  自带的官方用户模拟器通过同一接口接入，但保留原生动作空间和终止规则。

框架把任务正确性、Harness 可用性和评测基础设施健康度分开。`[timeout]` 终态回复只提高终态回复
率，不算正常完成；Harness 自停、评测截止、崩溃、grader 失败和沙盒故障具有不同 outcome。
官方时间上限是最大允许预算而不是成功标准，评测器不得用更短的临时上限替代它；Harness 选择
提前终止仍作为被测产品行为保留并单独报告。

## Motivation

现有 public-bench pilot 已证明 Daytona 能隔离运行 SWE-bench Verified、Terminal-Bench、TUA-Bench
和 tau3，但执行逻辑分散在逐题脚本中，协议和口径随实验追加。近期试跑暴露出四类系统性问题：

1. 统一写死的 360 秒 controller 截止短于 Terminal-Bench 的 1–2 小时和 TUA-Bench 的 40 分钟
   官方 agent 预算，导致环境验证结果被误读为官方 benchmark 失败。
2. baseline v0 在 240 秒返回 `[timeout]`，旧汇总因收到了 reply 而将其计为 Harness 完成；这混淆
   了“有终态回复”“正常完成”和“任务通过”。
3. 非 tau3 任务先阻塞等待完整 Harness 回复，再让 LLM 生成一次追问；该 half-duplex 包装没有
   接入已有 persona 心跳、在途消息和 interrupt，不能回答用户介入是否改善体验或正确率。
4. 临时运行的 manifest、失败归一化和对比 JSON 由人工拼接；同一题的 setup 错误、无 patch、
   grader 0、内部超时和外层超时容易进入不同分母，且恢复时可能重复收费或遗漏远端命令日志。

标准化框架的目标不是替换各 benchmark 的官方 grader，也不是制造一个新的综合排行榜。它提供
可复现的实验外壳，使“比较 Harness 版本”“比较 direct 与 simulated-user”“比较模型”三类问题
各自只改变声明的实验变量。小样本 pilot 仍只能给出方向性证据，但不能再因为执行预算、交互协议
或统计口径漂移而得出错误结论。

## Guide-level explanation

### 核心对象

- **Suite**：锁定 revision 的任务集合及 benchmark 插件配置。
- **Plan**：一次实验设计，声明 Harness、模型、模式、预算策略、重复与调度。
- **Run**：plan 预检后冻结的不可变执行实例，拥有唯一 `run_id` 和 `manifest_digest`。
- **Trial**：`case × harness × model × interaction × seed × repetition` 的逻辑测量单元。
- **Attempt**：某 trial 的一次基础设施尝试。只有无效的基础设施 attempt 可补跑；业务终态不重跑。

### 操作者流程

计划使用 YAML 编写，密钥只通过运行环境注入：

```yaml
schema_version: 1
suite: public-harness-pilot-19
harnesses:
  - id: baseline-v0
    archive: /artifacts/harness-v0.tar.gz
    sha256: dd7cdd91...
models:
  harness: z-ai/glm-5.2
interactions:
  - mode: direct
  - mode: simulated_user
    policy: heartbeat-persona-v1
    model: z-ai/glm-5.2
    seed_set: [17, 29, 43, 71]
    heartbeat_seconds: 90
budgets:
  agent: benchmark
  harness_self_timeout: as_shipped
provider:
  type: daytona
measurement:
  repetitions: 3
```

标准入口为：

```text
hbench validate plan.yaml
hbench plan plan.yaml
hbench run plan.yaml
hbench resume <run-id>
hbench summarize <run-id>
hbench compare <run-a> <run-b>
```

`validate` 离线检查 schema、任务解析、模式兼容性、制品摘要和隐藏数据边界。`plan` 联网解析镜像
digest、benchmark 官方预算及 provider 容量，输出待签名 manifest 而不消费模型。`run` 只接受冻结
manifest；运行中断后由 `resume` 对账 attempt 状态和远端沙盒，不能从已修改的 YAML 静默续跑。

### 两种交互模式

`direct` 将官方 instruction 作为唯一用户消息写入持久 Harness 会话。progress、usage 和 heartbeat
只是观测事件，不能被当作 reply；Harness 返回正常 reply、自有 timeout、crash 或达到 trial deadline
时结束。该模式适用于 SWE、Terminal 和 TUA。强制需要用户动作的任务必须在 plan 阶段拒绝 direct，
不能用空用户或固定追问伪装。

`simulated_user` 在 agent 沙盒外运行监督器。初始消息仍来自公开 benchmark 输入；Harness 在途时，
每次心跳把已公开的 progress、累计等待时间、HELP 能力和对话历史交给冻结的用户策略。策略只能选择
`keep_waiting`、`send_message`、`interrupt` 或 `give_up`。Harness reply 在决策期间到达时，待发送动作
作废并优先读取 reply，防止针对过时状态继续施压。reply 后的下一轮由同一 persona 和会话状态决定，
直到接受、放弃、达到最大轮数或任务预算。

tau3 等 benchmark-native 用户实现相同的 supervisor 接口，但其官方 simulator、seed、最大轮数、工具
动作和 reward 规则保持原样。通用 persona 不替换 native simulator。仅在第一条完整 reply 后生成一条
LLM 追问的策略可以作为显式实验扩展存在，但不得标记为 `simulated_user/heartbeat-persona-v1`。

### 预算与结果阅读

每个 trial 在启动前形成 `BudgetResolution`，分别列出 agent、用户模拟、verifier、环境构建和清理
预算及来源。Terminal/TUA 必须读锁定 `task.toml`；题目不提供官方 agent 作答时限时，标准 suite
使用 1800 秒并记录 `fallback_no_official_timeout`。评测器 deadline 不得早于解析后的 agent
预算；transport/cleanup grace 只能用于收尾，不能让 Agent 继续工作。

Harness 的自有 timeout 默认按 `as_shipped` 保留。它提前返回 timeout 是有效的被测行为，计入
Harness 失败/任务未通过，而不是基础设施无效；若实验要通过公开配置将其对齐任务预算，必须使用
另一 manifest 和 `task_aligned` 标签，不能在 A/B 的一侧静默修改。

报告至少并列展示：端到端通过率、终态回复率、正常非超时回复率、grader 到达率、评测 deadline
率、基础设施无效率、延迟，以及 Harness/用户模拟/judge 三套 token 与成本。不同 interaction mode
分别出表；只有任务、seed、预算、模型和资源完全配对时才计算差值。

## Reference-level explanation

### 1. 控制面、数据面与信任边界

controller 只持有计划、凭证引用和 controller-private benchmark 数据。agent sandbox 只接收公开
instruction、任务环境、Harness 制品和完成任务所需的最小网络权限。通用用户模拟器运行在 agent
sandbox 外，只能看到一个真实用户能看到的 instruction、Harness HELP、可见 progress/reply 和自己
发送过的消息；它不能读取 solution、gold patch、测试、grader 标准或 grader 输出。

grader 默认使用新沙盒，接收 agent 退出后导出的声明产物或 patch。TUA 类需要原任务状态的插件可在
同一任务沙盒延迟上传测试，但必须先终止 Harness、撤销模型凭证并证明 controller-private 路径此前
不存在。tau3 通过原生环境计算 reward。所有例外都由插件 capability 明示，不能由 runner 按任务名
写分支。

沙盒 provider 接口至少提供 `create`、`upload`、`exec_async`、`poll`、`download`、`inspect` 和
`delete`。远端长命令必须使用可重新连接的 session/command id；controller HTTP 超时不能等同远端
命令失败。资源容量按声明的 CPU、内存和磁盘做 bin-packing，禁止因并行度不同改变单 trial 配额。

### 2. Plan 与不可变 manifest

plan schema 至少包含：

```text
suite revision, case ids, case digests
harness artifact digest, adapter digest, launch contract
agent model/provider/base URL identity, prompt/tool-schema digest
interaction mode and policy digest
user model/persona/temperature/seed/heartbeat/max-turns
budget values, clock semantics and provenance
sandbox provider, image digests, resources, network policy
repetitions, scheduling seed, retry policy, cost ceiling
grader plugin/version/digest and isolation mode
redaction policy and artifact retention policy
```

manifest 将环境解析后的 mutable tag 换成 digest，展开每个 trial id，并记录 framework commit。凭证值
永不序列化，只保存 secret slot 名。manifest 使用 canonical JSON 计算 SHA-256；resume、summarize 和
compare 都验证摘要。环境验证与正式 measurement 是不同 stage 和 trial id，前者不能进入正式分数。

### 3. 预算解析与时钟

benchmark 插件返回结构化预算：

```text
agent_timeout_seconds
verifier_timeout_seconds
environment_build_timeout_seconds
source = official_metadata | suite_custom
clock = trial_wall | benchmark_native
```

官方 metadata 缺失时使用固定 1800 秒 fallback 并明确记录来源，不能静默继承 runner 默认值。
另行声明的 `suite_custom` 必须给出值和理由，并传播到文件名、报告头和比较兼容性检查。
bootstrap/build 不消耗 agent budget；官方 instruction 成功写入 Harness 时启动 agent
时钟。direct 到终态即停止。通用 simulated-user 默认使用 trial wall clock：在途心跳和用户动作不会
重置截止时间；若某 benchmark 的官方协议暂停用户思考时间，则由 native 插件实现并在 manifest 中
标记不同 clock。

controller 可有固定 transport grace 读取已在 deadline 前产生的终态和执行清理，但不得在 grace 中
继续模型或工具工作。若 controller 配置早于解析预算，预检失败；若实现 bug 仍提前中断，outcome 为
`protocol_invalid`，不能计作 Harness 失败。

### 4. Harness 会话协议

统一事件信封含 `schema_version`、`trial_id`、`session_id`、`request_id`、单调 `seq`、时间戳、
`type` 和 payload。最小事件集为：

```text
controller: message | control.interrupt | shutdown
harness: accepted | progress | usage | reply | error | exited
```

每条用户消息获得唯一 request id；progress/usage 归属当前 request，但不关闭它。`reply` 必须携带
`terminal_kind = normal | self_timeout | interrupted | refused`。无法升级的旧 Harness 可由 adapter 基于
明确、版本锁定的协议标记解析；禁止用任意自然语言包含 “timeout” 猜终态。若旧版仅有已声明的哨兵
前缀，adapter 必须保存原文与解析规则 digest。

session 暴露非阻塞 `write_message`、`poll(timeout)`、`try_reply`、`interrupt`、`shutdown` 和公开事件
快照。它允许 Harness 工作时接收排队消息，但 interaction policy 决定何时发送。一个 trial 从初始消息
到结束只使用一个逻辑 session；底层进程重建必须由 Harness 自己暴露连续性证据，否则分类为 crash，
controller 不能悄悄新建会话继续。

### 5. 交互状态机

```mermaid
flowchart TD
    S[send official instruction] --> W[await event]
    W -->|progress| W
    W -->|normal reply| D{mode}
    W -->|self timeout/crash/deadline| X[terminal]
    D -->|direct| G[grade]
    D -->|simulated_user| J[user judge/intent/act]
    W -->|heartbeat due| H[user waiting decision]
    H -->|keep_waiting| W
    H -->|send_message| W
    H -->|interrupt/give_up| X
    J -->|send_message| W
    J -->|accept/give_up|max turns| G
    G --> R[result]
```

用户每次主决策和等待决策都保存模型原始调用、结构化动作、可见上下文摘要、耗时与 usage。协议解析
失败允许有限重试；反复失败产生 `simulator_failure` 无效 trial，不伪造用户动作。心跳次数上限必须
覆盖 trial 预算，例如 `ceil(agent_timeout / heartbeat_seconds)` 再加明确余量；不能用固定 12 次使
两小时题在 18 分钟被用户框架强制放弃。

### 6. Benchmark 插件契约

插件实现以下能力，而 orchestrator 不读取 benchmark 私有格式：

```text
resolve_case() -> immutable CaseSpec
supported_interactions() -> capabilities
resolve_budgets() -> BudgetResolution
prepare_agent_input() -> public payload
provision_agent() -> sandbox recipe
export_submission() -> declared artifacts/patch/trajectory
grade() -> raw official result + normalized pass
validate_oracle() -> optional environment preflight
```

SWE 插件导出 patch 并在新官方镜像执行 F2P/P2P；没有 patch 是 task failure，不是 controller failure。
Terminal 插件从 `task.toml` 读取 agent/verifier/build timeout，只导出 `artifacts` 声明路径。TUA 插件
保留任务状态并在 Harness 退出后注入 verifier。tau3 插件使用官方 simulator、环境、tool schema、
turn cap 和 reward；若某任务不支持 direct，capability check 在花费模型预算前失败。

### 7. Outcome 分类与计分

trial 终态由结构化证据归一化：

| Outcome | 是否进入有效 trial 分母 | 说明 |
|---|---:|---|
| `task_success` | 是 | 官方 grader 通过 |
| `task_failure` | 是 | 正常提交但 grader 未通过，或缺少声明提交物 |
| `harness_self_timeout` | 是 | Harness 在任务 deadline 前主动超时 |
| `evaluator_deadline` | 是 | 完整官方/自定义预算耗尽仍无终态 |
| `harness_crash` / `harness_protocol_error` | 是 | 被测制品崩溃或违反协议 |
| `simulator_failure` | 否 | 评测用户模型或动作协议失败 |
| `grader_failure` | 否 | grader 自身不可用或结果不可解析 |
| `infrastructure_failure` | 否 | sandbox、镜像、网络控制面或 provider 故障 |
| `protocol_invalid` | 否 | 计划或 runner 违反冻结协议，例如过早截止或泄露测试 |

`task_pass_rate = task_success / valid_trials`。此外独立计算 terminal reply、normal reply、grader reach、
self-timeout、deadline、crash 和 invalid attempt 比例。收到 `[timeout]` 不能增加 normal completion；
未到 grader 的 Harness 失败仍在 task pass 分母中。人工修复环境后的补跑保留原 attempt，不删除历史。

成本分为 `harness_agent`、`simulated_user`、`benchmark_native_user`、`judge/grader` 和 `controller`；主表
至少分别列出前三类，不用用户模型成本掩盖 Harness 成本。延迟同时报告 provision、time-to-first-
progress、active trial、time-to-terminal、grader 和总墙钟。

### 8. 恢复、重试与制品布局

run state 采用原子快照和追加 journal。trial 状态至少为 `planned → provisioning → running →
collecting → grading → terminal`，另有 `invalid` 和 `cleanup_pending`。每次远端操作保存 provider id、
command id 和后置条件；resume 先 inspect 已存在沙盒和文件，再决定继续收集、补 grade 或新建 attempt。

业务终态、Harness timeout/crash 和 grader 0 不自动重跑。基础设施、grader 或 simulator 无效 attempt
可以在原 trial 下递增 attempt 号补跑，但必须保持 manifest 不变。模型 API 的调用级 retry 由冻结策略
限制并逐次记录；禁止 fallback 到不同模型。全任务重复只用于无效 attempt，不能挑最好结果。

目录结构为：

```text
runs/<run-id>/
  manifest.json
  state.json
  journal.jsonl
  trials/<trial-id>/attempt-<n>/
    controller.jsonl
    trajectory.jsonl
    harness.stdout.jsonl
    harness.stderr.log
    usage.jsonl
    submission/
    grader/
    result.json
    cleanup.json
  summary.json
  report.md
```

轨迹按结构化字段脱敏，不得用删除整个 tool result 的方式破坏可审计性。每个文件记录摘要；summary
仅引用已封口 attempt。保留策略到期可删除大制品，但 manifest、result、摘要和删除回执长期保留。

### 9. 比较设计与报告门禁

A/B 比较必须使用相同 case digest、模型、interaction policy、预算、资源、网络、grader 和 seed；仅被
声明的 Harness 制品或目标变量可变化。调度顺序由冻结 seed 随机化，同一 pair 尽量处在相同时间块，
避免 provider 波动与版本效应完全重合。不同模式不可合并成一个总分。

环境验证每 case 一次且不计分。正式 measurement 的重复次数由 plan 声明；低成本默认建议 direct
至少三次、含随机 LLM 用户至少覆盖四个冻结 seed。报告同时给出逐题 paired outcome 和聚合区间；
样本不足时显式标记 preliminary，不从单次 winner 推断稳定提升。历史 trial 只有在完整 trial key 和
manifest digest 相同时才可复用，不能因“题目相同”跨协议拼表。

## Drawbacks

遵守官方长任务预算会显著增加沙盒占用、模型 token 和完成时间；四个 benchmark 的正式小样本也可能
需要数十个沙盒小时。带心跳用户监督器还会增加单独的模型成本和变异来源。严格保存轨迹、镜像摘要和
远端命令日志提高存储需求，provider-neutral 抽象也比逐题脚本有更多代码。

统一 outcome 不会消除归因争议。例如 provider 502 可能被 Harness 正确恢复，也可能触发 Harness
崩溃；框架只能基于冻结规则和证据分类，不能在看到分数后改口径。`as_shipped` 会让内建短 timeout
成为 Harness 的真实劣势，而 `task_aligned` 会评测一个配置后的产品；两者都合理但不能混报。

LLM 模拟用户不等于真人，其耐心、措辞和接受标准受模型影响。即使使用心跳，它也只能看到协议公开的
进度，无法判断未暴露的内部工作。该模式适合比较交互韧性，不应取代 direct 或官方 native simulator。

## Rationale and alternatives

选择“不可变计划 + 插件 + 状态机”而不是继续扩展逐题脚本，是因为可比性的主要风险来自跨层隐式默认：
题目时限、Harness 自停、用户策略、sandbox 资源和 grader 隔离必须在运行前共同解析。只有冻结后的
manifest 能证明两次运行除了目标变量外相同。

用户模拟采用外置 supervisor 和持久双向协议，而不是把用户 LLM 放进 agent prompt。后者无法在
Harness 忙碌时观察或中断，也会把用户 token、隐藏策略和 Agent 上下文混在一起。单次固定追问成本低，
可作为 smoke test，但不能表示真实多轮或等待体验。完全使用同步 request/reply API 实现简单，却复现
了本次“用户在完整回复前永远无法介入”的错误。

预算默认尊重 benchmark metadata，而不是为快速试跑选择统一最小值。统一短预算适合明确命名的
latency stress suite，但不能生成官方口径分数。框架不强行延长 Harness 自身 timeout，因为提前交还
控制权是产品行为；需要 budget alignment 时通过显式策略形成另一个实验条件。

选择官方 grader 作为唯一 task pass 权威，不用 LLM judge 替代确定性测试。LLM judge 可产生用户体感
等次级指标，但必须单独计费、固定模型且不改变 pass。基础设施无效 attempt 排除出分母，是为了不把
Daytona 或 grader 故障归咎 Harness；Harness 自身错误仍进入分母，避免以“没交卷”提高条件成功率。

## Prior art

Harbor/Terminal-Bench 的 `task.toml` 已提供 agent、verifier、build 预算和资源声明；SWE-bench 官方
evaluation harness 提供 patch 级 F2P/P2P 验证；TUA 采用任务环境与 verifier；tau3 提供原生模拟用户、
工具轨迹和 reward。本框架复用这些权威内容，不重写题目或评分器。

仓库现有 `ahe_beta.user.sim.loop` 已实现 `write_message/poll/interrupt` 心跳监督、迟到 reply 竞态
和 persona 动作日志；0064 的可恢复实验运行提供原子状态、operation key 和外部状态对账思路。当前
public-bench pilot 的 agent/grader 隔离、Daytona async command 和 prepared 数据边界是可迁移的验证
资产，但临时 runner 和手工汇总不作为新框架 API。

常见 benchmark harness 的 run manifest、内容寻址制品、paired trial 和 invalid-run 分类提供相同的
可复现原则：执行环境与评分规则必须先锁定，失败原因和任务分数必须分开，原始轨迹是汇总数字的审计
来源。

## Unresolved questions

1. `task_aligned` 是否应成为 Harness 比较的主表，还是只报告 `as_shipped`。前者更接近相同计算预算，
   后者更接近用户拿到的实际产品；spec 要求分开，但不预先决定主次。
2. 通用 LLM 用户的 persona 集合和满意度指标如何冻结。现有严苛 persona 可复用，但需避免让 simulator
   知道 benchmark 类型或 grader 条件，并验证不同模型下协议有效率。
3. 官方 agent 时限很长时，低成本 preliminary suite 是否另设显式 `stress-budget`。若设置，它只能与
   相同 stress plan 比较，不能与官方预算结果混合。
4. Daytona 的镜像 digest、暂停/恢复和长会话保留能力若不足，哪些证据允许将断连 attempt 判为基础
   设施无效，而不是 Harness deadline；需通过故障注入确定。
5. generic simulated-user 作用于原本单轮的 SWE/Terminal/TUA 时，本质上形成新的交互 benchmark
   variant。其用户提升应按每个 Harness 内部 paired 分析，是否发布跨 benchmark 总分仍待实证。

## Future possibilities

完成首期后可增加 E2B、本地 Docker/Kubernetes provider，保持相同 manifest 和 outcome 契约；也可将
provider 容量与价格估算加入 `plan`，在运行前给出沙盒小时、token 和存储上限。

积累足够重复后，可生成 paired bootstrap 区间、成本归一化前沿、time-to-progress 生存曲线和用户动作
转移图。框架还可支持录制真人交互后确定性 replay、模拟用户 shadow mode（只决策不执行）以及同一
Harness 在 `direct/as_shipped`、`direct/task_aligned`、`simulated_user` 三个条件下的因果拆分。

当事件协议稳定后，可发布一个最小 conformance kit，让新 Harness 在进入昂贵 benchmark 前先验证
progress、reply、usage、interrupt、timeout 和恢复语义；benchmark 插件也可由独立包注册，而无需修改
orchestrator。
