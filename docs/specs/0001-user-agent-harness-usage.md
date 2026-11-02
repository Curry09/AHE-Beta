---
number: "0001"
title: 用户 agent 使用 harness 的最小链路
issue: 0
slug: user-agent-harness-usage
summary: 本组实现进化闭环的 **a｜用户侧**：让 user agent 扮成真实用户，按 persona + 种子场景多轮使用 harness，产出两类信号——**体感评分**（训练信号）与 **issue**（bug/需求）。本组只搭「最小链路」，且全部用 Fake 后端，不依赖真 Gitea / 真 harness，可独立测；真后端由 0002（Gitea）、0003（harness）补齐。
tasks:
  - id: T1
    title: 用户侧数据模型
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/models.py
      - backend/tests/test_models.py
    scope: "定义用户侧七个公共数据结构及其序列化契约，按在一局会话中的角色分层：\n- 给定输入：Persona（用户画像）、SeedScenario（种子场景）。\n- 过程产物：Transcript（多轮对话记录）。\n- 会话产出：FeelingScore（1–4 体感评分 + 理由）、IssueDraft（问题草稿 title/body/labels）、IssueRef（Gitea 回执 number/url/state）。\n- 顶层封装：Session（聚合上述六者的一局完整记录）。\n仅含数据定义与 to_dict/from_dict；对话驱动、评分、提交、落盘逻辑分属 T2–T6，不在本任务。"
    acceptance: "- 七个 dataclass 均可构造，且 to_dict→from_dict round-trip 后字段级一致。\n- FeelingScore.score 越界（0/5）在构造期断言失败；Transcript role 非法值同样被拒。\n- IssueDraft.labels 缺省空列表；Session 在 0 条 issue 时 issue_refs 为空列表。\n- datetime 字段序列化为 ISO-8601 且可逆。"
  - id: T2
    title: Harness 对话接口
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/harness/interface.py
      - backend/tests/harness/test_interface.py
    scope: "做什么：\n- 定义 HarnessInterface 多轮对话协议（typing.Protocol），方法集为 send / reset / close。\n- 提供测试后端 FakeHarness，支持以「回复脚本」或「回调」两种方式注入确定性回复，并记录收发序列供断言。\n- 定义协议的状态机语义与调用契约（生命周期、幂等性、异常约定），使 T3/T4 可仅依赖协议编程。\n不做什么：\n- 不实现任何真实后端；launcher 启动 harness 程序并适配成本协议归 spec-0003。\n- 协议不含流式输出、工具调用回执、token/用量统计、并发会话等扩展面（见 tradeoffs）。\n- 不负责会话内容的语义（用户话术、终止判定属 T3；编排与落盘属 T4/T6）。"
    acceptance: "- HarnessInterface 三方法均有完整类型标注，且 FakeHarness 通过 isinstance/结构匹配满足该 Protocol。\n- FakeHarness 以 script 注入时，多轮 send 按序返回脚本各条；以 callback 注入时，返回 callback(message)。\n- script 与 callback 同时传入时构造期报错（互斥校验）。\n- reset 后 sent 清空、脚本游标归零；可重新开局逐轮收发。\n- close 后调用 send 或 reset 抛 RuntimeError；重复 close 不报错（幂等）。\n- send 返回类型恒为 str，空回复以空串表达且不被判为错误。"
  - id: T3
    title: 用户 agent 驱动器
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/user/user_agent.py
      - backend/tests/user/test_user_agent.py
    scope: "做什么：\n- 实现 persona 驱动的多轮对话循环：给定 Persona+SeedScenario，逐轮经 LLM 生成用户消息、调 harness.send 读回复、写入 Transcript。\n- 实现「用户自判终止」：解析 LLM 输出中的结束信号即停，并以 max_turns 硬上限兜底。\n- 会话结束后经 LLM 产出一条合法 FeelingScore（1–4 + reason）。\n- issue 产出实现最小桩：会话末由 LLM 产 0..n 条 IssueDraft（方案 a，见 open-questions），不锁死机制。\n不做什么：\n- 不实现具体 LLM 客户端（模型后端由调用方注入），不定义提示词工程细节之外的模型路由/重试。\n- 不提交 issue（提交归 T5/T4），不落盘（归 T6/T4），不构造 harness 后端（归 T2/T4）。\n- 不做逐轮体感打分（决定见 tradeoffs：会话末一次性产出）。"
    acceptance: "- 用 FakeHarness + mock LLM 可跑通一局多轮对话，Transcript 轮次与 harness 收发序列一致。\n- 自判终止生效：mock LLM 在第 k 轮发结束信号时，会话恰好进行 k 轮。\n- max_turns 兜底生效：mock LLM 永不发结束信号时，user 轮数恰为 max_turns。\n- 会话末产出合法 FeelingScore（score ∈ 1..4，含 reason）；越界分数在构造期失败。\n- issue 桩产出 0..n 条 IssueDraft，0 条时返回空列表。\n- max_turns <= 0 构造期断言失败。\n- run 全程不调用 harness.reset/close。"
  - id: T4
    title: 会话编排 runner
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
      - T3
      - T5
      - T6
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/user/session.py
      - backend/tests/user/test_session.py
    scope: "做什么：\n- 提供单一无状态入口函数 run_session，编排一局完整会话。\n- 负责 harness 的生命周期（开局 reset、收尾 close），调用 UserAgent.run 取 (Transcript, FeelingScore, drafts)。\n- 将每条 IssueDraft 经 IssueTracker 提交，收集 IssueRef；组装 Session 并经 SessionStore 落盘后返回。\n- 全部依赖经参数注入，runner 自身不构造任何后端。\n不做什么：\n- 不构造 harness / llm / tracker / store（由调用方注入）。\n- 不做跨会话并发/批量编排（归 loop/ 层），不做 issue 曲线统计（归 metrics/ 层）。\n- 不实现对话逻辑（T3）、提交逻辑（T5）、持久化逻辑（T6）本身，只做编排与生命周期管理。"
    acceptance: "- 用 Fake(harness/tracker/store) + mock LLM 端到端返回完整 Session（含 persona/scenario/transcript/feeling/issue_refs）。\n- harness.reset 与 harness.close 各恰调一次，且 reset 先于 user_agent.run、close 在其后（或异常时仍执行）。\n- 每条 draft 经 tracker.create_issue 得到带号 IssueRef，issue_refs 顺序与 drafts 对应。\n- 0 条 draft 时 issue_refs 为空列表且 store 仍落盘该局。\n- store 已写盘该 Session（可经 load 还原）。\n- 提前放弃的会话其 user 轮数 < max_turns，且仍返回完整 Session。\n- user_agent.run 抛异常时 harness.close 仍被调用，且不落盘、不提交。"
  - id: T5
    title: IssueTracker 接口与 FakeTracker
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/tracker/base.py
      - backend/ahe_beta/tracker/fake.py
      - backend/tests/tracker/test_fake.py
    scope: "做什么：\n- 定义 IssueTracker 协议（typing.Protocol），方法集为 ensure_labels / create_issue / add_comment / set_state。\n- 明确各方法的类型契约、发号与状态语义，使其与 Gitea 后端语义对齐（FakeTracker 与 GiteaTracker 对 run_session 等价）。\n- 提供内存实现 FakeTracker：自增发号、维护 issue 表与标签集，供单测与无 Gitea 环境端到端跑通。\n不做什么：\n- 不实现真实 GiteaTracker（HTTP 客户端、鉴权、重试）——归 spec-0002。\n- 不照搬 Gitea 全量 API（里程碑、指派、搜索、分页等不纳入）。\n- 不负责何时产 IssueDraft（归 T3）、何时调用提交（归 T4）。"
    acceptance: "- IssueTracker 四方法均有完整类型标注，FakeTracker 结构匹配满足该 Protocol。\n- create_issue 返回 IssueRef，number 从 1 起单调递增，初始 state 为 \"open\"，url 由 number 确定性合成。\n- add_comment 后该 issue 评论列表含该 body；set_state 后 state/reason 被更新。\n- ensure_labels 幂等：重复传入同名标签不重复创建；空列表为 no-op。\n- 对不存在 number 调用 add_comment/set_state 抛 KeyError；set_state 非法 state 抛 ValueError。\n- 同一 draft 两次 create_issue 得到两个不同 number（不去重）。"
  - id: T6
    title: 本地 SessionStore
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/user/session_store.py
      - backend/tests/user/test_session_store.py
    scope: "做什么：\n- 将一局 Session 全量持久化为 root/<session_id>.json（证据文件）。\n- 维护单一总索引 root/index.json，每局追加一条最小统计记录 {session_id, score, created_at, n_issues}。\n- 提供按 id 读回全量、读总索引的能力，供 loop/metrics 画体感与 issue 曲线、供 dev 侧取回归基线。\n不做什么：\n- 不做数据库/外部存储；不做查询引擎（按字段过滤/聚合归 metrics 层消费索引）。\n- 不处理并发写索引的竞态（单进程 MVP，并发归 loop 层并行时再解决）。\n- 不负责 Session 的产生（归 T4）与序列化契约本身（归 T1 的 to_dict/from_dict）。"
    acceptance: "- save(session) 写出 root/<session_id>.json 全量文件，并在 root/index.json 追加一条含 {session_id, score, created_at, n_issues}。\n- root 目录不存在时 save 自动创建。\n- load(session_id) 还原与原 Session 字段级等价（依赖 T1 round-trip）。\n- index() 返回的条目 score 等于 session.feeling.score、created_at 为 ISO-8601、n_issues 等于 issue_refs 长度。\n- load 不存在 id 抛 FileNotFoundError；首次 index()（无索引文件）返回空列表。\n- 同一 session 两次 save：全量文件被覆盖，索引出现两条（不去重）。"
---

# 0001 · 用户 agent 使用 harness 的最小链路

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

本组实现进化闭环的 **a｜用户侧**：让 user agent 扮成真实用户，按 persona + 种子场景多轮使用 harness，产出两类信号——**体感评分**（训练信号）与 **issue**（bug/需求）。本组只搭「最小链路」，且全部用 Fake 后端，不依赖真 Gitea / 真 harness，可独立测；真后端由 0002（Gitea）、0003（harness）补齐。

数据流脊柱（贯穿 T1…T6，后面每个任务都挂在这条线上）：

```
Persona / SeedScenario ─► UserAgent(T3) ⇄ HarnessInterface(T2) ─► Transcript
                                  │
                                  ├─► FeelingScore 1–4(+理由) ─► SessionStore(T6) 落本地
                                  └─► IssueDraft 0..n ─[IssueTracker(T5)]► Gitea ─► IssueRef
        run_session(T4) 收集上述 ─► Session（结构由 T1 定义）
```

读图即读任务：**T1** 定全部数据结构（地基，被其余任务共用）；**T2** 定与 harness 的对话契约；**T3** 是训练信号的产生点（扮得像不像真人决定信号真不真）；**T5** 定 issue 的去向；**T6** 定体感落地；**T4** 把它们编排成「跑一局」的唯一入口 `run_session`。下游：0003 的闭环直接复用 `run_session`。

## Motivation

整条进化闭环的训练信号来自「模拟真实使用」：user agent 按 persona 与种子场景多轮使用 harness，产出体感评分与 issue。要让这一信号可复现、可统计、可喂给开发者侧，首先要把一局使用会话的输入与产出固化为稳定结构（T1），这是其余任务共用的地基，否则驱动与编排都无从谈起。

CLAUDE.md 要求 harness 兼容 nexau / claude code / codex，用户侧因此只应依赖一个稳定的对话协议而非绑定具体后端（T2）——这也是「被进化对象」与「评测脚手架」解耦的边界，否则每换一个 agent 实现都要改动用户侧代码。

在协议之上，真正决定训练信号是否可信的是驱动器本身（T3）：信号「真不真」取决于它扮演得「像不像真人」——会追问、会绕路、会卡住、会受够了放弃，而不是机械跑满固定轮数。

数据结构、协议与驱动器就绪后，闭环编排（loop/）与统计（metrics/）都需要一个稳定的「跑一局」入口，把组装逻辑收在单一 runner 中，上层只管喂输入、收 Session，不关心内部怎么对话（T4）。

会话产出的两类信号各有去向：issue 最终提交至 Gitea，但用户侧逻辑与单测不应依赖一个运行中的服务，因此以 IssueTracker 接口隔离后端——测试用 FakeTracker，运行时注入 GiteaTracker，二者对 run_session 等价（T5）；体感则是训练信号本身，必须可追溯、可统计，Session 全量留作证据，索引供 loop/metrics 画 issue/体感曲线、供 dev 侧取回归基线（T6）。

## Guide-level explanation

用户侧最小链路的公共数据结构由 T1 统一定义，被其余任务共用：以 Persona（用户画像）与 SeedScenario（种子场景）为给定输入，经多轮对话产出一局 Session，其中封装 Transcript（对话记录）、FeelingScore（1–4 体感评分及理由）、IssueDraft（用户 agent 产出的问题草稿 title/body/labels）与 IssueRef（issue 提交至 Gitea 后的回执 number/url/state）。该任务只定义结构本身，要求纯数据、可双向序列化；对话与评分逻辑由后续任务实现。

被使用的 harness 由 T2 抽象为统一的多轮对话协议 HarnessInterface，使用户侧与具体 agent 实现解耦。该协议是「被进化对象」（harness）与「评测脚手架」（用户侧）之间的稳定边界：用户侧仅依赖协议，具体后端是一个「可启动程序」（内部可为单或多 nexau，由其入口脚本编排），通过 launcher 接入（见 spec-0003）；T2 只定义协议并提供测试后端 FakeHarness。

在协议之上，T3 的用户 agent 驱动器模拟真实用户：依据 Persona 与 SeedScenario 驱动与 harness 的多轮对话，由 agent 自主判定对话终止时机，并在会话结束时产出体感评分（FeelingScore，1–4 及理由）。这是训练信号的产生点，信号的真实性取决于该驱动器对真实使用行为（追问、绕路、卡顿、放弃）的拟真程度，而非机械跑满固定轮数；issue 产出在此任务仅实现最小桩，具体机制待定（见 Unresolved questions）。

T4 提供用户侧的最小可用入口：单一无状态函数 run_session 将 Persona、SeedScenario、HarnessInterface 与 UserAgent 编排为一局会话，收集 Transcript、FeelingScore 与 IssueDraft，返回结构化的 Session。所有依赖由参数注入，runner 自身不构造任何后端，便于测试替换与上层（loop 编排、metrics 统计）复用。

会话产出的两类信号在此汇入各自出口：issue 的提交去向由 T5 抽象为 IssueTracker 接口，使用户侧不绑定具体 tracker 后端，该任务提供内存实现 FakeTracker，使 run_session 在无 Gitea 环境下可端到端测试，真实 GiteaTracker 实现归 spec-0002；体感与 Session 则由 T6 的 SessionStore 持久化到本地——全量文件 + 一个总索引，索引承载体感曲线与回归基线所需的最小信息（session_id、体感分、时间），无需打开全量文件即可统计。

## Reference-level explanation

全部数据结构用 dataclass 实现，纯数据、无行为，可双向 dict/json 序列化；协议一律用 typing.Protocol（PEP 544，结构化子类型）表达，测试后端与运行时后端对协议等价，可互相替换而不影响上层。体感与 Session 落本地 `data/sessions/`；issue 不落本地，由 IssueDraft 经 IssueTracker 提交至 Gitea，回执为 IssueRef。本组覆盖范围内的数据流：

```
Persona ─┐
         ├─► UserAgent ⇄ HarnessInterface ─► Transcript
SeedScenario ─┘                │
                               ├─► FeelingScore (1-4 + reason)
                               └─► IssueDraft (0..n) ─[IssueTracker]→ Gitea ─► IssueRef
          run_session 收集 ─► Session(含 transcript/feeling/issue_refs)
```

**数据模型（T1）** 定义七个 dataclass，按其在一局会话中的角色分层：给定输入 Persona（身份、水平、领域、目标、说话风格；来源归后续 distill spec）与 SeedScenario（初始诉求/任务描述，非测试用例）；过程产物 Transcript（有序 (role, content) 轮次列表，role ∈ {user, harness}）；会话产出 FeelingScore（score:int(1..4) + reason:str，一局一个，会话末产出）、IssueDraft（title/body/labels，一局 0..n 条）、IssueRef（number/url/state，Gitea 回执）；顶层封装 Session（session_id/created_at/persona/scenario/transcript/feeling/issue_refs）。序列化契约：to_dict 产出纯 JSON 可序列化结构（嵌套 dataclass 递归转 dict，datetime 转 ISO-8601 字符串），from_dict 为其逆且遇未知键忽略，以兼容字段前向演化（旧代码读新数据不崩）；选 json 而非 yaml 落盘，因 Session 按局逐条追加，json 行利于体感曲线/回归基线的流式统计，人读性交给 summary/OVERVIEW 视图承担。不变量在 `__post_init__` 断言（FeelingScore.score ∈ 1..4；Transcript 每轮 role ∈ {user, harness}），越界即构造期失败，不引入外部校验器。持久化边界上，体感与 Session 落本地（由 T6 落盘），issue 不落本地——其权威存储是 Gitea，本地只持 IssueRef 回执，杜绝双写漂移。`models.py` 暴露上述 dataclass 及其 to_dict/from_dict，不依赖其它模块，处于依赖图最底层。单测覆盖：各 dataclass round-trip(to_dict/from_dict) 字段级一致（含嵌套 Session→Transcript/FeelingScore/IssueRef）；FeelingScore 越界(0/5)、Transcript 非法 role 均在构造期断言失败；IssueDraft.labels 与 Session.issue_refs 默认空列表；datetime 序列化为 ISO-8601 字符串且可逆；from_dict 对未知键忽略不报错。

**Harness 对话接口（T2）** 将被使用的 harness 抽象为统一的多轮对话协议 HarnessInterface，是「被进化对象」（harness）与「评测脚手架」（用户侧）之间的稳定边界：具体后端是一个「可启动程序」（内部可为单或多 nexau，由其入口脚本编排），通过 launcher 接入（见 spec-0003），用户侧仅依赖协议本身。协议方法只留三件套（新决策，奥卡姆）：`send(message: str) -> str` 发送一条用户消息、返回本轮完整回复（非流式，整段文本，message 非空由调用方保证，返回必为 str 且空串合法，不等同于错误）；`reset() -> None` 丢弃当前会话状态、回到新一局起点，幂等；`close() -> None` 释放后端资源（进程/连接/句柄），幂等。合法生命周期为 `(reset? · send* · close)`：reset 为开局显式动作，由编排方（T4）在每局起始调用，不在协议内自动触发，以保持协议无隐式状态；close 之后再调用 send/reset 的行为未定义，允许后端抛异常，FakeHarness 选择抛 RuntimeError 以暴露误用。send 的调用序与 Transcript 的 user 轮次一一对应，harness 回复对应 harness 轮次，协议本身不持有 Transcript，转写归 T3。协议层不规定重试与超时，异常向上传播由编排层（T4）决定处理策略，本协议不吞异常。之所以不直接复用 harbor 的 episode/rollout 批式接口，是因其输入输出粒度是 episode 而非单轮，套到「逐轮真人对话 + 用户自判终止」上语义错位、需大量适配；流式输出、工具调用回执、token/用量统计等扩展面同样按奥卡姆暂不纳入协议方法面，留待真实 nexau 接入暴露需求再扩。FakeHarness 支持两种注入（script：有序 list[str]，按 send 次序逐条弹出；或 callback：Callable[[str], str]，按入参动态产回复），两者互斥、构造时择一；内部记录 `sent: list[str]`（收到的全部 message）供单测断言收发序列与次数；reset 清空 sent 与脚本游标；close 置「已关闭」标志，之后 send/reset 抛 RuntimeError。脚本耗尽策略选择抛 IndexError，而非静默循环或返回空串——后两者会掩盖 T3 终止逻辑跑飞（应由 max_turns 截断而非脚本兜底），抛错则直接暴露测试用例轮数设定不足。接口：`HarnessInterface(Protocol)` { send / reset / close }；`FakeHarness(script: list[str] | None, callback: Callable[[str], str] | None)`：script 与 callback 互斥，二者均空时回复退化为固定占位串，暴露只读属性 `sent: list[str]` 供断言。单测覆盖：script 注入按序返回、sent 记录与传入序列一致；callback 注入按入参动态返回；互斥校验构造期报错；reset 后 sent 清空且脚本游标复位；close 后 send/reset 均抛 RuntimeError、重复 close 不报错；脚本耗尽抛 IndexError；空回复不视为错误。

**用户 agent 驱动器（T3）** 是训练信号的产生点。UserAgent 由注入的 LLM 后端驱动（本组不实现具体模型客户端）：LLM 后端约定为 Callable，输入为已组织的上下文（persona/scenario/transcript 摘要），输出为文本；UserAgent 负责把 Persona/SeedScenario/Transcript 组织成提示，并以三类解析器消费同一后端——消息生成解析（取 user_msg + end_flag）、体感解析（取 score:int + reason:str）、issue 解析（取 list[IssueDraft]）。一局主循环（伪流程）：

```
reset 由编排层(T4)负责；UserAgent 仅消费已就绪的 harness
turn = 0
loop:
  user_msg, end_flag = parse(llm(persona, scenario, transcript))   # 生成本轮用户话 + 是否结束
  若 end_flag → break                                              # 自判：达成 / 放弃 / 受够
  reply = harness.send(user_msg)
  transcript.append(user 轮); transcript.append(harness 轮)
  turn += 1
  若 turn >= max_turns → break                                     # 兜底防不收敛
结束后:
  feeling = parse_feeling(llm(...))        # 1..4 + reason，会话末一次
  drafts  = parse_drafts(llm(...))         # 0..n 条 IssueDraft（最小桩，方案 a）
return (transcript, feeling, drafts)
```

信号「真不真」取决于该驱动器对真实使用行为（追问、绕路、卡顿、放弃）的拟真程度，而非机械跑满固定轮数——这正是选自判终止 + max_turns 兜底、而非固定轮数的原因：固定轮数无法表达「达成即停/受够放弃」的真实行为，会使训练信号失真；纯自判又有不收敛风险，故以 max_turns 收口（计入 user 轮数，达上限即便 LLM 未发结束信号也强制结束，保证可终止性）。终止信号编码选约定文本 sentinel（如末行固定标记）而非强制 JSON/工具调用 schema（新决策，奥卡姆），避免对模型后端形态过度假设，与「兼容多种 agent/模型」的目标相悖；解析失败时按「未结束」处理，由 max_turns 兜底收口。体感与 issue 均在循环结束后一次性产出（采纳决定，而非逐轮产出）：信号更干净、实现更简，对齐 FeelingScore「一局一个总分」的形态，代价是丢失「第几轮开始变差」的细粒度，留待后续需要时再升级为逐轮。issue 产出在本任务仅实现方案 a 的最小桩（in-character 会话末产出，机制不锁死，见 Unresolved questions）。边界处理上，max_turns <= 0 在构造期断言失败（无意义配置）；体感解析越界依赖 FeelingScore 构造期断言（T1）失败，UserAgent 不重复校验，保持单一校验点；issue 解析得 0 条为合法（多数会话无 issue）；harness.send 抛异常不在本层吞掉，向上传播交 T4 决定（与 T2 协议约定一致）。接口：`UserAgent(llm: Callable[..., str], persona: Persona, max_turns: int)`，`run(scenario: SeedScenario, harness: HarnessInterface) -> tuple[Transcript, FeelingScore, list[IssueDraft]]`；max_turns > 0 由构造期断言保证，run 不调用 harness.reset/close（生命周期归编排层 T4）。单测（mock LLM 返回固定脚本）覆盖：定轮发结束信号后会话轮数精确匹配、Transcript 轮次对应；永不结束时 user 轮数截断至 max_turns；体感解析落在 1..4 且携带 reason；FakeHarness 收到的消息序列与 Transcript 的 user 轮内容逐条一致；issue 桩 0 条与 2 条场景均正确；max_turns<=0 与体感越界（如解析得 5）均构造期失败；结束信号缺失时按未结束处理并由 max_turns 收口；harness.send 抛异常时 run 不吞异常、向上传播。

**会话编排 runner（T4）** 提供闭环编排（loop/）与统计（metrics/）都需要的稳定「跑一局」入口：单一无状态函数，全部依赖注入：

```
run_session(persona, scenario, harness, user_agent, tracker, store) -> Session:
    harness.reset()                                          # 开局（生命周期归编排层）
    try:
        transcript, feeling, drafts = user_agent.run(scenario, harness)
    finally:
        harness.close()                                      # 无论成败都释放后端资源
    issue_refs = [tracker.create_issue(d) for d in drafts]   # 逐条提交至 tracker
    session = Session(persona, scenario, transcript, feeling, issue_refs)
    store.save(session)                                      # 体感 + session 落本地
    return session
```

reset 在 user_agent.run 之前调用，对应 T2「开局责任归编排层」的约定，UserAgent 自身不 reset/close。close 置于 finally（新决策，奥卡姆）：UserAgent.run 抛异常时仍保证 harness 资源释放，避免后端句柄泄漏，异常本身继续向上传播。提交与落盘在 run 成功返回后才进行——run 抛异常时不产生 IssueRef、不落盘，保持「失败局不留半成品」；issue_refs 顺序与 drafts 一一对应，0 条 draft 时为空列表。错误处理上，tracker.create_issue 或 store.save 抛异常时本层不吞，直接向上传播（编排/重试策略归 loop 层）；run_session 不做重试、不做幂等去重，同一局重复调用产生重复提交，调用方负责不重复调用。依赖注入面：harness 满足 HarnessInterface（T2），user_agent 为 UserAgent（T3），tracker 满足 IssueTracker（T5），store 为 SessionStore（T6）；测试以 FakeHarness + mock LLM + FakeTracker + 临时目录 SessionStore 全替换，运行时注入真实 launcher/Gitea/本地盘。接口：`run_session(persona: Persona, scenario: SeedScenario, harness: HarnessInterface, user_agent: UserAgent, tracker: IssueTracker, store: SessionStore) -> Session`，纯函数、无返回副本之外的全局状态；harness 生命周期（reset/close）由本函数负责，close 在 finally 中保证执行。集成测（FakeHarness + mock LLM + FakeTracker + 临时目录 store）覆盖：正常结束返回含 transcript/feeling/issue_refs 的完整 Session；harness.reset/close 各调一次、顺序为 reset → run → close；2 条 draft 得 2 条带号 IssueRef 且顺序对应、0 条 draft 时 issue_refs 为空列表；run_session 后经 store.load 还原等价 Session；提前放弃场景 user 轮数 < max_turns 但 Session 仍完整；mock UserAgent.run 抛异常时 harness.close 仍被调用、异常向上传播、store 未写盘、tracker 未收到提交。

**IssueTracker 接口与 FakeTracker（T5）** 将 issue 的提交去向抽象为接口，使用户侧不绑定具体 tracker 后端：`ensure_labels(names: list[str]) -> None` 确保给定标签均存在，幂等（Gitea 后端在此先建标签并解析 id，FakeTracker 仅维护名称集合）；`create_issue(draft: IssueDraft) -> IssueRef` 依据 draft.title/body/labels 建 issue，返回带号回执 IssueRef(number, url, state)，新建 issue 初始 state 为 "open"；`add_comment(number: int, body: str) -> None` 向指定 issue 追加评论，number 不存在时抛 KeyError（Gitea 后端对应 404）；`set_state(number: int, state: str, reason: str) -> None` 改状态，state ∈ {"open", "closed"}，reason 记录变更原因（对齐 Gitea state_reason 语义），number 不存在时抛 KeyError。number 由后端单调递增发放，从 1 起，每实例独立计数（FakeTracker 语义对齐 Gitea 的实例内自增）；IssueRef.url 由后端按其 number 合成（FakeTracker 用占位前缀 + number 拼出确定性 url）；create_issue 不去重——相同 draft 多次提交得到不同 number，与 Gitea 行为一致，去重责任在调用方。协议方法只取四项（建/评论/改状态/建标签）而非照搬 Gitea 全量 API（奥卡姆）：这是 issue 闭环的最小充分集，里程碑/指派/搜索等无当前消费方，待 dev 侧需要再扩；「未找到」用标准 KeyError 而非自定义异常类型，当前无需区分错误类别。FakeTracker 以内存结构实现：`_counter: int`（发号游标）、`_issues: dict[int, dict]`（number → {title, body, labels, state, reason, comments}）、`_labels: set[str]`；create_issue 递增 _counter、写入 _issues、返回 IssueRef，语义对齐 Gitea 但无网络/持久化，并暴露按 number 读取快照的只读查询供单测断言 comment/state 生效；真实 GiteaTracker 实现归 spec-0002。接口：`IssueTracker(Protocol)` { ensure_labels / create_issue / add_comment / set_state }；`FakeTracker()`：内存实现，发号自 1 起单调递增，暴露按 number 读取 issue 快照的只读查询供断言。单测覆盖：create_issue 连续两次发号 1、2 且字段（number/url/state="open"）正确；add_comment 后按 number 读快照含该 body；set_state 为 closed+reason 后状态更新、再 set_state open 可还原；ensure_labels 幂等（同名标签不重复创建）、空列表 no-op；不存在 number 调 add_comment/set_state 抛 KeyError、set_state 传非法 state 抛 ValueError；相同 draft 两次 create_issue 得到不同 number（不去重）。

**本地 SessionStore（T6）** 提供 `SessionStore(root: str | Path)`：`save(session: Session) -> None` 写 `root/<session_id>.json`（经 Session.to_dict 全量序列化），并向 `root/index.json` 追加一条 `{session_id, score, created_at, n_issues}`，root 不存在时自动创建；`load(session_id: str) -> Session` 读回并经 Session.from_dict 还原全量，文件不存在抛 FileNotFoundError；`index() -> list[dict]` 读 root/index.json 全部条目，索引不存在时返回空列表。索引条目是全量文件的派生投影——score 取自 session.feeling.score，created_at 取自 session.created_at（ISO-8601 字符串），n_issues 取 len(session.issue_refs)——全量文件为唯一权威，索引可由全量重建。写入顺序约定「先写全量文件、后追加索引」（新决策，奥卡姆）：若中途失败，至多出现「有全量文件但索引缺该条」（可由全量重建索引），而非「有索引无证据」的不可恢复态；索引追加用「读-改-写」单文件（load 现有 index → append 新条 → 整体写回），MVP 单进程足够。同一 session_id 重复 save 会覆盖全量文件，但索引会追加重复条目（新决策：save 不做索引去重，去重责任归调用方/metrics 消费侧；保持 save 简单且与 T4「不重复调用」约定一致）。load 不存在的 id 抛 FileNotFoundError（标准异常，不自定义）；index() 在索引文件缺失时返回空列表而非抛错，首次运行无索引为合法初始态。接口：`SessionStore(root: str | Path)` { save / load / index }；root 不存在时由 save 自动创建，load 不存在 id 抛 FileNotFoundError，index 缺失时返回空列表。单测覆盖：save 后全量文件与 index 均出现该局，index 条目字段（session_id/score/created_at/n_issues）正确；load 还原等价 Session（字段级一致，含 transcript/feeling/issue_refs）；root 不存在时 save 自动建目录后成功写入；index() 在无索引文件时返回空列表、多局 save 后按写入顺序返回多条；n_issues 与 issue_refs 长度一致（0 条 issue 时 n_issues=0）；load 不存在 id 抛 FileNotFoundError；同一 session 两次 save 后全量被覆盖、索引含两条。

**文件分配（单一 writer 所有权）**

| Task | 文件 |
| --- | --- |
| T1 | `backend/ahe_beta/models.py`、`backend/tests/test_models.py` |
| T2 | `backend/ahe_beta/harness/interface.py`、`backend/tests/harness/test_interface.py` |
| T3 | `backend/ahe_beta/user/user_agent.py`、`backend/tests/user/test_user_agent.py` |
| T4 | `backend/ahe_beta/user/session.py`、`backend/tests/user/test_session.py` |
| T5 | `backend/ahe_beta/tracker/base.py`、`backend/ahe_beta/tracker/fake.py`、`backend/tests/tracker/test_fake.py` |
| T6 | `backend/ahe_beta/user/session_store.py`、`backend/tests/user/test_session_store.py` |

依赖 DAG：`T1 → T2`，`T1 → T3`，`T2 → T3`，`T1 → T4`，`T2 → T4`，`T3 → T4`，`T5 → T4`，`T6 → T4`，`T1 → T5`，`T1 → T6`

## Drawbacks

<!-- 待填 -->

## Rationale and alternatives

数据建模层面（T1），选 dataclass 而非 pydantic/attrs（奥卡姆，零依赖），运行时强校验的缺失由 `__post_init__` 断言 + 单测兜底，将来若需 schema 导出再评估 pydantic；落盘选 json 而非 yaml，因逐条可追加、统计友好，代价是牺牲人读性，交由生成视图承担；Session 选嵌套而非扁平+外键，使一局自包含、单文件可回放，代价是跨局聚合需遍历，规模小可接受；issue 只存回执 IssueRef 而非本地全量副本，以 Gitea 为单一权威源，避免本地与远端双写不一致。

协议设计上，T2 与 T5 均选 typing.Protocol（结构化子类型）而非 ABC 抽象基类：Fake 实现与真实后端无需显式继承即满足契约，降低耦合、便于测试替身。两者的方法面都刻意收窄（奥卡姆）：T2 只留 send/reset/close 三件套，不预先纳入流式/工具调用/用量统计——这些需求需真实 nexau 接入后才能定形，过早抽象会锁死错误的契约；也未直接复用 harbor 的 episode/rollout 批式接口，因其输入输出粒度是 episode 而非单轮，套到「逐轮真人对话 + 用户自判终止」上需大量适配且语义错位。T5 只取建/评论/改状态/建标签四项而非照搬 Gitea 全量 API，这是 issue 闭环的最小充分集，里程碑/指派/搜索等无当前消费方，待 dev 侧需要再扩；「未找到」用标准 KeyError 而非自定义 TrackerNotFound 异常，当前无需区分错误类别，标准异常足够，若后续需统一错误码再引入异常层级；FakeTracker 选每实例独立发号而非全局发号，与 Gitea「按仓库实例计数」语义一致，也使单测互不串号、可独立断言；create_issue 选不去重，与 Gitea 一致，去重责任归调用方，避免在接口层引入隐式幂等假设。send 返回选 str 而非含 metadata/usage 的结构体，因当前用户侧只需回复文本写入 Transcript，附加元数据无消费方（YAGNI）；reset 选显式而非在 send 首次调用时隐式复位，避免「开局」语义分散进 send、破坏单一职责并使「续局」无法表达；FakeHarness 脚本耗尽选抛 IndexError 而非静默循环或返回空串，以暴露测试用例轮数设定不足，而非掩盖 T3 终止逻辑跑飞（应由 max_turns 截断而非脚本兜底）。

驱动器行为上（T3），体感与 issue 选会话末一次产出而非逐轮产出（采纳决定）：信号更干净、实现更简，且对齐 FeelingScore「一局一个总分」的形态，代价是丢失「第几轮开始变差」的细粒度，后续若需要再开 spec 升级为逐轮。终止方式选自判 + max_turns 兜底而非固定轮数：固定轮数无法表达「达成即停/受够放弃」的真实行为，会使训练信号失真，纯自判又有不收敛风险，故以上限收口。终止信号编码选约定 sentinel/字段而非强制 JSON/工具调用 schema（奥卡姆），因后者对模型后端形态做强假设，与「兼容多种 agent/模型」相悖，解析失败安全降级为「未结束」。issue 产出评估过三种方案——方案 a（in-character 会话末产出）、方案 b（独立分析器读 transcript 归纳）、方案 c（两步：标摩擦点+归纳）——本组选 a 的最小桩，不锁死：a 实现最省且足以打通链路，b/c 更准但引入额外组件，待 dev 侧 spec 对接需求时再定。LLM 后端选注入通用 Callable 而非绑定具体客户端类，使单测可用 mock 固定脚本、运行时换真实模型，符合依赖倒置。

编排职责上（T4），选纯函数 + 依赖注入而非 SessionRunner 类持有依赖（奥卡姆）：本组无跨会话共享状态，类只会引入无谓的生命周期，并发/批量需求出现时在 loop/ 层包装，不污染本入口。harness 生命周期归 run_session 而非 UserAgent：reset/close 是编排关注点，放 UserAgent 会让其同时承担「对话」与「资源管理」双职责，违背单一职责且妨碍 T3 单测（须 mock 生命周期）。close 放 finally 而非正常流末尾：后者在 run 抛异常时会泄漏后端资源，finally 保证释放且不掩盖异常。失败局是否落盘选仅成功落盘：半成品 Session（缺 feeling/transcript）落盘会污染体感曲线与回归基线，宁可丢失失败局记录，由 loop 层按需补记。提交失败是否回滚已落盘 session 的问题不成立：本组提交在落盘前、且失败即向上抛，落盘根本不发生，无需回滚逻辑（顺序天然规避）。

存储层面（T6），选一文件一局 + 单总索引而非数据库（sqlite 等），因规模小、写少读少，文件零依赖且全量即证据，规模增大或需复杂查询时再迁移；索引选单 index.json 全量「读-改-写」而非追加式 JSONL，便于 index() 一次性读回为 list[dict]，代价是每次 save 重写整文件，规模小可接受，若局数膨胀至重写成本显著，再切 JSONL 追加。索引派生自全量、全量为权威而非索引为权威：索引可由全量重建，避免双权威漂移，这也决定了「先写全量后追加索引」的顺序。save 索引去重选不去重（奥卡姆）：去重需先扫索引，增加每次 save 成本；重复 save 由 T4「不重复调用」约定规避，去重归消费侧。并发安全（文件锁）本任务不处理，单进程 MVP 已足够；并发由 loop 层并行编排时统一解决，避免在存储层过早引入锁复杂度。

## Prior art

CLAUDE.md「方法：模拟用户使用→开发者迭代」的用户侧(a) 是本组的直接依据：体感评分 + issue 两类信号的产出机制（T1 数据结构、T3 驱动器）均由此展开，会话末总分的具体形态由本 spec 需求澄清。架构层面对应「被进化对象：harness 作为可启动程序」与「兼容 nexau / claude code / codex」（T2，真实后端 launcher 归 spec-0003），以及「状态去向：issue → Gitea」（T5，GiteaTracker 实现归 spec-0002，IssueDraft/IssueRef 结构归 T1）与「状态去向：体感 + session → 本地」及观测指标「issue 数量随时间曲线」（T6，下游 loop/metrics 消费索引，Session 序列化契约归 T1）。协议设计遵循 typing.Protocol（PEP 544，结构化子类型），T2/T5 均据此定义。T4 的 run_session 是 CLAUDE.md 用户侧(a) 的落地入口，也是下游 loop/ 编排 a→b→c、metrics/ 统计 issue 曲线，以及 spec-0003 闭环复用的唯一入口。

## Unresolved questions

IssueDraft 的字段形态已对齐 Gitea 建 issue 入参（title/body/labels），T1 取此三元组；但其产出机制（谁在何时生成）留给 T3 决定，尚待定案。用户已确认 issue 产出「类似往 github 提 issue，具体 TBD」，候选路径有三：(a) UserAgent 直接 in-character 产出 IssueDraft；(b) 单独分析器读完 transcript 再归纳；(c) 两步——先标摩擦点、再归纳。T3 先实现 (a) 的最小桩（LLM 会话末产 0..n 条 draft），不锁死，待后续 dev 侧 spec 对接具体需求时再定。

## Future possibilities

<!-- 待填 -->

