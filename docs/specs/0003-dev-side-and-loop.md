---
number: "0003"
title: 开发者侧与闭环
issue: 0
slug: dev-side-and-loop
summary: 本组实现 **b｜开发者侧** 与 **c｜闭环回灌**，把前两组的零件总装成可重复的进化轮次。一轮 = a（用户产 issue + 体感）→ b（开发者改 harness、测试体感门禁、发版）→ c（新版 harness 回到 a）。
tasks:
  - id: T1
    title: harness launcher 与 harness_template
    status: pending
    priority: P1
    tags: []
    depends-on:
      - 0001/T2
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/harness/launcher.py
      - backend/harness_template/entry.py
      - backend/harness_template/params.yaml
      - backend/harness_template/agents/main.md
      - backend/tests/harness/test_launcher.py
    scope: "做什么：\n- 定义「harness 可启动程序」契约：entry 启动方式（由 params.yaml 声明）与逐轮 stdio JSONL 收发协议。\n- 实现 HarnessLauncher：按 git ref 把 harness 仓 checkout 到 data/harness_runs/<ref>/，起子进程跑 entry，适配成 spec-0001/T2 的 HarnessInterface（send/reset/close）。\n- 提供 v0 种子 harness_template：entry.py（起单个 nexau）、params.yaml（声明启动命令）、agents/main.md（单 agent 定义）。\n不做什么：\n- 不实现 harness 内部的多 agent 编排——entry 内部如何组织 1 或 N 个 nexau 由 harness 仓自身决定，launcher 视其为黑盒。\n- 不负责 harness 仓的建仓与推送（归 spec-0002/T3），不负责取哪个 ref 的决策（归 T4/T6）。\n- 不实现流式、工具调用透传、token 统计——协议只覆盖逐轮整段收发。\n- 不做并发多会话；一个 launch() 对应一个子进程、一条会话。"
    acceptance: "- launcher 能按某 ref checkout 并启动 entry，经 HarnessInterface 多轮 send/reply、可 reset（重启）、close（终止）。\n- checkout 写到 data/harness_runs/<ref>/，同 ref 重复 launch 复用该目录。\n- 子进程启动失败、ref 不存在、stdout 非法 JSON 或缺 reply 键、子进程提前退出 EOF，均显式抛错。\n- close 幂等；close 后再 send 抛错。\n- harness_template 是合法 v0：params.yaml 声明的 entry 可启动，单 nexau 按协议逐轮收发。"
  - id: T2
    title: nexau_runtime 与角色定义
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/nexau_runtime.py
      - backend/agent_defs/user_agent/prompt.md
      - backend/tests/test_nexau_runtime.py
    scope: "做什么：\n- 定义角色定义的目录布局契约：backend/agent_defs/<role>/ 下含 prompt.md（必需）与可选工具配置（如 tools.yaml）。\n- 实现 nexau_runtime：load(agent_def_dir) 读取一份定义、构造对 nexau 的薄封装 Agent；Agent.run(input) 执行一次调用并返回输出。\n- 落地 user_agent 角色定义（backend/agent_defs/user_agent/prompt.md）作为首个消费者，对接 spec-0001 UserAgent 所需的 LLM 后端。\n不做什么：\n- 不抽象多运行时（CC/codex 接入为后续目标，本任务只服务 nexau）。\n- 不实现 developer/test 角色定义（分属 T3/T4）。\n- 不负责角色定义的语义正确性评测（prompt 内容质量不在本任务校验范围，只校验可被 load）。\n- 不实现会话级状态管理、多轮记忆——run 是一次调用，多轮编排由消费方（UserAgent/run_session）负责。"
    acceptance: "- load 能读取一份角色定义目录并构造 Agent；目录缺失或缺 prompt.md 时抛错。\n- Agent.run 透传输入到 nexau、返回输出（可 mock nexau 验证）。\n- backend/agent_defs/user_agent/prompt.md 合法、可被 load。\n- 无工具配置时 Agent 为纯文本角色可正常 run。"
  - id: T3
    title: developer_agent
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T2
      - 0002/T2
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/dev/developer_agent.py
      - backend/agent_defs/developer_agent/prompt.md
      - backend/tests/dev/test_developer_agent.py
    scope: "做什么：\n- 实现 DeveloperAgent：从 IssueTracker 取一条 open issue，按 label 分流到分支策略，checkout harness 仓建分支，用 nexau（developer_agent 定义）改 harness bundle，commit/push，并在 issue 上 comment 关联分支。\n- 落地 backend/agent_defs/developer_agent/prompt.md（读 issue + harness bundle、产出修改的角色定义）。\n- MVP 单 agent、一次处理一条 issue、串行。\n不做什么：\n- 不负责候选合并与发版（归 T5），不负责体感判定/门禁（归 T4）。\n- 不做并发多 agent、不做分支冲突自动解决。\n- 不决定一轮处理几条 issue（编排归 T6），work_one 只处理一条。\n- 不实现 issue 的产生（归用户侧 spec-0001）。"
    acceptance: "- 给定一条 bug issue，在 harness 仓从 release 切出快修分支并产出一次修改提交；给定 feature issue，切出 feature 分支并提交；分流正确。\n- 无 open issue 时 work_one 返回空结果、不建分支、不报错。\n- nexau 未产出改动时不空提交、在 issue 上 comment 说明。\n- 提交后在对应 issue 上留有关联分支名的 comment。"
  - id: T4
    title: test_agent 体感门禁
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
      - 0001/T4
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/dev/test_agent.py
      - backend/agent_defs/test_agent/prompt.md
      - backend/tests/dev/test_test_agent.py
    scope: "做什么：\n- 实现 TestAgent：对候选 harness ref 用 T1 launcher 起服务，对固定 (persona, scenario) 集跑 run_session×N，算平均体感，与当前 release 基线均值比较，不退化（容差内）则放行。\n- 定义门禁判定语义：均值不低于基线减容差 → pass，否则 fail。\n- 落地 backend/agent_defs/test_agent/prompt.md（若评测复用 user_agent 跑会话，本任务负责测试侧角色定义/配置）。\n不做什么：\n- 不引入 benchmark 参与判定——benchmark 全程 held-out，只在 metrics（T6）事后观测、不投票。\n- 不负责合并/发版（归 T5），不负责产生候选分支（归 T3）。\n- 不实现固定集的来源构造（persona/scenario 集由用户侧/distill 提供，本任务消费）。\n- 不实现基线的写入（基线是 release 版历史体感，写入归用户侧 run_session/SessionStore）。"
    acceptance: "- 对一个候选 ref 跑 |集|×N 局得平均体感，与基线按 mean >= baseline - tol 判定，返回 Verdict(pass/mean/baseline)。\n- N、tol 可配；候选均值持平基线时放行。\n- 基线缺失时按约定放行并在 Verdict 标记 baseline 不可用。\n- evaluate 不接收任何 benchmark 输入（held-out 在签名层即成立）。\n- 固定集为空或 N<=0 时抛错；某局失败计为最低分并记录失败局数。"
  - id: T5
    title: release 发版
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T4
      - 0002/T3
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/dev/release.py
      - backend/tests/dev/test_release.py
    scope: "做什么：\n- 实现 release：体感门禁 Verdict 通过时，把候选分支合入 harness 仓 release 分支并打 tag（单调递增版本号），关联 issue 置 closed；返回 ReleaseResult。\n- Verdict 否决时不动 release、不打 tag，可在关联 issue 上 comment 否决原因。\n不做什么：\n- 不含评测/门禁逻辑（归 T4，本任务消费其 Verdict）。\n- 不决定何时调用、跑几轮（编排归 T6）。\n- 不引入语义化版本/发版说明生成/版本管理框架。\n- 不负责候选分支的产生（归 T3）。"
    acceptance: "- verdict.pass 的候选被合入 release 分支并打出新 tag（版本号 = 旧最大 +1）；返回 released=True 且带 tag/ref。\n- verdict.pass=False 时 release 分支与 tag 不变；返回 released=False。\n- 给定 tracker+issue_number 时：通过则 issue 置 closed，否决则 issue 留否决 comment；缺省时跳过且不报错。\n- candidate_branch 不存在或合并冲突时抛错、release 分支保持原状。"
  - id: T6
    title: 闭环编排与曲线
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T3
      - T4
      - T5
      - 0001/T4
      - 0001/T6
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/loop/orchestrator.py
      - backend/auto_designer/loop/metrics.py
      - backend/tests/loop/test_orchestrator.py
      - backend/tests/loop/test_metrics.py
    scope: "做什么：\n- 实现 orchestrator：把一轮 a（用户会话产 issue + 体感）→ b（开发者改、测试门禁、发版）→ c（新版回到 a）串成 run_round，并提供 run(n_rounds) 跑多轮。\n- 实现 metrics：从 Gitea + 本地 SessionStore 统计 issue 数量随时间的曲线（开/关/净未解）与体感趋势。\n- 各部件经依赖注入，便于 mock 整轮。\n不做什么：\n- 不实现各部件本身（run_session/developer_agent/test_agent/release 分属 spec-0001 与 T3/T4/T5），orchestrator 只编排。\n- 不做流水线/并发/分支合并策略调优（MVP 顺序单轮）。\n- 不让 benchmark 参与编排或发版判定——benchmark 仅由 metrics 旁路观测、不进入 run_round 的控制流。\n- metrics 不自建存储，只读 Gitea 与 SessionStore。"
    acceptance: "- run_round 跑通一轮 a→b→c（各部件可 mock），返回新 release_ref；发版时为新 tag、未发版时为旧 ref。\n- run(n_rounds) 把每轮 new_release_ref 喂下一轮，返回长度为 n_rounds 的 ref 链。\n- 无 issue / 门禁否决的轮次沿用旧 release_ref、不中断。\n- metrics.issue_curve() 产出 (opened, closed, net_open) 时间序列；feeling_trend() 产出体感随时间序列。\n- benchmark 不出现在 run_round 控制流中（仅 metrics 旁路）。"
---

# 0003 · 开发者侧与闭环

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

本组实现 **b｜开发者侧** 与 **c｜闭环回灌**，把前两组的零件总装成可重复的进化轮次。一轮 = a（用户产 issue + 体感）→ b（开发者改 harness、测试体感门禁、发版）→ c（新版 harness 回到 a）。

一轮闭环（节点后标负责任务）：

```
a  用户会话(0001 run_session, harness=launch(release)) ─产→ issue(Gitea) + 体感(SessionStore)
        │
b       ├ developer_agent(T3)  取 issue → 按 label 分流 → 改 harness 分支
        ├ test_agent(T4)       候选 ref 跑 N 局算平均体感，与 release 基线比 → 体感门禁
        └ release(T5)          过门禁则合入 release 分支 + 打 tag（= 新版本）
        │
c  orchestrator(T6) 把新 tag 作为下一轮 a 的 harness，循环；metrics(T6) 记 issue 数~时间曲线
```

支撑件：**T1** launcher 把「某版 harness 程序」接成 0001 的 `HarnessInterface`（粘合层），并给出 v0 种子 `harness_template`；**T2** 是 user/developer/test 三角色共用的 nexau 适配层。本组核心约束：**门禁只用体感，benchmark 全程 held-out**（只事后观测、不参与发版判定）。

## Motivation

### T1 harness launcher 与 harness_template

harness 是独立可启动程序（可单/多 agent），用户侧只认 HarnessInterface。launcher 是二者的粘合层；
harness_template 提供进化的 v0 起点。二者一起定义了「harness 程序」的启动与 I/O 契约。

### T2 nexau_runtime 与角色定义

MVP 只接 nexau 一种运行时，三角色仅 prompt/工具不同。把「加载定义并运行」收敛成一处，
避免每个角色各写一套；user_agent 定义补上 spec-0001 中被抽象为「注入 LLM」的那一块。

### T3 developer_agent

issue 要变成 harness 的真实改动。label(bug/feature) 驱动分支策略——bug 走 release 快修、feature 走
独立分支孵化——正是 CLAUDE.md 用「分支模型」化解「增量打补丁 vs 结构性改动」张力的落点。

### T4 test_agent 体感门禁

发版要有客观闸门，且必须守住 train/test 分离：门禁只看体感回归，benchmark 全程 held-out。
测试 agent 复用用户侧 run_session——「评一个 harness」就是「让用户 agent 用它跑几局看体感」。

### T5 release 发版

闭环要有「定版」动作把候选变成可被用户侧使用的稳定版本。tag 提供可 pin、可回溯的版本标识；
release 分支是用户侧默认运行的线。

### T6 闭环编排与曲线

前面各部件都是零件，orchestrator 是总装：定义一轮 a→b→c 怎么跑、跑几轮。metrics 落实 CLAUDE.md 要求的
「issue 数量~时间曲线」，用于判断探索(新 issue)与收敛(解决)是否平衡。

## Guide-level explanation

### T1 harness launcher 与 harness_template

把「被进化的 harness」接成 spec-0001 的 HarnessInterface：launcher 按 git ref 取出某版 harness、
启动其自带 entry、按黑盒逐轮协议适配为 send/reset/close。harness_template 给出 v0（单 nexau）作为起点。

### T2 nexau_runtime 与角色定义

单一 nexau 适配层：把一份角色定义(prompt+工具)加载成可调用的 agent，供 user/developer/test 三角色共用。
本任务并落地 user_agent 角色定义作为首个消费者，验证适配可跑。

### T3 developer_agent

开发者 agent：从 Gitea 取一条 open issue，按 label 分流到对应分支策略，用 nexau 修改 harness bundle 并提交。
MVP 单 agent 串行，是闭环 b 段的核心。

### T4 test_agent 体感门禁

测试 agent：用候选 harness ref 跑固定集的 N 局用户会话，算平均体感并与当前 release 基线比较，
不退化则放行。这是发版门禁，且只用体感——benchmark 不参与判定。

### T5 release 发版

发版：体感门禁通过的候选分支合入 harness 仓 release 分支并打 tag；tag 即用户侧下一轮 pin 的版本。
否决则不动 release。

### T6 闭环编排与曲线

orchestrator 把用户侧(a)、开发者侧(b)、回灌(c) 串成可重复的进化轮次；metrics 从 Gitea 与本地 session
统计 issue 数量随时间的曲线与体感趋势。这是整个系统的总装与观测。

## Reference-level explanation

### T1 harness launcher 与 harness_template

启动契约（launcher 与 harness 程序之间）：
- params.yaml 声明启动命令，至少含 `entry`（启动命令的 argv 列表）与可选 `cwd`、`env`。launcher 据此起子进程，不硬编码解释器或路径。
- 子进程启动后进入逐轮循环：从 stdin 逐行读一条 JSON `{"message": str}`，处理后向 stdout 逐行写一条 JSON `{"reply": str}`（行尾换行分隔，即 JSONL）。一读一写严格配对。
- 内部 1 或 N 个 nexau 如何编排、harness 一轮内部跑几步，对 launcher 不可见。

HarnessLauncher 接口（类型层面）：
- `HarnessLauncher(harness_repo: str)`：harness_repo 为 harness 仓本地路径或可 clone 的 URL。
- `launch(ref: str) -> HarnessInterface`：返回一个实现 spec-0001/T2 协议的句柄对象。
- 内部 `_checkout(ref)`：git 把 harness 仓某 ref 取到 data/harness_runs/<ref>/（已存在则复用，保证同 ref 幂等）。

返回句柄实现 HarnessInterface（send/reset/close）的语义：
- `send(message: str) -> str`：向子进程 stdin 写一行 `{"message": message}`，阻塞读一行 `{"reply": ...}`，返回 reply 字符串。
- `reset() -> None`：终止当前子进程并重启 entry，开新一局（最简实现，不要求 harness 自身支持 reset 指令）。
- `close() -> None`：终止子进程、释放管道。

关键时序：
- launch 内先 _checkout(ref)（一次），再起首个子进程；send 在已启动子进程上逐轮收发；reset = close 旧进程 + 起新进程；close 后句柄不可再用。

边界与错误处理：
- 子进程启动失败（命令不存在、entry 崩溃）→ launch 抛错，附 ref 与命令信息。
- send 时子进程已退出或 stdout 读到 EOF → 抛错而非静默返回空串。
- 子进程输出非合法 JSON 或缺 `reply` 键 → 抛错（协议违例显式失败）。
- ref 在 harness 仓不存在 → _checkout 抛错。
- close 幂等：重复 close 不抛错。

关键决策及理由：
- 子进程 + stdio JSONL（而非 import 或 HTTP）：把 harness 当黑盒外部程序，launcher 不依赖其语言/依赖/内部结构，支持任意内部编排与将来换 CC/codex。
- checkout 到 data/harness_runs/<ref>/ 而非临时目录：同 ref 可复用、可人工查验，且与 SessionStore/metrics 的本地 data/ 布局一致。
- reset 用重启子进程实现：harness_template entry 无需实现复位指令，把复位语义收在 launcher 一侧，最简。

**接口**

类型契约：
- `HarnessLauncher(harness_repo: str)`。
- `HarnessLauncher.launch(ref: str) -> HarnessInterface`（HarnessInterface 见 spec-0001/T2：send(str)->str / reset()->None / close()->None）。
- 启动契约：params.yaml 声明 entry argv；子进程逐轮 stdin `{"message": str}` → stdout `{"reply": str}`（JSONL）。
- harness_template 文件面：entry.py、params.yaml、agents/main.md。

**测试**

单测（用最小假 entry，回显或脚本式回复，不依赖真 nexau）：
- launch → 连续多轮 send，断言每轮 reply 与假 entry 脚本一致、一读一写配对。
- reset 后子进程重启、会话状态清空（假 entry 的计数器归零）。
- close 后子进程被终止；重复 close 不抛错；close 后 send 抛错。
- checkout 把内容写到 data/harness_runs/<ref>/；同 ref 二次 launch 复用目录。
- 失败路径：entry 命令不存在 → launch 抛错；假 entry 输出非法 JSON 或缺 reply 键 → send 抛错；假 entry 提前退出 → send 读到 EOF 抛错。

**文件（单一 writer 所有权）**

  - `backend/auto_designer/harness/launcher.py`
  - `backend/harness_template/entry.py`
  - `backend/harness_template/params.yaml`
  - `backend/harness_template/agents/main.md`
  - `backend/tests/harness/test_launcher.py`

### T2 nexau_runtime 与角色定义

目录与加载契约：
- 角色定义位于 backend/agent_defs/<role>/：prompt.md 为系统提示/角色定义（必需）；可选工具配置声明该角色可用的工具。
- `load(agent_def_dir: str) -> Agent`：读取目录、解析 prompt 与工具配置，构造 Agent。目录缺失或缺 prompt.md → 抛错。

Agent 契约（类型层面）：
- `Agent.run(input: str) -> str`：以加载的角色定义为系统侧上下文，对 input 执行一次 nexau 调用，返回模型输出文本。
- Agent 持有底层 nexau 客户端的句柄；run 是对 nexau 的薄封装，不在本层做提示工程或重试逻辑。

关键时序：
- load 一次（读定义、建客户端）→ run 多次（每次独立一调）。同一 Agent 可被消费方多次 run 以驱动多轮，但 run 自身无状态记忆，上下文由调用方拼接传入。

边界与错误处理：
- agent_def_dir 不存在或缺 prompt.md → load 抛错并指明缺失项。
- nexau 后端调用失败（网络/鉴权）→ run 透传错误，不在本层吞掉。
- 工具配置缺省：无 tools 配置时 Agent 为纯文本对话角色（user_agent 即此形态）。

关键决策及理由：
- 三角色共用一份 load/run，仅 prompt 与工具配置不同：把「加载定义并运行」收敛成单点，避免每角色各写一套适配。
- 薄封装、run 无状态：多轮编排与上下文拼接归消费方（spec-0001 UserAgent），nexau_runtime 只做「定义→可调用对象」的转换，职责单一。

**接口**

类型契约：
- `nexau_runtime.load(agent_def_dir: str) -> Agent`。
- `Agent.run(input: str) -> str`。
- 角色定义布局：backend/agent_defs/<role>/prompt.md（必需）+ 可选工具配置。
- 本任务产出 backend/agent_defs/user_agent/prompt.md。

**测试**

单测（mock nexau）：
- load 读取角色定义目录、解析 prompt，构造出 Agent。
- Agent.run 把 input 透传给底层 nexau 并返回其输出（mock 断言入参与返回）。
- load 指向不存在目录或缺 prompt.md 的目录 → 抛错。
- backend/agent_defs/user_agent/ 可被 load 且 run 一次成功（mock 后端）。
- 底层 nexau 调用抛错时 run 透传该错误、不吞掉。

**文件（单一 writer 所有权）**

  - `backend/auto_designer/nexau_runtime.py`
  - `backend/agent_defs/user_agent/prompt.md`
  - `backend/tests/test_nexau_runtime.py`

### T3 developer_agent

一次处理一条 issue 的时序：
① 经 IssueTracker（运行时为 spec-0002/T2 GiteaTracker）取一条 open issue（含 number/title/body/labels）；无 open issue → work_one 返回空结果、不建分支。
② 按 label 定分支策略：含 `bug` 标签 → 从 release 分支切快修分支；含 `feature` 标签 → 切 feature 分支；二者皆无或冲突 → 走默认策略（按 bug 处理，记录于 design 决策）。
③ checkout harness 仓到工作目录，基于策略基线建并切到新分支（分支名含 issue number 以可追溯）。
④ nexau(developer_agent 定义).run 读 issue + harness bundle 内容，产出对 bundle 的修改。
⑤ commit（信息引用 issue number）/push 到该分支；经 tracker.add_comment 在 issue 上留关联分支名的 comment。

分支命名与基线契约：
- bug 快修分支基线 = release 分支（HEAD），命名如 `fix/issue-<number>`。
- feature 分支基线 = release 分支（HEAD），命名如 `feat/issue-<number>`。
- 两类均从 release 切出，差异在于 T5 的合并节奏（bug 快修、feature 孵化后合）与命名前缀，便于人工与编排区分。

接口（类型层面）：
- `DeveloperAgent(tracker: IssueTracker, harness_repo: str, nexau_agent: Agent)`。
- `work_one() -> DevResult`：DevResult 含所处理 issue number、所建 branch、commit sha（或在无 issue/未改动时为空）。

边界与错误处理：
- 无 open issue → 返回空 DevResult，不建分支、不报错。
- nexau 未产出任何文件改动 → 不空提交；在 issue 上 comment 说明未改动，DevResult 标记无 commit。
- label 既无 bug 也无 feature → 默认按 bug 路径（最快反馈），并在 comment 注明分流为默认。
- push 失败 / checkout 失败 → 抛错，附 issue number 与分支名。

关键决策及理由：
- label 驱动分支分流，正是 CLAUDE.md 用「分支模型」化解「增量打补丁 vs 结构性改动」张力的落点：bug 走 release 快迭代、feature 走独立分支孵化。
- 两类分支都从 release 切出（而非 feature 从某长期 dev 分支切）：MVP 保持单一基线、避免多基线合并复杂度；合并策略集中由 T5 决定。
- work_one 只处理一条且无 issue 时返回空：把「处理几条/何时停」的编排决策上移到 T6，本 agent 职责单一、可被反复调用。

**接口**

类型契约：
- `DeveloperAgent(tracker: IssueTracker, harness_repo: str, nexau_agent: Agent)`。
- `DeveloperAgent.work_one() -> DevResult`（DevResult: issue_number? / branch? / commit? / changed: bool）。
- 依赖：IssueTracker（spec-0001/T5 接口，spec-0002/T2 实现）、Agent（T2 nexau_runtime）。

**测试**

单测（mock nexau + FakeTracker/GiteaTracker + 临时 git 仓）：
- bug issue → 从 release 派生 `fix/issue-<n>` 分支、产出一次提交并 push。
- feature issue → 切 `feat/issue-<n>` 分支、产出提交。
- 无 open issue → work_one 返回空、临时仓无新分支。
- nexau 返回无文件改动 → 不产生 commit，issue 上有「未改动」comment。
- 处理后 issue 上出现关联分支名的 comment（断言 tracker.add_comment 入参）。
- label 既无 bug 也无 feature → 走默认（bug 路径），comment 注明默认分流。

**文件（单一 writer 所有权）**

  - `backend/auto_designer/dev/developer_agent.py`
  - `backend/agent_defs/developer_agent/prompt.md`
  - `backend/tests/dev/test_developer_agent.py`

### T4 test_agent 体感门禁

评测时序 `evaluate(candidate_ref) -> Verdict`：
① launcher.launch(candidate_ref) 得 HarnessInterface（候选 harness）。
② 对固定 (persona, scenario) 集，每个场景跑 run_session×N（共 |集|×N 局），收集每局 FeelingScore.score。
③ 算候选均值 mean_candidate（所有局体感分的算术平均）。
④ 取 release 基线均值 baseline（同一固定集在 release 版的历史体感均值，经 SessionStore 索引聚合）。
⑤ 判定：mean_candidate >= baseline - tol → pass，否则 fail。

门禁阈值语义：
- tol 为容差（默认小正数），吸收体感噪声；判据是「候选不显著低于基线」，等号放行（持平即过）。
- N 为每场景局数，跑多局取均值以压低单局方差。
- N 与判定方式（单点均值 vs 分布检验，如 Welch t / 单边区间）列为 spec 待定项，MVP 用均值 + 容差。

held-out 保证（关键约束的落地）：
- evaluate 的输入只有 (candidate_ref, 固定 persona/scenario 集, 基线体感)；签名与实现不接收任何 benchmark 数据源。
- 体感分来自 run_session 的 FeelingScore，与 benchmark 评分无关联路径。benchmark 仅由 T6 metrics 旁路观测，不进入 Verdict。

接口（类型层面）：
- `TestAgent(launcher: HarnessLauncher, fixed_set: list[(Persona, SeedScenario)], baseline: float, n: int, tol: float)`。
- `evaluate(candidate_ref: str) -> Verdict`，Verdict 含 pass: bool / mean: float / baseline: float / n: int / per_session: list[int]。

边界与错误处理：
- 基线缺失（首轮无 release 历史体感）：无可比基线 → MVP 约定放行（pass）并在 Verdict 标记 baseline 不可用，把首版定为基线；该约定显式记录。
- 固定集为空 / N<=0：配置非法 → 抛错。
- 某局 run_session 失败（harness 崩溃）：该局计为最低体感分（1）而非丢弃，避免崩溃局被无声忽略抬高均值；记录失败局数。
- 候选 launch 失败 → evaluate 抛错（无法评测）。

关键决策及理由：
- 评测即「让用户 agent 用候选 harness 跑几局看体感」，复用 spec-0001 run_session：评测与训练信号同源，门禁度量与优化目标一致。
- 跑 N 局取均值：体感是噪声信号、单局方差大，均值是最简的方差压低手段。
- 持平放行（>= baseline - tol）：进化允许平台期，门禁只挡「退化」不挡「未提升」，避免卡死探索。
- 失败局计 1 分而非丢弃：防止「崩溃即跳过」让不稳定候选反而更易过门禁。

**接口**

类型契约：
- `TestAgent(launcher: HarnessLauncher, fixed_set: list[tuple[Persona, SeedScenario]], baseline: float, n: int, tol: float)`。
- `TestAgent.evaluate(candidate_ref: str) -> Verdict`（Verdict: pass: bool / mean: float / baseline: float / n: int / per_session: list[int]）。
- 依赖：HarnessLauncher（T1）、run_session（spec-0001/T4）、SessionStore 索引（spec-0001/T6，取基线）。

**测试**

单测（FakeHarness + mock LLM 注入体感分，不依赖真模型/真 launcher）：
- 候选均值 > 基线 → pass；候选均值 == baseline - tol 边界 → pass；< baseline - tol → fail。
- N 可配：改 N 改变跑的局数与 per_session 长度（断言 run_session 调用次数 = |集|×N）。
- 基线缺失 → pass 且 Verdict 标记 baseline 不可用。
- 某局 run_session 抛错 → 该局计体感 1 分、记入失败局数、不中断整次评测。
- 固定集为空或 N<=0 → 抛错。

**文件（单一 writer 所有权）**

  - `backend/auto_designer/dev/test_agent.py`
  - `backend/agent_defs/test_agent/prompt.md`
  - `backend/tests/dev/test_test_agent.py`

### T5 release 发版

发版时序 `release(harness_repo, candidate_branch, verdict, tracker?, issue_number?) -> ReleaseResult`：
- verdict.pass 为真：
  ① 在 harness 仓把 candidate_branch 合入 release 分支（fast-forward 或 merge commit，见决策）。
  ② 打 tag：版本号 = 现有最大版本 + 1，tag 名即版本（如 v3）。
  ③ 若给定 tracker 与 issue_number，将关联 issue 置 closed（tracker.set_state）。
  ④ 返回 ReleaseResult(released=True, tag=<新 tag>, ref=<新 release HEAD 或 tag>)。
- verdict.pass 为假：
  ① 不合并、不打 tag、不动 release 分支。
  ② 若给定 tracker 与 issue_number，在 issue 上 comment 否决原因（取自 Verdict 的 mean/baseline）。
  ③ 返回 ReleaseResult(released=False, tag=None)。

版本号契约：
- 单调递增整数计数，tag 名由其派生；新版本号 = 扫描 harness 仓现有 tag 取最大值 +1（无 tag 则从 v1 起）。
- tag 即用户侧下一轮 pin 的版本标识（T6 把 ReleaseResult.ref/tag 作为下一轮 launch 的 ref）。

接口（类型层面）：
- `release(harness_repo: str, candidate_branch: str, verdict: Verdict, tracker: IssueTracker | None, issue_number: int | None) -> ReleaseResult`。
- ReleaseResult: released: bool / tag: str | None / ref: str | None。

边界与错误处理：
- candidate_branch 不存在 → 抛错。
- 合并冲突（candidate 与 release 分叉冲突）：MVP 不自动解冲突 → 抛错、release 分支保持原状、返回失败信息；自动解冲突列为后续。
- tracker/issue_number 缺省（None）→ 跳过 issue 状态/comment 操作，仅做 git 合并 + tag。
- 重复对同一已合入候选调用 → 合并为 no-op（幂等），版本号仍递增打新 tag 还是复用，按「无实际差异不打新 tag」处理避免空版本。

关键决策及理由：
- 发版 = 合并 + tag 的轻动作，不引版本管理框架：奥卡姆，发版语义就是「定一个可 pin 的稳定点」。
- 版本号用单调计数而非语义化版本：MVP 无 major/minor/patch 语义需求；可比较、可排序、可回溯即足。
- issue 关闭/comment 走 tracker 且可选：发版与 issue 跟踪解耦，git 操作不强依赖 Gitea 可达，便于单测只验 git。
- 合并策略默认 merge commit（保留候选分支历史），与 spec-0002/T3「走真实分支/合并」一致；冲突不自动解、显式失败，避免静默错误合并。

**接口**

类型契约：
- `release(harness_repo: str, candidate_branch: str, verdict: Verdict, tracker: IssueTracker | None, issue_number: int | None) -> ReleaseResult`。
- ReleaseResult: released: bool / tag: str | None / ref: str | None。
- 依赖：Verdict（T4）、IssueTracker（spec-0001/T5 接口）、harness 仓（spec-0002/T3）。

**测试**

单测（临时 git 仓 + FakeTracker）：
- pass → candidate 合入 release，出现新 tag（版本号递增），ReleaseResult.released=True。
- fail → release HEAD 与 tag 集合不变，ReleaseResult.released=False。
- pass 且给 tracker → issue 被 set_state 为 closed；fail 且给 tracker → issue 上有否决 comment。
- tracker=None → 仅做 git 合并 + tag、不调用 tracker、不报错。
- candidate_branch 不存在 → 抛错；制造合并冲突 → 抛错且 release 分支不变。
- 无任何现有 tag 时首次发版从 v1 起。

**文件（单一 writer 所有权）**

  - `backend/auto_designer/dev/release.py`
  - `backend/tests/dev/test_release.py`

### T6 闭环编排与曲线

一轮编排时序 `run_round(release_ref) -> new_release_ref`：
a) 对固定/采样的 (persona, scenario) 集，以 harness=launcher.launch(release_ref) 跑 run_session：产 issue 入 Gitea（经 IssueTracker）、体感入 SessionStore。
b) developer_agent.work_one() 取一条 issue 改 harness、产候选分支 → test_agent.evaluate(candidate_ref) 得 Verdict → release(harness_repo, candidate_branch, verdict, ...) 得 ReleaseResult。
c) 若 ReleaseResult.released：new_release_ref = ReleaseResult.ref/tag；否则 new_release_ref = release_ref（沿用旧版，本轮无发版）。返回 new_release_ref 供下一轮 a。

`run(n_rounds)`：以初始 release_ref 起，循环调用 run_round、把返回的 new_release_ref 喂下一轮，跑 n_rounds 轮；记录每轮的 release_ref 链。

无发版 / 无 issue 的轮次语义：
- a 段未产出任何 issue，或 b 段无 open issue 可处理 → 本轮无候选、不发版，new_release_ref = release_ref；轮次仍计数、metrics 仍记录该轮 a 段产出。
- test_agent 否决 → 不发版，沿用旧 release_ref。

metrics 契约：
- `issue_curve()`：从 Gitea 拉 issue 的 created/closed 时间戳 → 按时间产出 (opened, closed, net_open) 序列；net_open = 累计开 − 累计关，即 CLAUDE.md「净未解 issue」曲线。
- `feeling_trend()`：从 SessionStore 索引取每局体感分与时间 → 体感随时间序列（可按轮/按时间窗聚合均值）。
- held-out 观测：benchmark 分数（若有）只作为 metrics 的旁路观测序列，与 issue_curve/feeling_trend 并列展示，不参与任何 run_round 决策。

接口（类型层面）：
- `Orchestrator(launcher, fixed_set, tracker, store, developer_agent, test_agent, release_fn)`：全部依赖注入。
- `Orchestrator.run_round(release_ref: str) -> str`；`Orchestrator.run(n_rounds: int) -> list[str]`（各轮 release_ref 链）。
- `Metrics(tracker, store)`：`issue_curve() -> list[(t, opened, closed, net_open)]`；`feeling_trend() -> list[(t, score)]`。

边界与错误处理：
- n_rounds <= 0 → 抛错。
- 某轮 b 段部件抛错（developer/test/release 失败）→ 本轮失败上抛，编排不静默吞错；run 可选择记录已完成轮次后中止。
- metrics 数据源为空（首轮前）→ 返回空序列，不抛错。

关键决策及理由：
- run_round 输入输出皆为 release_ref：把「版本回灌」显式化为函数签名，闭环 c 段即「返回值喂下一轮入参」，无隐藏状态。
- 顺序单轮（a 全跑完再 b）：奥卡姆，MVP 不做流水线；编排逻辑可读、可单测。
- 无发版轮次沿用旧 ref：闭环不因某轮未通过门禁而中断，保证可持续多轮、与「issue 曲线长期观测」一致。
- metrics 只读 Gitea + SessionStore：不自建存储、不与权威源双写，issue 权威在 Gitea、体感权威在 SessionStore。
- 可恢复运行与 checkpoint 不在本任务：run_round/run 保持纯编排（无隐藏状态、可单测）；沙盒易失下的恢复由 spec-0004 的 harbor runner 在外层包裹——逐轮调 run_round、每轮 save_checkpoint，run() 自身不做 checkpoint。

**接口**

类型契约：
- `Orchestrator(launcher: HarnessLauncher, fixed_set, tracker: IssueTracker, store: SessionStore, developer_agent: DeveloperAgent, test_agent: TestAgent, release_fn)`。
- `Orchestrator.run_round(release_ref: str) -> str`（新 release_ref）。
- `Orchestrator.run(n_rounds: int) -> list[str]`。
- `Metrics(tracker: IssueTracker, store: SessionStore)`：`issue_curve() -> list[tuple]`；`feeling_trend() -> list[tuple]`。

**测试**

单测（注入 mock 部件）：
- run_round 断言调用次序 a→b→c：先 run_session（产 issue + 体感）、再 work_one → evaluate → release；Verdict.pass 时返回新 ref、否决时返回旧 ref。
- run(n_rounds) 断言 new_release_ref 链式回灌（第 k 轮入参 = 第 k-1 轮返回），返回长度 = n_rounds。
- a 段无 issue 或 b 段无 open issue → 本轮不发版、沿用旧 ref、轮次仍计数。
- metrics.issue_curve() 对构造的 created/closed 时间产出正确 (opened, closed, net_open) 序列。
- metrics.feeling_trend() 对构造的 SessionStore 索引产出正确体感随时间序列；数据源为空时返回空序列。
- n_rounds<=0 抛错；b 段部件抛错时编排上抛、不静默吞错。

**文件（单一 writer 所有权）**

  - `backend/auto_designer/loop/orchestrator.py`
  - `backend/auto_designer/loop/metrics.py`
  - `backend/tests/loop/test_orchestrator.py`
  - `backend/tests/loop/test_metrics.py`

依赖 DAG：`0001/T2 → T1`，`T2 → T3`，`0002/T2 → T3`，`T1 → T4`，`T2 → T4`，`0001/T4 → T4`，`T4 → T5`，`0002/T3 → T5`，`T3 → T6`，`T4 → T6`，`T5 → T6`，`0001/T4 → T6`，`0001/T6 → T6`

## Drawbacks

<!-- 待填 -->

## Rationale and alternatives

### T1 harness launcher 与 harness_template

- 进程接入方式：子进程 + stdio JSONL vs Python import vs 本地 HTTP 服务。选子进程 + JSONL——对 harness 内部实现零假设、最大解耦、契合「兼容 CC/codex」；代价是进程启动与序列化开销，自用规模可接受。import 方式要求 harness 是 Python 包且共享依赖，违背黑盒原则；HTTP 引入端口管理与服务生命周期，过重。
- reset 实现：重启子进程 vs 协议加 reset 指令 vs 每局新 launch。选重启子进程——seed entry 不必实现复位、语义集中在 launcher；协议加指令会增加 harness 侧契约负担；每局新 launch 则要重复 checkout、浪费。
- checkout 落地：data/harness_runs/<ref>/ 复用 vs 每次临时目录。选前者——同 ref 幂等复用、可查验；临时目录每次重拉、不可追溯。
- 协议传输单元：逐轮整段 JSONL vs 流式分块。选逐轮整段——与 HarnessInterface 的 send->完整 reply 语义一致、实现最简；流式留待真实交互暴露需求再扩。

### T2 nexau_runtime 与角色定义

- 运行时抽象：薄封装单一 nexau vs 预留多运行时抽象层。选薄封装（YAGNI/奥卡姆）——CC/codex 是后续目标，现在多一层抽象只增复杂度；接入时再在 load 内分发。
- 定义格式：目录 + prompt.md(+可选工具配置) vs 单一 YAML 清单 vs 代码内常量。选目录布局——prompt 用 markdown 便于人写人读、工具配置可选挂载、三角色同构；单 YAML 把长 prompt 塞进字段不便编辑；代码内常量不可被非工程改。
- run 状态：无状态单次调用 vs 内置多轮会话对象。选无状态——多轮语义已由 UserAgent/run_session 持有，runtime 再持一份会话状态会与消费方重复且易漂移。

### T3 developer_agent

- 并发度：单 agent 串行 vs 并发多 agent。选串行（奥卡姆）——并发引入分支冲突解决与 issue 抢占，MVP 不需要；规模化后再加。
- 分流粒度：bug/feature 两标签 vs 含优先级/类型的多维分流。选两标签——恰好驱动两条分支路径，够用；更细分类后续按需加。
- feature 分支基线：从 release 切 vs 从长期 dev 分支切。选从 release 切——单一基线、合并语义简单；长期 dev 分支会引入二级合并，MVP 不必要。
- 无改动处理：comment 说明 + 不空提交 vs 强制空提交占位。选前者——空提交污染历史且无信息量，comment 已能追溯。

### T4 test_agent 体感门禁

- 判定方式：均值 + 容差 vs 分布检验（t 检验/区间）vs 单局比较。选均值 + 容差（MVP）——最简且对小 N 稳健；分布检验更严谨但需先定显著性水平与样本量，列为待定项；单局比较方差过大不可用。
- 门禁信号：只用体感 vs 体感 + benchmark 混合。选只用体感——守住 train/test 分离与 held-out；代价是可能放过 benchmark 上变差的改动，而这正是设计接受的（benchmark 只观测不投票）。
- 失败局处理：计最低分 vs 丢弃 vs 整体判失败。选计最低分——既不被无声忽略、又不让单局偶发崩溃一票否决整次评测。
- 基线缺失：首版放行设为基线 vs 阻塞等待人工基线。选前者——闭环需自启动，首版天然是后续基线；阻塞会卡住第一轮。

### T5 release 发版

- 版本标识：单调计数 tag vs 语义化版本（semver）vs commit sha。选单调计数（奥卡姆）——可排序可 pin、无需 major/minor 语义；semver 需变更分级规则，过早；sha 不可读、不表达版本顺序。
- 合并方式：merge commit vs fast-forward vs squash。选 merge commit——保留候选分支历史、契合「走真实分支/合并」；ff 要求线性、squash 丢历史。
- 冲突处理：显式抛错 vs 自动解冲突 vs 强制覆盖。选抛错（MVP）——自动解冲突复杂且易错，强制覆盖会丢 release 既有改动；显式失败交由上层/人工处理。
- issue 联动：可选 tracker 参数 vs 强制 tracker。选可选——发版核心是 git 动作，issue 跟踪为旁路，解耦便于测试与离线运行。

### T6 闭环编排与曲线

- 编排粒度：顺序单轮 a→b→c vs 流水线/并发跑多会话与多 issue。选顺序单轮（奥卡姆）——逻辑清晰、易单测；并发引入会话/分支调度，规模化后再优化。
- 版本回灌方式：run_round 显式收发 release_ref vs orchestrator 内部持有当前版本状态。选显式 ref——闭环 c 段在签名层即可见、无隐藏状态、便于按轮注入与回放。
- 无发版轮处理：沿用旧 ref 继续 vs 中止闭环。选沿用——观测指标要求长期跑、看 issue 曲线是否平衡，单轮不过门禁不应终止整个进化。
- metrics 存储：只读 Gitea + SessionStore vs 自建指标库。选只读（奥卡姆）——避免与权威源双写漂移；聚合在读时计算，数据量小可接受。
- benchmark 位置：metrics 旁路观测 vs 进入编排/门禁。选旁路——守住 held-out 与 train/test 分离，benchmark 只验证不投票。

## Prior art

### T1 harness launcher 与 harness_template

HarnessInterface 协议：spec-0001/T2（send/reset/close）。harness 仓来源与 release 分支：spec-0002/T3。
CLAUDE.md 架构「被进化对象：harness 作为可启动程序」「兼容 claude code / codex 接入」。

### T2 nexau_runtime 与角色定义

运行时与角色：CLAUDE.md 架构「nexau 作为 agent 实现，兼容 claude code / codex 接入」。
user_agent 消费方：spec-0001/T3（UserAgent）。多轮编排入口：spec-0001/T4（run_session）。

### T3 developer_agent

nexau_runtime/Agent：T2。IssueTracker 接口：spec-0001/T5；GiteaTracker 实现：spec-0002/T2。
harness 仓与 release 分支：spec-0002/T3。CLAUDE.md 方法 b「bug → release 分支，大 feature → feature 分支」。

### T4 test_agent 体感门禁

run_session：spec-0001/T4。基线（历史体感索引）：spec-0001/T6（SessionStore）。launcher：T1。
CLAUDE.md 约束「发版门禁只用体感；benchmark 只用于观测」「benchmark 全程 held-out」。

### T5 release 发版

门禁 Verdict：T4。IssueTracker.set_state/add_comment：spec-0001/T5、spec-0002/T2。
harness 仓与 release 分支：spec-0002/T3。CLAUDE.md 方法 b「合并和发版前由测试 agent 内测」「过门禁则合入 release 分支 + 打 tag」。

### T6 闭环编排与曲线

run_session：spec-0001/T4。SessionStore（体感索引）：spec-0001/T6。IssueTracker：spec-0001/T5。
launcher：T1。developer/test/release：T3/T4/T5。可恢复 harbor 运行入口与 checkpoint：spec-0004。
CLAUDE.md「c｜闭环：发版后的新 harness 回到用户侧，循环」「观测指标：记录 issue 数量随时间的曲线」「benchmark 全程 held-out」。

## Unresolved questions

<!-- 待填 -->

## Future possibilities

<!-- 待填 -->

