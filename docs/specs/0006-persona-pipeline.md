---
number: "0006"
title: Persona 管线：采集（蒸馏）与注入 sim
issue: 0
slug: persona-pipeline
summary: 本组实现 persona 管线：把「从真实数据采集 persona」与「把 persona 注入控制信封 sim」串成一条链， 为 0005 的用户侧重型实现供给真实画像。对应 CLAUDE.md「蒸馏模块」，落实约束「persona 来自真实数据、 不依据 benchmark 或轨迹构造」。
tasks:
  - id: T1
    title: Persona 采集（蒸馏，skill 形式）
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to:
      - ref: 0005/T1
        type: note
    parallel: false
    files:
      - tools/persona-distill/card-schema.md
      - tools/persona-distill/extract-selfreport-persona/SKILL.md
      - tools/persona-distill/extract-selfreport-persona/reference.md
      - tools/persona-distill/extract-selfreport-persona/recruitment/seeds.md
      - backend/auto_designer/distill/library.py
      - backend/tests/distill/test_library.py
    scope: 按轮辐式落地采集侧并定义 persona 卡库格式。本步范围：① card-schema.md（唯一公共契约：卡 schema + 枚举 + D5 词表 + 注入分布 + 真实性门原则，source-agnostic）；② extract-selfreport-persona（薄 skill，从第一人称自述提取，引用契约）；③ library.py 读写。不接具体数据源、不做卡→sim 注入映射（归 T2）。cc/so/未来源作同契约的后续薄 skill，留待补入（见 open-questions）。
    acceptance: card-schema.md 为唯一 source-agnostic 公共契约（卡 schema + 枚举 + D5 词表 + 注入分布 + 真实性门原则）；extract-selfreport-persona 为薄 skill，只引用契约、无 skill→skill 依赖、无悬空引用；library 按契约读写多条卡库、可按 id 取、对未知键前向兼容；卡记录不含任何 benchmark/轨迹派生字段；D5.area 为受控词表单 token。
  - id: T2
    title: Persona 注入 sim
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
      - 0005/T1
    relates-to:
      - ref: 0005/T1
        type: extends
      - ref: 0005/T5
        type: note
    parallel: false
    files:
      - backend/auto_designer/user/sim/persona_io.py
      - backend/tests/user/sim/test_persona_io.py
    scope: 把 persona 卡（0006/T1）注入 sim：card_to_persona 映射卡 → dimensions.Persona，grounded 轴透传、finalize_persona 只填卡未 ground 的派生维度（覆盖派生）；处理 6 维卡↔9 维的字段对齐、枚举并轨（surface↔shallow 等）、缺省与校验。不改卡格式（归 T1）；sim 维度模型仅做「finalize 降为 fallback-only」的配套修正（契约见 0005/T1，本组依赖）。不构造 harness/client（0005/T6）。
    acceptance: card_to_persona 对合法卡产出完整不可变 Persona：grounded 的 d3(卡 D2)/trust(卡 D4) 原样保留、卡未 ground 的派生维（d3/trust/d6 中缺的）经 finalize_persona 填齐；expert×over-trust 卡注入后 trust 仍为 over-trust 映射值（不被 derive_trust 改写成 skeptical）；缺字段/非法枚举显式报错；注入结果可直接喂 0005/T5 run_session 跑通一局。
  - id: T3
    title: 观测型 persona spoke：SO / GitHub 收编（含局限声明）
    status: done
    priority: P1
    tags:
      - persona-distill
      - observed-source
    depends-on:
      - T1
    relates-to:
      - ref: T2
        type: note
    parallel: false
    files:
      - tools/persona-distill/extract-stackoverflow-persona/SKILL.md
      - tools/persona-distill/extract-stackoverflow-persona/reference.md
      - tools/persona-distill/extract-github-persona/SKILL.md
      - tools/persona-distill/extract-github-persona/reference.md
      - tools/persona-distill/extract-github-persona/recruitment/domains.md
      - tools/persona-distill/extract-github-persona/recruitment/swe-bench.md
      - tools/persona-distill/extract-github-persona/recruitment/terminal-bench.md
    scope: "改造并实现两个**观测型** spoke（照 T1 的 extract-selfreport-persona 结构），本 task 范围：\n① extract-github-persona（源 extract-cc-user-persona；真实来源是 GitHub 足迹 repos/issues/PRs）——含\nSKILL.md + reference.md + recruitment/（domains.md 域登记 + swe-bench.md + terminal-bench.md）；\n② extract-stackoverflow-persona（源 extract-so-user-persona；Stack Overflow API）——含 SKILL.md +\nreference.md。三项改造：引契约去 spoke→spoke、补 basis、态度轴降 injected（SO 的 D1 降 medium）。\n两个 spoke 各写「局限与缺陷」段，显著记录观测型方法内容质量边界。**不改** card-schema.md（契约，归 T1）、\n不改 extract-selfreport-persona/（归 T1）、不改 backend 代码（library.py/validate_card/persona_io.py 归 T1/T2）、\n不改动 NexAU 原件（vendored 改造版进本仓）。库侧硬门（basis 强制 / 观测源态度轴强制 injected）本 task 不做，\n见 open-questions。"
    acceptance: "两个 spoke 落在 tools/persona-distill/ 下、结构对齐 extract-selfreport-persona，只引用 ../card-schema.md、\n无 spoke→spoke 的 schema 反向引用、无自带整套 schema、无悬空引用；每个 grounded 维封套带 basis（观测型为\nobserved），injected 维不带 basis 且 confidence=low；GitHub spoke 的 D4/无一手证据 D2 默认 injected、\nD1/D5 grounded；SO spoke 的 D1 grounded 封顶 medium、D4 默认 injected、D1/D5 grounded；两个 spoke 各含\n显著的「局限与缺陷」段（记录 D1×D5 可靠、态度轴注入/外推、来源偏差、使用边界）；两个 spoke 的\nworked-example 卡过 PersonaLibrary.validate_card 且可被 card_to_persona 消费；改名对齐 extract-<source>-persona。"
---

# 0006 · Persona 管线：采集（蒸馏）与注入 sim

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

本组实现 persona 管线：把「从真实数据采集 persona」与「把 persona 注入控制信封 sim」串成一条链，
为 0005 的用户侧重型实现供给真实画像。对应 CLAUDE.md「蒸馏模块」，落实约束「persona 来自真实数据、
不依据 benchmark 或轨迹构造」。

数据流脊柱：

```
真实使用数据(第一人称自述 · GitHub 足迹 · Stack Overflow · 未来源)
        │  采集/归纳（T1，轮辐式：共享卡契约 + 薄抽取 skill）
        ▼
   persona 卡库（6 维行为卡：D1–D6 + authenticity/era/provenance）
        │  注入（T2，card_to_persona：grounded 轴透传 + 覆盖派生）
        ▼
   spec-0005 dimensions.Persona ─► 0005/T5 run_session 跑一局 ─► 体感 + issue
```

读图即读任务：**T1** 定「采集什么、卡长什么样」——不另造 skill，而是收编既有的真实抽取方法（此前写在 NexAU 仓库里、非 NexAU 自身的方法），并按
**轮辐式**组织：唯一公共契约 `card-schema.md`（6 维卡 schema + 枚举 + D5 词表 + 注入分布 + 真实性门原则，
source-agnostic）+ 各「薄抽取 skill」只描述「从某类来源提取 + ground 哪几维」、只依赖契约、彼此不依赖。本步
先落契约 + `extract-selfreport-persona`（第一人称自述，唯一 ground 信任轴 D4 且带 card_to_persona 覆盖规则）；
cc/so/未来源作同契约的后续薄 skill 插入。库 schema 即该契约。**T2** 定「卡如何变成 sim 能跑的 Persona」
（唯一桥接层 card_to_persona）。

**覆盖派生（关键约束）**：6 维卡是「正交 ground 的真实画像」，每维各自有证据；sim 9 维里 d3/trust/d6 原是
「从 D1/D5 派生」。注入时 **卡里 grounded 的 验收 D2 → sim d3、信任 D4 → sim trust 直接写入、不被 derive_*
改写**（这两个正是 sim 的派生维），finalize_persona 只填卡未 ground 的派生维——否则 expert×over-trust
（selfreport 例 C / Karpathy）会被模拟成 skeptical×rigorous 的反面。此约束在 extract-selfreport-persona
reference 例 C 已写明（card_to_persona），并要求 0005/T1 把 finalize_persona 降为 fallback-only（本组同改）。
注：卡 D6 自主 → sim D5Autonomy 是采样维（直接写入，本无 derive）；sim 的派生维 D6Authz 卡中无对应来源，
仍按 D5Autonomy + task_risk 派生（见 T2）。

与 0005 的关系：本组是 0005（控制信封用户模拟器）的上游供给。6 维卡 ↔ sim 9 维 ↔ spec-0001 models.Persona
的最终并轨记在各 Task open-questions，待真实数据与下游需求收敛后定。

## Motivation

整条进化的训练信号取自「模拟真实使用」分布上的用户体感，其真实性根植于 persona 是否来自真实数据。既有的
三个真实抽取方法（此前写在 NexAU 仓库里，非 NexAU 自身的方法：extract-selfreport-persona、
extract-cc-user-persona、extract-so-user-persona）已沉淀「证据或弃 / 维度正交 / 双向真实性门」——重写必失真，
故收编而非另起炉灶（T1 收编 selfreport，T3 收编另两个观测型方法）。更关键是**可扩展性**：这些方法现状把
公共 schema 只写在 cc、so/selfreport 反向引用 cc（skill→skill 依赖），这正是 basis/provenance 在三者间漂移
的根因。轮辐式把公共部分抽成唯一契约、各 spoke 只依赖契约且彼此独立——契约改一处全员生效，加新来源只是
新增一个薄 spoke，不碰别人；T1 先落契约与首个 spoke，T3 按此规划补入另外两个。

T3 在收编之外还需按内容评审收紧态度轴：观测型源（GitHub 足迹、Stack Overflow 问答）可靠观测到的只有
能力与领域，把信任/验收/自主从外部行为反推（例如从 CVE 卫生、auto-merge 记录反推信任）是脆弱外推，
须显式降 injected 并在文档记录质量边界，避免单卡被误当真人「态度」锚使用而污染训练信号真实性。

在采集之后，注入层（T2）面对的是另一重矛盾：采集产出的是「正交 ground 的真实画像」，sim 消费的是「9 维
结构化系数」，两者格式不一，需一层显式、可测的映射。更关键的是，sim 的 d3/trust/d6 原是「从 D1/D5 派生」，
若注入时一律 finalize，会把卡里真实 ground 的信任/验收/授权改写成合成值——例如 expert×over-trust 的
Karpathy（selfreport 例 C）会被模拟成 skeptical×rigorous 的反面，直接污染训练信号的真实性。故注入层必须
让 grounded 值覆盖派生。

## Guide-level explanation

采集（蒸馏）侧按**轮辐式**组织，不另造大 skill：唯一公共契约 card-schema.md（source-agnostic）定义
6 维行为卡 schema（D1–D6 + authenticity + era + provenance）+ 维度枚举 + D5.area 受控词表 + 注入分布 +
双向真实性门原则，采既有 selfreport skill 的最新约定（每维 source+basis+confidence、provenance 并集、
value 键）。三个薄抽取 spoke 各只依赖该契约、彼此不依赖：extract-selfreport-persona（T1）从第一人称
自述（博客/访谈/演讲/推文长贴）提取，是唯一能 ground 态度轴 D4 信任的来源；extract-github-persona 与
extract-stackoverflow-persona（T3，改造自既有的 extract-cc-user-persona / extract-so-user-persona，改名
对齐 extract-<source>-persona 约定）观测 GitHub 足迹与 Stack Overflow 问答，可靠 ground 的是 D1 能力与
D5 领域·栈，态度轴（D2 验收、D3 交互、D4 信任、D6 自主）在观测型源里默认降为 injected（SO 的 D1 因证据
弱进一步封顶 medium），避免单卡被误当真人态度锚。本步先落契约 + selfreport（T1），cc/so 作同契约后续
薄 spoke 插入（T3 兑现），未来源留待补入。三个 spoke 交付的卡记录由 library.py（T1）统一读写，按契约
存取，供注入层消费。

把采集到的 persona 卡注入控制信封 sim 是唯一桥接层（T2）：card_to_persona 将一条卡映射为 sim 的
dimensions.Persona —— 卡里 grounded 的轴直接透传，finalize_persona 仅填卡未 ground 的派生维度（即
「覆盖派生」：grounded 的验收/信任/授权不被 derive_* 改写）。产物直接交 spec-0005/T5 run_session 使用。

## Reference-level explanation

### 采集侧：轮辐式契约与三个抽取 spoke（T1、T3）

采集侧落地范围是「唯一公共契约 + 三个彼此独立的薄抽取 spoke + 一个读写库」，均在 tools/persona-distill/
下按轮辐式组织：

```
tools/persona-distill/
  card-schema.md                     唯一公共契约（hub，source-agnostic，归 T1）
  extract-selfreport-persona/        自述型 spoke（T1，grounds 态度轴 D2/D3/D4/D6）
  extract-github-persona/            观测型 spoke（T3，grounds D1/D5）
  extract-stackoverflow-persona/     观测型 spoke（T3，grounds D1/D5 低端）
```

铁律：spoke 只依赖契约，**彼此不依赖 schema**（杜绝 spoke→spoke 与多副本漂移）——这是修复既有方法
「公共 schema 只写在 cc、so/selfreport 反向引用 cc」导致 basis/provenance 漂移的关键设计。

card-schema.md（T1，公共契约）定义 6 维行为卡：D1 评估能力 | D2 验收门槛(primary+flags) | D3 交互
(delegation·supervision·on_offtrack) | D4 信任 | D5 领域(area+depth+stack+weak) | D6 自主期望；每维携
{value | (primary,flags), source(grounded|injected), basis(observed|stated|stated+observed), confidence}；
meta 含 authenticity / era{value,basis} / provenance（并集：layers? · sources? · self_report? · reputation? +
evidence_quotes[{quote,source}]）；另含 D1–D6 枚举取值、D5.area 受控词表、注入分布、双向真实性门原则。

三个 spoke 各只描述「从某类来源提取 + ground 哪几维」，彼此互补，合起来使每轴至少被一个源观测或自述
ground：extract-selfreport-persona（T1）从第一人称自述提取，强 ground D2/D3/D4/D6（验收/交互/信任/自主），
D1/D5 为 medium 需佐证，含 stated→confidence 规则与 performative/promotional/second-hand 真实性门，是唯一
能 ground 信任轴 D4 的来源。extract-github-persona 与 extract-stackoverflow-persona（T3，分别改造自既有
的 extract-cc-user-persona 与 extract-so-user-persona，改名对齐 extract-<source>-persona 约定——"cc" 原指
驱动的 harness 而非来源，真实来源是 GitHub 足迹）观测行为轨迹，可靠 ground D1 能力与 D5 领域·栈；态度轴
按内容评审收紧：GitHub 的 D4 信任、缺一手证据的 D2 验收默认降 injected（改掉此前「从 CVE 卫生/auto-merge
推 D4 grounded」的写法，仅有一手信任/验收陈述才 grounded），SO 的 D4 保持默认 injected、D1 由单帖+
reputation 弱信号封顶 medium（不再 blind@high）。T3 的改造同时做了两项结构清理：① 删除两个 spoke 原有的
「公共 schema 只写在 cc、so 反向引用 cc」整套 schema 表与反向引用（漂移根因），改引 ../card-schema.md；
② 为每个 grounded 维补 basis（观测型 grounded 值记 observed，区分转录事实与评审判断；injected 维不带
basis）。两个观测型 spoke 各含显著的「局限与缺陷」段：只有 D1×D5 由一手观测可靠支撑，态度轴 D2/D3/D4/D6
在观测型源里是注入先验/外推、单卡不忠于真人态度，来源存在偏差（SO 偏卡住来问者/幸存者自选择，GitHub
偏公开活跃），使用边界是「适合铺 D1×D5 覆盖网格，态度轴真人锚须来自 selfreport」。GitHub spoke 附带的
recruitment 多源 profile（swe-bench.md / terminal-bench.md / domains.md）是共享招募数据（决定看谁），SO
spoke 引用其 pools.stackoverflow；这不构成 schema 契约，不算 schema 漂移。

三个 spoke 产出的卡记录由 library.py（T1）统一读写：一个库文件承载多条卡记录，纯数据，可双向序列化，
对未知键前向兼容（演化友好），提供 load / get(id) / add 最小读写。卡格式与 sim 9 维 Persona 解耦——卡是
「采集到的真实画像（正交 ground）」，到 sim 维度的映射归注入层（T2）。

**接口**

```
PersonaLibrary(root|path)
- load() -> list[dict]            # 读全库（卡记录）
- get(persona_id: str) -> dict    # 按 id 取一条卡
- add(record: dict) -> None       # 追加一条卡记录
```

卡 schema 由 card-schema.md（唯一契约）定义；与 spec-0001 models.Persona 的并轨见 Unresolved questions。
两个观测型 spoke（T3）不引入新代码接口，产出 card-schema.md 定义的同一卡形状，可被
PersonaLibrary.validate_card 校验、被 T2 的 card_to_persona 消费。

**测试**

单测（T1，library.py）：
- PersonaLibrary 读写：add 后 load 含该条、get(id) 取回等价记录；空库 load 返回空列表。
- 卡 schema round-trip：含 source/basis/confidence 与 provenance 并集字段的记录 to/from dict 字段级一致；
  遇未知键忽略不报错（前向兼容）。
- 约束校验：卡记录不含 benchmark/轨迹派生字段（字段白名单断言）；D5.area ∈ card-schema.md 受控词表。

验证（T3，spoke 收编，doc/skill 层面，不新增库侧代码/测试）：
- 两个 spoke 的 worked-example 卡（github 例 A、stackoverflow 例 A）实跑 PersonaLibrary.validate_card 通过、
  card_to_persona 产出可用 Persona（grounded 轴透传、injected 态度轴交 finalize 派生）。
- 静态核验：spoke 内无 spoke→spoke 的 schema 反向引用、无自带 schema 表；grounded 维均带 basis；
  D5.area ∈ card-schema.md 受控词表。
- spec validate 无 error、spec render 无 drift。

**文件（单一 writer 所有权）**

T1：
  - `tools/persona-distill/card-schema.md`
  - `tools/persona-distill/extract-selfreport-persona/SKILL.md`
  - `tools/persona-distill/extract-selfreport-persona/reference.md`
  - `tools/persona-distill/extract-selfreport-persona/recruitment/seeds.md`
  - `backend/auto_designer/distill/library.py`
  - `backend/tests/distill/test_library.py`

T3：
  - `tools/persona-distill/extract-stackoverflow-persona/SKILL.md`
  - `tools/persona-distill/extract-stackoverflow-persona/reference.md`
  - `tools/persona-distill/extract-github-persona/SKILL.md`
  - `tools/persona-distill/extract-github-persona/reference.md`
  - `tools/persona-distill/extract-github-persona/recruitment/domains.md`
  - `tools/persona-distill/extract-github-persona/recruitment/swe-bench.md`
  - `tools/persona-distill/extract-github-persona/recruitment/terminal-bench.md`

### 注入侧：card_to_persona 桥接层（T2）

采集到的卡进入 sim 前需经唯一桥接层 card_to_persona（T2）：按字段映射把卡翻成 sim 维度——

| 卡维度 | sim 维度 | 说明 |
|---|---|---|
| D1 评估能力 | D1Eval | surface↔shallow 并轨 |
| D5 领域(area/depth/stack/weak) | D2Domain + D2Depth | |
| D2 验收门槛(primary) | D3Accept | 派生维，grounded 时直接写入（覆盖派生） |
| D3 交互(delegation/supervision/on_offtrack) | D41Grain / D42Supervise / D43Correct | |
| D4 信任(over-trust/balanced/skeptical) | trust(blind/balanced/skeptical；over-trust↔blind) | 派生维，grounded 时直接写入（覆盖派生） |
| D6 自主期望(advisory/collaborative/agentic) | D5Autonomy | 采样维，直接写入 |

卡里 source=grounded 的轴直接写入对应 sim 维；其中 D2→d3、D4→trust 落在 sim 的派生维上，其余
（D1/D5/D3/D6）落在采样维上、本就直接写入；缺的派生维交 spec-0005/T1 finalize_persona 填齐。

**覆盖派生**是本层的核心设计：sim 的派生维只有 d3/trust/d6 三个，其中 d3（来自卡 D2）、trust（来自卡 D4）
在卡已 ground 时直接写入、不被 derive_d3/derive_trust 改写——否则 expert×over-trust（selfreport 例 C /
Karpathy）会被模拟成 skeptical×rigorous 的反面。此设计依赖 spec-0005/T1 把 finalize_persona 降为
fallback-only（只填卡未提供的派生维），本组对该处做配套修正。sim D6Authz（授权尺度，派生维）卡中无对应
轴——卡 D6 语义是「期望 agent 扮什么角色」而非「授权它能做什么」，故不 ground 它，仍由 finalize 按
D5Autonomy + task_risk 派生填齐。非法/缺失枚举值显式报错（不静默兜底），把采集质量问题暴露在注入边界；
批量入口 card_to_personas(library)。

**接口**

```
card_to_persona(record: dict) -> Persona        # 单条卡 → sim Persona；grounded 轴透传、其余 finalize 派生
card_to_personas(library: PersonaLibrary) -> list[Persona]
```

**测试**

单测：
- 覆盖派生（核心）：selfreport 例 C / Karpathy（D1=expert、D4=over-trust、D2=ship-fast，均 grounded）注入后
  Persona.trust = over-trust 映射值（非 derive_trust(expert)=skeptical）、d3 非 rigorous —— 即 grounded 值未被改写。
- 透传+派生：grounded 轴透传；未提供的派生轴由 finalize 正确填齐、可复现。
- 枚举并轨/校验：surface↔shallow 等映射正确；非法/缺失枚举值 → 显式报错（不静默兜底）。
- 端到端：注入产物喂 0005/T5 run_session（离线 ScriptedPersonaClient + 脚本化 harness）跑通一局。
- 批量：card_to_personas 把多条卡映射为等长 Persona 列表。

**文件（单一 writer 所有权）**

  - `backend/auto_designer/user/sim/persona_io.py`
  - `backend/tests/user/sim/test_persona_io.py`

依赖 DAG：`T1 → T2`，`0005/T1 → T2`，`T1 → T3`

## Drawbacks

本方案的代价集中在四处：① 采集侧把三个真实抽取方法收编为 vendored 改造版而非直接复用源仓，需要人工
同步——若源方法此前的存放处（NexAU 仓库）后续演进契约，本仓 card-schema.md 不会自动跟随，需另行移植；
② 观测型来源（GitHub / Stack Overflow）能可靠 ground 的仅 D1 能力与 D5 领域·栈，态度轴（D2/D3/D4/D6）
几乎全部降为 injected，观测型 spoke 扩大的是覆盖广度而非态度深度，训练信号里真人态度锚的多样性仍依赖
selfreport 单一来源；③ 注入层（T2）为保留 grounded 值不被派生覆盖，需按 source 显式区分
grounded/injected 并对非法枚举报错，比"卡与 sim 同构"的方案更复杂，且依赖 spec-0005/T1 finalize_persona
降级为 fallback-only 这一外部前置条件；④ 本组明确未给契约加库侧硬门（basis 强制校验、观测型源态度轴
强制 injected），短期内契约的强制力依赖各 spoke 作者自觉遵守，而非工具校验兜底。

## Rationale and alternatives

- **轮辐式公共契约 vs 各 spoke 自带 schema**：选轮辐式（T1 建 hub，T3 扩充 spoke 时遵循同一模式）。各自带
  必漂移——既有方法现状把公共 schema 只写在 cc、so/selfreport 反向引用 cc，basis/provenance 已在三者间
  漂移；契约一处改全员生效，新来源只插一个薄 spoke、彼此解耦可扩展。代价是要先把公共部分抽成契约（T1），
  且 T3 收编两个观测型 spoke 时需同步删除其自带 schema 表与反向引用。
- **收编真实方法 vs 重写**：选收编（T1 的 selfreport、T3 的 GitHub/StackOverflow 均如此）。既有方法已沉淀
  「证据或弃 / 维度正交 / 双向真实性门（观测型源体现为 trace-floor 真实性门）」，重写必失真且违背
  「persona 来自真实数据」的约束；代价是带进跨仓制品需 vendored 并标注来源，不改动原件。
- **先 selfreport 单一切片 vs 三源齐上**：选 selfreport 首切片（T1），cc/so 作同契约后续薄 spoke 插入
  （T3 兑现）。selfreport 唯一 ground 信任轴 D4、且带 card_to_persona 覆盖派生规则（正是 T2 所需），避免
  首切片体量过大。
- **观测型源态度轴降 injected vs 保留从行为反推 grounded**（T3）：选降 injected。从 CVE 卫生/auto-merge/
  reputation 反推信任/验收是脆弱外推，会把合成态度当真人态度污染训练信号；代价是观测型卡的态度轴几乎全
  injected（这正确反映「观测型源观测不到态度」的事实），真人态度锚交给 selfreport。
- **recruitment profile 放 github spoke 供 SO 引用 vs 各自复制**（T3）：选前者。profile 天然多源（一份同列
  github repos 与 SO tags），复制会引入多副本漂移；跨 spoke 只剩这一处共享招募数据引用，且非 schema 契约。
- **T3 只做文档/skill 收编、不加库侧硬门**：选先文档。硬门（basis 强制、观测源态度轴强制 injected）属库侧
  加固，改 validate_card，风险与范围更大，归后续（见 Unresolved questions）。
- **grounded 覆盖派生 vs 一律 finalize**（T2）：选覆盖。一律 finalize 会丢弃卡里真实 ground 的信任/验收/
  授权，把正交真实画像压成 sim 的派生面（违背训练信号真实性，见 selfreport 例 C）；代价是注入层要按
  source 区分 grounded/injected。
- **显式映射表 vs 卡与 sim 同构（免映射）**（T2）：选显式映射。卡保留真实画像原貌、sim 用受控枚举，映射层
  吸收差异。
- **非法值报错 vs 安全缺省**（T2）：选报错——缺省会把劣质采集悄悄变成"看似合法"的 persona，污染信号。

## Prior art

本组三个 task 的源头都是此前存放于 NexAU 仓库、但非 NexAU 自身方法的一组真实抽取方法：
extract-cc-user-persona（GitHub 足迹 L0–L5，公共 schema/枚举/D5.area 词表/注入分布原出处，本组改名为
extract-github-persona）、extract-so-user-persona（Stack Overflow API，改名为
extract-stackoverflow-persona）、extract-selfreport-persona（第一人称自述；reference 例 C 写明
card_to_persona 须以 grounded D2/D4 覆盖 derive_trust/derive_d3，否则真实人物被模拟成其反面——这正是
T2 覆盖派生设计的直接依据）。T1 以 extract-selfreport-persona 的最新约定为模板（结构与文风），把三者的
公共部分收敛为唯一契约 tools/persona-distill/card-schema.md（6 维卡 + 枚举 + D5 词表 + 注入分布 + 真实性门 +
basis 四元 + 铁律：grounded 须有 evidence_quote、injected confidence=low）；T3 将 vendored 改造版进本仓、
不改动原件，把另两个方法收编为遵循同一契约的观测型 spoke。T2 的注入层依赖 spec-0005/T1
dimensions.Persona 与 finalize_persona（fallback-only 契约，本组依赖其降级）、spec-0005/T5 run_session
入口；消费侧确认可消费、不改的还有 backend/auto_designer/distill/library.py（PersonaLibrary/
validate_card）。整体对应 CLAUDE.md「蒸馏模块」与「persona 来自真实数据、不依据 benchmark 或轨迹构造」的
约束，以及 spec-0001/T1 的 Persona 字段约定。

## Unresolved questions

- **来源覆盖率（T1/T3）**：cc/so 已由 T3 兑现补入；「未来源」作同契约后续薄 spoke 何时/是否补入仍未定。
- **契约的库侧强制力（T3）**：是否给 card-schema.md 补库侧硬门（basis 字段强制校验 / 观测型源态度轴强制
  injected 的加固）？本组明确不做（用户暂不做库侧硬门），归后续，届时改 card-schema.md 契约 +
  validate_card（T1 文件）。
- **T2 的前置依赖**：覆盖派生依赖 spec-0005/T1 把 finalize_persona 降为 fallback-only（本组同改）；若未
  就绪则覆盖派生无法生效。
- **卡 schema 与 sim/models.Persona 的最终并轨**：6 维行为卡、spec-0001 models.Persona（五元组）、sim
  9 维三者如何最终并轨尚未定；6 维卡 → 9 维枚举映射表细则随 T1 契约演进收敛，sim D6Authz 作注入轴的派生
  规则待定；若后续并轨为共用一套 Persona，T2 注入层可退化为薄校验或被移除。
- **recruitment profile 的跨 spoke 共享（T3）**：SO spoke 引用 github spoke 的 pools.stackoverflow 是否
  进一步抽到中立位置，以彻底消除仅剩的这一处 spoke→spoke 引用？当前判定：招募数据天然多源、非 schema
  契约，暂保留。
- **源仓是否同步重构**：这些方法此前的存放处（NexAU 仓库）是否也重构为轮辐式（公共契约 + 薄 skill，补
  basis/统一 provenance/补 card_to_persona 覆盖注记）？此为改其源仓，属另一件事；本仓 card-schema.md
  统一以 T1 selfreport 最新约定为准。
- **种子场景库**：是否同时蒸馏「种子场景库」(SeedScenario)？CLAUDE.md 蒸馏模块含场景库，本组先聚焦
  persona，场景库另议。

## Future possibilities

后续可扩展方向包括：① 按同一契约继续插入更多来源的薄 spoke（除已收编的 selfreport / GitHub / Stack
Overflow 外的「未来源」）；② 给 card-schema.md 补库侧硬门（basis 字段强制校验、观测型源态度轴强制
injected 的加固），把当前依赖文档自律的约束升级为 validate_card 强制；③ 把 6 维行为卡、spec-0001
models.Persona（五元组）与 sim 9 维最终并轨为一套共用 Persona 表示，届时 T2 注入层可退化为薄校验甚至
移除；④ 将这些方法此前的存放处（NexAU 仓库）中的对应源方法同步重构为轮辐式（公共契约 + 薄 skill），
使两侧契约长期保持一致；⑤ 在 persona 之外同时蒸馏「种子场景库」(SeedScenario)，覆盖 CLAUDE.md 蒸馏
模块的另一半范围。

