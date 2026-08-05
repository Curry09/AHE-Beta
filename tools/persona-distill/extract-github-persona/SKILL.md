---
name: extract-github-persona
description: >-
  Extract behavior-first personas of real developers from their GitHub footprint
  (public repos, issues, and PRs) to drive simulated users of a coding-agent
  harness. Use when building or expanding the user-agent persona library at the
  competent/expert end, extracting a persona from a GitHub user or issue-reporter,
  or auditing observed-source persona authenticity. Emits the shared persona card
  defined in ../card-schema.md (the single public contract); this skill is one
  thin "spoke" among the observed-behavior spokes (Stack Overflow) and the
  self-report spoke. GitHub is an OBSERVED source: it reliably grounds only the
  capability (D1) and domain/stack (D5) axes; the attitude axes (D2 acceptance,
  D4 trust, D6 autonomy, D7 time temperament — and most of D3) are NOT visible
  in a footprint and default to injected priors. The authenticity gate is a
  trace-floor + cross-layer-consistency check, not a performative-content check.
  Spec-0037/T5 spoke alignment (D7 inject; on_offtrack ⊥ tempo).
  Read the 「局限与缺陷」section before treating any single card's attitude axes as real.
---

# Extract GitHub Persona

一个**薄抽取 skill（spoke）**：从开发者的**公开 GitHub 足迹**（repos / issues / PRs）抽 persona，
供 coding-agent harness 的模拟用户使用。卡的 schema / 枚举 / D5 词表 / 注入分布 / 真实性裁决词表
一律来自唯一公共契约 [`../card-schema.md`](../card-schema.md)，本文件只写**「从 GitHub 足迹这类
**观测型**来源提取、可靠 ground 哪几维」**这一来源特异性，不内嵌 schema，也不依赖任何其它 skill。

> **命名**：源 skill 名为 `extract-cc-user-persona`（"cc" 指这些 persona 将驱动的 Claude Code /
> Codex 式 harness），但**真实抽取来源是 GitHub 足迹**——故本仓收编时改名 `extract-github-persona`，
> 与 `extract-<source>-persona` 约定对齐。

它与 `extract-stackoverflow-persona`（同为观测型，读求助者）、`extract-selfreport-persona`（自述型，
读本人怎么说自己的工作流）互补。GitHub 读的是 **一个人做了什么**——看得到其代码能力与技术栈，
**看不到** 他如何驾驭 agent、有多信它、验收线画在哪、**干等多久受得了**。故 GitHub 只可靠 ground
**D1（能力）与 D5（领域/栈）**；态度/交互轴 **D2/D4/D6/D7（及多数 D3）** 在足迹里基本沉默，
**默认 inject 并标 `confidence: low`**（见下「局限与缺陷」）。

## 核心原则（相对自述型 spoke 的反转）

1. **工具无关，只建模「这个人是谁、怎么工作」。** 绝不从「人们如何用 AI 助手」取材，绝不纳入
   AI 生成痕迹。persona 建模的是人，agent 是实验时才递到他手里的。
2. **观测即事实，但只覆盖 D1/D5。** GitHub 是 `observed` 源：能 ground 的维标 `basis: "observed"`
   （看其所做，硬证据）。但它**只观测得到能力/领域**——不要把「从 CVE 卫生 / auto-merge / CI 齐全
   反推信任或验收」当 grounded，那是评审外推，不是转录事实（见原则 4）。
3. **计数与星标一文不值。** issue/PR/repo 数、stars、followers 皆可刷。判断实质、永不看量。高 volume
   是**污染提示**而非质量信号：唯当实质深且**单域一致**才 authentic；高量 + 不连贯跨栈 = `contaminated`。
4. **态度轴默认 inject，不从行为反推 grounded。** D4 信任、D7 等待气质、以及**缺一手陈述的 D2 验收**
   默认 `source: injected` / `confidence: low`——**仅当足迹里有本人一手的信任/验收/等待陈述**才
   `grounded`（basis `stated`）。这与 `extract-selfreport-persona`「自述是 D4/D7 真人锚」立场对齐。
5. **grounds D1/D5（`observed`）；D2/D3/D4/D6/D7 默认 injected。** 见下表与 reference.md。
6. **维度正交——永不从一维派生另一维。** 与 card-schema.md 铁律 #3 同。**尤其不要**从 PR/commit 速度、
   issue 关闭速度反推 `impatient`；不要把 `on_offtrack=fix-self`（本人提交修复）与 `patient` 焊死——
   二者独立注入/ground。
7. **同一 schema，剥 PII。** 产出 card-schema.md 定义的卡形状（D1–D7 + `authenticity` + `era` +
   `provenance`）；句柄 hash 进 `id`，只存派生画像；公开原话 + 来源 ref 作 `evidence_quotes`。绝不存
   name/employer/location/email/social。

## GitHub 可靠 ground 哪几维（自述型源的镜像互补）

| Dim | GitHub 强度 | 从（足迹）ground | basis / source |
|-----|-------------|------------------|----------------|
| **D1 evaluation_capability** | **强（可验证）** | issue body 的技术深度（精确 repro / 根因推理）+ PR 的真实实质（真逻辑修复 vs docs/版本 bump） | `grounded` / `observed` |
| **D5 domain** | **强**（area+depth+stack） | repos/PR 的实际技术 → `area`（受控词表）+ `stack`（具体技术）；`depth` 从实质 | `grounded` / `observed` |
| **D3 interaction_style** | 弱→多为 injected | 仅 delegation 可从 issue 写法**弱观测**；on_offtrack=`fix-self` 唯当**本人真的提交了修复 PR**才 `observed`（质量失败策略，≠等待）；supervision=过程卷入，足迹基本观测不到 → inject | 有真实行为痕迹→`observed`，否则 `injected` |
| **D2 acceptance_bar** | 弱→默认 injected | 仅当 issue/PR 里有**本人一手验收陈述**才 `grounded`（basis `stated`） | 有一手陈述→`grounded`/`stated`，否则 `injected` |
| **D4 trust_model** | 无→默认 injected | 观测不到「他有多信 agent」 | 有一手陈述→`grounded`/`stated`，否则 `injected` |
| **D6 autonomy_expectation** | 无→默认 injected | 观测不到「他期望 agent 扮什么」 | `injected` |
| **D7 time_temperament** | 无→默认 injected | 足迹几乎看不到「干等多久受得了」；**禁止**从 PR 量/提交频率派生 | `injected`（极罕一手等待陈述才 `stated`） |

`era` 取 `owner.created_at` + 活动日期（约 2025-10 切分），在 `era.basis` 引日期。
**injected 维不带 `basis`**——`basis` 只描述「已 ground 值如何取证」（observed/stated），注入是评审先验、无转录基。

## 工作流：L0–L5 递归取证管线

```
GitHub persona extraction progress:
- [ ] L-1 recruitment (可选)  → 挑一个目标 profile → priority domain + pool（recruitment/）
- [ ] L0 profile             → 身份骨架 + era 标注（created_at）
- [ ] L1 repos (all)         → 技术指纹 + 产出模式（证据）
- [ ] L2 key repo contents   → 工程标准（tsconfig/CI/tests/release）——注意：这是行为，非本人验收陈述
- [ ] L3 cross-project issue bodies → D1 深度信号；仅当有一手验收陈述才 ground D2
- [ ] L4 cross-project PRs    → D1 能力 + D5 实质；on_offtrack=fix-self 若本人真的提交修复
- [ ] L5 gate → (a) trace-floor，再 (b) 跨层一致性 → 裁决
- [ ] Map: D1/D5 grounded(observed)；D2/D4/D6/D7（+ 多数 D3）inject 并标 low（除非有一手陈述）
      ——D7 与 on_offtrack 独立采样，勿从 PR 速度派生 impatient
- [ ] 剥 PII，hash id，产出 card-schema.md 卡形状（须含 D7_time_temperament）
```

返回 0 结果的层（0 repos / 0 PRs）**不是** grounding 层——不要写进 `provenance.layers`。
L-1（招募）解耦且可选：见 [`recruitment/`](recruitment/)（`domains.md` 域登记 +
`swe-bench.md` / `terminal-bench.md` 两个 profile）。profile 只决定 *看谁*，不决定卡怎么评级。

GitHub endpoints、D1/D5 取证细则、真实性门（trace-floor + 跨层一致性）细则、态度轴注入、三个范例
（authentic / contaminated / insufficient_evidence）见 [reference.md](reference.md)。枚举 / D5 词表 /
注入分布 / 卡形状 / 真实性裁决词表见 [`../card-schema.md`](../card-schema.md)。

## 局限与缺陷（观测型方法的内容质量边界）

GitHub 足迹是**观测型**来源，须诚实记录其内容质量边界——单张卡的态度轴**不忠于真人的"态度"**：

- **只有 D1（能力）× D5（领域/栈）由一手观测可靠支撑。** 驱动体感的**态度/交互轴 D2/D3/D4/D6/D7**
  （验收、过程卷入、信任、自主、**等待气质**）在足迹里**是注入先验或从行为外推**——GitHub 观测不到
  「他有多信 agent、验收线画在哪、干等多久受得了」。
- **推断跨度过大不可靠。** 把信任/验收/自主/等待从外部行为反推（CVE 卫生 → skeptical、
  PR 很快 → impatient）是脆弱外推。故这些轴一律降 `injected`；**态度与等待气质的真人锚必须来自
  `extract-selfreport-persona`**。
- **来源偏差：GitHub 偏公开活跃、builder-skew。** 低文化度多数低于 trace-floor，应路由到 SO。
- **使用边界：这类卡适合铺 D1×D5 覆盖网格。** **不要**拿它的 D2/D4/D6/D7 当真人态度/等待锚——
  那些是逐卡采样的先验。

（此段与 card-schema.md「真实性优先」一致：ground 不了的轴宁可标 injected/low，也不假装观测到了态度。）

## 完成时报告

报告：哪些维 GitHub-grounded（`observed`；或罕见的一手陈述 `stated`）vs injected、真实性裁决、
行为预测。明确**拒绝** contaminated / insufficient_evidence。若在某 recruitment profile 下抽取，另报
`priority_domain` 桶。**切记**：本源的 D2/D4/D6/D7 多为注入先验——报告里如实标注。
