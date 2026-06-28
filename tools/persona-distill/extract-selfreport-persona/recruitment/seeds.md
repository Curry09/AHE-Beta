# Recruitment: self-report persona seeds (pluggable)

自述源的发现不能是爬虫（没有"博过自己 AI-coding 工作流的人"的可查索引）。本文件把它做成**可重复**：
一份按**维度刻度极点**组织的策选 seed 列表，加一个找新鲜第一人称材料的搜索配方。挑**欠锚定的极点**，
取下一个目标，再跑 SKILL.md L0→emit 管线 + reference.md §3 门。seed 只决定 *看谁*。

seed 是锚（anchor-B），不是样本：每极点 **1–3 张强卡** 校准刻度，然后让 bulk 采样（dev.to / HN，anchor-A）填量。

## 要锚定的极点（校准格）

按库缺什么排序。每个极点 = 一个 (D1 × D2/D4) 区域，需要一张高保真、完全 grounded 的卡钉住。

| 极点 | 目标维 | 为何重要 |
|------|--------|----------|
| **over-trust / ship-fast / non-technical** | D1 `blind`，D4 `over-trust`，D2 `ship-fast` | 纯 vibe 极端；体感 = "反正能跑" |
| **expert × over-trust（正交）** | D1 `expert`，D4 `over-trust`，D3 `hands-off` | 证明 D1 ⟂ D4；校准 能力 ≠ 严谨 |
| **务实中间** | D1 `competent`，D4 `balanced`，D2 `ship-fast` | 庞大的真实中段；ship 丑但能跑生产 |
| **skeptical / rigorous** | D1 `expert`，D4 `skeptical`，D2 `modern-correct` | agentic-engineering / TDD 纪律端 |
| **type-safety-purist** | D2 `type-safety-purist`，flags `types` | 正确性狂热验收门（仍薄） |
| **advisory-only** | D6 `advisory` | 要答案/片段，不让 agent 动手 |

## 策选 seed（按极点）

作起始目标；每个都有丰富可验证的第一人称长篇。（名字仅供 *招募*；产出卡 hash id、存派生画像 +
公开原话——见 SKILL.md 原则 #6。）

- **over-trust / ship-fast / non-technical** → 爆款"vibe 编码翻车被黑"复盘（如 EnrichLead "我被攻击了 /
  我不懂技术"长推）。认错即 grounding，由公开结局佐证。
- **expert × over-trust** → Karpathy 的出处定义 + 任何"我周末项目放手让它跑"自述。能力有佐证；立场 stated。
- **务实中间** → indie-hacker / build-in-public 访谈（如 Lex #440 与 levelsio）："ship 丑、ship 快"，单人跑生产、随手修。
- **skeptical / rigorous** → Simon Willison 博客语料 + 大会炉边；TDD / "证明过能跑的代码" / "不提交我解释不了的"。
- **type-safety-purist** → TS/Rust 正确性博主描述如何约束 agent（严类型、"无 `any`"、穷尽匹配）——用搜索配方找。
- **advisory-only** → 资深开发博"我把它当更聪明的自动补全 / 我问选项但自己写代码"——用搜索配方找。

## 搜索配方（找新鲜第一人称材料）

某极点无 seed 或想要更多时，搜——然后**读本人长篇**，别从搜索命中本身抽：

- **dev.to**（Forem API，免 key）：`GET https://dev.to/api/articles?tag=vibecoding&top=30`
  （也用 tag `ai`, `cursor`, `aiagents`）；再 `GET /api/articles/{id}` 取全文 `body_markdown`。
  留第一人称"我怎么用 / 我学到了什么"帖；丢工具广告。
- **Hacker News**（Algolia，免 key）：`GET https://hn.algolia.com/api/v1/search?query=<workflow phrase>&tags=comment`
  （如 "I never read the diffs"、"I always review"、"claude code workflow"）。高量低信噪——狠筛；顺作者找到其博客读长篇。
- **直接**：作者博客索引 / "uses" 页 / newsletter 存档常有最丰富、最具体的工作流帖。

一律过 SKILL.md / reference.md §3 门：拒 `promotional`（课程漏斗）、`second_hand`（关于某人的写作）、
`contaminated`（AI SEO 流水文）、`insufficient_evidence`（无具体怎么做细节的观点）。

## 覆盖纪律

- over-trust/blind 还没卡时，别再堆第三张 skeptical-expert——先填**薄极点**。
- 每张锚卡必须**完全 grounded**（这是 anchor-B；注入重的卡违背初衷——那种需求路由到 dev.to/HN 采样）。
- 记录每张卡锚定了哪个极点，让库与（未来观测型 spoke 的）格覆盖一起追踪校准覆盖度。
