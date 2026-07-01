# 0009 种子工作区供给可插拔（SeedSource 接缝）

> 本文件由 `spec render` 自动生成，请勿手工编辑。
> 内容来源：本组 `metadata.yaml` 与 `tasks/T*.yaml`（关联 issue #9）。

## 总览

本组承接 spec-0008/T1：彼时 `SeedScenario.workspace` 经 `WorkspaceSpec{fixture, setup}` + `materialize()` 落地，供给路径是**唯一且硬编码的本地 copytree**。随着任务源增多（NL2Repo 式空仓起步、未来 SWE-bench / Terminal-Bench 等），**供给侧需可插拔**；而**消费港口**——`SeedScenario.description` 文本 + 一个被 `Sandbox`/`sim_user` 当 cwd 的工作区目录——保持冻结、零改动。

本组把「工作区供给」抽象为按 `kind` 注册的 `SeedSource` 协议：把既有 `materialize` 降为首个 `local-fixture` 实现（行为等价、向后兼容），并新增一个轻量 `empty` 源（新建空目录，可选写入需求说明文件，覆盖 NL2Repo 式「仅说明文档」起步）以证明**可加性**——新增一个源 = 落一个新模块（被自动发现注册）+ 注册侧/消费侧零改动。`workspace.materialize()` 退化为薄壳委托给注册表，故 `sim_user` 桥接与 `Sandbox` 调用点一行不改。

**明确非目标**（仅作为下游 spec 的扩展点记录，本组不实现）：Oracle / 客观判分（属平行评测系统，与用户主观核实解耦）；容器化「可运行句柄」运行时（`run(cmd)`/`cleanup`）。依赖供给（venv/pip）原亦列为非目标、拟推下游，现掰正收进本组 **T3**（见下）——因为「供给一个工作区」若不含「按其声明依赖可跑」，NL2Repo 式带依赖任务（如 funcy 需 pytest/whatever）在 stdlib-only 假设的 Sandbox 里根本跑不起来。git@commit 取数原亦列为下游非目标，现兑现为本组 **T4**（`git` 源：clone repo@commit 成快照工作区）——真实 repo 任务（SWE-bench 的 `base_commit` 未修复态、funcy@某版本等）的起点正是「某仓库停在某 commit 的快照」，两个本地源（local-fixture/empty）立不起来，故补上此扩展点。本组动供给侧：凿接缝（T1）+ 一个已验证的第二实现（T2）+ 激活 `setup` 依赖供给（T3）+ 通用 `git` 快照源（T4）；重型框架（容器 / Oracle / 具体 benchmark 适配层）仍留下游、不提前造。

数据流脊柱（编号即执行序：先立接缝 T1，再加第二源 T2 证明可插拔，再由 T3 激活 `setup` 依赖供给使工作区可跑其声明依赖，再由 T4 补通用 `git` 快照源接入真实 repo 任务）：

```
seed 场景  SeedScenario.workspace = WorkspaceSpec{kind, fixture?, params, setup}
   │  按 kind 查 SeedSource 注册表（T1 立协议 + 注册表 + sources/ 自动发现）
   ▼
SeedSource.provision(spec, dest) -> workspace_dir
   ├─ kind="local-fixture": copytree in-repo fixture      （T1，= 0008 行为）
   ├─ kind="empty":         新建空目录，可选写需求文档     （T2，可加性证明）
   └─ kind="git":           clone repo + checkout <commit> （T4，真实 repo 快照）
   ▼
依赖供给：ensure_deps(dir, spec) 执行 spec.setup 备 per-workspace .venv （T3）
   │  → 消费侧 Sandbox.run_shell 探测 .venv 自动用之（python/pytest 命中依赖）
   ▼
消费港口不变：workspace.materialize() 薄壳委托 → sim_user 桥接 → Sandbox(workspace=dir) 当 cwd（0008 原样）
```

## 任务编排

```mermaid
graph LR
    nT1["T1 SeedSource 协议 + 注册表 + local-fixture 实现"]
    nT2["T2 empty/nl-doc 源（可插拔证明）"]
    nT3["T3 依赖供给（setup 钩子落地：per-workspace venv + pip）"]
    nT4["T4 git 源（clone repo@commit 成快照工作区）"]
    nT1 --> nT2
    nT1 --> nT3
    nT1 --> nT4
```

| 任务 | 标题 | 优先级 | 状态 | 依赖 |
|----|----|----|----|----|
| T1 | SeedSource 协议 + 注册表 + local-fixture 实现 | P1 | done | — |
| T2 | empty/nl-doc 源（可插拔证明） | P2 | done | T1 |
| T3 | 依赖供给（setup 钩子落地：per-workspace venv + pip） | P1 | done | T1 |
| T4 | git 源（clone repo@commit 成快照工作区） | P1 | done | T1 |

## 各任务方案

### T1 · SeedSource 协议 + 注册表 + local-fixture 实现（P1 / done）

**涉及文件**

- `backend/auto_designer/user/sim/seed_source.py`
- `backend/auto_designer/user/sim/sources/__init__.py`
- `backend/auto_designer/user/sim/sources/local_fixture.py`
- `backend/auto_designer/models.py`
- `backend/auto_designer/user/sim/workspace.py`
- `backend/tests/user/sim/test_seed_source.py`
- `backend/tests/user/sim/test_workspace.py`

**做什么**

本组底座任务：把工作区供给从「唯一硬编码的本地 copytree」抽象为按 `kind` 注册的 `SeedSource` 协议。定义 `SeedSource.provision(spec, dest) -> workspace_dir` 与一个 `kind → SeedSource` 注册表（含 `sources/` 子包 import 期自动发现，使新增源无需改注册侧）；把 0008/T1 的 `materialize` 逻辑迁为首个 `local-fixture` 实现，`WorkspaceSpec` 增 `kind`（缺省 `local-fixture`）与通用 `params`，`workspace.materialize()` 退化为委托注册表的薄壳。编号即执行序：本任务先立接缝，T2 才能纯靠新增模块接入第二个源。

**为什么**

0008/T1 让 seed 场景能携带工作区，但供给路径写死在 `materialize` 的本地 copytree 上。后续要接入多样任务源（NL2Repo 式空仓起步、SWE-bench / Terminal-Bench 等），若每来一种都改 `materialize`，供给侧会退化为 if/else 拼盘。本任务把「按何种机制把 workspace 备好」抽成可插拔接缝；消费港口（`SeedScenario.description` + 被 `Sandbox` 当 cwd 的工作区目录）保持冻结，从而供给侧可独立演进、消费侧零波及。

**范围**

1) `seed_source.py`：定义 `SeedSource` 协议、`kind → SeedSource` 注册表、`register` 装饰器、顶层 `provision` 分派，并在 import 期遍历 `sources/` 子包触发各源自注册。2) `sources/local_fixture.py`：把 0008/T1 的 copytree 逻辑迁来，作为 `kind="local-fixture"` 首实现。3) `models.py`：`WorkspaceSpec` 增 `kind: str = "local-fixture"` 与 `params: dict = {}`（向后兼容，缺字段→缺省）。4) `workspace.py`：`materialize` 改为委托 `provision` 的薄壳，调用点不动。不实现任何新源（empty 归 T2）、不碰消费侧（sim_user / Sandbox）。

**整体设计**

接缝与分派：

```
WorkspaceSpec{kind, fixture?, params, setup}
        │ kind
        ▼
SeedSource 注册表  dict[str, SeedSource]   ◄── import 期遍历 sources/ 子包，各源自注册
        │ provision(spec, dest_root) -> workspace_dir
        ▼
LocalFixtureSource(kind="local-fixture")：copytree seed_workspaces/<fixture>/project（= 0008 行为）
```

- `SeedSource` 为 `Protocol`，约定 `kind: str` 与 `provision(spec: WorkspaceSpec, dest_root: str | None) -> str`（返回隔离工作区目录绝对路径）。
- 注册机制：`@register("<kind>")` 装饰器把实现写入模块级 `_REGISTRY`；`seed_source.py` 在 import 期用 `pkgutil.iter_modules` 遍历 `sources/` 子包逐一 import，触发各源自注册——这是「新增源 = 落一个模块」可加性的机制根基（T2 依赖之，无需改注册侧）。
- 顶层 `provision(spec, dest_root)`：按 `spec.kind` 查表分派；未命中抛 `ValueError`（消息列出已注册 kind）。
- 向后兼容：`WorkspaceSpec` 增 `kind: str = "local-fixture"` 与 `params: dict = {}`；`from_dict` 缺 `kind` → `local-fixture`、缺 `params` → `{}`，故 0008 落盘数据与 `billing-split` fixture 原样可用。`workspace.materialize(spec, dest_root)` 改为 `return provision(spec, dest_root)` 薄壳——`sim_user` 桥接与 `Sandbox` 调用点一行不改（消费港口冻结）。
- `local_fixture.py` 收纳原 copytree 逻辑（fixture 不存在报错、每局隔离拷贝），从 `workspace.py` 迁出；`workspace.py` 仅留兼容壳与 `seed_workspaces_root()` 等共用 helper。

**接口**

- `SeedSource`（protocol，`sim/seed_source.py`）：属性 `kind: str`；方法 `provision(spec: WorkspaceSpec, dest_root: str | None = None) -> str`。
- 注册表 API（`seed_source.py`）：`register(kind: str)` 装饰器；`get_source(kind) -> SeedSource`；`provision(spec, dest_root=None) -> str` 顶层分派；`available_kinds() -> list[str]`。`sources/` 子包 import 期自动发现注册。
- `WorkspaceSpec`（`models.py`）：新增 `kind: str = "local-fixture"`、`params: dict[str, Any] = field(default_factory=dict)`；保留 `fixture: str`（local-fixture 使用）、`setup`。`to_dict` 省略缺省项以保持旧序列化形状；`from_dict` 缺 `kind`→`local-fixture`、缺 `params`→`{}`。
- `LocalFixtureSource`（`sources/local_fixture.py`）：`kind="local-fixture"`；`provision` = 把 `seed_workspaces/<spec.fixture>/project` copytree 到新隔离目录并返回其绝对路径。
- `workspace.materialize(spec, dest_root=None) -> str`：保留为委托 `provision` 的兼容壳（不弃用，缓冲后续）。

**取舍**

- 选「子包自动发现 + 装饰器自注册」而非「集中 import 列表」：换来新增源对注册侧零改动（T2 只落一个文件即接入），代价是 import 期一次目录扫描 + 注册依赖 import 副作用——以「不手动 import 也能查到 local-fixture」的测试兜底。备选「集中列表」每加一源都要改一处公共文件，违背可加性目标，故弃。
- `WorkspaceSpec` 用扁平 `fixture` + 通用 `params: dict` 而非「每 kind 一个强类型子类」：换来加源不改 `WorkspaceSpec`、序列化形状稳定；代价是 source 内部需自校验所需字段（local-fixture 要求 `fixture` 非空）。
- 保留 `materialize` 薄壳而非改 0008 调用点：换来消费侧零改动、渐进迁移，代价是多一层间接（可接受）。

**验收标准**

注册表按 `kind` 分派到正确源；未知 kind 抛 `ValueError` 且消息含已注册 kind；`available_kinds()` 含 `local-fixture`。不手动 import `local_fixture` 时，import `seed_source` 后 `local-fixture` 已在注册表（自动发现生效）。`WorkspaceSpec.kind` 缺省 `local-fixture`、`params` 缺省 `{}`；`to_dict/from_dict` 往返一致；旧 dict（无 `kind`/`params`）→ `local-fixture` 且既有行为不变。对 `billing-split` provision 落地目录存在、含 `billing/core.py` 且 stdlib 可 import/运行，两次 provision 互相隔离。`materialize(spec)` 与 `provision(spec)` 等价。

**测试**

test_seed_source.py：(a) `provision` 按 kind 分派正确；未知 kind 抛 `ValueError` 且消息列出已注册 kind；(b) 自动发现——不手动 import `local_fixture`，import `seed_source` 后 `available_kinds()` 含 `local-fixture`；(c) local-fixture 平价——对 `billing-split` 落地目录存在、含 `billing/core.py`、stdlib 可执行，两次 provision 隔离，fixture 不存在报错；(d) `WorkspaceSpec` kind/params 缺省与 to_dict/from_dict 往返、旧 dict 兼容。  更新 test_workspace.py：补 `materialize` 薄壳与 `provision` 等价、既有 materialize 断言在新路径下仍通过。

**参考**

扩展 0008/T1（`workspace.py` 的 `materialize`、`WorkspaceSpec`，`models.py` 的 `SeedScenario`）。消费侧 0008/T1 的 `sim_user` 桥接与 0008/T2 的 `Sandbox(workspace=dir)` 原样复用、不在本任务 files 内。被本组 T2（落 `sources/empty.py` 经自动发现注册）消费。

**待解问题**

1) 依赖供给与 `WorkspaceSpec.setup` 钩子（0008 起仅占位、不执行）的落地：**已收进本组 T3**（每局建 per-workspace `.venv` + pip、Sandbox 探测 `.venv` 使用之），使带第三方依赖的任务（部分 NL2Repo、多数真实仓库）能在 Sandbox 里跑起来；cached venv 复用等细节见 T3 open-questions。
2) 后续重型源（容器化的 SWE-bench / Terminal-Bench、git@commit 快照）是否需把消费港口从「工作区目录」升级为「可运行句柄 {cwd, run(cmd), cleanup}」，以便 Provider 与（将来的）客观评测共享同一运行时能力。本组港口保持「目录 + 本地 shell」不变；是否升级、何时升级留下游评估，目的是让重型源接入时尽量不返工港口。

### T2 · empty/nl-doc 源（可插拔证明）（P2 / done）

**涉及文件**

- `backend/auto_designer/user/sim/sources/empty.py`
- `backend/tests/user/sim/test_seed_source_empty.py`

**做什么**

在 T1 接缝上接入第二个源 `empty`，作为「可插拔/可加性」的活体证明：新建一个隔离空工作区目录，`params` 含 `doc` 时把其文本写成一个需求说明文件（覆盖 NL2Repo 式「仅一份说明文档、从空仓起步」的场景）。关键约束——接入它**只新增 `sources/empty.py` 一个模块**，靠 T1 的子包自动发现注册，`seed_source.py` / `models.py` / `workspace.py` 与消费侧（sim_user / Sandbox）零改动。

**为什么**

接缝若不被第二个真实源验证，「可插拔」只是声明。`empty` 选作第二源有两重价值：一是零新基建（仍是本地目录，不引入容器 / git / 依赖供给），把验证成本压到最低；二是它直接表达「空工作区 + 一段自然语言诉求」这一最小任务形态——即 NL2Repo 式从零构建的注入形状，证明现有港口已能承载这类任务（其客观评测属非目标，归下游）。本任务以「加一个源 = 一个文件、核心零改」来锁死 T1 边界是否真的解耦。

**整体设计**

`sources/empty.py` 定义 `EmptySource`，`@register("empty")` 自注册（T1 的子包扫描在 import 期自动发现，无需任何中心登记）：

```
WorkspaceSpec{kind="empty", params={"doc"?: str, "doc_name"?: str}}
        │ provision(spec, dest_root)
        ▼
新建隔离目录（tempfile.mkdtemp 或 dest_root/<name>）
        └─ params.doc 非空 → 写 params.doc_name（缺省 "SPEC.md"）为该目录下的说明文件
返回目录绝对路径（空或仅含说明文件）
```

- 不读 `fixture`（empty 与本地 fixture 无关）；只认 `params`。`doc` 缺省为空 → 落纯空目录；给定 → 写一个需求说明文件，使内层 agent 有「读说明文档」的落脚。
- 隔离与返回契约同 local-fixture：每次 provision 一个全新目录、互不污染、返回绝对路径，从而 `Sandbox(workspace=dir)` 可直接当 cwd 复用。
- 可加性的硬证据：本任务 files 仅 `sources/empty.py` + 测试；T1 拥有的文件一律不在本任务 files 内（disjoint），却能在测试中验证 `empty` 已被注册——这正是 ports-and-adapters 边界成立的判据。

**接口**

- `EmptySource`（`sources/empty.py`）：`kind="empty"`；`provision(spec, dest_root=None) -> str` 新建隔离目录；`spec.params.get("doc")` 非空时写 `spec.params.get("doc_name", "SPEC.md")`。
- 经 `@register("empty")` 入 T1 注册表；调用方仍走 T1 顶层 `provision(spec)`，不直接依赖本类。
- 复用 T1 的 `WorkspaceSpec`（不新增字段）：`empty` 的输入完全落在既有 `kind` + `params` 上，印证 `params: dict` 的扩展位足够承载新源。

**取舍**

- 用通用 `params.doc`/`doc_name` 而非给 `empty` 引入专属 schema：保持 `WorkspaceSpec` 不随每个源膨胀；代价是 `params` 弱类型，靠 source 内部自校验与测试约束。
- 第二源选 `empty` 而非直接做 git/容器源：以最低成本验证接缝是否解耦；代价是未覆盖「重型供给」路径——那是有意为之，重型运行时句柄、git@commit 仍为本组非目标、留下游 spec；依赖供给（venv/pip）现由本组 T3 落地（`empty` 导入的带依赖任务如 funcy 靠 T3 备齐依赖方能真跑）。

**验收标准**

`provision(WorkspaceSpec(kind="empty"))` 返回一个存在的隔离空目录；带 `params={"doc": "..."}` 时目录下含对应说明文件且内容一致，`doc_name` 可覆盖文件名。两次 provision 目录隔离。**不修改 T1 任何文件**的前提下，import `seed_source` 后 `available_kinds()` 含 `empty`（自动发现注册生效）。该目录可作为 `Sandbox` 的 cwd 正常 run/读写（沿用 0008/T2 行为，不重测 Sandbox 内部）。

**测试**

test_seed_source_empty.py：(a) `provision(kind="empty")` 落地隔离空目录、存在且为空；(b) 带 `doc` → 目录含说明文件且内容一致，`doc_name` 覆盖生效；(c) 两次 provision 隔离；(d) 可加性证据——本测试不 import `empty` 模块本身、仅 import `seed_source`，断言 `available_kinds()` 含 `empty`（证明仅靠落模块即被自动发现）；(e) 序列化——`WorkspaceSpec(kind="empty", params={...})` to_dict/from_dict 往返一致。

**参考**

依赖 0009/T1 的 `SeedSource` 协议、`register`/`provision` 注册表与 `sources/` 自动发现机制，以及 T1 为 `WorkspaceSpec` 增的 `kind`/`params`。落脚的 `Sandbox`（0008/T2）原样复用、不在本任务 files 内。NL2Repo 式任务的客观评测（跑上游测试）为非目标，归下游 spec。

### T3 · 依赖供给（setup 钩子落地：per-workspace venv + pip）（P1 / done）

**涉及文件**

- `backend/auto_designer/user/sim/deps.py`
- `backend/tests/user/sim/test_deps.py`
- `backend/auto_designer/user/sim/sandbox.py`
- `backend/auto_designer/loop/orchestrator.py`
- `backend/auto_designer/loop/sim_user.py`

**做什么**

把 `WorkspaceSpec.setup`（0008 起仅占位、从不执行）真正落地，补上供给侧最后一环：一个源 provision 出工作区目录后，按 `setup` 命令在该目录里备好依赖环境（约定为 per-workspace `.venv` + pip 安装），并让消费侧 `Sandbox` 的 `run_shell` 自动使用该 venv。由此带第三方依赖的任务（如 NL2Repo 的 funcy 需 `pytest`/`whatever`）不再卡在「stdlib-only 假设」上——工作区从「有文件」升级为「按其声明依赖可跑」。新增 `deps.py`（setup 执行器）+ 在共享工作区落地点（orchestrator，materialize 之后、launch 之前）调用它，并让 `Sandbox` 探测 `.venv` 注入 PATH。不改 T1/T2 任何文件、不扩 `WorkspaceSpec` schema（复用既有 `setup`）。

**为什么**

0008/T1、0009/T1 都把「依赖供给」列为非目标、`WorkspaceSpec.setup` 只留占位不执行，于是当前 `Sandbox` 只能用宿主 ambient 环境跑 stdlib——带第三方依赖的任务（大多数真实仓库、部分 NL2Repo）无法真跑其声明的验证。以 funcy 为例：库本体是纯 stdlib，但其 `start.md` 声明验证需 `pytest 7.4.3` + 第三方 `whatever 0.7`，还要求 `pip install -e .`；没有依赖供给，用户 agent 在 Sandbox 里 `import whatever` 必 `ModuleNotFoundError`、`python setup.py test` 跑不起来。本任务补上这一环，让「供给一个工作区」真正意味着「供给一个能按其声明依赖运行的工作区」，是 0009 供给侧的收口（此前刻意推迟、现收进本组）。

**范围**

1) `deps.py`（新）：`ensure_deps(workspace_dir: str, spec: WorkspaceSpec) -> None`——`spec.setup` 非空时，在 `workspace_dir` 为 cwd 逐条执行 setup 命令（subprocess，带超时/输出捕获），失败即抛并附命令与 stderr。约定 setup 命令自建 per-workspace `.venv` 并把依赖装进去（如 `python -m venv .venv` → `.venv/bin/pip install -e .` / 装 pytest+whatever）；`ensure_deps` 本身不硬编码建 venv 逻辑，只忠实执行 setup（奥卡姆：机制留在数据里）。幂等：`.venv` 已就位可跳过重建（由 setup 命令或一个 marker 判定）。2) `sandbox.py`（0008/T2，跨组）：`run_shell` 探测 `<workspace>/.venv/bin`，存在则注入 `VIRTUAL_ENV` 并把它前置进 `PATH`，使 `python`/`pytest` 解析到 venv；无 `.venv` 时行为不变（退化为今天的 ambient）。3) `orchestrator.py`（0007/0008，跨组）：在共享工作区 materialize *之后、launch 之前* 调 `ensure_deps(workspace_dir, scenario.workspace)`，使 harness 与用户 agent 两侧共享的同一目录在开跑前依赖已就位。4) `sim_user.py`（0005/0007，跨组）：其 `run()` 的直连回落路径（未收到 orchestrator 传入 `workspace_dir` 但 `scenario.workspace` 非空时自行 `materialize_workspace`）在 materialize *之后、bind_session 之前* 也对称调 `ensure_deps(ws, scenario.workspace)`，与 orchestrator 主路径同构——确保这条生产接缝「建了工作区即备好依赖」，不静默缺依赖。orchestrator 已传 `workspace_dir` 的主路径依赖已由 orchestrator 就位，sim_user 不重复调。**非目标**（留后续）：容器/hermetic 隔离与网络策略；跨会话 venv 缓存/复用（本轮每局现装）；lockfile/版本求解；从需求文档自动推导 setup 命令（本轮 setup 由场景作者/未来 adapter 显式给出）；harness 子进程内 bash 使用该 venv（harness 为 0003 黑盒，其 bash 是否走 workspace venv 留 open-question）。

**整体设计**

供给链补最后一环（消费港口仍冻结：目录 + 本地 shell）：

```
SeedSource.provision(spec) -> workspace_dir      （T1/T2，落地文件）
        │  orchestrator：materialize 之后、launch 之前
        ▼
deps.ensure_deps(workspace_dir, spec)            （T3，执行 spec.setup 备依赖）
        │  约定 setup 建 <workspace_dir>/.venv 并 pip 装入
        ▼
两侧共享 workspace_dir 开跑：
   ├─ harness 子进程（SANDBOX_WORK_DIR=workspace_dir，0008/T1v2）
   └─ 用户 agent Sandbox(workspace=workspace_dir)（0008/T2）
            └─ run_shell 探测 .venv → 注入 VIRTUAL_ENV + PATH 前置 → python/pytest 用 venv
```

- 为何 hook 在 orchestrator 而非 provision 内：与 0008/T1v2 让 materialize 上移 orchestrator 同因——工作区要被 harness 与用户 agent 两侧共享，依赖必须在 launch *之前* 就位、且落在两侧同指的那个目录上；orchestrator 是唯一同时掌握 materialize 结果与 launch 时机的层。这也让 T3 只碰跨组的 orchestrator/sandbox，不动 0009-T1/T2 的 provision/materialize 文件（组内 files disjoint）。
- 为何复用 `setup: list[str]` 而非给 `WorkspaceSpec` 加结构化 deps 字段：0008/T1 已预留 `setup` 钩子，MVP 直接激活它即可，不扩 schema（不碰 T1 的 models.py）；setup 是「在工作区里把环境备好」的通用命令序列，venv 约定活在数据（命令）里而非代码里。
- 为何 per-workspace `.venv` 而非装进 ambient：每局隔离、可清理、不污染宿主/其它会话；代价是每局现装有耗时（缓存留 open-question）。
- Sandbox 探测 `.venv` 而非要求 agent 显式调 `.venv/bin/python`：让「工作区带 venv」对内层 LLM 透明——它照常 `run_shell("pytest ...")` 即命中 venv，符合真人在已配好环境的项目里的直觉。
- 退化与兼容：`spec.setup` 为空（含所有既有 fixture/empty 场景）时 `ensure_deps` 空操作、无 `.venv` 生成、Sandbox 走 ambient——对 0008/0009 既有行为零改动。

**接口**

- `deps.ensure_deps(workspace_dir: str, spec: WorkspaceSpec) -> None`（`user/sim/deps.py`）：`spec.setup` 空则直接返回；否则以 `workspace_dir` 为 cwd 逐条 subprocess 执行，非零退出抛异常（附命令、returncode、截断 stderr）；可选带总超时。
- `Sandbox`（`user/sim/sandbox.py`，0008/T2）：新增私有 env 组装——`run_shell` 执行前，若 `<workspace>/.venv/bin` 存在则设 `VIRTUAL_ENV=<workspace>/.venv` 且 `PATH=<workspace>/.venv/bin:$PATH`。对外接口签名不变。
- `orchestrator.run_round`（0007/0008，跨组）：在 `workspace_dir = materialize_workspace(...)` 之后、`launch(..., workspace_dir=workspace_dir)` 之前插入 `ensure_deps(workspace_dir, scenario.workspace)`（`scenario.workspace` 为 None 时跳过）。
- `sim_user.run`（0005/0007，跨组）：直连回落分支（`workspace_dir` 为 None 且 `scenario.workspace` 非空）在 `ws = materialize_workspace(scenario.workspace)` 之后、`bind_session` 之前插入 `ensure_deps(ws, scenario.workspace)`，与 orchestrator 主路径对称。orchestrator 已传 `workspace_dir` 的路径不在 sim_user 内重复 ensure（依赖已由 orchestrator 就位）。故 ensure_deps 的落点覆盖两处：orchestrator 主路径 + sim_user 直连回落。
- 不新增/不修改 `WorkspaceSpec` 字段（复用 `setup`）；不改 `SeedSource`/`provision`/`materialize` 签名；不改 harness stdio 协议。
- setup 命令示例（funcy，由场景/adapter 提供）：`["python -m venv .venv", ".venv/bin/pip install pytest==7.4.3 whatever==0.7", ".venv/bin/pip install -e ."]`。

**取舍**

- 激活既有 `setup` 而非新造 provisioner 框架：奥卡姆，最小改动打通依赖路径；代价是 setup 是弱类型 shell 命令、靠场景作者写对（无 lockfile 求解）。
- 每局现装 venv：环境确定、隔离、可清理；代价是耗时与网络依赖（pip 需可达源）——跨会话缓存/预热留 open-question，不在 MVP。
- 只让用户 agent 侧 Sandbox 用 venv、暂不管 harness bash：把改动限制在可控的消费侧，不侵入 0003 harness 黑盒；代价是若某任务要 harness 也按 venv 跑，需后续让 harness entry 也识别 workspace `.venv`（open-question）。
- 非安全/非 hermetic：sandbox 仍是 cwd+超时的最小隔离，venv 只解决「依赖可见」，不解决「恶意代码/网络隔离」——沿用 0008/T2 威胁模型，强隔离留下游。
- hook 落在「materialize 工作区的每个生产接缝」而非仅 orchestrator：主路径由 orchestrator 在共享工作区 materialize 后 ensure；sim_user 的直连回落（未经 orchestrator 但仍自行 materialize）同样在 materialize 后对称 ensure_deps——保证任何「建了工作区」的生产路径都不会静默缺依赖（修订 A2：早期版本把回落路径不调 ensure_deps 记为可接受 tradeoff，实践中它是一条会静默缺依赖的生产接缝，故收敛为对称调用）。代价是两处落点需各自维护对称性；只有纯工具/独立 smoke 脚本（不走这两条生产接缝、自行 materialize）才需自理 `ensure_deps`（可接受，属工具侧）。

**验收标准**

`spec.setup` 为空时 `ensure_deps` 空操作、不建 `.venv`、Sandbox 行为与今天一致（既有场景零回归）。给定一个 `setup` 会建 `.venv` 并 pip 装入某包的 spec：`ensure_deps` 后 `<workspace>/.venv` 存在且该包可被 venv 的 python import。`Sandbox(workspace=dir)` 在 `<dir>/.venv` 存在时，`run_shell("python -c 'import <pkg>'")` 成功、`run_shell` 内 `python` 解析到 `.venv`（PATH/VIRTUAL_ENV 注入生效）；无 `.venv` 时退化 ambient。orchestrator 在 materialize 之后、launch 之前调 `ensure_deps`（`scenario.workspace` 为 None 时不调）。不经 orchestrator 的 sim_user 直连回落路径（未传 `workspace_dir` 但 `scenario.workspace` 非空）在自行 materialize 之后、bind_session 之前也调 `ensure_deps`（且顺序：materialize 在前）；传入 `workspace_dir` 的主路径不在 sim_user 内重复调 `ensure_deps`。setup 命令失败时 `ensure_deps` 抛错并携带足够诊断（命令+stderr）。端到端（可选、需网络）：以 funcy 式 setup 备好 `pytest`+`whatever` 后，Sandbox 内 `pytest` 能 import `whatever`。

**测试**

test_deps.py：(a) `setup` 为空 → `ensure_deps` 空操作、目录无 `.venv`；(b) setup 建 `.venv` + 装一个纯本地可控包（用离线/本地 wheel 或标准库脚本模拟，避免 CI 走网络）→ `.venv` 存在且目标可 import；(c) setup 某命令非零退出 → 抛错且消息含该命令与 stderr；(d) 幂等——`.venv` 已在时重复调不重复重建/不报错。更新 sandbox 测试（在 0008/T2 的 test_tools.py 或本任务 test_deps.py 内，按落点归属）：(e) 工作区含 `.venv/bin` 时 `run_shell` 的 `python` 命中 venv（造一个假 `.venv/bin/python` 或断言注入的 PATH/VIRTUAL_ENV）；无 `.venv` 时不注入。orchestrator 测试（跨组 test_orchestrator.py）：(f) materialize 之后、launch 之前调用 `ensure_deps`（spy 断言顺序），`scenario.workspace` 为 None 时不调。sim_user 测试（跨组 test_sim_user.py）：(g) 不传 `workspace_dir`、`scenario.workspace` 非空 → 回落分支自行 materialize 后调 `ensure_deps`（spy 断言顺序：materialize 在前）；(h) 传入 `workspace_dir` 的主路径不在 sim_user 内调 `ensure_deps`（反向断言）。皆离线、不走网络。CI 约束：默认用例不依赖真实 pip 网络；需网络的 funcy 端到端标记为可选/手动。

**参考**

激活 0008/T1 预留的 `WorkspaceSpec.setup` 钩子；落地点在 0008/T1v2 的共享工作区 materialize 之后（orchestrator，run_session 之前）；消费于 0008/T2 的 `Sandbox`（run_shell 注入 venv）。依赖本组 T1 的 `provision`/`WorkspaceSpec`（不改其文件）。解决本组 T1 open-question #1、0008/T1 tradeoffs 记录的依赖供给缺口。funcy 等 NL2Repo 任务经 T2 `empty` 源导入后，靠本任务把其声明依赖备齐方能真跑验证（其客观判分仍为非目标）。

**待解问题**

1) 跨会话 venv 缓存/预热：每局现装耗时且需网络；是否按 (deps 指纹) 缓存复用一份 venv、或预构建镜像层。2) harness 子进程 bash 是否也应使用 workspace `.venv`（当前仅用户 agent Sandbox 用）：需 0003 harness entry 识别 workspace venv，涉及跨仓改动。3) 无网络/受限环境的依赖供给（离线镜像、vendored wheels）。4) setup 命令的来源：从需求文档（如 funcy start.md 的依赖清单）自动生成 setup，还是由场景/adapter 手写——前者需一个「文档→setup」的推导步骤，归后续。5) 依赖安装失败的策略：整局判失败，还是降级为「无该依赖的受限核实」。

### T4 · git 源（clone repo@commit 成快照工作区）（P1 / done）

**涉及文件**

- `backend/auto_designer/user/sim/sources/git.py`
- `backend/tests/user/sim/test_git_source.py`

**做什么**

在 T1 接缝上接入第三个源 `git`：`provision` 时把 `repo` clone 到隔离工作区目录并 `git checkout <commit>`，得到「某仓库停在某 commit」的干净快照，返回该目录。兑现 0009 当初为「未来 SWE-bench / Terminal-Bench」预留的扩展点——真实 repo 任务（SWE-bench 的 `base_commit` 未修复态、funcy@某版本等）的起点正是这一快照，而现有两源（`local-fixture` 只拷 vendored 目录、`empty` 只给空目录）立不起来。`repo`/`commit`（及可选 `ref`/`depth`）经 `WorkspaceSpec.params` 承载，不扩 schema、`kind="git"`；每局 fresh（每 round 重 clone/checkout 一份，隔离避免跨局串状态，与 local-fixture 每局重拷同理）。接入它**只新增 `sources/git.py` 一个模块**，靠 T1 子包自动发现注册，协议/注册表/`materialize` 薄壳/既有两源/orchestrator/sim_user/Sandbox 一律不改。

**为什么**

0009 把供给做成可插拔（T1 接缝 + T2 可加性证明），明确目标之一是为「未来 SWE-bench / Terminal-Bench」留扩展点；但已落地的两源均只能起本地：`local-fixture` copytree 一个 in-repo vendored 目录、`empty` 开一个空目录（可选写说明文档）。真实软件工程任务的注入形状不是这两者——它是「某公开仓库停在某历史 commit 的工作树快照」：SWE-bench 实例即 `repo` 在 `base_commit` 处的未修复态，funcy 式任务是某发布版本的源码树。没有「从 git clone @commit」的源，这类任务的起点根本立不起来，可插拔接缝对真实 repo 分布形同虚设。本任务兑现该扩展点，补上通用 `git` 源，使供给侧能承载「基于某仓库某快照」的任务族（具体 benchmark 字段→场景的适配层为非目标，见下）。

**范围**

1) `sources/git.py`（新）：定义 `GitSource`，`@register("git")` 自注册（T1 子包扫描 import 期自动发现，无中心登记）。`provision(spec, dest_root)`：从 `spec.params` 读 `repo`（必填）、`commit`（必填）、可选 `ref`/`depth`；在隔离目录里 `git clone` 该 repo、`git checkout <commit>` 恢复快照，返回该目录绝对路径。隔离/返回契约同另两源（每局全新目录、互不污染、返回绝对路径）。2) 复用既有 `WorkspaceSpec.params` 承载 `repo`/`commit`/`ref`/`depth`——**不新增/不修改 `WorkspaceSpec` 字段**（与 T1 给 empty 用 params 一致，不碰 T1 的 models.py）。**不改** `SeedSource` 协议/注册表/顶层 `provision`（T1）、`empty`（T2）、`materialize` 薄壳、消费侧 `orchestrator`/`sim_user`/`Sandbox`。非目标（留后续/单独）：具体 benchmark（SWE-bench 等）字段→`SeedScenario` 的适配层（adapter）；容器/hermetic 与版本 pin 的环境强度；私有仓鉴权。

**整体设计**

第三源接入，消费侧零改（港口仍冻结：目录 + 本地 shell）：

```
WorkspaceSpec{kind="git", params={repo, commit, ref?, depth?}}
        │ provision(spec, dest_root)   ← T1 顶层分派按 kind 命中 GitSource
        ▼
新建隔离目录（tempfile.mkdtemp 或 dest_root/<name>）
        ├─ git clone <repo> <dir>        （可选 --depth / 指定 ref 加速）
        └─ git checkout <commit>         （恢复到该快照：SWE-bench 即 base_commit 未修复态）
返回目录绝对路径（该 repo 在该 commit 的工作树）
        ▼
每局时序不变：materialize(git clone+checkout) → ensure_deps(按 setup 在快照里装依赖，如 pip install -e .，T3)
              → launch harness(注入 SANDBOX_WORK_DIR) → 跑会话(user agent 绑同一快照)
```

- 签名与另两源一致：`GitSource.kind="git"`、`provision(spec, dest_root=None) -> str`，从而 T1 顶层 `provision`/注册表分派、`materialize` 薄壳、消费侧全部零改——这是 ports-and-adapters 边界成立的又一判据（第三个 adapter 只落一个文件）。
- 复用 `params` 而非给 `git` 引入专属 schema：`repo`/`commit`/`ref`/`depth` 全落在既有 `params: dict`，`WorkspaceSpec` 不随源膨胀（不碰 T1 models.py），与 T2 给 empty 用 `params.doc` 同构；字段完整性由 source 内部自校验。
- 每局 fresh：每 round 重新 clone/checkout 一份干净快照，独立目录、跨局隔离、可清理，避免上一局 harness 改动或用户 agent 写入串到下一局——与 local-fixture 每局重拷同理。
- 与 T3 依赖供给正交：`git` 只负责「把某仓库某快照落成工作区」，环境强度（venv/pip、`pip install -e .`）仍由 T3 的 `setup`/`ensure_deps` 在该快照目录里备齐；二者在既有时序里前后衔接，互不改对方文件。

**接口**

- `GitSource`（`sources/git.py`）：`kind="git"`；`provision(spec: WorkspaceSpec, dest_root: str | None = None) -> str`——从 `spec.params` 读 `repo`（必填，url 或 owner/repo）、`commit`（必填，恢复的快照 sha/ref）、可选 `ref`（clone 时定向分支/tag）、`depth`（浅克隆深度）；在隔离目录 clone + `git checkout <commit>`，返回该目录绝对路径。
- 经 `@register("git")` 入 T1 注册表；调用方仍走 T1 顶层 `provision(spec)`，不直接依赖本类。
- 复用 T1 的 `WorkspaceSpec`（不新增字段）：`git` 的输入完全落在既有 `kind` + `params` 上，再证 `params: dict` 扩展位足够承载新源。
- `repo`/`commit` 缺失或 clone/checkout 失败时抛错并携带诊断（缺失字段名、失败命令 + stderr）。
- 不改 `SeedSource`/`provision`/`materialize` 签名，不改消费侧 `orchestrator`/`sim_user`/`Sandbox`，不改 harness stdio 协议。

**取舍**

- clone 每局现做（而非缓存/共享 bare 镜像）：换来确定、隔离、可清理的干净快照；代价是耗时 + 需网络可达 git 源——跨局 clone 缓存/本地镜像复用留后续，不在本任务。
- 用通用 `params.repo`/`commit` 而非给 `git` 引入专属强类型 schema：保持 `WorkspaceSpec` 不随每源膨胀、不碰 T1；代价是 `params` 弱类型，靠 source 内部自校验与测试约束（同 T2 empty）。
- 只解决「把某仓库某快照落成工作区」：环境强度仍靠 T3 的 `setup`（venv+pip）；挑版本/系统依赖/需官方镜像的实例不保证可跑——属容器/hermetic 那条既有非目标，本任务不越界造重型运行时。
- 第三源选通用 `git` 而非直接做 SWE-bench 专用源：通用 clone@commit 可复用于所有「基于某仓库某快照」的任务族，把 benchmark 专属字段映射隔离到独立 adapter；代价是本任务不产出可直接消费 SWE-bench 数据集的端到端链路（adapter 归后续）。

**验收标准**

给定 `WorkspaceSpec(kind="git", params={repo, commit})`，`provision` 后返回目录是该 repo 在该 commit 的工作树：可校验 `git rev-parse HEAD` == `commit`、关键文件存在。隔离——每次 provision 落独立目录、互不污染。`commit` 缺失（或 `repo` 缺失）时抛错且消息含缺失字段名；clone/checkout 失败时抛错并携带失败命令 + stderr 诊断。注册表按 `kind="git"` 分派到 `GitSource`；**不修改 T1/T2/T3 任何文件**的前提下 import `seed_source` 后 `available_kinds()` 含 `git`（自动发现注册生效）。与既有源（local-fixture/empty）及消费侧（materialize 薄壳 / orchestrator / sim_user / Sandbox）零回归。该目录可作为 `Sandbox` 的 cwd 与 harness 的 `SANDBOX_WORK_DIR` 正常复用（沿用既有行为，不重测消费侧内部）。CI 约束：默认单测**不走真实网络**——用一个本地临时 git 仓当 `repo`（origin），或对 clone 命令做 spy/mock；真实远端 clone 的端到端标记为可选/手动。

**测试**

test_git_source.py（皆离线、不走网络）：(a) 本地临时 git 仓——`git init` + 造两个 commit（记 C1、C2），以其路径为 `repo`；`provision(kind="git", params={repo, commit=C1})` 后断言工作树恢复到 C1（`git rev-parse HEAD` == C1、C1 特有文件在/C2 新增文件不在）；(b) 目录隔离——两次 provision 落不同目录、互不污染；(c) 缺 `commit`（及缺 `repo`）→ 抛错且消息含缺失字段名；clone/checkout 失败（如不存在的 commit 或坏 repo 路径）→ 抛错且携带失败命令 + stderr；(d) 可加性/分派——本测试不 import `git` 模块本身、仅 import `seed_source`，断言 `available_kinds()` 含 `git` 且顶层 `provision` 按 `kind="git"` 分派到 `GitSource`（证明仅靠落模块即被自动发现）；(e) 序列化——`WorkspaceSpec(kind="git", params={repo, commit})` to_dict/from_dict 往返一致。真实远端 clone 的端到端标记为可选/手动，不在默认 CI 用例内。

**参考**

依赖 0009/T1 的 `SeedSource` 协议、`register`/`provision` 注册表与 `sources/` 自动发现机制，以及 T1 为 `WorkspaceSpec` 增的 `kind`/`params`（本任务复用 `params`，不改其文件）。落脚的共享工作区（0008/T1 materialize 上移 orchestrator）与 `Sandbox`（0008/T2）原样复用、不在本任务 files 内。与本组 T3 依赖供给正交衔接：`git` 落快照、T3 的 `setup`/`ensure_deps` 在该快照里备依赖。兑现 0009 metadata 为「未来 SWE-bench / Terminal-Bench」预留的供给侧扩展点。

**待解问题**

1) 具体 benchmark（SWE-bench 等）字段 → `SeedScenario`/`WorkspaceSpec` 的适配层（adapter）：把数据集实例的 `repo`/`base_commit`/环境声明映射成本源可消费的 `params` + T3 的 `setup`——本任务只给通用 git 源，adapter 归后续/单独 spec。2) 容器 / hermetic 与版本 pin 的环境强度：挑系统依赖或需官方镜像的实例，仅靠 clone@commit + venv 不保证可跑（沿用既有「重型运行时留下游」非目标）。3) oracle / 客观判分（跑上游测试判修复对错）：红线 held-out，永不进本框架训练。4) harness 子进程 bash 是否用工作区 venv：属 harness 侧 / 开发者进化，已明确划出框架范围（同 T3 open-question）。5) 私有仓鉴权（token / ssh key 注入 clone）：本任务默认公开仓 / 本地仓，鉴权留后续。6) 跨局 clone 缓存 / 本地 bare 镜像复用以省耗时与网络：本轮每局现 clone，缓存留后续。
