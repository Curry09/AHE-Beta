---
name: extract-harness-seed
description: >-
  Harvest one reproducible task seed (with a built-in oracle) from an
  already-resolved real artifact — a closed issue + merged fix PR, or a
  high-voted Q&A — to feed the seed library that drives the user → issue → 体感
  loop. Use when building or expanding the seed library, sourcing real coding
  tasks for harness simulation, or auditing seed oracle/reproducibility quality.
  A seed = a real user demand + a harness-independent success oracle + a
  harbor-reproducible env, tagged by the harness capability it stresses. Emits
  the shared seed card defined in ../seed-card-schema.md (the single public
  contract); this skill is one thin "spoke" among future source spokes
  (extract-log-seed / extract-so-seed). It does NOT embed the schema/enums/gates
  — those live in the contract.
---

# Extract Harness-Seed

一个**薄抽取 skill（spoke）**：从**已解决的真实制品**（closed issue + merged fix PR、accepted /
高票 Q&A）harvest **一张种子卡**。卡的 schema / 枚举 / domain 词表 / 两道门原则 / held-out 字段
存放约定一律来自唯一公共契约 [`../seed-card-schema.md`](../seed-card-schema.md)，本文件只写
**「从『已解决制品』这类来源 harvest、过两道门、ground/转录哪几字段」**这一来源特异性，不内嵌
schema，也不依赖任何其它 skill。

它是 `signal = persona × seed × judgment` 里 **WHAT + 成功标尺** 那一半：persona 供 WHO，seed 供
真实任务 + 客观 oracle。seed 与 persona **独立采集**，下游按约束配对（domain 匹配 + 能力可信 +
autonomy 适配）——配对不在本 skill、也不在 0010 本组。

> **收编说明**：本 skill 收编 NexAU 仓 `extract-harness-seed` 沉淀的既有方法（harvest 不 author /
> 两道门 / 与 held-out 解耦），但**只引本仓契约、不拷贝 NexAU 的 skill 文件**。契约以本仓
> `seed-card-schema.md` 为准。

## 核心原则（本源特异，其余引契约铁律）

1. **Harvest，不 author（本源的立身之本）**：只从**已解决**的真实制品取卡。真实世界那次解决
   *即* 沉淀好的 oracle——转录它，别发明。fix PR 新增的回归测试是理想 oracle（FAIL@parent →
   PASS@fix，即 SWE-bench 配方，但施于**非 benchmark** 实例）。见契约铁律 #2。
2. **capability-first**：只保留压测某个**distinct** harness 能力的卡（契约 §capability 分类法）。
   库的对象是**分类法覆盖度**，不是任务堆。从 *修复揭示* 的真实所需去标 `capability_probed`。
3. **两道门缺一不可**：oracle 门（成功须 harness-独立且可判）+ harbor 可复现门（可确定性搭环境跑
   oracle）。门细则、oracle 分层、可复现分层一律见契约 §两道门原则。不过门 → 出**被拒卡**
   （`{reject_reason, action}`），不入库。
4. **保留真实诉求原貌**：`task.prompt` 保留用户原话与规格层级（欠规格 / 含糊 / 缺上下文都保留），
   不 sanitize 成干净 spec。见契约铁律 #4。
5. **非 benchmark + 与当前 bug 解耦**：绝不采 held-out benchmark 实例（契约铁律 #3）；也不据 harness
   *当前已知* bug 采卡（否则过拟合今日失败而非泛化能力）。
6. **FACT 转录 / JUDGMENT 判定**：`repo_at`/`test_cmd`/`not_in_benchmark`/`resolution_quote`/urls
   逐字转录工具输出或由命令派生（**绝不发明**——错的 fact 会静默让 oracle 反转或不跑）；
   `task.prompt`/`domain`/`capability_probed`/`difficulty`/`scope`/`oracle.tier` 按准则判定。

## harvest 流水线

```
Seed harvest progress:
- [ ] 选目标：(domain → 其锚点仓) × (一个欠覆盖的 capability)
- [ ] 找一个 RESOLVED 制品（closed issue + merged fix PR / accepted answer）——不是 benchmark 实例
- [ ] 抽 task：自然诉求（保留 messiness）+ 最小 context
- [ ] 从解决制品 harvest oracle；分层；记 reference_solution 与 resolution_quote
- [ ] 搭 env spec：base_image、repo@parent-commit（真实 SHA）、setup、test_cmd、external_deps、budget
- [ ] oracle 门：成功是否 harness-独立且可判？
- [ ] harbor 可复现门：能否在 budget 内确定性搭环境 + 跑 oracle？
- [ ] 校准 difficulty/scope/autonomy_required；设 pairing_constraints；产出契约形状的卡
```

来源类型词表、oracle / repro 分层表、difficulty/scope 校准、harvest mechanics（发现 query、
`repo_at` 求法、`not_in_benchmark` 机检、`external_deps` 读法、reproduce-once）与三个范例
（admit / reject / rubric）见 [reference.md](reference.md)。枚举 / domain 词表 / 卡形状 / 两道门 /
held-out 存放约定见 [`../seed-card-schema.md`](../seed-card-schema.md)。

## 完成时报告

报告：这张卡填的 `(domain × capability)` 格、oracle tier、harbor 可复现 tier、difficulty。宁可**显式
拒**（oracle-less 或不可复现，出被拒卡）也不要 admit 一张无法产出可归因、可运行信号的卡。
