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

直接对轨迹做自进化，容易把轨迹特征带进 harness、产生对 benchmark 的局部过拟合；破局之道是把训练信号（用户体感）与测试信号（benchmark）分离，本组要把这一原则落实到「开发者如何迭代 harness」与「新版本如何回到用户侧」两个环节。

harness 是独立可启动程序（可单/多 agent），用户侧只认 HarnessInterface；要把「某个 git ref 的 harness」变成可对话的对象，需要一层粘合——这是 T1 harness launcher 的动机，同时给出 v0 种子 harness_template 作为进化起点。MVP 阶段用户/开发者/测试三个角色都只接 nexau 一种运行时、仅 prompt 与工具配置不同，因此 T2 把「加载定义并运行」收敛成一处 nexau_runtime，避免每个角色各写一套；user_agent 定义顺带补上 spec-0001 中被抽象为「注入 LLM」的那一块。

有了这两层支撑，issue 要能变成 harness 的真实改动：T3 developer_agent 按 label(bug/feature) 驱动分支策略——bug 走 release 快修、feature 走独立分支孵化——正是 CLAUDE.md 用「分支模型」化解「增量打补丁 vs 结构性改动」张力的落点。但发版不能没有客观闸门，且必须守住 train/test 分离：T4 test_agent 复用用户侧 run_session（「评一个 harness」就是「让用户 agent 用它跑几局看体感」），只用体感回归判定是否放行，benchmark 全程 held-out。门禁通过后，闭环要有「定版」动作把候选变成可被用户侧使用的稳定版本：T5 release 把候选合入 release 分支并打 tag，提供可 pin、可回溯的版本标识。

最后，前面各部件都是零件，需要总装：T6 orchestrator 定义一轮 a→b→c 怎么跑、跑几轮；同任务下的 metrics 落实 CLAUDE.md 要求的「issue 数量~时间曲线」，用于判断探索(新 issue)与收敛(解决)是否平衡。

## Guide-level explanation

整套系统对外呈现为一条可重复运行的流水线，由两层支撑件与三段主流程构成。支撑层：T1 launcher 把「被进化的 harness」接成 spec-0001 的 HarnessInterface——按 git ref 取出某版 harness、启动其自带 entry、按黑盒逐轮协议适配为 send/reset/close，harness_template 给出 v0（单 nexau）作为起点；T2 nexau_runtime 是单一 nexau 适配层，把一份角色定义(prompt+工具)加载成可调用的 agent，供 user/developer/test 三角色共用，并落地 user_agent 角色定义作为首个消费者验证适配可跑。

在此基础上，b 段三步依次发生：T3 developer_agent 从 Gitea 取一条 open issue，按 label 分流到对应分支策略，用 nexau 修改 harness bundle 并提交（MVP 单 agent 串行），是闭环 b 段的核心；T4 test_agent 用候选 harness ref 跑固定集的 N 局用户会话，算平均体感并与当前 release 基线比较，不退化则放行——这是发版门禁，且只用体感，benchmark 不参与判定；T5 release 把体感门禁通过的候选分支合入 harness 仓 release 分支并打 tag，tag 即用户侧下一轮 pin 的版本，否决则不动 release。

最外层由 T6 收口：orchestrator 把用户侧(a)、开发者侧(b)、回灌(c) 串成可重复的进化轮次；metrics 从 Gitea 与本地 session 统计 issue 数量随时间的曲线与体感趋势——这是整个系统的总装与观测。

## Reference-level explanation

本组由两层支撑件与三段主流程组成：T1（launcher/harness_template）与 T2（nexau_runtime）是地基，T3（developer_agent）→T4（test_agent）→T5（release）构成 b 段流水线，T6（orchestrator/metrics）在最外层把 a→b→c 串成可重复轮次；完整依赖 DAG 见本节末。

**支撑层：launcher 与 harness_template（T1）**。启动契约约定 harness 程序与 launcher 之间如何对接：params.yaml 声明启动命令，至少含 `entry`（argv 列表）与可选 `cwd`、`env`，launcher 据此起子进程、不硬编码解释器或路径；子进程启动后进入逐轮循环，从 stdin 逐行读一条 JSON `{"message": str}`、向 stdout 逐行写一条 JSON `{"reply": str}`（JSONL，一读一写严格配对），内部 1 或 N 个 nexau 如何编排、harness 一轮内部跑几步，对 launcher 不可见。类型层面：`HarnessLauncher(harness_repo: str).launch(ref: str) -> HarnessInterface`（HarnessInterface 即 spec-0001/T2 的 send/reset/close 协议）；内部 `_checkout(ref)` 用 git 把 harness 仓某 ref 取到 `data/harness_runs/<ref>/`（已存在则复用，保证同 ref 幂等）。返回句柄语义：`send` 写一行读一行并返回 reply 字符串；`reset` 终止当前子进程并重启 entry（不要求 harness 自身支持复位指令）；`close` 终止子进程、释放管道、幂等。时序上 launch 先 `_checkout` 一次再起首个子进程，`reset` 等价于 close 旧进程加起新进程，close 后句柄不可再用。错误处理：子进程启动失败、send 时子进程已退出或 stdout 读到 EOF、输出非法 JSON 或缺 `reply` 键、ref 不存在，均显式抛错而非静默返回；close 幂等。关键决策：用子进程+stdio JSONL 而非 import 或 HTTP，把 harness 当黑盒外部程序、不依赖其语言/依赖/内部结构，为兼容 CC/codex 留余地，代价是进程与序列化开销、自用规模可接受；reset 用重启子进程而非协议指令实现，复位语义收在 launcher 一侧，harness_template 不必实现复位；checkout 落地到 `data/harness_runs/<ref>/` 而非临时目录，换取同 ref 复用与可人工查验，并与 SessionStore/metrics 的本地 data/ 布局一致；传输单元用逐轮整段 JSONL 而非流式分块，与 HarnessInterface 的 send→完整 reply 语义一致、实现最简。harness_template 作为 v0 种子随 T1 一并交付：entry.py（起单个 nexau）、params.yaml（声明启动命令）、agents/main.md（单 agent 定义）。单测用最小假 entry（回显/脚本式回复，不依赖真 nexau）验证多轮收发一致、reset 后状态清空、close 幂等且 close 后 send 抛错、checkout 同 ref 复用目录，以及 entry 命令不存在、协议违例（非法 JSON/缺 reply）、提前退出（EOF）三类失败路径。T1 全部文件：`backend/auto_designer/harness/launcher.py`、`backend/harness_template/entry.py`、`backend/harness_template/params.yaml`、`backend/harness_template/agents/main.md`、`backend/tests/harness/test_launcher.py`。

**支撑层：nexau_runtime 与角色定义（T2）**。角色定义位于 `backend/agent_defs/<role>/`：prompt.md 必需，可选工具配置声明该角色可用的工具；`load(agent_def_dir: str) -> Agent` 读取目录、解析 prompt 与工具配置构造 Agent，目录缺失或缺 prompt.md 时抛错。`Agent.run(input: str) -> str` 是对底层 nexau 的薄封装——以加载的角色定义为系统侧上下文执行一次调用并返回输出，不做提示工程或重试，也不持有多轮记忆，上下文拼接归消费方（spec-0001 UserAgent）负责。时序上 load 一次（读定义、建客户端），run 可被消费方多次调用以驱动多轮，但每次调用彼此独立。错误处理：agent_def_dir 不存在或缺 prompt.md 时 load 抛错并指明缺失项；nexau 后端调用失败（网络/鉴权）时 run 透传错误、不在本层吞掉；无工具配置时 Agent 为纯文本对话角色，user_agent 即此形态。关键决策：三角色（user/developer/test）共用同一份 load/run、仅 prompt 与工具配置不同，把「加载定义并运行」收敛成单点，避免每角色各写一套适配；run 保持薄封装、无状态，因为多轮编排与上下文拼接已由消费方持有，nexau_runtime 只做「定义→可调用对象」的单一转换。本任务落地 `backend/agent_defs/user_agent/prompt.md` 作为首个消费者。单测（mock nexau）覆盖 load 读取并构造 Agent、run 透传入参与返回（mock 断言）、目录缺失或缺 prompt.md 时抛错、user_agent 目录可被 load 且 run 一次成功、底层调用抛错时 run 透传不吞掉。T2 全部文件：`backend/auto_designer/nexau_runtime.py`、`backend/agent_defs/user_agent/prompt.md`、`backend/tests/test_nexau_runtime.py`。

**b 段第一步：developer_agent（T3）**。`work_one()` 依次执行：① 经 IssueTracker（运行时为 spec-0002/T2 GiteaTracker）取一条 open issue（含 number/title/body/labels），无 open issue 时返回空结果、不建分支；② 按 label 定分支策略——含 `bug` 标签从 release 分支切快修分支 `fix/issue-<n>`，含 `feature` 标签切 `feat/issue-<n>`，二者皆无或冲突时按 bug 处理（默认策略，comment 注明分流为默认）；③ checkout harness 仓到工作目录，基于 release HEAD 建并切到新分支（分支名含 issue number 以可追溯）；④ nexau(developer_agent 定义).run 读 issue + harness bundle 内容，产出对 bundle 的修改；⑤ commit（信息引用 issue number）/push 到该分支，经 tracker.add_comment 在 issue 上留关联分支名的 comment。两类分支均从 release 切出，差异只在 T5 的合并节奏（bug 快修、feature 孵化后合）与命名前缀，便于人工与编排区分。类型层面：`DeveloperAgent(tracker: IssueTracker, harness_repo: str, nexau_agent: Agent).work_one() -> DevResult`（DevResult: issue_number? / branch? / commit? / changed: bool）。错误处理：无 open issue 时返回空 DevResult、不建分支不报错；nexau 未产出任何文件改动时不空提交，仅在 issue 上 comment 说明并标记无 commit；push 或 checkout 失败抛错并附 issue number 与分支名。关键决策：label 驱动分支分流，正是 CLAUDE.md 用「分支模型」化解「增量打补丁 vs 结构性改动」张力的落点；两类分支都从 release 切出而非某长期 dev 分支，MVP 保持单一基线、避免多基线合并复杂度、合并策略集中由 T5 决定；work_one 只处理一条、无 issue 时返回空，把「处理几条/何时停」的编排决策上移到 T6，agent 本身职责单一、可反复调用。单测（mock nexau + FakeTracker/GiteaTracker + 临时 git 仓）覆盖 bug issue 派生 `fix/issue-<n>` 分支并提交、feature issue 切 `feat/issue-<n>` 分支并提交、无 open issue 返回空且不建分支、nexau 无改动时不产生 commit 且留「未改动」comment、处理后 issue 上出现关联分支名的 comment、label 缺失时走默认（bug）路径并在 comment 注明。T3 全部文件：`backend/auto_designer/dev/developer_agent.py`、`backend/agent_defs/developer_agent/prompt.md`、`backend/tests/dev/test_developer_agent.py`。

**b 段第二步：test_agent 体感门禁（T4）**。`evaluate(candidate_ref) -> Verdict` 依次执行：① `launcher.launch(candidate_ref)` 得候选 HarnessInterface；② 对固定 (persona, scenario) 集，每个场景跑 `run_session×N`（共 |集|×N 局），收集每局 FeelingScore.score；③ 算候选均值 mean_candidate；④ 取同一固定集在 release 版的历史体感均值 baseline（经 SessionStore 索引聚合）；⑤ 判定 `mean_candidate >= baseline - tol` 则 pass，否则 fail。tol 为容差、吸收体感噪声，判据是「候选不显著低于基线」、等号放行（持平即过）；N 为每场景局数，跑多局取均值压低单局方差；N 与判定方式（均值+容差 vs 分布检验，如 Welch t / 单边区间）列为 spec 待定项，MVP 用均值+容差。held-out 保证在签名层即成立：evaluate 的输入只有 candidate_ref、固定 persona/scenario 集与基线体感，不接收任何 benchmark 数据源；体感分只来自 run_session 的 FeelingScore，与 benchmark 评分无关联路径，benchmark 仅由 T6 metrics 旁路观测、不进入 Verdict。类型层面：`TestAgent(launcher: HarnessLauncher, fixed_set: list[tuple[Persona, SeedScenario]], baseline: float, n: int, tol: float).evaluate(candidate_ref: str) -> Verdict`（pass: bool / mean: float / baseline: float / n: int / per_session: list[int]）。错误处理：基线缺失（首轮无 release 历史体感）时 MVP 约定放行（pass）并在 Verdict 标记 baseline 不可用、把首版定为基线；固定集为空或 N<=0 抛错；某局 run_session 失败（harness 崩溃）计为最低体感分（1）而非丢弃、记录失败局数，避免崩溃局被无声忽略抬高均值；候选 launch 失败则 evaluate 抛错。关键决策：评测即「让用户 agent 用候选 harness 跑几局看体感」、复用 spec-0001 run_session，评测与训练信号同源、门禁度量与优化目标一致；跑 N 局取均值是压低单局方差最简的手段；持平放行（>= baseline - tol）让门禁只挡「退化」不挡「未提升」，避免卡死探索；失败局计 1 分而非丢弃，防止「崩溃即跳过」让不稳定候选反而更易过门禁。单测（FakeHarness + mock LLM 注入体感分，不依赖真模型/真 launcher）覆盖候选均值 > 基线、== baseline - tol 边界、< baseline - tol 三档判定，N 可配（断言 run_session 调用次数 = |集|×N），基线缺失时放行并标记不可用，某局抛错计 1 分且不中断整次评测，固定集为空或 N<=0 抛错。T4 全部文件：`backend/auto_designer/dev/test_agent.py`、`backend/agent_defs/test_agent/prompt.md`、`backend/tests/dev/test_test_agent.py`。

**b 段第三步：release 发版（T5）**。`release(harness_repo, candidate_branch, verdict, tracker?, issue_number?) -> ReleaseResult`：verdict.pass 为真时，在 harness 仓把 candidate_branch 以 merge commit 合入 release 分支（保留候选历史）、打新 tag（版本号 = 现有最大版本 + 1，无 tag 则从 v1 起）、若给定 tracker 与 issue_number 则将关联 issue 置 closed，返回 `ReleaseResult(released=True, tag=<新 tag>, ref=<新 release HEAD 或 tag>)`；verdict.pass 为假时不合并、不打 tag、不动 release 分支，若给定 tracker 与 issue_number 则在 issue 上 comment 否决原因（取自 Verdict 的 mean/baseline），返回 `ReleaseResult(released=False, tag=None)`。版本号为单调递增整数计数，新版本号 = 扫描 harness 仓现有 tag 取最大值 +1；tag 即用户侧下一轮 pin 的版本标识（T6 把 ReleaseResult.ref/tag 作为下一轮 launch 的 ref）。类型层面：`release(harness_repo: str, candidate_branch: str, verdict: Verdict, tracker: IssueTracker | None, issue_number: int | None) -> ReleaseResult`（ReleaseResult: released: bool / tag: str | None / ref: str | None）。错误处理：candidate_branch 不存在抛错；合并冲突时 MVP 不自动解冲突、抛错且 release 分支保持原状；tracker/issue_number 缺省（None）时跳过 issue 状态/comment 操作、仅做 git 合并+tag；重复对同一已合入候选调用按「无实际差异不打新 tag」处理，合并为 no-op（幂等），避免空版本。关键决策：发版 = 合并+tag 的轻动作、不引版本管理框架，语义就是「定一个可 pin 的稳定点」；版本号用单调计数而非语义化版本，MVP 无 major/minor/patch 语义需求，可比较可排序可回溯即足；issue 关闭/comment 走 tracker 且可选，使发版与 issue 跟踪解耦，git 操作不强依赖 Gitea 可达；合并策略默认 merge commit，与 spec-0002/T3「走真实分支/合并」一致，冲突不自动解、显式失败以避免静默错误合并。单测（临时 git 仓 + FakeTracker）覆盖 pass 时候选合入 release 并出现新 tag、fail 时 release HEAD 与 tag 集合不变、pass/fail 时对应的 issue 状态变更与否决 comment、tracker=None 时仅做 git 操作不报错、candidate_branch 不存在或合并冲突时抛错且 release 分支不变、无任何现有 tag 时首次发版从 v1 起。T5 全部文件：`backend/auto_designer/dev/release.py`、`backend/tests/dev/test_release.py`。

**总装与观测：orchestrator 与 metrics（T6）**。`run_round(release_ref) -> new_release_ref` 串起一轮 a→b→c：a) 对固定/采样的 (persona, scenario) 集，以 `harness=launcher.launch(release_ref)` 跑 run_session，产 issue 入 Gitea（经 IssueTracker）、体感入 SessionStore；b) `developer_agent.work_one()` 取一条 issue 改 harness 产候选分支 → `test_agent.evaluate(candidate_ref)` 得 Verdict → `release(harness_repo, candidate_branch, verdict, ...)` 得 ReleaseResult；c) 若 released 则 `new_release_ref = ReleaseResult.ref/tag`，否则沿用旧 release_ref，返回值即下一轮 a 的入参。`run(n_rounds)` 以初始 release_ref 起循环调用 run_round、把返回值喂下一轮，记录每轮 release_ref 链。a 段未产出任何 issue、b 段无 open issue 可处理、或 test_agent 否决时，本轮不发版、new_release_ref = release_ref，但轮次仍计数、metrics 仍记录该轮 a 段产出——闭环不因单轮未过门禁而中断。metrics 契约：`issue_curve()` 从 Gitea 拉 issue 的 created/closed 时间戳，按时间产出 (opened, closed, net_open) 序列，net_open = 累计开 − 累计关，即 CLAUDE.md「净未解 issue」曲线；`feeling_trend()` 从 SessionStore 索引取每局体感分与时间，产出体感随时间序列（可按轮/按时间窗聚合均值）；benchmark 分数（若有）只作为旁路观测序列与二者并列展示，不参与任何 run_round 决策。类型层面：`Orchestrator(launcher, fixed_set, tracker, store, developer_agent, test_agent, release_fn)` 全部依赖注入，`run_round(release_ref: str) -> str`、`run(n_rounds: int) -> list[str]`（各轮 release_ref 链）；`Metrics(tracker: IssueTracker, store: SessionStore)` 提供 `issue_curve() -> list[tuple]`、`feeling_trend() -> list[tuple]`。错误处理：`n_rounds <= 0` 抛错；某轮 b 段部件（developer/test/release）抛错时本轮失败上抛、编排不静默吞错，run 可选择记录已完成轮次后中止；metrics 数据源为空（首轮前）返回空序列、不抛错。关键决策：run_round 输入输出皆为 release_ref，把「版本回灌」显式化为函数签名，闭环 c 段即「返回值喂下一轮入参」、无隐藏状态；MVP 取顺序单轮（a 全跑完再 b）而非流水线/并发，编排逻辑可读、可单测；无发版轮次沿用旧 ref，闭环不因某轮未通过门禁而中断，保证可持续多轮、与「issue 曲线长期观测」一致；metrics 只读 Gitea + SessionStore、不自建存储、不与权威源双写，issue 权威在 Gitea、体感权威在 SessionStore；可恢复运行与 checkpoint 不在本任务范围，run_round/run 保持纯编排（无隐藏状态、可单测），沙盒易失下的恢复由 spec-0004 的 harbor runner 在外层包裹——逐轮调 run_round、每轮 save_checkpoint，run() 自身不做 checkpoint。单测（注入 mock 部件）覆盖 run_round 调用次序 a→b→c（先 run_session，再 work_one→evaluate→release）、Verdict.pass 时返回新 ref 否决时返回旧 ref、run(n_rounds) 的链式回灌（第 k 轮入参 = 第 k-1 轮返回）与返回长度、a/b 段无 issue 时本轮不发版但轮次仍计数、issue_curve 对构造的 created/closed 时间产出正确序列、feeling_trend 对构造的 SessionStore 索引产出正确序列且空数据返回空序列、n_rounds<=0 抛错、b 段部件抛错时编排上抛不吞错。T6 全部文件：`backend/auto_designer/loop/orchestrator.py`、`backend/auto_designer/loop/metrics.py`、`backend/tests/loop/test_orchestrator.py`、`backend/tests/loop/test_metrics.py`。

依赖 DAG：`0001/T2 → T1`，`T2 → T3`，`0002/T2 → T3`，`T1 → T4`，`T2 → T4`，`0001/T4 → T4`，`T4 → T5`，`0002/T3 → T5`，`T3 → T6`，`T4 → T6`，`T5 → T6`，`0001/T4 → T6`，`0001/T6 → T6`

## Drawbacks

<!-- 待填 -->

## Rationale and alternatives

本组的取舍反复回到三个跨部件的原则性问题：黑盒隔离要做到什么程度、门禁只信任体感的代价是否可接受、以及编排要多「重」。

**接入方式与运行时抽象（T1/T2）**：launcher 在子进程+stdio JSONL、Python import、本地 HTTP 三者间选子进程+JSONL——对 harness 内部实现零假设、最大解耦、契合「兼容 CC/codex」的长期目标，代价是进程启动与序列化开销，自用规模可接受；import 要求 harness 与本仓共享语言与依赖、违背黑盒原则，HTTP 引入端口与服务生命周期管理、过重。reset 在重启子进程、协议加 reset 指令、每局新 launch 三者间选重启子进程——语义集中在 launcher 一侧，harness_template 不必实现复位指令；协议加指令会增加 harness 侧契约负担，每局新 launch 则要重复 checkout、浪费。checkout 选落地到 `data/harness_runs/<ref>/` 复用而非每次临时目录，换取同 ref 幂等复用与可人工查验，并与 SessionStore/metrics 的本地 data/ 布局一致；协议传输单元选逐轮整段 JSONL 而非流式分块，与 HarnessInterface 的 send→完整 reply 语义一致、实现最简，流式留待真实交互暴露需求再扩。nexau_runtime 在薄封装单一 nexau 与预留多运行时抽象层之间选前者（YAGNI/奥卡姆）——CC/codex 接入是后续目标，现在多一层抽象只增复杂度，接入时再在 load 内分发；角色定义格式在目录+prompt.md(+可选工具配置)、单一 YAML 清单、代码内常量三者间选目录布局——prompt 用 markdown 便于人写人读、工具配置可选挂载、三角色同构，单 YAML 把长 prompt 塞进字段不便编辑，代码内常量不可被非工程改；run 选无状态单次调用而非内置多轮会话对象，因为多轮语义已由 UserAgent/run_session 持有，runtime 再持一份会话状态会与消费方重复且易漂移。

**分支与版本模型（T3/T5）**：developer_agent 的并发度选单 agent 串行（奥卡姆）而非并发多 agent——并发引入分支冲突解决与 issue 抢占，MVP 不需要，规模化后再加；分流粒度选 bug/feature 两标签而非含优先级/类型的多维分流，两标签恰好驱动两条分支路径、够用，更细分类后续按需加；feature 分支基线选从 release 切而非从长期 dev 分支切，保持单一基线、合并语义简单，长期 dev 分支会引入二级合并、MVP 不必要；无改动处理选 comment 说明+不空提交而非强制空提交占位，因为空提交污染历史且无信息量、comment 已能追溯。release 的版本标识在单调计数 tag、语义化版本(semver)、commit sha 三者间选单调计数（奥卡姆）——可排序可 pin、无需 major/minor 语义，semver 需变更分级规则、过早，sha 不可读也不表达版本顺序；合并方式选 merge commit 而非 fast-forward 或 squash，保留候选分支历史、契合「走真实分支/合并」，ff 要求线性、squash 丢历史；冲突处理选显式抛错（MVP）而非自动解冲突或强制覆盖，因为自动解冲突复杂且易错、强制覆盖会丢 release 既有改动，显式失败交由上层/人工处理；issue 联动做成可选 tracker 参数而非强制 tracker，因为发版核心是 git 动作、issue 跟踪为旁路，解耦便于测试与离线运行。

**门禁哲学（T4）**：判定方式在均值+容差、分布检验(t 检验/区间)、单局比较三者间选均值+容差（MVP）——最简且对小 N 稳健，分布检验更严谨但需先定显著性水平与样本量、列为待定项，单局比较方差过大不可用；门禁信号在只用体感与体感+benchmark 混合之间选只用体感——守住 train/test 分离与 held-out，代价是可能放过 benchmark 上变差的改动，而这正是设计接受的（benchmark 只观测不投票）；失败局处理在计最低分、丢弃、整体判失败三者间选计最低分——既不被无声忽略、又不让单局偶发崩溃一票否决整次评测；基线缺失时选首版放行设为基线而非阻塞等待人工基线，因为闭环需自启动、首版天然是后续基线，阻塞会卡住第一轮。

**编排粒度（T6）**：编排粒度选顺序单轮 a→b→c（奥卡姆）而非流水线/并发跑多会话与多 issue——逻辑清晰、易单测，并发引入会话/分支调度、规模化后再优化；版本回灌选 run_round 显式收发 release_ref 而非 orchestrator 内部持有当前版本状态，使闭环 c 段在签名层即可见、无隐藏状态、便于按轮注入与回放；无发版轮处理选沿用旧 ref 继续而非中止闭环，因为观测指标要求长期跑、看 issue 曲线是否平衡，单轮不过门禁不应终止整个进化；metrics 存储选只读 Gitea+SessionStore 而非自建指标库（奥卡姆）——避免与权威源双写漂移，聚合在读时计算、数据量小可接受；benchmark 位置选 metrics 旁路观测而非进入编排/门禁，守住 held-out 与 train/test 分离，benchmark 只验证不投票。

## Prior art

各部件的先例均在本组内部或前序 spec 中：T1 launcher 承接 spec-0001/T2 的 HarnessInterface 协议（send/reset/close）与 spec-0002/T3 的 harness 仓/release 分支来源，落实 CLAUDE.md 架构「被进化对象：harness 作为可启动程序」与「兼容 claude code / codex 接入」。T2 nexau_runtime 对应 CLAUDE.md「nexau 作为 agent 实现，兼容 claude code / codex 接入」，其首个消费方是 spec-0001/T3 UserAgent，多轮编排入口为 spec-0001/T4 run_session。T3 developer_agent 依赖 T2 的 Agent、spec-0001/T5 的 IssueTracker 接口与 spec-0002/T2 的 GiteaTracker 实现、spec-0002/T3 的 harness 仓与 release 分支，对应 CLAUDE.md 方法 b「bug → release 分支，大 feature → feature 分支」。T4 test_agent 复用 spec-0001/T4 run_session 与 spec-0001/T6 SessionStore（基线索引）、依赖 T1 launcher，落实 CLAUDE.md 约束「发版门禁只用体感；benchmark 只用于观测」与「benchmark 全程 held-out」。T5 release 消费 T4 的 Verdict，经 spec-0001/T5 与 spec-0002/T2 的 IssueTracker.set_state/add_comment 操作 spec-0002/T3 的 harness 仓与 release 分支，对应 CLAUDE.md 方法 b「合并和发版前由测试 agent 内测」「过门禁则合入 release 分支 + 打 tag」。T6 orchestrator 与 metrics 总装前述所有部件（run_session：spec-0001/T4；SessionStore：spec-0001/T6；IssueTracker：spec-0001/T5；launcher：T1；developer/test/release：T3/T4/T5），可恢复 harbor 运行入口与 checkpoint 留给 spec-0004，对应 CLAUDE.md「c｜闭环：发版后的新 harness 回到用户侧，循环」「观测指标：记录 issue 数量随时间的曲线」「benchmark 全程 held-out」。

## Unresolved questions

<!-- 待填 -->

## Future possibilities

<!-- 待填 -->

