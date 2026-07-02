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
  D4 trust, D6 autonomy — and most of D3) are NOT visible in a footprint and
  default to injected priors. The authenticity gate is a trace-floor +
  cross-layer-consistency check, not a performative-content check. Read the
  「局限与缺陷」section before treating any single card's attitude axes as real.
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
读本人怎么说自己的工作流）互补：三者合起来六轴皆「有观测或自述硬证据」。GitHub 读的是 **一个人
做了什么**——看得到其代码能力与技术栈，**看不到** 他如何驾驭 agent、有多信它、验收线画在哪。故
GitHub 只可靠 ground **D1（能力）与 D5（领域/栈）**；态度轴 **D2/D4/D6（及多数 D3）** 在足迹里
基本沉默，**默认 inject 并标 `confidence: low`**（见下「局限与缺陷」）。

## 核心原则（相对自述型 spoke 的反转）

1. **工具无关，只建模「这个人是谁、怎么工作」。** 绝不从「人们如何用 AI 助手」取材，绝不纳入
   AI 生成痕迹。persona 建模的是人，agent 是实验时才递到他手里的。
2. **观测即事实，但只覆盖 D1/D5。** GitHub 是 `observed` 源：能 ground 的维标 `basis: "observed"`
   （看其所做，硬证据）。但它**只观测得到能力/领域**——不要把「从 CVE 卫生 / auto-merge / CI 齐全
   反推信任或验收」当 grounded，那是评审外推，不是转录事实（见原则 4）。
3. **计数与星标一文不值。** issue/PR/repo 数、stars、followers 皆可刷。判断实质、永不看量。高 volume
   是**污染提示**而非质量信号：唯当实质深且**单域一致**才 authentic；高量 + 不连贯跨栈 = `contaminated`。
4. **态度轴默认 inject，不从行为反推 grounded。** D4 信任、以及**缺一手陈述的 D2 验收**默认
   `source: injected` / `confidence: low`——**仅当足迹里有本人一手的信任/验收陈述**（如 issue 里明说
   "我不会合并没测试的 PR"、"任何 `any` 都不可接受"）才 `grounded`（basis `stated`）。这与
   `extract-selfreport-persona`「自述是唯一能 ground 信任轴 D4 的源」立场对齐：观测型源观测不到态度。
5. **grounds D1/D5（`observed`）；D2/D3/D4/D6 默认 injected。** 见下表与 reference.md。这是自述型源的
   镜像互补——那里态度轴是强项，这里能力/领域是强项。
6. **维度正交——永不从一维派生另一维。** 与 card-schema.md 铁律 #3 同：一个 `expert` 同时
   `over-trust` / `ship-fast` 真实且常见。**尤其不要让高 D1 把 D2/D4 拉向严谨**——这正是原则 4 存在的理由。
7. **同一 schema，剥 PII。** 产出 card-schema.md 定义的卡形状（6 维 + `authenticity` + `era` +
   `provenance`）；句柄 hash 进 `id`，只存派生画像；公开原话 + 来源 ref 作 `evidence_quotes`。绝不存
   name/employer/location/email/social。

## GitHub 可靠 ground 哪几维（自述型源的镜像互补）

| Dim | GitHub 强度 | 从（足迹）ground | basis / source |
|-----|-------------|------------------|----------------|
| **D1 evaluation_capability** | **强（可验证）** | issue body 的技术深度（精确 repro / 根因推理）+ PR 的真实实质（真逻辑修复 vs docs/版本 bump） | `grounded` / `observed` |
| **D5 domain** | **强**（area+depth+stack） | repos/PR 的实际技术 → `area`（受控词表）+ `stack`（具体技术）；`depth` 从实质 | `grounded` / `observed` |
| **D3 interaction_style** | 弱→多为 injected | 仅 delegation 可从 issue 写法**弱观测**（模板/极简）；on_offtrack=`fix-self` 唯当**本人真的提交了修复 PR**（真实行为）才 `observed`；supervision 观测不到 | 有真实行为痕迹→`observed`，否则 `injected` |
| **D2 acceptance_bar** | 弱→默认 injected | 仅当 issue/PR 里有**本人一手验收陈述**（明说其标准）才 `grounded`（basis `stated`）；repo 里 CI/tests 存在与否是行为、不等于本人陈述的验收线 | 有一手陈述→`grounded`/`stated`，否则 `injected` |
| **D4 trust_model** | 无→默认 injected | 观测不到「他有多信 agent」。除非有一手信任陈述，否则 **inject**（原则 4） | 有一手陈述→`grounded`/`stated`，否则 `injected` |
| **D6 autonomy_expectation** | 无→默认 injected | 观测不到「他期望 agent 扮什么」。inject | `injected` |

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
- [ ] Map: D1/D5 grounded(observed)；D2/D4/D6（+ 多数 D3）inject 并标 low（除非有一手陈述）
- [ ] 剥 PII，hash id，产出 card-schema.md 卡形状
```

返回 0 结果的层（0 repos / 0 PRs）**不是** grounding 层——不要写进 `provenance.layers`。
L-1（招募）解耦且可选：见 [`recruitment/`](recruitment/)（`domains.md` 域登记 +
`swe-bench.md` / `terminal-bench.md` 两个 profile）。profile 只决定 *看谁*，不决定卡怎么评级。

GitHub endpoints、D1/D5 取证细则、真实性门（trace-floor + 跨层一致性）细则、态度轴注入、三个范例
（authentic / contaminated / insufficient_evidence）见 [reference.md](reference.md)。枚举 / D5 词表 /
注入分布 / 卡形状 / 真实性裁决词表见 [`../card-schema.md`](../card-schema.md)。

## 局限与缺陷（观测型方法的内容质量边界）

GitHub 足迹是**观测型**来源，须诚实记录其内容质量边界——单张卡的态度轴**不忠于真人的"态度"**：

- **只有 D1（能力）× D5（领域/栈）由一手观测可靠支撑。** 这两轴看得见、可验证（真代码、真修复、
  真技术栈）。驱动体感的**态度轴 D2/D3/D4/D6**（验收线、交互风格、信任、自主期望）在足迹里
  **是注入先验或从行为外推**——GitHub 观测不到「他有多信 agent、验收线画在哪、期望 agent 扮什么」。
- **推断跨度过大不可靠。** 把内在心理特质（信任/验收/自主）从外部行为反推（如「CVE 卫生 → skeptical」、
  「auto-merge → over-trust」）是脆弱的外推：一个测试齐全的维护者对 **agent** 的信任可能恰恰相反。
  故这些轴一律降 `injected`；**态度轴的真人锚必须来自 `extract-selfreport-persona`**。
- **来源偏差：GitHub 偏公开活跃、builder-skew 的人群。** 有丰富足迹的多是 expert/competent 端建造者；
  低文化度/求助者多数**低于 trace-floor 被拒**（应路由到 `extract-stackoverflow-persona`）。故 GitHub
  单用会把库 D1 分布拉向高端，需与 SO 端配对填 blind/surface。
- **使用边界：这类卡适合铺 D1×D5 覆盖网格。** 用 GitHub 卡钉「哪个域 × 哪个能力档」的覆盖格；
  **不要**拿它的 D2/D4/D6 当真人态度锚——那些是逐卡采样的先验，只保证分布不塌缩，不保证单卡忠实。

（此段与 card-schema.md「真实性优先」一致：ground 不了的轴宁可标 injected/low，也不假装观测到了态度。）

## 完成时报告

报告：哪些维 GitHub-grounded（`observed`；或罕见的一手陈述 `stated`）vs injected、真实性裁决、
行为预测（一句话：该 persona 如何用 harness、什么驱动其体感）。明确**拒绝** contaminated /
insufficient_evidence，而非降级。若在某 recruitment profile 下抽取，另报该卡填了哪个 `priority_domain`
桶（供库覆盖度追踪）。**切记**：本源的 D2/D4/D6 多为注入先验——报告里如实标注，勿声称观测到了态度。
