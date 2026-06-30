# 0009 种子工作区供给可插拔（SeedSource 接缝）

> 本文件由 `spec render` 自动生成，请勿手工编辑。
> 内容来源：本组 `metadata.yaml` 与 `tasks/T*.yaml`（关联 issue #9）。

## 总览

本组承接 spec-0008/T1：彼时 `SeedScenario.workspace` 经 `WorkspaceSpec{fixture, setup}` + `materialize()` 落地，供给路径是**唯一且硬编码的本地 copytree**。随着任务源增多（NL2Repo 式空仓起步、未来 SWE-bench / Terminal-Bench 等），**供给侧需可插拔**；而**消费港口**——`SeedScenario.description` 文本 + 一个被 `Sandbox`/`sim_user` 当 cwd 的工作区目录——保持冻结、零改动。

本组把「工作区供给」抽象为按 `kind` 注册的 `SeedSource` 协议：把既有 `materialize` 降为首个 `local-fixture` 实现（行为等价、向后兼容），并新增一个轻量 `empty` 源（新建空目录，可选写入需求说明文件，覆盖 NL2Repo 式「仅说明文档」起步）以证明**可加性**——新增一个源 = 落一个新模块（被自动发现注册）+ 注册侧/消费侧零改动。`workspace.materialize()` 退化为薄壳委托给注册表，故 `sim_user` 桥接与 `Sandbox` 调用点一行不改。

**明确非目标**（仅作为下游 spec 的扩展点记录，本组不实现）：Oracle / 客观判分（属平行评测系统，与用户主观核实解耦）；容器化「可运行句柄」运行时（`run(cmd)`/`cleanup`）；git@commit 取数；依赖供给（venv/pip）。本组只动供给侧、只凿接缝 + 一个已验证的第二实现，不提前造框架。

数据流脊柱（编号即执行序：先立接缝 T1，再加第二源 T2 证明可插拔）：

```
seed 场景  SeedScenario.workspace = WorkspaceSpec{kind, fixture?, params, setup}
   │  按 kind 查 SeedSource 注册表（T1 立协议 + 注册表 + sources/ 自动发现）
   ▼
SeedSource.provision(spec, dest) -> workspace_dir
   ├─ kind="local-fixture": copytree in-repo fixture （T1，= 0008 行为）
   └─ kind="empty":        新建空目录，可选写需求文档 （T2，可加性证明）
   ▼
消费港口不变：workspace.materialize() 薄壳委托 → sim_user 桥接 → Sandbox(workspace=dir) 当 cwd（0008 原样）
```

## 任务编排

```mermaid
graph LR
    nT1["T1 SeedSource 协议 + 注册表 + local-fixture 实现"]
    nT2["T2 empty/nl-doc 源（可插拔证明）"]
    nT1 --> nT2
```

| 任务 | 标题 | 优先级 | 状态 | 依赖 |
|----|----|----|----|----|
| T1 | SeedSource 协议 + 注册表 + local-fixture 实现 | P1 | pending | — |
| T2 | empty/nl-doc 源（可插拔证明） | P2 | pending | T1 |

## 各任务方案

### T1 · SeedSource 协议 + 注册表 + local-fixture 实现（P1 / pending）

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

1) 依赖供给与 `WorkspaceSpec.setup` 钩子（0008 起仅占位、不执行）何时真正实现：用 cached venv 还是每局 pip install？这决定带第三方依赖的任务（部分 NL2Repo、多数真实仓库）能否在当前 stdlib-only 假设的 Sandbox 里跑起来。本组不做，归后续独立 spec。
2) 后续重型源（容器化的 SWE-bench / Terminal-Bench、git@commit 快照）是否需把消费港口从「工作区目录」升级为「可运行句柄 {cwd, run(cmd), cleanup}」，以便 Provider 与（将来的）客观评测共享同一运行时能力。本组港口保持「目录 + 本地 shell」不变；是否升级、何时升级留下游评估，目的是让重型源接入时尽量不返工港口。

### T2 · empty/nl-doc 源（可插拔证明）（P2 / pending）

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
- 第二源选 `empty` 而非直接做 git/容器源：以最低成本验证接缝是否解耦；代价是未覆盖「重型供给」路径——那是有意为之，重型运行时句柄、git@commit、依赖供给均为本组非目标，留下游 spec。

**验收标准**

`provision(WorkspaceSpec(kind="empty"))` 返回一个存在的隔离空目录；带 `params={"doc": "..."}` 时目录下含对应说明文件且内容一致，`doc_name` 可覆盖文件名。两次 provision 目录隔离。**不修改 T1 任何文件**的前提下，import `seed_source` 后 `available_kinds()` 含 `empty`（自动发现注册生效）。该目录可作为 `Sandbox` 的 cwd 正常 run/读写（沿用 0008/T2 行为，不重测 Sandbox 内部）。

**测试**

test_seed_source_empty.py：(a) `provision(kind="empty")` 落地隔离空目录、存在且为空；(b) 带 `doc` → 目录含说明文件且内容一致，`doc_name` 覆盖生效；(c) 两次 provision 隔离；(d) 可加性证据——本测试不 import `empty` 模块本身、仅 import `seed_source`，断言 `available_kinds()` 含 `empty`（证明仅靠落模块即被自动发现）；(e) 序列化——`WorkspaceSpec(kind="empty", params={...})` to_dict/from_dict 往返一致。

**参考**

依赖 0009/T1 的 `SeedSource` 协议、`register`/`provision` 注册表与 `sources/` 自动发现机制，以及 T1 为 `WorkspaceSpec` 增的 `kind`/`params`。落脚的 `Sandbox`（0008/T2）原样复用、不在本任务 files 内。NL2Repo 式任务的客观评测（跑上游测试）为非目标，归下游 spec。
