---
number: "0017"
title: 多用户会话并行化：a 段线程池 + 共享状态加锁
issue: 0
slug: user-parallel-sessions
summary: 把闭环 a 段的用户会话从串行改为 ThreadPoolExecutor 并行：并发单元=整局会话（工作区+harness 子进程+client+run_session 一整包），信封内部时序不动；配套修共享状态（client 每局一实例、工作区供给前移、SessionStore/live 加锁），单会话失败降级不废整轮。d/b 段维持串行（同仓 push + 全局 env 的固有约束）。落点 loop/orchestrator + loop/sim_user + run.py + user/session_store + loop/live。
tasks:
  - id: T1
    title: 存储与观测投影加锁
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/user/session_store.py
      - backend/auto_designer/loop/live.py
      - backend/tests/user/test_session_store.py
      - backend/tests/loop/test_live.py
    scope: SessionStore 挂实例级 threading.Lock，save 全程持锁（先写全量后追加索引的顺序不变，锁只消并发丢条目竞态）；live.py 加模块级一把锁，包住 update_agent/append_agent_log/archive_agent/update_live_run/clear_live 的读-改-写全程——mkstemp 原子写只防撕裂写，不防两个写者基于同一旧快照互相覆盖（丢更新）。锁粒度=单文件操作全程，持锁期内无网络/子进程等待，无死锁面。
    acceptance: 多线程并发 save N 局后 index.json 恰好 N 条、sessions 目录 N 个全量文件（竞态回归测试）；多线程并发 update_agent 不同 agent_id 后 agents.json 各槽位全部保留；append_agent_log 并发追加不丢行；现有单线程测试全绿。
  - id: T2
    title: client 每局一实例（工厂注入）
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/loop/sim_user.py
      - backend/tests/loop/test_sim_user.py
    scope: 'make_sim_run_session_fn 的 client 参数改为 client_factory: Callable[[], PersonaClient]（破坏性改签名，调用方仅 run.py 与本测试）；run() 内每局 client = client_factory() 后再守卫式 bind_session（仅具 bind_session 的实现调用）。底层 ApiPersonaClient 无会话态可全局共享，工厂只新建 AgenticPersonaClient 外壳。杜绝并发下后 bind 覆盖先 bind 的串台。'
    acceptance: 注入记录型 fake factory 的单测断言：每局获得独立 client 实例、各自 bind 的 persona/workspace 互不覆盖；两个并发会话（线程模拟）产出的 TurnLog 归属正确不串台；现有 sim_user 测试改造后全绿。
  - id: T3
    title: a 段并行化 + 并发度旋钮
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/loop/orchestrator.py
      - backend/run.py
      - backend/tests/loop/test_orchestrator.py
    scope: run_round a 段拆两阶段：阶段一串行 prepare（materialize_workspace + ensure_deps / mkdtemp，规避 git clone 缓存并发竞争）；阶段二 ThreadPoolExecutor(max_workers=min(n, max_parallel_users)) 并行 launch + run_session_fn，as_completed 收割，单会话异常记日志跳过不废整轮。Orchestrator 构造新增 max_parallel_users 参数；run.py 读 MAX_PARALLEL_USERS 环境变量（默认 roster 用户数）传入，并把 client 侧接成 T2 工厂。a 段全部汇齐后才进 d/b 段（维持串行）。
    acceptance: FakeHarness+Scripted 下 max_workers=4 跑 8 局：全部落盘、d/b 段在 a 汇齐后才执行；单会话 launch 抛异常时其余会话正常完成、轮不中断；max_parallel_users=1 与旧串行行为等价（回归基线）；现有 orchestrator 测试全绿。
  - id: T4
    title: 并发端到端回归测试
    status: pending
    priority: P2
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/tests/loop/test_parallel_sessions.py
    scope: 新增本组 e2e 专测（全 Fake，不依赖真 LLM/Gitea）：①并发正确性——8 局并发后 sessions 目录 8 个全量文件、index.json 恰 8 条、live history 按轮归档完整；②慢会话注入——fake harness 延迟回复，断言快会话先完成、慢会话不阻塞收割、轮末全部汇齐；③崩溃注入——send 抛 RuntimeError，断言会话内 [harness error] 信号路径在并发下仍成立且不影响同批其他会话。
    acceptance: 三类专测全绿；断言为精确计数（index 条数/文件数/live 槽位数），可捕获竞态丢更新回归；pytest 全套通过。
---

# 0017 · 多用户会话并行化：a 段线程池 + 共享状态加锁

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

把闭环一轮 a 段（用户会话）从顺序执行改为 **ThreadPoolExecutor 并行**：并发单元 = **整局会话**
（共享工作区 + harness 子进程 + persona client + `run_session` 一整包），控制信封内部的单线程
确定性时序一根线程都不动。配套三件事：① persona client 从跨局复用单实例改为**每局一实例**
（工厂注入，根治 `bind_session` 串台）；② 工作区供给（materialize + ensure_deps）**前移到并行段
之前串行完成**（规避 git clone 缓存并发竞争）；③ 共享状态加锁（`SessionStore.save` 的
index.json 读-改-写、`live.py` 观测投影的读-改-写）。N 个用户的 a 段 wall-clock 从 ~ΣTᵢ 降到
~max(Tᵢ)，且**并发不改变任何信号语义**。d（designer）/ b（developer）段维持串行，是明确的
Non-goal（多 dev 直推同一 main 必然 push 冲突 + `SANDBOX_WORK_DIR` 全局 env 变异，串行是纯
trunk 模型的固有约束）。

## Motivation

**现状（就地复述，本 spec 自包含）。** `orchestrator.run_round` 的 a 段是一个顺序 for 循环：
对固定集里每个 (persona, scenario) 配对，串行走完「materialize 工作区 → `launcher.launch(sha)`
起 harness 子进程 → `run_session` ≤12 轮对话 → 落盘/提 issue」全程。roster 默认 3 用户，每局
动辄数分钟（外层每轮 1-2 次 persona LLM 调用 + 内层 ≤4 步工具循环 + harness 自己的 LLM/bash，
单轮 harness 回复最坏 ~16 分钟），a 段耗时随用户数**线性增长**，是整轮 wall-clock 的主要成分。
要扩 persona 覆盖面（更多锚点用户）就要么等更久、要么减少轮数——两头都伤训练信号的密度。

而用户会话之间**天然完全隔离**：各自独立的工作区目录（orchestrator 每局 materialize/mkdtemp
一份）、各自的 harness 子进程（launcher 一句柄一进程一会话）、各自的 client 绑定、互不通信、
无共享可写状态（除了三个明确的汇聚点：SessionStore、live 观测投影、issue tracker）。这是最理想
的并行对象。

**为什么现在做（前提已被 0012/0013 解决）。** 并发的生存前提是「单会话的挂死/崩溃不能拖垮
worker 池」。这在旧基线上不成立（launcher 的 `readline` 无超时、异常直接炸整条 run），但
0012/0013 已就地解决：launcher `begin/poll` 拆分片轮询（进程死了没回完整行 → 精确判死锁上抛；
1800s 绝对上限防活锁），loop 侧 `route`/`_supervise_send` 把一切 harness 异常转成
`[harness error]` 文本回填给 persona 当观测（会话不炸、坏 commit 产生梯度）。因此本 spec
**不再包含任何超时/异常转译工作**，只做编排层并行化与共享状态收口。

## Guide-level explanation

对运行者：`./run.sh` 行为不变，但 a 段里 N 个用户卡片在看板上**同时呼吸**（本就每 agent 一槽、
roster 即房间容量，这是看板"本该有"的样子）。新旋钮 `MAX_PARALLEL_USERS` 环境变量（默认 =
roster 用户数）控制并发度；设 1 即退化为今天的串行行为。一轮的形状变为：

```
round K:
  ┌─ a 段（并行，≤max_parallel_users 线程）──┐
  │  user1: launch → run_session → 落盘      │  ← 每局独立进程树+工作区+client
  │  user2: launch → run_session → 落盘      │
  │  user3: launch → run_session → 落盘      │
  └───────── as_completed 全部汇齐 ──────────┘
  d 段（designer，串行）→ b 段（developer，串行）→ c 段（回灌 main HEAD SHA）
```

对信号消费者（设计师/metrics/看板）：**并发只改 wall-clock，不改信号语义**——体感分布、issue
产出、TurnLog 内容与串行基线一致；单会话意外失败（如 launch 崩溃）记录日志后跳过，不废整轮、
不阻塞其他会话。

## Reference-level explanation

### 并发单元与不变量

并发单元 = 一局会话的完整包：`(persona, scenario, workspace_dir, harness_handle, client)`。
信封内部（`run_session` 循环、`_supervise_send` 心跳、内层 tool-loop）保持单线程确定性时序，
每局内的行为与串行完全一致。launcher 句柄内部本就有一个在途读线程（0013 的 `begin/poll`），
它是句柄私有的，与本 spec 的会话级并行正交。

### T2：client 每局一实例（头号地雷）

`AgenticPersonaClient` 是会话级有状态的：`bind_session(persona, workspace_dir)` 写
`self._persona/_workspace_dir`（persona_client.py:447-453），当前 run.py 单实例顺序复用，
并发下必串台（后 bind 覆盖先 bind）。修法：`make_sim_run_session_fn(client=...)` 改为
`client_factory: Callable[[], PersonaClient]`，`run()` 内每局 `client = client_factory()` 后再
守卫式 `bind_session`。底层 `ApiPersonaClient.complete` 无会话态（纯函数式补全 + 429 退避），
openai SDK 客户端线程安全，**全部会话共享同一个 `ApiPersonaClient` 实例**、只是各自新建外壳：
`client_factory = lambda: AgenticPersonaClient(shared_api.complete)`。破坏性改签名，调用方仅
run.py（随 T3 一起改）与 sim_user 测试。

### T3：a 段两阶段拆分 + 线程池

```python
# 阶段一（串行，快）：工作区供给前移——规避 sources/git.py 共享 clone 缓存的并发竞争
prepared = []
for persona, scenario in self._fixed_set:
    ws = materialize_workspace(scenario.workspace) if scenario.workspace else mkdtemp(...)
    if scenario.workspace: ensure_deps(ws, scenario.workspace)
    prepared.append((persona, scenario, ws))

# 阶段二（并行）：launch + 会话
def _one(persona, scenario, ws):
    harness = self._launcher.launch(sha, workspace_dir=ws)
    return self._run_session(persona, scenario, harness, workspace_dir=ws)

with ThreadPoolExecutor(max_workers=min(len(prepared), self._max_parallel_users)) as pool:
    futs = {pool.submit(_one, p, s, ws): (p, s) for p, s, ws in prepared}
    for fut in as_completed(futs):
        try:
            fut.result()
        except Exception:      # 0012 后会话内异常已转信号；此处只剩 launch 类意外
            log.exception(...)  # 单会话失败不废整轮，其余会话照常汇齐
```

- `max_parallel_users` 经 Orchestrator 构造参数注入；run.py 读 `MAX_PARALLEL_USERS` 环境变量，
  默认 = roster 用户数。
- launch 放进线程（而非前移）：checkout 有 SHA 目录缓存，第一个线程解包后其余复用；即便并发
  首轮各自解包也只是浪费不冲突（`dest.mkdir(exist_ok=True)` + 同内容覆盖）——**保持简单**。
- a 段全部汇齐（`as_completed` 循环走完）后才进 d/b 段，轮边界语义与 checkpoint（spec-0004，
  轮粒度）不受影响。

### T1：共享状态加锁（全量审计表）

| 共享点 | 现状 | 判决 |
|---|---|---|
| `SessionStore.save`（index.json 读-改-写） | docstring 自认「单进程 MVP 不处理并发写竞态」 | **加锁**：实例级 `threading.Lock`，save 全程持锁（先全量后索引的顺序不变） |
| `live.py` agents/history/run.json | mkstemp 原子写只防撕裂写；`update_agent` 等仍是读-改-写，并发丢更新 | **加锁**：模块级一把锁包住 update_agent / append_agent_log / archive_agent / update_live_run / clear_live 的读-改-写全程 |
| `sources/git.py` clone 缓存 | 同仓并发 provision 撞缓存目录 | **前移规避**（T3 阶段一），不加锁 |
| `GiteaTracker`（共享 `requests.Session`） | 仅 token header、无 cookie 状态，urllib3 连接池线程安全 | 无需改（见 Unresolved #3 留观察） |
| `os.environ` | 用户段不碰（launcher 显式传 env dict 给 Popen）；dev/designer 段才设全局 env | d/b 串行，天然无冲突（Non-goal 的依据之一） |
| run.py `current["round"]` | a 段内只读（round 游标只在轮边界写） | 无需改 |

### Task DAG 与文件分配

```
T1（存储/投影加锁）──┐
                      ├──> T3（a 段并行化 + 旋钮）──> T4（并发端到端回归）
T2（client 工厂）────┘
```

| Task | files（互斥） |
|---|---|
| T1 | `backend/auto_designer/user/session_store.py`, `backend/auto_designer/loop/live.py`, `backend/tests/user/test_session_store.py`, `backend/tests/loop/test_live.py` |
| T2 | `backend/auto_designer/loop/sim_user.py`, `backend/tests/loop/test_sim_user.py` |
| T3 | `backend/auto_designer/loop/orchestrator.py`, `backend/run.py`, `backend/tests/loop/test_orchestrator.py` |
| T4 | `backend/tests/loop/test_parallel_sessions.py`（新增，本组 e2e） |

e2e 验证路径：`backend/tests/loop/test_parallel_sessions.py`（全 Fake，不依赖真 LLM/Gitea）。
另有一项**不进 CI 的真实小规模验证**：3 用户 × 1 轮，并行 vs 串行基线对比体感分布与 issue
数量级，确认无系统性偏移（并发只该改 wall-clock）。

### 前端影响（审计结论：零改动）

已核查前端全链路，本 spec 不含任何前端任务，依据如下：

- **PERSONA_LIMIT（覆盖面）与 max_parallel_users（并发度）解耦对前端零影响**：房间展示
  实际跟的是「run 里出现了几个 agent 槽」（`App.tsx` 按 role 过滤 `/api/agents`），并非任何
  配置值——`/api/config` 的 roster 管道虽已铺好（api.ts `getConfig` + `Roster` 类型），但前端
  **无任何调用点**（既有死代码，不属本 spec）。并发度对前端天然不可见，两旋钮独立、互不需要
  对方感知。
- **运行中卡片顺序不受并发影响**：`live.read_agents` 服务端按 `(role, agent_id)` 字典序排序
  （`user-SR-001 < user-SR-002 < …`），与写入/更新先后无关，任何时刻轮询到的列序都稳定。
- **「+已完成」轮内顺序语义变化（接受，不改）**：history 为 append-only、轮内按归档先后展示；
  串行时归档序=固定集序（SR 序），并行后=**完成先后**（谁先跑完谁在前，每次 run 可不同）。
  判定为可接受的真实语义（先完成先归档，顺带反映快慢）；若将来要确定性，前端轮内按 label
  排序一行即可，留给前端主线。
- 多卡同时 running 本就受支持：每槽独立 status/`started_at` 计时，3s 轮询无顺序假设；数据层
  竞态由 T1 的 live 锁消除。

## Drawbacks

- **LLM 网关压力放大**：N 并发用户 ×（外层 ≤12 轮 + 心跳唤醒 + 内层 ≤4 步）的调用并发化，
  429 概率上升；`ApiPersonaClient` 已有退避，跨会话信号量先不做（Unresolved #1）。
- **进程数放大**：每局 = 1 个 harness Python 进程 + 其 bash/sandbox 子进程；3-4 并发本地十几个
  进程无压力，但更高并发需关注。
- **日志交错**：多会话 stderr/print 交错，排查单局问题需按 session_id/agent 槽过滤（看板已按
  agent 分槽，影响有限）。
- 线程池吞异常的路径若处理不当会静默丢会话——靠 T3 的 as_completed 收割 + 显式日志约束。

## Rationale and alternatives

**三选项判决（工作负载：一局会话 ~100% 是阻塞等待，全程释放 GIL——persona LLM 网络 IO +
harness 管道 IO 是两个大头）：**

| 方案 | 判决 | 理由 |
|---|---|---|
| **线程池** | ✅ 采用 | 现有同步代码零重写，只改编排层；GIL 非瓶颈（纯等待型负载）；NexAU 自身 subagent_manager 同一判断 |
| asyncio | ❌ | 需重写 run_session / persona_client（AsyncOpenAI）/ launcher（异步管道）整条链路；信封的确定性单线程时序是设计资产；并发规模仅 3~10，协程收益用不上——违背奥卡姆 |
| 多进程 | ❌ | 隔离已存在于正确位置——每局重活本就在独立子进程（harness=Popen 进程树），编排线程只是等管道；再套多进程徒增 on_turn 回调跨进程、Session pickle、live 写复杂化，零收益 |

**备选：维持串行、靠减 persona 数换轮数**——被否：persona 多样性正是体感信号的分布基础
（观测指标一节明说 issue 过早归零 = persona 多样性不足），缩覆盖面与目标背道而驰。

## Prior art

- **NexAU `subagent_manager`**：多 subagent 并行用 ThreadPoolExecutor，同样的「阻塞 IO 型
  agent 负载 + 线程池」判断，本仓运行时的既有先例。
- **0012/0013（本 spec 的鲁棒性基线，要点就地复述）**：launcher `begin/poll/control` 把一轮
  send 拆成分片轮询（进程活着=合法长任务不盲杀、进程死了没回完整行=精确判死锁、1800s 绝对上限
  防活锁、`start_new_session`+`killpg` 整组回收孤儿）；loop 侧一切 harness 异常转
  `[harness error]` 回填 persona 当观测，会话不炸、崩溃产生体感+issue 梯度。没有这些，挂死
  harness 在串行时"卡住能看见"，并发时是"worker 池静默耗干"。
- **spec-0004 HarborRunner**：checkpoint 粒度是轮，轮内如何并行对 runner 透明——本 spec 与
  Harbor 模式正交兼容。

## Unresolved questions

1. **跨会话 LLM 并发信号量**：是否需要 `threading.Semaphore(MAX_LLM_CONCURRENCY)` 包住
   `ApiPersonaClient._create`？先不做，跑起来观察网关 429 频率再决定（退避已有）。
2. **GiteaTracker 共享 `requests.Session`**：官方不承诺线程安全，但本用法仅 token header、无
   cookie 变异，实践中并发 POST 安全；留观察，若出现连接池异常再改 per-thread session。

## Future possibilities

- **b 段并行**：多 dev agent 各在独立 worktree 改 + rebase 后串行 push（需要冲突处理设计，
  另立 spec）。
- **跨会话协作场景**：多个 persona 共用一个 harness（结对/接力），信封需要会话间通信原语。
- **并发度自适应**：按网关 429 率动态收缩 max_parallel_users。
- **Harbor 多 task 分片**：a 段按 persona 分片到多个 harbor task（沙盒级并行），checkpoint
  聚合语义需扩展。

