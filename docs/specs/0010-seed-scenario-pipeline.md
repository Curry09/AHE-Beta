---
number: "0010"
title: 种子场景管线：采集(蒸馏)与注入 SeedSource
issue: 10
slug: seed-scenario-pipeline
summary: 本组实现种子场景管线：把「从真实数据采集种子场景」与「把种子卡注入 SeedSource 供给」串成一条链， 为 0009 的 SeedSource（工作区供给接缝）与 0005 的用户侧模拟供给真实任务。对应 CLAUDE.md「蒸馏模块」 产出的**种子场景库**这一半（persona 半边是 0006，本组与之对称镜像），落实约束「seed 来自真实数据、 benchmark 全程 held-out」。上游供给给 0009 的 SeedSource，消费侧（models / seed_source / sources / run.py）零改。
tasks:
  - id: T1
    title: 种子场景采集（蒸馏，skill 形式）
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to:
      - ref: 0006/T1
        type: note
      - ref: 0009/T1
        type: note
    parallel: false
    files:
      - tools/seed-distill/seed-card-schema.md
      - tools/seed-distill/extract-harness-seed/SKILL.md
      - tools/seed-distill/extract-harness-seed/reference.md
      - backend/auto_designer/distill/seed_library.py
      - backend/tests/distill/test_seed_library.py
    scope: "按轮辐式落地采集侧并定义种子卡库格式。本步范围：① seed-card-schema.md（唯一公共契约：种子卡 schema + 枚举\n+ 两道门原则 + held-out 字段存放约定，source-agnostic）；② extract-harness-seed（薄 skill，从 closed\nissue+merged fix PR 等真实源 harvest，引用契约）；③ seed_library.py 读写。不接具体数据源拉取实现、不做\n卡→SeedScenario 注入映射（归 T2）。日志/SO/未来源作同契约的后续薄 skill，留待补入（见 open-questions）。\n智能配对（persona×seed）、容器/私有仓鉴权、oracle 客观判分运行时均为 out-of-scope（见 open-questions）。"
    acceptance: "seed-card-schema.md 为唯一 source-agnostic 公共契约（种子卡 schema + 枚举 + 两道门原则 + held-out 字段存放\n约定）；extract-harness-seed 为薄 skill，只引用契约、无 skill→skill 依赖、无悬空引用，且不把 NexAU 的 skill\n文件实际拷入本仓（spec 仅描述交付物）；seed_library 按契约读写多条卡库、可按 id 取、对未知键前向兼容；卡记录\n`source.not_in_benchmark` 恒为真（契约级断言）；domain ∈ 受控词表、capability_probed ⊆ 能力分类法。"
  - id: T2
    title: 种子注入（card → SeedScenario）
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to:
      - ref: 0006/T2
        type: note
      - ref: 0009/T1
        type: note
      - ref: 0009/T4
        type: note
      - ref: 0009/T3
        type: note
    parallel: false
    files:
      - backend/auto_designer/distill/seed_adapter.py
      - backend/tests/distill/test_seed_adapter.py
    scope: "把种子卡（0010/T1）注入 SeedScenario：card_to_seed 做字段映射（见 design 映射表），输出 `{version, seeds}`\n信封；对无 repo 的纯文本场景产 `workspace: null` 或 `kind=\"empty\"`；对 git 型场景产 `WorkspaceSpec{kind=\"git\",\nparams={repo, commit}, setup}`（setup 按 0009/T3 venv 前缀化）。不改卡格式（归 T1）；不改 SeedScenario/\nWorkspaceSpec/SeedSource（0009，消费侧零改，本组只读其契约）。**不做**智能配对（persona×seed，见\nopen-questions）、不做容器/私有仓鉴权、不做 oracle 判分运行时。"
    acceptance: "card_to_seed 对合法卡产出可被 0009 SeedSource 物化的 SeedScenario：git 型卡产 `WorkspaceSpec{kind=\"git\",\nparams={repo=https://github.com/…git, commit=已解析 SHA}}` 且 setup 已 venv 前缀化；纯文本卡产 workspace=null\n或 kind=\"empty\"。**held-out 红线**：产出的 SeedScenario（及 to_dict/信封 JSON）**绝不含** oracle/test_cmd/\ngates，这些经 extract_sidecar 单独取出。card_to_seeds 产 `{version, seeds}` 信封，可直接喂 run.py 的\n_load_seeds 而消费侧零改。缺 repo_at / 占位未解析 / 非法枚举 → 显式报错。"
---

# 0010 · 种子场景管线：采集(蒸馏)与注入 SeedSource

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

本组实现种子场景管线：把「从真实数据采集种子场景」与「把种子卡注入 SeedSource 供给」串成一条链，
为 0009 的 SeedSource（工作区供给接缝）与 0005 的用户侧模拟供给真实任务。对应 CLAUDE.md「蒸馏模块」
产出的**种子场景库**这一半（persona 半边是 0006，本组与之对称镜像），落实约束「seed 来自真实数据、
benchmark 全程 held-out」。上游供给给 0009 的 SeedSource，消费侧（models / seed_source / sources / run.py）零改。

数据流脊柱：

```
真实源(closed issue+merged PR · 日志 · Stack Overflow · 未来源)
        │  采集/归纳（T1，轮辐式：公共契约 seed-card-schema.md + 薄抽取 skill）
        ▼
   种子卡库（source-agnostic 种子卡：task/source/env/oracle… + 真实性·非 benchmark 门）
        │  注入（T2，card_to_seed：字段映射 → SeedScenario；oracle/test_cmd 落 sidecar、绝不进环）
        ▼
   spec-0001 models.SeedScenario{description, workspace} ─► 0009 SeedSource.provision 物化工作区
        ─► 0005 sim run_session 跑一局 ─► 体感 + issue
```

读图即读任务：**T1** 定「采集什么、种子卡长什么样」——不另造 skill，而是收编既有的真实抽取方法（此前写在
NexAU 仓库里的 `extract-harness-seed`），并按**轮辐式**组织：唯一公共契约 `seed-card-schema.md`（种子卡 schema +
枚举 + 两道门原则，source-agnostic）+ 薄抽取 skill 只描述「从某类真实源 harvest + 判两道门」、只依赖契约、
彼此不依赖。本步先落契约 + `extract-harness-seed`（closed issue+merged fix PR 的 harvest 流水线，唯一 ground
oracle 的真实来源）；日志/SO/未来源作同契约的后续薄 skill 插入。库 schema 即该契约。**T2** 定「种子卡如何变成
0009 SeedSource 能物化的 SeedScenario」（唯一桥接层 card_to_seed）。

**held-out 纪律（关键约束，红线）**：种子卡采集了完整的 `oracle`/`test_cmd`/`gates`（客观判分证据），但这些是
**benchmark 侧**制品：注入时 `task.prompt → SeedScenario.description` **绝不携带 oracle/test_cmd**，判分字段落
**sidecar**、不进 `SeedScenario`、不进训练环。理由引 CLAUDE.md「benchmark 全程 held-out：不参与训练，不参与
发版门禁」——训练信号只取自「模拟真实使用」分布上的用户体感，oracle 客观判分归 harbor 侧的平行评测系统。

与 0009 的关系：本组是 0009（SeedSource 可插拔供给）的上游供给。种子卡的 `source.repo`+`env.repo_at` 映射为
0009/T4 的 `WorkspaceSpec{kind="git", params={repo, commit}}`，`env.setup` 映射为 `WorkspaceSpec.setup`（按
0009/T3 约定 venv 前缀化）；无 repo 的纯文本场景退化为 `workspace: null` 或 `kind="empty"`。智能配对
（persona×seed）与容器/私有仓鉴权等重型能力**不在本组**，记为 open-questions / out-of-scope（见各 Task）。

## Motivation

### T1 种子场景采集（蒸馏，skill 形式）

整条进化的训练信号取自「模拟真实使用」分布上的用户体感；其真实性根植于种子场景是否来自真实数据、不据
benchmark 构造（CLAUDE.md 约束）。既有真实 harvest 方法（NexAU 仓库 `extract-harness-seed`）已沉淀「harvest
不 author / 从已解决的真实制品取沉淀 oracle / 两道门（oracle 门 + harbor 可复现门）/ 与 held-out benchmark
解耦」——重写必失真，故收编。更关键是**可扩展性**：与 persona 采集同构，公共部分（种子卡 schema + 枚举 +
两道门）抽成唯一契约、各薄 skill 只依赖契约且彼此独立——契约改一处全员生效，加新真实源只是新增一个薄 skill，
不碰别人。

### T2 种子注入（card → SeedScenario）

采集产出的是「真实任务 + benchmark 侧判分证据」的完整种子卡，SeedSource 消费的是「description + WorkspaceSpec」，
两者格式不一，需一层显式、可测的映射。更关键是 **held-out 纪律**：种子卡携带 oracle/test_cmd/gates（客观
判分），若随注入进入 SeedScenario，就把 benchmark 特征带进了训练环、把 held-out 判分泄露给用户侧模拟——直接
违背 CLAUDE.md「benchmark 全程 held-out：不参与训练，不参与发版门禁」，并让「训练信号只取体感」的分离失效。
故注入层必须在边界上剥离判分字段：description 只保留真实诉求原文，判分证据落 sidecar 供 harbor 侧平行评测。

## Guide-level explanation

### T1 种子场景采集（蒸馏，skill 形式）

采集（蒸馏）侧按**轮辐式**组织，与 0006/T1（persona 采集）对称镜像，不另造大 skill：① 唯一公共契约
seed-card-schema.md（source-agnostic）——种子卡 schema（source · task · domain · capability_probed ·
difficulty · scope · autonomy_required · oracle · env · pairing_constraints · gates · provenance）+ 枚举
+ 两道门原则（真实性/非 benchmark 门 + oracle 与 harbor 可复现门）+ held-out 侧字段（oracle/test_cmd/gates）
的存放约定；② 薄抽取 skill extract-harness-seed——只描述「从 closed issue+merged fix PR 等真实源 harvest +
过两道门 + ground 哪几字段」，只引用契约、不依赖任何其它 skill，收编 NexAU 既有 `extract-harness-seed`。本步
先落这两者；日志/SO/未来源作同契约的后续薄 skill 插入。交付物：③ 种子卡库的读写 seed_library.py（按契约存取
卡记录），供 0010/T2 注入消费。

### T2 种子注入（card → SeedScenario）

把采集到的种子卡（0010/T1）注入 0009 的 SeedSource 供给：card_to_seed 将一条卡映射为 spec-0001
models.SeedScenario —— `task.prompt` 成 description，`source.repo`+`env.repo_at` 成 git 工作区（0009/T4），
`env.setup` 成 venv 前缀化的 setup（0009/T3）。**held-out 红线**：客观判分制品（oracle/test_cmd/gates）落
sidecar、绝不进 SeedScenario、不进训练环。输出 `{version, seeds:[...]}` 信封，对齐 seed_scenarios.json 与
run.py 的 _load_seeds。是「采集」与「0009 SeedSource 引擎」之间的唯一桥接层，与 0006/T2（card_to_persona）
对称镜像。

## Reference-level explanation

### T1 种子场景采集（蒸馏，skill 形式）

- 轮辐式结构（tools/seed-distill/），与 tools/persona-distill/（0006）对称：
    seed-card-schema.md            唯一公共契约（hub），source-agnostic
    extract-harness-seed/          薄 skill（spoke），只依赖契约（收编 NexAU 既有方法）
    (后续) extract-log-seed / extract-so-seed / …  各自薄 skill，同样只依赖契约
  铁律：skill 只依赖契约，**彼此不依赖**（杜绝 skill→skill 与多副本漂移）。
- seed-card-schema.md（公共契约）：定义 source-agnostic 种子卡字段——
    source{repo, issue_url?, fix_ref, not_in_benchmark}（真实来源 + 非 benchmark 断言）
    task{prompt, context}（保留真实诉求原貌，不 sanitize；prompt 即注入 SeedScenario.description 的原文）
    domain / capability_probed / difficulty / scope / autonomy_required（校准与配对元数据）
    oracle{tier, spec, reference_solution, confidence} · env{repo_at, setup, test_cmd, base_image,
      external_deps, budget} · pairing_constraints · gates{oracle_gate, harbor_repro_gate} · provenance
  另含：各枚举受控取值（domain 词表与 persona D5.area 共享、capability 分类法、difficulty/scope/autonomy/
  oracle tier 等）、两道门原则（oracle 门：成功须 harness-独立且可判；harbor 可复现门：可确定性搭环境跑
  oracle），以及 **held-out 字段的存放约定**——`oracle`/`test_cmd`/`gates` 是 benchmark 侧客观判分制品，
  契约明确它们随卡采集但注入时落 sidecar、绝不进 SeedScenario（红线由 0010/T2 落实、契约在此声明）。
- extract-harness-seed（薄 skill）：收编 NexAU 既有方法，只描述「从 closed issue+merged fix PR / 高票 Q&A
  等**已解决**的真实制品 harvest 一张卡 + 过两道门 + FACT 字段转录/JUDGMENT 字段判定」；枚举/门/卡形状一律
  引用 seed-card-schema.md，不再内嵌。**收编=只引契约、不把 NexAU 的 skill 文件拷进本仓**（spec 只描述交付物）。
- seed_library.py：一个库文件承载多条种子卡记录；纯数据，可双向序列化、对未知键前向兼容（演化友好）；提供
  load / get(id) / add 最小读写。与 0006 的 PersonaLibrary 同构。
- 卡格式与 models.SeedScenario 解耦：卡是「采集到的真实任务 + benchmark 侧判分证据」，到 SeedScenario 的
  映射（含 held-out 字段剥离）归 0010/T2。

**接口**

SeedLibrary(root|path)
- load() -> list[dict]           # 读全库（种子卡记录）
- get(seed_id: str) -> dict      # 按 id 取一条卡
- add(record: dict) -> None      # 追加一条卡记录
种子卡 schema 由 seed-card-schema.md（唯一契约）定义；与 models.SeedScenario 的映射见 0010/T2。

**测试**

单测（backend/tests/distill/test_seed_library.py）：
- SeedLibrary 读写：add 后 load 含该条、get(id) 取回等价记录；空库 load 返回空列表。
- 卡 schema round-trip：含 source/task/env/oracle/gates/provenance 的记录 to/from dict 字段级一致；
  遇未知键忽略不报错（前向兼容）。
- 约束校验：卡记录 source.not_in_benchmark 为真（否则拒收，防 benchmark 污染）；domain ∈ seed-card-schema.md
  受控词表、capability_probed ⊆ 能力分类法。

**文件（单一 writer 所有权）**

  - `tools/seed-distill/seed-card-schema.md`
  - `tools/seed-distill/extract-harness-seed/SKILL.md`
  - `tools/seed-distill/extract-harness-seed/reference.md`
  - `backend/auto_designer/distill/seed_library.py`
  - `backend/tests/distill/test_seed_library.py`

### T2 种子注入（card → SeedScenario）

- card_to_seed(record: dict) -> models.SeedScenario：按下表把一张种子卡翻成 SeedScenario——

  | 种子卡字段 | SeedScenario 目标 | 规则 |
  |---|---|---|
  | `task.prompt` | `SeedScenario.description` | 原文直传；**禁带 oracle/test_cmd/验收标准**（held-out） |
  | `source.repo` + `env.repo_at` | `workspace.kind="git"` + `params.repo` + `params.commit` | repo(owner/repo)→`https://github.com/owner/repo.git`；commit=repo_at（**须已解析为真实 SHA**，占位如 `<parent-...>` 拒收） |
  | `env.setup` | `workspace.setup` | **venv 前缀化**（对齐 0009/T3）：注入 `python -m venv .venv` 于首，pip 步骤改写为 `.venv/bin/pip …` |
  | 无 repo 的纯文本场景 | `workspace: null` 或 `WorkspaceSpec{kind="empty"}` | prompt 落 description（empty 源可选把说明落 doc，见 0009/T2） |
  | `oracle` / `env.test_cmd` / `gates` | **不进 SeedScenario** | 落 sidecar（见 held-out 红线），供 harbor 侧评测；training 环不可见 |

- 输出信封：card_to_seeds(library) 产 `{"version": <int>, "seeds": [SeedScenario.to_dict(), …]}`，形状对齐
  backend/seed_scenarios.json 与 run.py 的 _load_seeds（`data["seeds"]` 或裸数组皆可消费），故注入产物可直接
  喂现有加载器、消费侧零改。
- **held-out 纪律（红线）**：oracle / test_cmd / gates 是 benchmark 侧客观判分制品。card_to_seed 在映射时
  **剥离**它们到一个 sidecar（如 `{seed_id: {oracle, test_cmd, gates, provenance}}` 的旁路文件/返回结构），
  SeedScenario 及其 to_dict **绝不含**这些键。理由：CLAUDE.md「benchmark 全程 held-out」——训练信号只取体感，
  oracle 归 harbor 侧平行评测，二者物理隔离于注入边界。断言：注入产物 JSON 里不出现 oracle/test_cmd/gates。
- venv 前缀化（对齐 0009/T3 约定）：卡的 `env.setup`（如 `["pip install -e ."]`）注入时前置 `python -m venv
  .venv` 并把裸 `pip`/`python` 改写为 `.venv/bin/pip`/`.venv/bin/python`，使 0009/T3 的 ensure_deps 建
  per-workspace venv、Sandbox 探测 `.venv` 生效。
- 缺字段/非法值（如 git 型缺 repo_at、repo_at 仍是未解析占位、domain 越表）显式报错（不静默兜底），把采集
  质量问题暴露在注入边界；与 0006/T2 报错而非安全缺省同策。

**接口**

card_to_seed(record: dict) -> SeedScenario          # 单卡 → SeedScenario；held-out 字段被剥离
card_to_seeds(library: SeedLibrary) -> dict         # {version, seeds:[SeedScenario.to_dict()...]} 信封
extract_sidecar(record: dict) -> dict               # 剥离出的 oracle/test_cmd/gates（供 harbor 侧，不进训练环）
git 型：WorkspaceSpec(kind="git", params={repo, commit}, setup=venv 前缀化后的 env.setup)；
纯文本型：workspace=None（或 kind="empty"）。消费方为 0009 SeedSource（本组只读其契约、零改其文件）。

**测试**

单测（backend/tests/distill/test_seed_adapter.py）：
- held-out 红线（核心）：含 oracle/test_cmd/gates 的卡注入后，SeedScenario.to_dict() 及 card_to_seeds 信封
  JSON 均不含这三键；extract_sidecar 能取回它们。
- git 型映射：source.repo=owner/repo + env.repo_at=<SHA> → WorkspaceSpec(kind="git", params.repo=
  https URL、params.commit=SHA)；env.setup venv 前缀化（首条为 `python -m venv .venv`、pip→`.venv/bin/pip`）。
- 纯文本型：无 source.repo 的卡 → workspace=None（或 kind="empty"，prompt 落 description）。
- 信封形状：card_to_seeds 产 {version, seeds:[...]}，喂 run.py._load_seeds 得等长 SeedScenario 列表。
- 校验：缺 repo_at / repo_at 为未解析占位 / domain 越表 → 显式报错（不静默兜底）。
- 端到端（可选）：注入产物经 0009 SeedSource.provision（git 源用本地临时仓，离线）物化出工作区目录。

**文件（单一 writer 所有权）**

  - `backend/auto_designer/distill/seed_adapter.py`
  - `backend/tests/distill/test_seed_adapter.py`

依赖 DAG：`T1 → T2`

## Drawbacks

<!-- 待填 -->

## Rationale and alternatives

### T1 种子场景采集（蒸馏，skill 形式）

- 轮辐式公共契约 vs 各 skill 自带 schema：选轮辐式（与 0006 同）。各自带必漂移；契约一处改全员生效，新真实源
  只插一个薄 skill、彼此解耦可扩展。代价是要先把公共部分抽成契约。
- 收编 NexAU extract-harness-seed vs 另写 seed-distill skill：选收编。既有方法已沉淀「harvest 不 author /
  两道门 / 与 held-out 解耦」，重写必失真且违背「seed 来自真实数据」；代价是带进跨仓制品需 vendored 并标注来源。
- 契约里保留完整 oracle/env/gates（含 test_cmd）vs 只留注入需要的字段：选保留完整。种子卡是真实制品的忠实
  转录，判分证据（oracle/test_cmd/gates）必须随卡沉淀以供 harbor 侧评测；held-out 纪律靠**注入边界**剥离
  （0010/T2），而非在采集侧就丢弃——丢弃会让卡不可复用于客观评测。

### T2 种子注入（card → SeedScenario）

- held-out 字段落 sidecar vs 直接丢弃 vs 原样带入：选 sidecar。带入违背 benchmark held-out（污染训练信号）；
  丢弃让种子卡不可复用于 harbor 客观评测；sidecar 在注入边界物理隔离，两全。代价是多一处旁路产物需管理。
- 唯一桥接层做字段映射 vs 卡与 SeedScenario 同构（免映射）：选显式映射。种子卡保留真实制品原貌（含 benchmark
  侧字段），SeedScenario 是精简的注入契约，映射层吸收差异并在此落 held-out 剥离——这正是红线该在的位置。
- repo_at 须已解析 SHA vs 接受占位/ref：选须解析（占位如 `<parent-commit>` 拒收）。0009/T4 的 git 源按 commit
  checkout，未解析占位会在物化时才炸；在注入边界前移校验，把采集缺陷暴露早。
- 非法值报错 vs 安全缺省：选报错（缺省会把劣质采集悄悄变成"看似合法"的场景，污染信号）。

## Prior art

### T1 种子场景采集（蒸馏，skill 形式）

既有真实 harvest 方法（NexAU 仓库 `extract-harness-seed`，公共 schema/两道门原出处）：SKILL.md（capability
分类法、两道门、harvest 流水线）、reference.md（枚举/oracle tier/repro tier/harvest mechanics）、产物示例
seeds/seed-pytest-13537.json、seed-requests-6964.json、校验器 validate_seed.py。本组将其公共部分收敛为
seed-card-schema.md 契约。与 0006（persona 采集）对称镜像；domain 词表与 persona D5.area 共享。
CLAUDE.md「蒸馏模块」「种子场景库来自真实数据、benchmark 全程 held-out」；spec-0001/T1 SeedScenario 字段。

### T2 种子注入（card → SeedScenario）

消费侧 spec-0001/T1 models.SeedScenario / WorkspaceSpec（本组只读、零改）；0009/T1 SeedSource 接缝与顶层
provision；0009/T4 git 源（kind="git" + params{repo, commit}）；0009/T3 依赖供给（venv 前缀化 setup 约定，
ensure_deps + Sandbox 探测 .venv）；backend/seed_scenarios.json 与 run.py._load_seeds 的 {version, seeds}
信封形状。上游 0010/T1 种子卡 schema。与 0006/T2 card_to_persona 对称镜像。CLAUDE.md「benchmark 全程
held-out：不参与训练，不参与发版门禁」为 held-out 红线的依据。

## Unresolved questions

### T1 种子场景采集（蒸馏，skill 形式）

- 日志/SO（及未来源）作「只依赖 seed-card-schema.md 的薄 skill」何时补入：本步先契约 + extract-harness-seed，
  余者后续插入。
- 是否把 NexAU 的源 skill（仅是它此前的存放处）也重构为轮辐式（公共契约 + 薄 skill）？此为改其源仓，属另一件
  事；本仓 seed-card-schema.md 统一以 extract-harness-seed 最新约定为准。
- 智能配对（persona×seed，domain 匹配 + 能力可信 + autonomy 适配）**不在本组**：run.py 现为 persona[i]×
  seed[i % len] 取模轮转，约束配对为独立的下游 spec，本组不做成 task。
- env.base_image / external_deps（容器供给）与私有仓鉴权：引 0009/T4 open-question，标为超出本框架当前能力。
- oracle 客观判分（跑上游测试判修复对错）归 harbor 侧平行评测系统，红线 held-out、永不进本框架训练环。

### T2 种子注入（card → SeedScenario）

- 智能配对（persona×seed）**不在本组**：seed-card 带 pairing_constraints（domain/min_capability/autonomy），
  但约束配对是独立下游 spec；run.py 现为 persona[i]×seed[i % len] 取模轮转，本组明确 out-of-scope、不做成 task。
- env.base_image / external_deps（容器供给）：git 源 + venv 前缀化 setup 只覆盖「clone@commit + pip 依赖」，
  挑系统依赖/需官方镜像的实例仍不保证可跑——引 0009/T4 open-question，标为超出本框架当前能力。
- 私有仓鉴权（token/ssh 注入 clone）：0009/T4 默认公开仓/本地仓，注入层不处理鉴权，引 0009/T4 open-question。
- sidecar 的落地形态（旁路 JSON 文件 vs 返回结构）与 harbor 侧如何消费：oracle 客观判分归 harbor 侧平行评测
  系统，本组只保证在注入边界剥离、不定义评测运行时。

## Future possibilities

<!-- 待填 -->

