---
number: "0037"
title: 人轴重构：时间气质 ⊥ 质量失败 · 过程卷入 · 蒸馏 spoke 对齐
issue: 0
slug: persona-time-temperament-reframe
summary: 接缝接近真人 CLI 后，等待体感差在「人」轴：旧设计把耐心焊在质量失败策略(d43)上、supervision 仍是回合制盯梢。本组新增 tempo(卡 D7)驱动耐心，d43 只答结果错了怎么办，supervision 改为过程卷入，D6Authz 标为会话策略不进卡；hub 加 D7 与正交注入；注入缺省 steady；三个蒸馏 spoke 对齐 ground/inject。不另起翻译模块，投影仍走 judge→intent→act；不把 interrupt/queued/slash 焊进人轴。
tasks:
  - id: T1
    title: 写 0037 活快照
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - docs/specs/0037-persona-time-temperament-reframe.md
    scope: 写清动机：接缝 0035/0036 后等待体感差在人轴；旧 d43 绑耐心导致正交人像失真；禁焊 interrupt/queued/slash 进卡。选定 tempo 驱动耐心、d43 只管质量失败、supervision=过程卷入、D6Authz 出卡、hub D7 + spoke 对齐。明确不做独立 Translation 模块、不宣称相对旧系统体感 uplift。
    acceptance: spec validate 通过；正文含 Summary/Motivation/Reference-level explanation/Rationale and alternatives；DAG 与文件分配清楚；Unresolved 记录存量卡回填与 D7 硬门边界。
  - id: T2
    title: sim：tempo 驱动耐心 · 过程卷入语义 · D6Authz 会话策略
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/user/sim/dimensions.py
      - backend/ahe_beta/user/sim/state.py
      - backend/ahe_beta/user/sim/clauses.py
      - backend/ahe_beta/user/sim/demo.py
      - backend/tests/user/sim/test_dimensions.py
      - backend/tests/user/sim/test_state.py
      - backend/tests/user/sim/test_heartbeat.py
    scope: Persona 增 TimeTemperament/tempo；init_state/make_coef 耐心基线与衰减跟 tempo，不再跟 d43；高过程卷入(d42 every_step) 可加 stuck_extra；clauses/BLOCK-P 写过程卷入与时间气质，不出现 interrupt/queued/slash 焊进维文案；D6Authz 文档标为会话策略（半派生，非卡库人轴）。demo 展示 tempo 正交。配套单测。
    acceptance: patience0/decay 随 tempo 分档；同 d43 不同 tempo 耐心不同；clauses 含 Process involvement / Time temperament；相关 pytest 绿；demo 可打印 tempo 与 stuck_extra。
  - id: T3
    title: hub：card-schema 增 D7 与语义注记
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - tools/persona-distill/card-schema.md
    scope: 唯一公共契约增 D7_time_temperament（patient|steady|impatient）与注入分布；注明 supervision=过程卷入、on_offtrack=质量失败策略且不驱动等待耐心；正交强制 on_offtrack ⊥ time_temperament；符合性：缺 D7 时注入侧回落 steady（旧卡兼容），新卡应显式写出。不改三个 spoke（归 T5）。
    acceptance: card-schema 含 D7 枚举、注入比例、正交强制与 supervision/on_offtrack 语义注记；授权尺度仍不进卡库。
  - id: T4
    title: 注入：card_to_persona 读 D7→tempo
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/user/sim/persona_io.py
      - backend/tests/user/sim/test_persona_io.py
    scope: card_to_persona 映射 D7_time_temperament → Persona.tempo；缺字段回落 steady（旧卡兼容，不报错）；非法枚举仍报错。D6Authz 仍不从卡读。配套单测。
    acceptance: 有 D7 的卡注入 tempo 正确；无 D7 卡 tempo=steady；非法 D7 报错；既有 grounded 覆盖派生（D2/D4）不回归。
  - id: T5
    title: 蒸馏 spoke 对齐 D7 与人轴语义
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T3
    relates-to:
      - ref: 0006/T1
        type: extends
      - ref: 0006/T3
        type: extends
    parallel: false
    files:
      - tools/persona-distill/extract-selfreport-persona/SKILL.md
      - tools/persona-distill/extract-selfreport-persona/reference.md
      - tools/persona-distill/extract-github-persona/SKILL.md
      - tools/persona-distill/extract-github-persona/reference.md
      - tools/persona-distill/extract-stackoverflow-persona/SKILL.md
      - tools/persona-distill/extract-stackoverflow-persona/reference.md
    scope: 三个薄 spoke 对齐 hub 的 D7 与语义注记，仍只引用 ../card-schema.md、不内嵌枚举。① selfreport：ground 表与 quote mining 增 D7（等待/干等耐受原话）；supervision→过程卷入；on_offtrack 明确≠等待耐心；文案「6 维」改为含 D7；范例卡补 D7。② github/SO：D7 默认 injected（走 hub 分布）；局限段写观测不到等待气质；禁止从 PR 量/发完消失派生 impatient 或与 abandon 锁死；范例卡补 injected D7。不改 card-schema（归 T3）、不改 backend、不重采存量卡库。
    acceptance: 三 spoke 无「仅 6 维」残留；selfreport ground 表含 D7 与正交说明；观测型两 spoke 写明 D7 默认 inject + 禁错误派生；范例卡形状含 D7_time_temperament 且可被 validate_card/card_to_persona 消费。
  - id: T6
    title: 探针：tempo / 过程卷入 / d43 正交可观测
    status: done
    priority: P2
    tags: []
    depends-on:
      - T2
      - T4
    relates-to: []
    parallel: false
    files:
      - tools/dev/probes/probe_persona_reframe.py
      - tools/dev/probes/probe_swebench_persona.py
      - tools/dev/probes/probe_d43_quality_fail.py
    scope: 脚本探针验证重构轴可观测：tempo A/B（耐心/等待菜单差异）、过程卷入差异、d43 质量失败路径差异；支持覆盖 tempo/d42/d43。不宣称相对旧系统体感 uplift；不把 probe 当 CI 门禁。
    acceptance: 三探针可独立跑通（脚本/脚本 harness/可选真 seed）；覆盖项文档化；不修改 sim 核心文件（归 T2/T4）。
---

# 0037 · 人轴重构：时间气质 ⊥ 质量失败 · 过程卷入 · 蒸馏 spoke 对齐

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

本组重构用户侧 **persona 人轴**：把「等多久受得了」从「结果错了怎么办」里拆出来，并让蒸馏卡库与 sim 消费对齐。

核心契约：

- 新增 **时间气质** `tempo`（卡字段 `D7_time_temperament`：`patient | steady | impatient`）驱动等待耐心基线与衰减；
- **质量失败策略**（sim `d43` / 卡 `on_offtrack`）只回答交付质量不行时怎么做，**不**驱动耐心；
- **过程卷入**（sim `d42` / 卡 `supervision`）回答进行中要不要可见感，**不是**产品键（interrupt / queued / slash）；
- **授权尺度** `D6Authz` 标为会话策略（由自主性期望半派生），**不进卡库**；
- 卡契约 hub（`tools/persona-distill/card-schema.md`）加 D7、注入分布与正交强制；注入缺 D7 → `steady`；
- 三个蒸馏 spoke 对齐「谁可 ground D7 / 谁只能 inject」，禁止把等待气质焊进 on_offtrack。

投影仍走既有 **judge → intent → act**，**不**另起 Translation 模块。本组**不宣称**相对旧系统的体感 uplift（轴可观测 ≠ 净收益已证）。

## Motivation

### 接缝已近真人 CLI，差在「人」

用户↔harness 内外通道与可见状态已收敛：内=message（含旁路 progress/status）、外=interrupt；stdin 统一写、以 `type=reply` 软唤醒；busy 时可有 queued/status。真人差异大量落在**时间轴**：有人干等几分钟仍 keep_waiting，有人两分钟就炸、催进度或打断。若人轴仍把「耐心」焊在「翻车策略」上，接缝再真，模拟用户也只会在质量失败路径上分叉，长等待上塌成同一种人。

### 旧焊点：耐心跟 d43 / on_offtrack

旧 sim 用质量失败策略（如 give_up vs feedback）间接影响等待耐心。真实正交组合因此失真，例如：

- **较真但能等**：结果不行要 file-issue / handover，但空转时仍耐心 keep_waiting；
- **随手接受但等不住**：交付差不多就过，干等两分钟就催/打断。

二者被焊死后，蒸馏卡 `on_offtrack=abandon` 容易被误读成 impatient，训练信号把「放弃交付」与「等不下去」混为一谈。

### supervision 语义过时

卡/sim 的 supervision 仍带「读不读 diff / 回合制盯梢」味道。接缝层已有进行中可见事件后，人轴应表达的是**过程卷入**（opaque 是否不安、要不要可见性），而不是把当前 harness UX 枚举焊进人格。

### 蒸馏 spoke 滞后于 hub

轮辐式采集：唯一契约 `card-schema.md` + 薄 spoke（selfreport / github / stackoverflow）。若 hub 已有 D7 而 spoke 仍按「6 维」教抽取，新采卡缺 D7 → 注入全变 `steady`，tempo 轴在库里塌缩，sim 侧 A/B 等于白做。

### 明确不做的事

- 不把 interrupt / queued / slash 写进人轴枚举或抽取指南；
- 不另起「情境→动作」独立 Translation 模块；
- 不重开 persona 管线史诗、不批量回填存量卡（旧卡缺省 steady）；
- 不把探针当 CI 门禁，不宣称旧系统 A/B 净收益。

## Guide-level explanation

三人像（只谈人，不绑 v0 字段名）：

1. **急**：任务一丢出去，空转就坐立不安；进度条停了就催一句或考虑打断。交付质量翻车时怎么处理是另一回事——他可能仍愿意让 agent 再试一次，只是**等**得难受。
2. **能等**：同样长任务，可以去干别的；心跳看见还在动就继续等。若最终结果烂，他可能直接自己收尾或开 issue——**耐心与翻车策略正交**。
3. **高过程卷入**：不一定急，但讨厌黑盒；进行中希望有可见进展，长时间无信号会更快觉得「卡住了」（耐心额外扣一点），仍不等于必须按某个产品按钮。

蒸馏侧：

- 读**自述**（博客/访谈）时，把「我受不了干等」「我去倒杯咖啡再回来」ground 进 D7；把「结果不对我就自己改」ground 进 on_offtrack——两句不要并成一维。
- 读 **GitHub / SO** 足迹时，多数时候**看不到**等待气质 → D7 按契约注入分布抽，并标 `injected` / `low`；不要从 PR 频率或「发完消失」推出 impatient 并与 abandon 锁死。

跑局时：卡 → `card_to_persona` → `Persona.tempo` / `d42` / `d43` → 状态机耐心系数 + BLOCK-P 文案 → 既有三跳决策。

## Reference-level explanation

### 人轴对照（卡 ↔ sim）

| 卡（hub） | sim | 语义 | 驱动 |
|----------|-----|------|------|
| `D7_time_temperament` | `Persona.tempo` | 对等待/空转的耐受 | 耐心初值与衰减 |
| `interaction_style.supervision` | `d42` | 过程卷入（可见感需求） | stuck 时额外扣耐心等 |
| `interaction_style.on_offtrack` | `d43` | 质量失败后的策略 | 翻车路径意图，**不**驱动耐心 |
| （不进卡） | `D6Authz` | 会话授权尺度 | 由自主性期望半派生 |
| `interaction_style.delegation` | `d41` | 委派粒度 | 既有 |
| `D2_acceptance_bar` / `D4_trust_model` | `d3` / `trust` | 验收 / 信任 | 既有覆盖派生 |

枚举（卡侧，契约真源在 `card-schema.md`）：

- D7：`patient | steady | impatient`
- supervision：`hands-off | reviews | micromanage`（语义=过程卷入）
- on_offtrack：`abandon | retry | correct | fix-self | file-issue`（语义=质量失败；≠等待）

注入分布（沉默轴）：D7 为 patient 25% / steady 50% / impatient 25%；**强制**与 on_offtrack 独立采样。

### 状态与文案

- `init_state`：耐心初值按 tempo 分档（impatient 低、patient 高）；任务量仅微浮动，不盖过气质档。
- `make_coef`：`patience_decay` 跟 tempo；`stuck_extra` 在高过程卷入时 >0。
- `clauses` / BLOCK-P：Process involvement + Time temperament；**禁止**把当前 harness 产品键写进维文案当人格定义。

### 注入与兼容

`card_to_persona`：有 `D7_time_temperament.value` → 映射 tempo；缺字段 → `steady`（旧卡兼容）；非法值报错。D6Authz 永不从卡读。

### 蒸馏 spoke（T5）

轮辐不变：spoke 只依赖 `../card-schema.md`，彼此不依赖 schema。

| Spoke | D7 | 语义改写要点 |
|-------|----|--------------|
| selfreport | 可 **ground**（等待/干等原话）；无证则 inject | supervision→过程卷入；on_offtrack≠等待；文案含 D7；范例卡补字段 |
| github / SO | **默认 inject** | 局限段写「观测不到等待气质」；禁从 PR 量/发完消失派生 impatient 或与 abandon 锁死；范例补 injected D7 |

不重采存量卡库；不改 hub（T3 已定契约）。

### 探针（非门禁）

- `tools/dev/probes/probe_persona_reframe.py` — 脚本态正交
- `tools/dev/probes/probe_swebench_persona.py` — 可选真 seed；可覆盖 `--tempo/--d42/--d43`
- `tools/dev/probes/probe_d43_quality_fail.py` — 质量失败路径

验收口径：轴可观测、正交成立；**不**写「优于旧系统」。

e2e / 探针入口（非 CI 门禁）：

```text
tools/dev/probes/probe_persona_reframe.py
tools/dev/probes/probe_swebench_persona.py
tools/dev/probes/probe_d43_quality_fail.py
```

当前维护工具从仓库根目录用 `PYTHONPATH=backend .venv/bin/python -m tools.dev.probes.<module>` 调用。
各工具的显式输入、凭证与是否调用模型见 `tools/dev/README.md`；它们不注册另一套实验配置或多任务入口。

实现注释约定：本组落地代码用「本编号 + 任务号」追溯（形如本文件 `number` 加 `/T2` 的注释前缀，见 tools/spec-driven-development 注释规范）。

### 任务 DAG 与文件分配

```text
T1 活快照
 ├─ T2 sim（dimensions/state/clauses/demo + 单测）
 ├─ T3 hub card-schema
 │    └─ T5 三 spoke 文档对齐（done）
 └─ T2+T3 → T4 persona_io
              └─ T2+T4 → T6 探针
```

| Task | 状态 | 拥有文件（互斥） |
|------|------|------------------|
| T1 | done | `docs/specs/0037-persona-time-temperament-reframe.md` |
| T2 | done | `user/sim/{dimensions,state,clauses,demo}.py` + 对应单测 |
| T3 | done | `tools/persona-distill/card-schema.md` |
| T4 | done | `persona_io.py` + `test_persona_io.py` |
| T5 | done | 三个 spoke 的 `SKILL.md` / `reference.md` |
| T6 | done | 三个 `probe_*.py` |

依赖：`T1→T2`，`T1→T3`，`T1+T2+T3→T4`，`T1+T3→T5`，`T2+T4→T6`。

## Drawbacks

- 旧卡无 D7 一律 `steady`；新采 selfreport/github 卡已显式带 D7，但观测型 D7 仍多为 inject，库内「真人等待锚」仍偏依赖 selfreport。
- 观测型源 D7 几乎全 inject → 等待气质真人锚仍主要靠 selfreport（与态度轴历史局面同构）。
- 枚举字符串（hands-off/reviews 等）先保留、只改语义注释，读者可能短暂混淆旧名新义。
- handover 等质量失败路径在无真实可写工作区时弱可测，探针不能代替有工作区的验收。
- 本组不证旧系统 uplift，产品叙事上不能夸大「体感进化已验证」。

## Rationale and alternatives

- **tempo 独立轴 vs 继续用 d43 代理耐心**：选独立轴。焊在 d43 上无法表达正交人像，且污染蒸馏语义。
- **过程卷入改语义 vs 新开一维替换 supervision**：选改语义、保留枚举槽。奥卡姆：卡形状少炸一次；产品键不进枚举。
- **D6Authz 出卡 vs 进卡库**：选出卡。授权是会话/产品策略，不是「这个人是谁」；进卡会把实验条件焊进画像。
- **缺 D7 → steady vs 强制报错**：选 steady 兼容旧卡；新卡应显式写。硬门留给 Unresolved。
- **spoke 同组对齐 vs 另开蒸馏组**：选同组。契约变更与消费者（sim + spoke）同组才闭环；spoke 是文档对齐不是新管线。
- **独立 Translation 模块 vs 既有三跳**：选三跳。tempo/卷入进 state 系数与 prompt 已够投影；另起实体无必要证据。
- **备选否决：把 interrupt/queued 写进 persona**：否。那是 harness 产品面，进化对象不能焊进人真源。

## Prior art

- 本仓 persona 管线：轮辐式 `card-schema` + selfreport/github/SO spoke；卡→sim 唯一桥 `card_to_persona`；覆盖派生保留 grounded 信任/验收。
- 用户侧等待环与接缝：心跳 judge→intent→act；stdout 可见 progress/status；统一 stdin 写与 reply 软唤醒——本组承接「差在人轴」而非再改线协议。
- 探针实践：矩阵探针验证轴可观测，不作发版门禁（benchmark held-out 纪律不变）。

## Unresolved questions

- 合并库（`persona_library.json` = sr + gh）里，是否还要对**更旧、无 D7** 的遗留卡做批次回填（现注入缺省 `steady`）？
- `validate_card` 是否对**新卡**强制 D7 必填（旧卡仍合法）？
- handover 在真实可写工作区下的行为验收是否另开探针/任务？
- 是否要做旧系统 vs 本组的体感 A/B（大 N）？本组明确**不**把它当作验收前提。
- 采样器是否要显式「GitHub 取 D1×D5 + selfreport/注入取态度」混搭（现行是整卡使用，无自动拼轴）？

## Future possibilities

- 继续用 selfreport 补齐 impatient/patient 真人锚，校准注入分布；用 SO spoke 补 blind/surface 网格。
- 库侧硬门：basis 强制、观测源态度轴/D7 注入约束升级为 `validate_card`。
- 若枚举旧名持续误导，可另开组做 rename（micromanage→high involvement 等）并迁移卡库——本组不做。
- 过程卷入与可见事件（progress/status）的更细耦合（例如「无新进度」与 stuck 判定）可在等待环侧演进，仍不把具体 UX 键焊进卡。
- 可选：卡库分文件（`persona_library_selfreport.json` / `persona_library_github.json`）+ 合并默认库，便于按源跑实验（已在运行侧落地，非本组 Task 文件归属）。
