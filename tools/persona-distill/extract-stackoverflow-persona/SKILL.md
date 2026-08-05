---
name: extract-stackoverflow-persona
description: >-
  Extract behavior-first personas of low-literacy / newcomer / blind users from
  Stack Overflow to fill the segment the GitHub footprint spoke cannot reach. Use
  when building the user-agent persona library and needing blind/surface-tier or
  web/data-analysis personas, or when sourcing "stuck help-seeker" user types.
  Emits the shared persona card defined in ../card-schema.md (the single public
  contract); this skill is one thin "spoke" among the observed-behavior spokes
  (GitHub) and the self-report spoke. Stack Overflow is an OBSERVED source: it
  reliably grounds D1 (capability, at the low end) and D5 (domain/stack from tags),
  plus D3 delegation weakly from the question text; the attitude axes (D2 acceptance,
  D4 trust, D6 autonomy, D7 time temperament) are NOT visible and default to
  injected priors. The authenticity gate is INVERTED vs a trace floor — messy
  newbie questions are authentic; over-polished AI-formatted questions from
  competent askers are the ones to reject. Spec-0037/T5 spoke alignment
  (D7 inject; on_offtrack ⊥ tempo).
  rep≈1 accounts are suspect. Read the 「局限与缺陷」section before treating any
  single card's attitude axes as real.
---

# Extract Stack Overflow Persona

一个**薄抽取 skill（spoke）**：从 **Stack Overflow** 抽低文化度 / newcomer / blind 用户的 persona，
填 `extract-github-persona`（读富足迹的 builder，expert-skewed，且在 trace-floor **拒**低文化度大多数）
够不着的段。卡的 schema / 枚举 / D5 词表 / 注入分布 / 真实性裁决词表一律来自唯一公共契约
[`../card-schema.md`](../card-schema.md)，本文件只写**「从 SO 求助帖这类**观测型**来源提取、可靠 ground
哪几维」**这一来源特异性，不内嵌 schema，也不依赖任何其它 skill。

Stack Overflow 是「**自己解不了才来问**」的地方，故提问者人群**本身就是** blind / surface / newcomer
段。本 skill 唯一职责：**填低文化度 + web/data-analysis 配额**，产出同一卡契约以并入一库。它与
`extract-github-persona`（同为观测型，读富足迹 builder）、`extract-selfreport-persona`（自述型，读态度与等待气质）
互补。

## 核心原则（相对 GitHub 观测型 spoke 的反转）

1. **仅补位——本 skill 只出 `blind`/`surface`。** 瞄准低端 + GitHub 薄的域（web/frontend、data-analysis、
   初学脚本）。`competent`/`expert` 提问者**出范围**：隔离（`action: out-of-scope, route to GitHub skill`），
   **不要**当 `surface` 收。*卡住 ≠ 低文化度*——能干的 dev 卡在冷门 bug 仍是 competent。
   **competent tells（任一成立即非 surface）**：给出精确 expected/actual、贴干净 MRE、对已知良基复现、
   已自建 workaround、隔离出多个失败案例、问精确机制/边界问题。surface = 能描述问题但浅、复制粘贴导向、无根因推理。
2. **无 trace floor（反转）。** GitHub 上低 trace → `insufficient_evidence`；这里**低 reputation / 单条卡住的
   提问本身就是 persona 信号**——rep≈1 用户问真新手问题就是一张完整可入库的 `blind` 卡。
3. **真实性门反转。** *凌乱的*新手问题是 **authentic**（真卡住的人就这样）；红旗是反面：rep≈1 / 全新账号
   发**过度光洁、AI 格式化的问题**（模板分节、`id=` 围栏、深主题 ⊥ 低 rep）→ `suspect`/`contaminated`。
4. **态度轴（D2/D4/D6/D7）默认 `injected`。** 求助者极少暴露验收线、信任模型或等待气质——inject 并标
   `confidence: low`。SO 可靠 ground **D1、D5**（+ D3 delegation 弱观测）。
5. **能力（D1）别超置信。** 单帖 + reputation **不足以** `blind@high`——rep 与问题质量是弱信号，
   **D1 grounded 封顶 `confidence: medium`**（basis `observed`）。别把「rep=1 + 一段 traceback」当 high。
6. **同一 schema，剥 PII。** 产出 card-schema.md 卡形状（D1–D7 + `authenticity` + `era` + `provenance`）；
   每个 grounded 值需问题原话 + URL；丢弃 display name / 任何真实身份字段。
7. **维度正交——永不从一维派生另一维、永不按档锁死注入维。** 与 card-schema.md 铁律 #3 同。
   **尤其**：发完消失 → on_offtrack 可弱观测 `abandon`，但**禁止**因此锁死 `impatient`——D7 独立注入。

## SO 可靠 ground 哪几维（GitHub 观测型的镜像）

| Dim | SO 强度 | 从（问题）ground | basis / source |
|-----|---------|------------------|----------------|
| **D1 evaluation_capability** | **强（低端）** | `owner.reputation` + 问题质量；**封顶 medium** | `grounded` / `observed` / **≤medium** |
| **D5 domain** | **强**（area+stack） | `tags` → `area` + `stack`；`weak` 低端多 `injected` 或 `[]` | `grounded` / `observed` |
| **D3 interaction_style** | delegation 弱观测 | 问题=委派写法；有评论跟进→过程卷入/质量失败弱观测，否则 inject | delegation 有文本→`observed`，其余多 `injected` |
| **D2 acceptance_bar** | 无→`injected` | 至多从"接受第一个能跑的"弱推 | `injected` / `low` |
| **D4 trust_model** | 无→`injected` | 从盲复制被采纳答案弱推 | `injected` / `low` |
| **D6 autonomy_expectation** | 无→`injected` | 从措辞弱推（"就给我 X" = advisory；"帮我自动化" = agentic） | `injected` / `low` |
| **D7 time_temperament** | 无→`injected` | 求助帖几乎无等待气质；**禁止**从「发完消失」派生 impatient | `injected` / `low` |

`era` 取 `owner.creation_date`（约 2025-10 切分）；全新账号常见且欢迎——同填 blind 与 `post_vibe` 缺口。
**injected 维不带 `basis`**——`basis` 只描述已 ground 值如何取证（此处 `observed`）。

## 工作流

```
SO persona extraction progress:
- [ ] 挑目标缺口（tier + domain）——可从某 recruitment profile 的 pools.stackoverflow tags
      （见 ../extract-github-persona/recruitment/）
- [ ] 找候选提问者（低 rep + 目标 tags / blind-phrase 搜索）
- [ ] 拉提问者 profile（rep, creation_date, answers given, tags）——**记录 `reputation`**
- [ ] 读问题 body（D1, D5 + era；delegation 弱观测）
- [ ] Tier 门：若 D1 读作 competent/expert（见 competent tells）→ 隔离 out-of-scope，停
- [ ] SO 真实性门（一致性 + AI-光洁检查；无 trace floor）
- [ ] Map: D1(≤medium)/D5 grounded(observed)、delegation 有文本则 observed；
      D2/D4/D6/D7 inject(low，不锁死；on_offtrack ⊥ D7)
- [ ] 剥 PII，hash id，产出 card-schema.md 卡形状（须含 D7_time_temperament）
```

Stack Exchange API、targeting 配方、门细则、注入、两个范例（入库 blind / 拒 AI 光洁）见
[reference.md](reference.md)。枚举 / D5 词表 / 注入分布 / 卡形状 / 真实性门词表见
[`../card-schema.md`](../card-schema.md)。

## 局限与缺陷（观测型方法的内容质量边界）

SO 是**观测型**来源，须诚实记录其内容质量边界——单张卡的态度轴**不忠于真人的"态度"**：

- **只有 D1（能力）× D5（领域/栈）由一手观测支撑（且 D1 仅 ≤medium）。** 态度/交互轴
  **D2/D3/D4/D6/D7** 在一条求助帖里**是注入先验/外推**——SO 观测不到验收线、信任、自主、**等待气质**。
- **来源偏差最强：SO 偏「卡住来问的人」。** 极易撞雷同刻板卡（每张都成 blind×vibe-dump×over-trust×impatient）。
  故注入维必须逐卡真抽、批后查克隆（含 D7 ⊥ on_offtrack）。
- **推断跨度过大不可靠。** 「发完消失」至多弱推 on_offtrack=`abandon`，**不得**锁死 D7=`impatient`。
  态度与等待气质真人锚须来自 `extract-selfreport-persona`。
- **使用边界：铺 D1×D5 覆盖网格的低端行。** **不要**拿它的 D2/D4/D6/D7 当真人锚。

（此段与 card-schema.md「真实性优先」一致。）

## 完成时报告

报告：填的缺口（tier + domain + era）、哪些维 grounded（`observed`）vs injected、真实性裁决。明确**拒绝**
AI 光洁/不连贯问题；competent/expert 提问者路由回 GitHub。**切记**：本源的 D2/D4/D6/D7 为注入先验、
D1 仅 ≤medium——报告里如实标注。
