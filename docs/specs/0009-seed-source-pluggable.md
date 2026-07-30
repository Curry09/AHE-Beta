---
number: "0009"
title: 种子工作区供给可插拔（SeedSource 接缝）
issue: 9
slug: seed-source-pluggable
summary: 本组承接 spec-0008/T1：彼时 `SeedScenario.workspace` 经 `WorkspaceSpec{fixture, setup}` + `materialize()` 落地，供给路径是**唯一且硬编码的本地 copytree**。随着任务源增多（NL2Repo 式空仓起步、未来 SWE-bench / Terminal-Bench 等），**供给侧需可插拔**；而**消费港口**——`SeedScenario.description` 文本 + 一个被 `Sandbox`/`sim_user` 当 cwd 的工作区目录——保持冻结、零改动。
tasks:
  - id: T1
    title: SeedSource 协议 + 注册表 + local-fixture 实现
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to:
      - ref: 0008/T1
        type: extends
    parallel: false
    files:
      - backend/auto_designer/user/sim/seed_source.py
      - backend/auto_designer/user/sim/sources/__init__.py
      - backend/auto_designer/user/sim/sources/local_fixture.py
      - backend/auto_designer/models.py
      - backend/auto_designer/user/sim/workspace.py
      - backend/tests/user/sim/test_seed_source.py
      - backend/tests/user/sim/test_workspace.py
    scope: '1) `seed_source.py`：定义 `SeedSource` 协议、`kind → SeedSource` 注册表、`register` 装饰器、顶层 `provision` 分派，并在 import 期遍历 `sources/` 子包触发各源自注册。2) `sources/local_fixture.py`：把 0008/T1 的 copytree 逻辑迁来，作为 `kind="local-fixture"` 首实现。3) `models.py`：`WorkspaceSpec` 增 `kind: str = "local-fixture"` 与 `params: dict = {}`（向后兼容，缺字段→缺省）。4) `workspace.py`：`materialize` 改为委托 `provision` 的薄壳，调用点不动。不实现任何新源（empty 归 T2）、不碰消费侧（sim_user / Sandbox）。'
    acceptance: 注册表按 `kind` 分派到正确源；未知 kind 抛 `ValueError` 且消息含已注册 kind；`available_kinds()` 含 `local-fixture`。不手动 import `local_fixture` 时，import `seed_source` 后 `local-fixture` 已在注册表（自动发现生效）。`WorkspaceSpec.kind` 缺省 `local-fixture`、`params` 缺省 `{}`；`to_dict/from_dict` 往返一致；旧 dict（无 `kind`/`params`）→ `local-fixture` 且既有行为不变。对 `billing-split` provision 落地目录存在、含 `billing/core.py` 且 stdlib 可 import/运行，两次 provision 互相隔离。`materialize(spec)` 与 `provision(spec)` 等价。
  - id: T2
    title: empty/nl-doc 源（可插拔证明）
    status: done
    priority: P2
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/user/sim/sources/empty.py
      - backend/tests/user/sim/test_seed_source_empty.py
    scope: ''
    acceptance: '`provision(WorkspaceSpec(kind="empty"))` 返回一个存在的隔离空目录；带 `params={"doc": "..."}` 时目录下含对应说明文件且内容一致，`doc_name` 可覆盖文件名。两次 provision 目录隔离。**不修改 T1 任何文件**的前提下，import `seed_source` 后 `available_kinds()` 含 `empty`（自动发现注册生效）。该目录可作为 `Sandbox` 的 cwd 正常 run/读写（沿用 0008/T2 行为，不重测 Sandbox 内部）。'
  - id: T3
    title: 依赖供给（setup 钩子落地：per-workspace venv + pip）
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to:
      - ref: 0008/T1
        type: note
      - ref: 0008/T2
        type: note
    parallel: false
    files:
      - backend/auto_designer/user/sim/deps.py
      - backend/tests/user/sim/test_deps.py
      - backend/auto_designer/user/sim/sandbox.py
      - backend/auto_designer/loop/orchestrator.py
      - backend/auto_designer/loop/sim_user.py
    scope: '1) `deps.py`（新）：`ensure_deps(workspace_dir: str, spec: WorkspaceSpec) -> None`——`spec.setup` 非空时，在 `workspace_dir` 为 cwd 逐条执行 setup 命令（subprocess，带超时/输出捕获），失败即抛并附命令与 stderr。setup 命令可自建 per-workspace `.venv` 并把依赖装进去（如 `python -m venv .venv` → `.venv/bin/pip install -e .` / 装 pytest+whatever）；`ensure_deps` 本身不硬编码建 venv 逻辑，只忠实执行 setup（奥卡姆：机制留在数据里）。幂等：`.venv` 已就位可跳过重建（由 setup 命令或一个 marker 判定）。2) `sandbox.py`（0008/T2，跨组）：`run_shell` 只切换 cwd 并继承宿主 ambient env，不再自动探测/激活 `<workspace>/.venv/bin`；如果 harness 或用户要使用某个虚拟环境，必须显式运行 `.venv/bin/python ...` / `source .venv/bin/activate && ...`，从而两侧默认执行环境一致、环境选择由 harness/用户行为自然发生。3) `orchestrator.py`（0007/0008，跨组）：在共享工作区 materialize *之后、launch 之前* 调 `ensure_deps(workspace_dir, scenario.workspace)`，使依赖准备动作（若场景声明了 setup）发生在两侧共享目录中。4) `sim_user.py`（0005/0007，跨组）：其 `run()` 的直连回落路径（未收到 orchestrator 传入 `workspace_dir` 但 `scenario.workspace` 非空时自行 `materialize_workspace`）在 materialize *之后、bind_session 之前* 也对称调 `ensure_deps(ws, scenario.workspace)`，与 orchestrator 主路径同构。orchestrator 已传 `workspace_dir` 的主路径依赖已由 orchestrator 就位，sim_user 不重复调。**非目标**（留后续）：容器/hermetic 隔离与网络策略；跨会话 venv 缓存/复用（本轮每局现装）；lockfile/版本求解；从需求文档自动推导 setup 命令（本轮 setup 由场景作者/未来 adapter 显式给出）；替 harness 隐式选择/激活环境。'
    acceptance: "`spec.setup` 为空时 `ensure_deps` 空操作、不建 `.venv`、Sandbox 行为与今天一致（既有场景零回归）。给定一个 `setup` 会建 `.venv` 并 pip 装入某包的 spec：`ensure_deps` 后 `<workspace>/.venv` 存在且该包可被 `.venv/bin/python` 显式 import。`Sandbox(workspace=dir)` 在 `<dir>/.venv` 存在时，`run_shell(\"python ...\")` 不自动解析到 `.venv`，仍继承 ambient；显式 `run_shell(\".venv/bin/python ...\")` 才使用该 venv。orchestrator 在 materialize 之后、launch 之前调 `ensure_deps`（`scenario.workspace` 为 None 时不调）。不经 orchestrator 的 sim_user 直连回落路径（未传 `workspace_dir` 但 `scenario.workspace` 非空）在自行 materialize 之后、bind_session 之前也调 `ensure_deps`（且顺序：materialize 在前）；传入 `workspace_dir` 的主路径不在 sim_user 内重复调 `ensure_deps`。setup 命令失败时 `ensure_deps` 抛错并携带足够诊断（命令+stderr）。端到端（可选、需网络）：以 funcy 式 setup 备好 `pytest`+`whatever` 后，Sandbox 可通过显式 `.venv/bin/python` import `whatever`。"
  - id: T4
    title: git 源（clone repo@commit 成快照工作区）
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to:
      - ref: 0008/T1
        type: note
      - ref: T3
        type: note
    parallel: false
    files:
      - backend/auto_designer/user/sim/sources/git.py
      - backend/tests/user/sim/test_git_source.py
    scope: 1) `sources/git.py`（新）：定义 `GitSource`，`@register("git")` 自注册（T1 子包扫描 import 期自动发现，无中心登记）。`provision(spec, dest_root)`：从 `spec.params` 读 `repo`（必填）、`commit`（必填）、可选 `ref`/`depth`；在隔离目录里 `git clone` 该 repo、`git checkout <commit>` 恢复快照，返回该目录绝对路径。隔离/返回契约同另两源（每局全新目录、互不污染、返回绝对路径）。2) 复用既有 `WorkspaceSpec.params` 承载 `repo`/`commit`/`ref`/`depth`——**不新增/不修改 `WorkspaceSpec` 字段**（与 T1 给 empty 用 params 一致，不碰 T1 的 models.py）。**不改** `SeedSource` 协议/注册表/顶层 `provision`（T1）、`empty`（T2）、`materialize` 薄壳、消费侧 `orchestrator`/`sim_user`/`Sandbox`。非目标（留后续/单独）：具体 benchmark（SWE-bench 等）字段→`SeedScenario` 的适配层（adapter）；容器/hermetic 与版本 pin 的环境强度；私有仓鉴权。
    acceptance: 给定 `WorkspaceSpec(kind="git", params={repo, commit})`，`provision` 后返回目录是该 repo 在该 commit 的工作树：可校验 `git rev-parse HEAD` == `commit`、关键文件存在。隔离——每次 provision 落独立目录、互不污染。`commit` 缺失（或 `repo` 缺失）时抛错且消息含缺失字段名；clone/checkout 失败时抛错并携带失败命令 + stderr 诊断。注册表按 `kind="git"` 分派到 `GitSource`；**不修改 T1/T2/T3 任何文件**的前提下 import `seed_source` 后 `available_kinds()` 含 `git`（自动发现注册生效）。与既有源（local-fixture/empty）及消费侧（materialize 薄壳 / orchestrator / sim_user / Sandbox）零回归。该目录可作为 `Sandbox` 的 cwd 与 harness 的 `SANDBOX_WORK_DIR` 正常复用（沿用既有行为，不重测消费侧内部）。CI 约束：默认单测**不走真实网络**——用一个本地临时 git 仓当 `repo`（origin），或对 clone 命令做 spy/mock；真实远端 clone 的端到端标记为可选/手动。
---

# 0009 · 种子工作区供给可插拔（SeedSource 接缝）

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

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
依赖供给：ensure_deps(dir, spec) 执行 spec.setup（可备 per-workspace .venv） （T3）
    ▼
消费港口不变：workspace.materialize() 薄壳委托 → sim_user 桥接 → Sandbox(workspace=dir) 当 cwd；默认只共享 cwd + ambient env，显式 `.venv/bin/python ...` 才用 venv
```

## Motivation

0008/T1 让 seed 场景能携带工作区，但供给路径写死在 `materialize` 的本地 copytree 上：后续要接入多样任务源（NL2Repo 式空仓起步、SWE-bench / Terminal-Bench 等）时，若每来一种都改 `materialize`，供给侧会退化为 if/else 拼盘。本组的驱动力是把「按何种机制把 workspace 备好」抽成可插拔接缝（T1），消费港口（`SeedScenario.description` + 被 `Sandbox` 当 cwd 的工作区目录）保持冻结；再用一个零新基建的第二源 `empty`（T2）验证接缝是否真的解耦——`empty` 直接表达「空工作区 + 一段自然语言诉求」这一最小任务形态，即 NL2Repo 式从零构建的注入形状，以「加一个源 = 一个文件、核心零改」锁死可插拔是否成立，而非只是声明。

接缝立好之后，暴露出两个此前被搁置为非目标、实践中却绕不开的缺口。其一，0008/T1、0009/T1 都把「依赖供给」列为非目标，`WorkspaceSpec.setup` 只留占位不执行，于是当前 `Sandbox` 只能用宿主 ambient 环境跑 stdlib——带第三方依赖的任务（大多数真实仓库、部分 NL2Repo）无法真跑其声明的验证。以 funcy 为例：库本体是纯 stdlib，但其 `start.md` 声明验证需 `pytest 7.4.3` + 第三方 `whatever 0.7`、还要求 `pip install -e .`；没有依赖供给，用户 agent 在 Sandbox 里 `import whatever` 必 `ModuleNotFoundError`、`python setup.py test` 跑不起来。T3 补上这一环，让「供给一个工作区」真正意味着「供给一个能按其声明依赖运行的工作区」，是本组供给侧的收口。

其二，已落地的两源均只能起本地：`local-fixture` copytree 一个 in-repo vendored 目录、`empty` 开一个空目录（可选写说明文档）。真实软件工程任务的注入形状不是这两者——它是「某公开仓库停在某历史 commit 的工作树快照」：SWE-bench 实例即 `repo` 在 `base_commit` 处的未修复态，funcy 式任务是某发布版本的源码树。没有「从 git clone @commit」的源，这类任务的起点根本立不起来，可插拔接缝对真实 repo 分布形同虚设。T4 兑现这一预留扩展点，补上通用 `git` 源，使供给侧能承载「基于某仓库某快照」的任务族（具体 benchmark 字段→场景的适配层为非目标，见下）。

## Guide-level explanation

本组把工作区供给从「唯一硬编码的本地 copytree」抽象为按 `kind` 注册的 `SeedSource` 协议（T1）：定义 `SeedSource.provision(spec, dest) -> workspace_dir` 与一个 `kind → SeedSource` 注册表，注册表在 import 期遍历 `sources/` 子包自动发现各源、使新增源无需改注册侧；把 0008/T1 的 `materialize` 逻辑迁为首个 `local-fixture` 实现，`WorkspaceSpec` 增 `kind`（缺省 `local-fixture`）与通用 `params`，`workspace.materialize()` 退化为委托注册表的薄壳。这是本组底座，编号即执行序：T1 先立接缝，其余三个源才能纯靠新增模块接入。

在此接缝上接入两个纯本地源验证可加性、再接入一个远程源覆盖真实 repo。T2 的 `empty` 新建一个隔离空工作区目录，`params` 含 `doc` 时把其文本写成一个需求说明文件，覆盖 NL2Repo 式「仅一份说明文档、从空仓起步」的场景。T4 的 `git` 把 `repo` clone 到隔离工作区目录并 `git checkout <commit>`，得到「某仓库停在某 commit」的干净快照，兑现 0009 当初为「未来 SWE-bench / Terminal-Bench」预留的扩展点——真实 repo 任务（SWE-bench 的 `base_commit` 未修复态、funcy@某版本等）的起点正是这一快照，而现有两源（`local-fixture` 只拷 vendored 目录、`empty` 只给空目录）立不起来。二者共享同一约束：接入各自**只新增一个 `sources/*.py` 模块**（`empty.py` / `git.py`），靠 T1 的子包自动发现注册，`seed_source.py` / `models.py` / `workspace.py` 与消费侧（sim_user / Sandbox）零改动；`doc`/`repo`/`commit`/`ref`/`depth` 等参数全部落在既有 `WorkspaceSpec.params` 上，不扩 schema。`git` 源每局 fresh（每 round 重 clone/checkout 一份，隔离避免跨局串状态，与 local-fixture 每局重拷同理）。

供给侧最后一环由 T3 补上：把 `WorkspaceSpec.setup`（0008 起仅占位、从不执行）真正落地——一个源 provision 出工作区目录后，按 `setup` 命令在该目录里备好依赖环境（可约定为 per-workspace `.venv` + pip 安装）。由此工作区从「有文件」升级为「声明过的 setup 已执行」。新增 `deps.py`（setup 执行器）+ 在共享工作区落地点（orchestrator，materialize 之后、launch 之前）调用它。消费侧不隐式激活任何 venv；harness 或用户若要用 setup 产物，应通过显式命令（如 `.venv/bin/python -m pytest ...`）自然使用。不改 T1/T2/T4 任何文件、不扩 `WorkspaceSpec` schema（复用既有 `setup`）。

## Reference-level explanation

### 接缝与三个 provision 实现

供给侧的核心是一条分派链：

```
WorkspaceSpec{kind, fixture?, params, setup}
        │ kind
        ▼
SeedSource 注册表  dict[str, SeedSource]   ◄── import 期遍历 sources/ 子包，各源自注册
        │ provision(spec, dest_root) -> workspace_dir
        ▼
LocalFixtureSource(kind="local-fixture")：copytree seed_workspaces/<fixture>/project（T1，= 0008 行为）
EmptySource(kind="empty")：新建空目录，可选写需求文档（T2）
GitSource(kind="git")：clone repo + checkout <commit>（T4）
```

`SeedSource`（T1）为 `Protocol`，约定 `kind: str` 与 `provision(spec: WorkspaceSpec, dest_root: str | None) -> str`（返回隔离工作区目录绝对路径）。注册机制：`@register("<kind>")` 装饰器把实现写入模块级 `_REGISTRY`；`seed_source.py` 在 import 期用 `pkgutil.iter_modules` 遍历 `sources/` 子包逐一 import，触发各源自注册——这是「新增源 = 落一个模块」可加性的机制根基，T2、T4 均依赖之、均无需改注册侧。顶层 `provision(spec, dest_root)` 按 `spec.kind` 查表分派，未命中抛 `ValueError`（消息列出已注册 kind）。

向后兼容（T1）：`WorkspaceSpec` 增 `kind: str = "local-fixture"` 与 `params: dict = {}`；`from_dict` 缺 `kind` → `local-fixture`、缺 `params` → `{}`，故 0008 落盘数据与 `billing-split` fixture 原样可用。`workspace.materialize(spec, dest_root)` 改为 `return provision(spec, dest_root)` 薄壳，保留为兼容壳不弃用——`sim_user` 桥接与 `Sandbox` 调用点一行不改（消费港口冻结）。`local_fixture.py` 收纳原 copytree 逻辑（fixture 不存在报错、每局隔离拷贝），从 `workspace.py` 迁出；`workspace.py` 仅留兼容壳与 `seed_workspaces_root()` 等共用 helper。

第二、第三源在此接缝上验证「加一个源 = 落一个新模块」：

- T2 `empty`（`sources/empty.py`）：定义 `EmptySource`，`@register("empty")` 自注册。不读 `fixture`，只认 `params`；`provision` 新建隔离目录（tempfile.mkdtemp 或 dest_root/<name>），`params.doc` 非空时把其文本写成 `params.doc_name`（缺省 `SPEC.md`）的说明文件，缺省则落纯空目录，使内层 agent 有「读说明文档」的落脚。覆盖 NL2Repo 式「仅一份说明文档、从空仓起步」的场景。
- T4 `git`（`sources/git.py`）：定义 `GitSource`，`@register("git")` 自注册。从 `spec.params` 读 `repo`（必填，url 或 owner/repo）、`commit`（必填，恢复的快照 sha/ref）、可选 `ref`（clone 时定向分支/tag）、`depth`（浅克隆深度）；在隔离目录 `git clone`（可选 `--depth`/指定 `ref`）+ `git checkout <commit>` 恢复快照，返回该目录绝对路径。SWE-bench 即 `repo` 在 `base_commit` 处的未修复态。每局 fresh：每 round 重新 clone/checkout 一份干净快照，独立目录、跨局隔离、可清理，避免上一局 harness 改动或用户 agent 写入串到下一局，与 local-fixture 每局重拷同理。与 T3 依赖供给正交：`git` 只负责「把某仓库某快照落成工作区」，环境强度（venv/pip、`pip install -e .`）仍由 T3 在该快照目录里备齐。

两源与 local-fixture 共享同一隔离/返回契约：每次 provision 一个全新目录、互不污染、返回绝对路径，从而 `Sandbox(workspace=dir)` 可直接当 cwd 复用。两源均只新增一个 `sources/*.py` 文件（+ 测试），T1 拥有的文件与另两源文件互不相交（disjoint）；`doc`/`doc_name`/`repo`/`commit`/`ref`/`depth` 等参数全部落在既有 `params: dict` 上，不扩 `WorkspaceSpec` schema（不碰 T1 的 models.py）——这正是 ports-and-adapters 边界成立的判据：第二、第三个 adapter 均只落一个文件。

### 依赖供给（T3）

供给链最后一环，消费港口仍冻结（目录 + 本地 shell）：

```
SeedSource.provision(spec) -> workspace_dir      （T1/T2/T4，落地文件）
        │  orchestrator：materialize 之后、launch 之前
        ▼
deps.ensure_deps(workspace_dir, spec)            （T3，执行 spec.setup 备依赖）
        │  约定 setup 建 <workspace_dir>/.venv 并 pip 装入
        ▼
两侧共享 workspace_dir 开跑：
   ├─ harness 子进程（SANDBOX_WORK_DIR=workspace_dir，0008/T1v2）
   └─ 用户 agent Sandbox(workspace=workspace_dir)（0008/T2）
            └─ run_shell 只切 cwd、继承 ambient；显式 `.venv/bin/python ...` 才使用 venv
```

Hook 落在 orchestrator 而非 provision 内：与 0008/T1v2 让 materialize 上移 orchestrator 同因——工作区要被 harness 与用户 agent 两侧共享，依赖准备若由场景声明，必须在 launch *之前* 落在两侧同指的那个目录上，orchestrator 是唯一同时掌握 materialize 结果与 launch 时机的层。这也让 T3 只碰跨组的 orchestrator/sandbox，不动 T1/T2/T4 的 provision/materialize 文件（组内 files disjoint）。复用既有 `setup: list[str]` 而非给 `WorkspaceSpec` 加结构化 deps 字段：0008/T1 已预留该钩子，MVP 直接激活即可，不扩 schema（不碰 T1 的 models.py）；venv 约定活在数据（命令）里而非代码里。per-workspace `.venv` 可由 setup 创建，代价是每局现装有耗时（缓存留 open-question）；但 Sandbox 不再隐式探测/激活 `.venv`，以免用户私有工具和 harness shell 的默认环境不一致。若 harness 或用户要用该 venv，应显式运行 `.venv/bin/python ...` 或等价激活命令，这让环境选择成为任务内可观察行为。退化与兼容：`spec.setup` 为空（含所有既有 fixture/empty/git 场景）时 `ensure_deps` 空操作、无 `.venv` 生成、Sandbox 走 ambient——对既有行为零改动。

### 接口

- `SeedSource`（protocol，`sim/seed_source.py`）：属性 `kind: str`；方法 `provision(spec: WorkspaceSpec, dest_root: str | None = None) -> str`。
- 注册表 API（`seed_source.py`）：`register(kind: str)` 装饰器；`get_source(kind) -> SeedSource`；`provision(spec, dest_root=None) -> str` 顶层分派；`available_kinds() -> list[str]`。`sources/` 子包 import 期自动发现注册。
- `WorkspaceSpec`（`models.py`）：新增 `kind: str = "local-fixture"`、`params: dict[str, Any] = field(default_factory=dict)`；保留 `fixture: str`（local-fixture 使用）、`setup`。`to_dict` 省略缺省项以保持旧序列化形状；`from_dict` 缺 `kind`→`local-fixture`、缺 `params`→`{}`。
- `LocalFixtureSource`（`sources/local_fixture.py`）：`kind="local-fixture"`；`provision` = 把 `seed_workspaces/<spec.fixture>/project` copytree 到新隔离目录并返回其绝对路径。
- `EmptySource`（`sources/empty.py`）：`kind="empty"`；`provision(spec, dest_root=None) -> str` 新建隔离目录；`spec.params.get("doc")` 非空时写 `spec.params.get("doc_name", "SPEC.md")`。经 `@register("empty")` 入注册表，调用方仍走顶层 `provision(spec)`，不直接依赖本类。
- `GitSource`（`sources/git.py`）：`kind="git"`；`provision` 从 `params` 读 `repo`/`commit`（必填）、`ref`/`depth`（可选），clone + checkout 后返回目录绝对路径；`repo`/`commit` 缺失或 clone/checkout 失败时抛错并携带诊断（缺失字段名、失败命令 + stderr）。经 `@register("git")` 入注册表，调用方仍走顶层 `provision(spec)`。
- `workspace.materialize(spec, dest_root=None) -> str`：保留为委托 `provision` 的兼容壳（不弃用，缓冲后续）。
- `deps.ensure_deps(workspace_dir: str, spec: WorkspaceSpec) -> None`（`user/sim/deps.py`）：`spec.setup` 空则直接返回；否则以 `workspace_dir` 为 cwd 逐条 subprocess 执行，非零退出抛异常（附命令、returncode、截断 stderr）；可选带总超时。
- `Sandbox`（`user/sim/sandbox.py`，0008/T2）：`run_shell` 只切 cwd 并继承 ambient env，不自动探测/激活 `<workspace>/.venv/bin`。对外接口签名不变。
- `orchestrator.run_round`（0007/0008，跨组）：在 `workspace_dir = materialize_workspace(...)` 之后、`launch(..., workspace_dir=workspace_dir)` 之前插入 `ensure_deps(workspace_dir, scenario.workspace)`（`scenario.workspace` 为 None 时跳过）。
- `sim_user.run`（0005/0007，跨组）：直连回落分支（`workspace_dir` 为 None 且 `scenario.workspace` 非空）在 `ws = materialize_workspace(scenario.workspace)` 之后、`bind_session` 之前插入 `ensure_deps(ws, scenario.workspace)`，与 orchestrator 主路径对称；orchestrator 已传 `workspace_dir` 的路径不在 sim_user 内重复 ensure（依赖已由 orchestrator 就位）。故 ensure_deps 的落点覆盖两处：orchestrator 主路径 + sim_user 直连回落。
- 不新增/不修改 `WorkspaceSpec` 字段（`empty`/`git` 均复用 `params`，T3 复用 `setup`）；不改 `SeedSource`/`provision`/`materialize` 签名；不改 harness stdio 协议。
- setup 命令示例（funcy，由场景/adapter 提供）：`["python -m venv .venv", ".venv/bin/pip install pytest==7.4.3 whatever==0.7", ".venv/bin/pip install -e ."]`。

### 测试

- **test_seed_source.py**（T1）：`provision` 按 kind 分派正确；未知 kind 抛 `ValueError` 且消息列出已注册 kind；自动发现——不手动 import `local_fixture`，import `seed_source` 后 `available_kinds()` 含 `local-fixture`；local-fixture 平价——对 `billing-split` 落地目录存在、含 `billing/core.py`、stdlib 可执行，两次 provision 隔离，fixture 不存在报错；`WorkspaceSpec` kind/params 缺省与 to_dict/from_dict 往返、旧 dict 兼容。更新 test_workspace.py：补 `materialize` 薄壳与 `provision` 等价、既有 materialize 断言在新路径下仍通过。
- **test_seed_source_empty.py**（T2）：`provision(kind="empty")` 落地隔离空目录、存在且为空；带 `doc` → 目录含说明文件且内容一致，`doc_name` 覆盖生效；两次 provision 隔离；可加性证据——本测试不 import `empty` 模块本身、仅 import `seed_source`，断言 `available_kinds()` 含 `empty`（证明仅靠落模块即被自动发现）；序列化——`WorkspaceSpec(kind="empty", params={...})` to_dict/from_dict 往返一致。
- **test_deps.py**（T3）：`setup` 为空 → `ensure_deps` 空操作、目录无 `.venv`；setup 建 `.venv` + 装一个纯本地可控包（用离线/本地 wheel 或标准库脚本模拟，避免 CI 走网络）→ `.venv` 存在且目标可 import；setup 某命令非零退出 → 抛错且消息含该命令与 stderr；幂等——`.venv` 已在时重复调不重复重建/不报错。配套 sandbox 测试：工作区含 `.venv/bin` 时 `run_shell("python ...")` 仍不自动命中 venv；只有显式 `.venv/bin/python ...` 才使用 venv。orchestrator 测试（跨组 test_orchestrator.py）：materialize 之后、launch 之前调用 `ensure_deps`（spy 断言顺序），`scenario.workspace` 为 None 时不调。sim_user 测试（跨组 test_sim_user.py）：不传 `workspace_dir`、`scenario.workspace` 非空 → 回落分支自行 materialize 后调 `ensure_deps`（spy 断言顺序：materialize 在前）；传入 `workspace_dir` 的主路径不在 sim_user 内调 `ensure_deps`（反向断言）。皆离线、不走网络；CI 约束：默认用例不依赖真实 pip 网络，需网络的 funcy 端到端标记为可选/手动。
- **test_git_source.py**（T4，皆离线、不走网络）：本地临时 git 仓——`git init` + 造两个 commit（记 C1、C2），以其路径为 `repo`；`provision(kind="git", params={repo, commit=C1})` 后断言工作树恢复到 C1（`git rev-parse HEAD` == C1、C1 特有文件在/C2 新增文件不在）；目录隔离——两次 provision 落不同目录、互不污染；缺 `commit`（及缺 `repo`）→ 抛错且消息含缺失字段名，clone/checkout 失败（如不存在的 commit 或坏 repo 路径）→ 抛错且携带失败命令 + stderr；可加性/分派——本测试不 import `git` 模块本身、仅 import `seed_source`，断言 `available_kinds()` 含 `git` 且顶层 `provision` 按 `kind="git"` 分派到 `GitSource`；序列化——`WorkspaceSpec(kind="git", params={repo, commit})` to_dict/from_dict 往返一致。真实远端 clone 的端到端标记为可选/手动，不在默认 CI 用例内。

### 文件分配（单一 writer 所有权）与依赖 DAG

| Task | 内容 | 文件 |
| --- | --- | --- |
| T1 | 协议/注册表/local-fixture | `backend/auto_designer/user/sim/seed_source.py`、`backend/auto_designer/user/sim/sources/__init__.py`、`backend/auto_designer/user/sim/sources/local_fixture.py`、`backend/auto_designer/models.py`、`backend/auto_designer/user/sim/workspace.py`、`backend/tests/user/sim/test_seed_source.py`、`backend/tests/user/sim/test_workspace.py` |
| T2 | empty 源 | `backend/auto_designer/user/sim/sources/empty.py`、`backend/tests/user/sim/test_seed_source_empty.py` |
| T3 | 依赖供给 | `backend/auto_designer/user/sim/deps.py`、`backend/tests/user/sim/test_deps.py`、`backend/auto_designer/user/sim/sandbox.py`、`backend/auto_designer/loop/orchestrator.py`、`backend/auto_designer/loop/sim_user.py` |
| T4 | git 源 | `backend/auto_designer/user/sim/sources/git.py`、`backend/tests/user/sim/test_git_source.py` |

依赖 DAG：`T1 → T2`，`T1 → T3`，`T1 → T4`（T2/T3/T4 彼此独立、并列依赖 T1 立的接缝）。

## Drawbacks

<!-- 待填 -->

## Rationale and alternatives

接缝层面的选择（T1）集中在如何让「新增源」保持零改动成本。选「子包自动发现 + 装饰器自注册」而非「集中 import 列表」：换来新增源对注册侧零改动（T2、T4 均只落一个文件即接入），代价是 import 期一次目录扫描 + 注册依赖 import 副作用——以「不手动 import 也能查到该 kind」的测试兜底；备选「集中列表」每加一源都要改一处公共文件，违背可加性目标，故弃。`WorkspaceSpec` 用扁平 `fixture` + 通用 `params: dict` 而非「每 kind 一个强类型子类」：换来加源不改 `WorkspaceSpec`、序列化形状稳定，T2 的 `doc`/`doc_name`、T4 的 `repo`/`commit`/`ref`/`depth` 均落在这一扩展位上，代价是各 source 内部需自校验所需字段（local-fixture 要求 `fixture` 非空）。保留 `materialize` 薄壳而非改 0008 调用点：换来消费侧零改动、渐进迁移，代价是多一层间接（可接受）。

第二、第三源的选型服务于不同验证目标。第二源选 `empty` 而非直接做 git/容器源：以最低成本（零新基建，仍是本地目录）验证接缝是否解耦；代价是未覆盖「重型供给」路径——这是有意为之，重型运行时句柄仍为本组非目标、留下游 spec；用通用 `params.doc`/`doc_name` 而非给 `empty` 引入专属 schema，保持 `WorkspaceSpec` 不随每个源膨胀，代价是 `params` 弱类型，靠 source 内部自校验与测试约束。第三源选通用 `git` 而非直接做 SWE-bench 专用源：通用 clone@commit 可复用于所有「基于某仓库某快照」的任务族，把 benchmark 专属字段映射隔离到独立 adapter，代价是本任务不产出可直接消费 SWE-bench 数据集的端到端链路（adapter 归后续）；同样用通用 `params.repo`/`commit` 而非专属强类型 schema，与 empty 同构。`git` 的 clone 选每局现做而非缓存/共享 bare 镜像：换来确定、隔离、可清理的干净快照，代价是耗时 + 需网络可达 git 源——跨局 clone 缓存/本地镜像复用留后续。`git` 只解决「把某仓库某快照落成工作区」，环境强度仍靠 T3 的 `setup`（venv+pip）；挑版本/系统依赖/需官方镜像的实例不保证可跑——属容器/hermetic 既有非目标，本任务不越界造重型运行时。

依赖供给（T3）选择激活既有 `setup` 而非新造 provisioner 框架：奥卡姆，最小改动打通依赖路径，代价是 setup 是弱类型 shell 命令、靠场景作者写对（无 lockfile 求解）。每局现装 venv：环境确定、隔离、可清理，代价是耗时与网络依赖（pip 需可达源）——跨会话缓存/预热留 open-question，不在 MVP。不让用户 agent 侧 Sandbox 自动用 venv：把默认执行环境保持为与 harness 一致的 ambient + 同 cwd。若某任务要用 venv，harness/用户都应显式调用 `.venv/bin/python ...`，环境选择成为任务内可观察行为，而不是平台接缝隐式行为。非安全/非 hermetic：sandbox 仍是 cwd+超时的最小隔离，venv 只解决「依赖可见」，不解决「恶意代码/网络隔离」——沿用 0008/T2 威胁模型，强隔离留下游。Hook 落在「materialize 工作区的每个生产接缝」而非仅 orchestrator：主路径由 orchestrator 在共享工作区 materialize 后 ensure；sim_user 的直连回落（未经 orchestrator 但仍自行 materialize）同样在 materialize 后对称 ensure_deps——保证任何「建了工作区」的生产路径都不会静默缺依赖（修订：早期版本把回落路径不调 ensure_deps 记为可接受 tradeoff，实践中它是一条会静默缺依赖的生产接缝，故收敛为对称调用）。代价是两处落点需各自维护对称性；只有纯工具/独立 smoke 脚本（不走这两条生产接缝、自行 materialize）才需自理 `ensure_deps`（可接受，属工具侧）。

## Prior art

本组整体扩展 0008/T1（`workspace.py` 的 `materialize`、`WorkspaceSpec`，`models.py` 的 `SeedScenario`）；消费侧 0008/T1 的 `sim_user` 桥接与 0008/T2 的 `Sandbox(workspace=dir)` 原样复用，始终不落在本组任何任务的 files 内。T1 立起协议、`register`/`provision` 注册表与 `sources/` 自动发现机制，并为 `WorkspaceSpec` 增 `kind`/`params`；T2 的 `empty`（`sources/empty.py`）与 T4 的 `git`（`sources/git.py`）均只依赖该接缝与这两个字段（不改 T1 文件）即接入注册表。其中 T4 与本组 T3 依赖供给正交衔接：`git` 落快照，T3 的 `setup`/`ensure_deps` 在该快照里备依赖；两者共同兑现了 0009 frontmatter 当初为「未来 SWE-bench / Terminal-Bench」预留的供给侧扩展点。T3 激活的是 0008/T1 预留、此前从未执行的 `WorkspaceSpec.setup` 钩子，落地点在 0008/T1v2 的共享工作区 materialize 之后（orchestrator，run_session 之前），消费于 0008/T2 的 `Sandbox`（run_shell 注入 venv），解决 T1 open-question 之一与 0008/T1 tradeoffs 记录的依赖供给缺口——funcy 等 NL2Repo 任务经 T2 `empty` 源导入后，靠 T3 把其声明依赖备齐方能真跑验证。NL2Repo 式任务的客观评测（跑上游测试判分）在 T2、T3、T4 中均被反复划为非目标，归下游平行评测系统。

## Unresolved questions

依赖供给的运行细节（源于 T3）：跨会话 venv 缓存/预热尚未做——每局现装耗时且需网络，是否按 (deps 指纹) 缓存复用一份 venv、或预构建镜像层；是否提供更强的环境描述/复现约定（例如 harness 最终回复必须说明使用 ambient python 还是 `.venv/bin/python`）；无网络/受限环境下的依赖供给（离线镜像、vendored wheels）尚未覆盖；setup 命令的来源——从需求文档（如 funcy `start.md` 的依赖清单）自动生成，还是由场景/adapter 手写，前者需一个「文档→setup」的推导步骤，归后续；依赖安装失败时的策略——整局判失败，还是降级为「无该依赖的受限核实」，尚未定。

消费港口是否需要升级（源于 T1）：后续更重型的源（容器化的 SWE-bench / Terminal-Bench）是否需把消费港口从「工作区目录」升级为「可运行句柄 {cwd, run(cmd), cleanup}」，以便 Provider 与（将来的）客观评测共享同一运行时能力——本组港口保持「目录 + 本地 shell」不变，是否升级、何时升级留下游评估，目的是让重型源接入时尽量不返工港口。

真实 repo 任务落地的剩余缺口（源于 T4）：具体 benchmark（SWE-bench 等）字段到 `SeedScenario`/`WorkspaceSpec` 的适配层尚未做——把数据集实例的 `repo`/`base_commit`/环境声明映射成本源可消费的 `params` + T3 的 `setup`，本组只给通用 git 源，adapter 归后续/单独 spec；容器/hermetic 与版本 pin 的环境强度——挑系统依赖或需官方镜像的实例，仅靠 clone@commit + venv 不保证可跑，沿用「重型运行时留下游」既有非目标；oracle/客观判分（跑上游测试判修复对错）为红线 held-out，永不进本框架训练；harness 子进程 bash 是否用工作区 venv，属 harness 侧/开发者进化范畴，已明确划出本组框架（同 T3 open-question）；私有仓鉴权（token / ssh key 注入 clone），本组默认公开仓/本地仓，鉴权留后续；跨局 clone 缓存/本地 bare 镜像复用以省耗时与网络，本轮每局现 clone，缓存留后续。

## Future possibilities

<!-- 待填 -->

