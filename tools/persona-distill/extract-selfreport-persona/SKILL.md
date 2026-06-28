---
name: extract-selfreport-persona
description: >-
  Extract behavior-first personas of real AI-coding practitioners from their
  long-form FIRST-PERSON self-disclosure (personal blogs, interview / podcast
  transcripts, conference talks, build-in-public tweet-threads). Use when building
  the user-agent persona library and you need the attitude/interaction axes
  (acceptance bar, interaction style, trust, autonomy) grounded rather than
  injected, or when you need high-fidelity anchor personas to calibrate the
  dimension scales. Emits the shared persona card defined in
  ../card-schema.md (the single public contract); this skill is one thin "spoke"
  among future observed-behavior spokes (GitHub / Stack Overflow). Self-report
  inverts those: the source is STATED behavior, so it grounds exactly the
  D2/D3/D4/D6 axes observed sources can only inject; the authenticity gate targets
  performative/promotional/second-hand content instead of a trace floor; and
  discovery is per-subject (seed list + search), not crawlable — this is the
  anchor-B source, not a bulk sampler.
---

# Extract Self-Report Persona

一个**薄抽取 skill（spoke）**：从 AI-coding 实践者的**第一人称长篇自述**（个人博客、访谈/播客
逐字稿、大会演讲、build-in-public 长推）抽 persona。卡的 schema / 枚举 / D5 词表 / 注入分布 /
真实性门词表一律来自唯一公共契约 [`../card-schema.md`](../card-schema.md)，本文件只写**「从自述这类来源
提取、ground 哪几维」**这一来源特异性，不内嵌 schema，也不依赖任何其它 skill。

它与未来的观测型 spoke（GitHub 足迹、Stack Overflow）互补：那些读 **一个人做了什么**，看不到
*他如何驾驭 agent、有多信它*——只能 **inject** D3/D4（连带 inject D2）。本 skill 读 **一个人怎么说
自己的 AI-coding 工作流**——博客/访谈/演讲——正是人们articulate其验收门槛、读 diff 习惯、信任立场、
期望 agent 做多少的地方。所以 self-report **grounds D2/D3/D4/D6**，补上观测源缺的行为轴。

代价诚实：这是 **stated**（自述，有自我报告偏差）而非 observed；来源偏向**两极**（名人专家 + 翻车爆款），
中间薄；发现**不可规模化**（没有"博过自己工作流的人"的可查索引）。故其角色：**anchor B**——少量高保真卡，
校准维度刻度、当 gold-standard 范例——与 bulk 采样（dev.to / HN）配对，不替代它们。

## 核心原则（相对观测型 spoke 的反转）

1. **第一人称 + 具体工作流，否则不取。** 来源必须是本人用具体细节描述**自己的**流程（读 diff 吗？卡住时怎么办？
   什么算完成？）。拒绝第三方转述、关于他的 listicle、无工作流细节的观点文——它们 ground 不了行为。去找一手源。
2. **标 `stated`，别假装 observed。** 每个从自述 ground 的维度在 provenance 里带 `basis: "stated"`，
   且 **`confidence` 封顶 `medium`**，除非有观测痕迹佐证（则升 `high` + `basis: "stated+observed"`）。
   这是观测型源的反面——那里证据 *就是* 行为。规则细节见 card-schema.md「`stated` → confidence 规则」。
3. **门猎的是表演与激励，不是 trace floor。** 失败模式是 **promotional**（卖课/带货，激励驱动、低信号）、
   **second-hand**（非本人原话）、**AI-spam**（SEO 流水文、过度均匀、零具体个人细节）。真实第一人称的夸张
   （"我总是 Accept All"）作为**立场是真实的**——抽出立场、标 `stated`，不要拒。门词表见 card-schema.md。
4. **交叉核验能力（D1）声明。** 自称"专家"而无佐证产出，`D1 confidence` 最多 `medium`；当本人可独立佐证
   （知名维护者、公开项目）则升 `high` + `basis: "stated+observed"`。
5. **grounds D2/D3/D4/D6；D1/D5 为 medium。** 见 reference.md 表。这是观测型源的镜像互补——三类源合起来
   六轴皆「有观测或自述硬证据」，且 self-report 是唯一能 ground 信任轴(D4) 的。
6. **同一 schema，可合并；剥 PII。** 产出 card-schema.md 定义的卡形状（6 维 + `authenticity` + `era` +
   `provenance`）。句柄 hash 进 `id`，只存派生画像；公开原话 + 来源 URL 作 `evidence_quotes`。
7. **维度正交——永不从一维派生另一维。** 与 card-schema.md 铁律 #3 同；本源恰是其证明：一个
   `expert` 同时 `over-trust` + `Accept-All`（vibe 模式的 Karpathy）真实且常见。不要让高 D1 把 D2/D4
   拉向严谨——每轴从自己的原话 ground。

## self-report 强 ground 哪几维（观测型源的镜像互补）

| Dim | self-report 强度 | 从（自述）ground |
|-----|------------------|------------------|
| **D2 acceptance_bar** | **强** | 他称为"完成/够好"的、他 ship 的、他 state 的门槛（"大致能用" vs "我能证明它对"） |
| **D3 interaction_style** | **强** | 显式工作流：怎么 prompt（vibe-dump vs spec）、读不读 diff（supervision）、卡住时做什么（on_offtrack） |
| **D4 trust_model** | **强** | 显式信任陈述（"我不再读 diff" → over-trust；"不会提交我解释不了的代码" → skeptical） |
| **D6 autonomy_expectation** | **强** | 期望 agent **是**什么（"它也是建造者" → agentic；"打字助手" → advisory） |
| **D1 evaluation_capability** | medium（stated；佐证） | 他如何描述自己的判断 + 任何可验证产出；无佐证封顶 `medium` |
| **D5 domain** | medium | stated 领域/栈 + 佐证项目；`weak` 常从自认盲区 ground |

`era` 取来源**发布日期**（约 2025-10 切分）。多数 vibe-coding 自述天然 `post_vibe`；在 `era.basis` 里引日期。

## 工作流

```
Self-report persona extraction progress:
- [ ] L-1 recruitment (optional): 从 seed 列表/搜索配方 (recruitment/seeds.md) 选一个目标
      （具名实践者，或搜第一人称帖）
- [ ] L0 source intake: 收集本人**第一人称长篇**（博客/逐字稿/演讲/长推）；记每条 {url, type, date}
- [ ] L1 gate: 第一人称 + 具体工作流？否 → promotional / second-hand / ai-spam / insufficient → 不入（去找一手）
- [ ] L2 quote mining: 抽原话 → 映射 D2/D3/D4/D6（强）、D1/D5（medium）
- [ ] L3 stated/observed: 每个 grounded 维标 basis:"stated"；尽量佐证 D1/D5；纯 stated 封顶 medium
- [ ] 只对来源确实沉默的轴 inject（这里少见）；标 low
- [ ] 剥 PII，hash id，产出 card-schema.md 卡形状
```

来源类型词表、门细则、`stated`→confidence 规则、发现/seed 配方、四个范例（两个入库极点、正交案例、一个被拒营销）
见 [reference.md](reference.md)。枚举 / D5 词表 / 注入分布 / 卡形状 / 真实性门词表见 [`../card-schema.md`](../card-schema.md)。

## 完成时报告

报告：哪些维 grounded（`stated` vs `stated+observed`）vs injected、真实性裁决、行为预测（一句话：该 persona 如何用
harness、什么驱动其体感）。明确**拒绝** promotional / second-hand / AI-spam，而非降级。因这是 anchor-B，另注该卡
锚定了哪个**维度刻度极点**（如"over-trust / ship-fast 极端"），让库知道它填了哪个校准格。
