# Reference: Self-Report Persona Extraction

来源类型词表、按维从自述 ground 的方法、performative/promotional 真实性门、`stated`→confidence 规则、
发现配方、四个范例。实际抽取时读本文件。

维度**枚举、`D5.area` 受控词表、注入分布、卡形状、真实性裁决词表**一律在唯一公共契约
[`../card-schema.md`](../card-schema.md)。本文件只写自述这类来源**不同**的部分。

## 1. 来源类型（每条来源记 `type`）

```
blog                | 个人博客 / Substack / 工程博客（第一人称）
interview-transcript| 播客或视频访谈逐字稿（Lex, Latent Space, …）
conf-talk           | 大会/峰会演讲逐字稿或纪要
tweet-thread        | X/Mastodon/LinkedIn 第一人称长推（build-in-public）
newsletter          | 作者自己的 newsletter 期号
```

全部必须**第一人称**（"这是 *我* 怎么…"）。第三方写他 = `second-hand` → 拒（找一手）。拉全文：
访谈逐字稿和长博客是工作流细节所在——略读 diff-reading / 卡住时 / 什么算完成 的段落，别只看标题。

## 2. 按维从自述 ground

self-report **反转**了观测源的 ground 图：态度/交互轴在这里是 *强* 项。从显式陈述映射、逐字引用。

### D2 acceptance_bar — *强*（这就是体感函数）
`primary ∈ {ship-fast | functional | modern-correct | type-safety-purist}`，`flags ⊆ {tests,types,scope,security,style,a11y,perf}`
- 从他 **state** 的门槛 ground。"周末扔掉的项目没那么糟"、"反正能跑" → `ship-fast`；"交付你证明过能跑的代码"、
  "不会提交我解释不了的代码" → `modern-correct` + flag `tests`。生产语境里缺 security/test 关注本身就是信号
  （Leo：`ship-fast`，无 `security` flag）。

### D3 interaction_style — *强*
`delegation ∈ {vibe-dump|loose|spec-driven}`，`supervision ∈ {hands-off|reviews|micromanage}`，`on_offtrack ∈ {abandon|retry|correct|fix-self|file-issue}`
- delegation："把侧栏 padding 减半" / 一句话出 app → `vibe-dump`；"写个函数，入 X 出 Y"、"我指定技术栈" → `spec-driven`。
- supervision："我总是 Accept All，不读 diff" → `hands-off`；"审所有生成代码"、"红绿 TDD" → `reviews`。
- on_offtrack："要它随便改到问题消失" → `retry`；"我自己上手收尾更快" → `fix-self`；放弃/关掉 → `abandon`。

### D4 trust_model — *强*
`over-trust | balanced | skeptical`
- 直接信任陈述通常很显式："AI 不再只是助手，它也是建造者" / "总是 Accept All" → `over-trust`；
  "你得担责"、"永远要验证" → `skeptical`；务实的 ship-but-watch → `balanced`。

### D6 autonomy_expectation — *强*
`advisory | collaborative | agentic`
- "它也是建造者"、"忘掉代码存在" → `agentic`；"打字助手"、"给我选项我自己整合" → `advisory`；
  "它跑测试但我审 / 我介入" → `collaborative`。

### D1 evaluation_capability — *medium，佐证*
`blind | surface | competent | expert`
- 仅自述 → 封顶 `confidence: medium`。"我不懂技术…搞不定" → `blind`（这里认错本身是强信号，`high` 也行）。
  声称 `expert`/`competent` 需佐证（知名维护者、公开项目、可验证履历）才到 `high`（`basis: "stated+observed"`）。
- ⚠️ 能力是他**能**判断什么，不是他**选择**判断什么。Karpathy 是 `expert` 但**主动**选 `hands-off`/`over-trust`——
  D1 保持在能力，把这种 opt-out 记进 D3/D4。

### D5 domain — *medium*
`{area, depth, stack, weak}`；`area` 取 card-schema.md 的受控词表。
- stated 领域/栈，由其已知项目佐证 → `medium`/`high`。`weak` 在这里常从自认盲区 **ground**（"懒得找 padding" →
  weak `web-frontend/css`；非技术创始人 → weak `security/auth`）——强的、塑造行为的信号。

## 3. 真实性门（performative / promotional / second-hand）

无 trace floor（观测型源那侧），无 AI-polish-of-a-newbie 测试。风险不同（裁决词表见 card-schema.md）：

| 裁决 / 动作 | 触发 | 动作 |
|------------|------|------|
| `authentic` | 第一人称 + 具体工作流细节；跨来源一致 | 入库（维标 `stated`） |
| 拒 — `promotional` | 卖课/工具营销、影响者"用我的方法 10x"、激励驱动；工作流只作销售话术 | 不入（激励偏置，低信号） |
| 拒 — `second_hand` | 第三方描述本人；"据…说"；无第一人称口吻 | 不入；去找一手 |
| `contaminated` | AI 生成 SEO 流水文、过度均匀分节、零具体个人细节、`id=` 标签围栏 | 隔离，永不入 |
| `insufficient_evidence` | 第一人称但无工作流细节（纯观点 vibes，无"我怎么…"） | 不入；ground 不了行为 |

**夸张不是失败。** 真实第一人称为效果夸张（"我从不读 diff"、"我总是 Accept All"）真实传达一种 *立场*——
抽出立场、标 `stated`、置 `confidence: medium`。只在内容是激励驱动（promotional）、非本人原话（second-hand）、
机器生成（contaminated）、或无细节（insufficient）时才拒。

## 4. `stated` → confidence 规则（强制）

见 card-schema.md 同名小节。要点：纯自述 grounded → `basis: "stated"` + 封顶 `medium`；有观测佐证 → `high` +
`basis: "stated+observed"`；认错弱点造假动机低可 `high`，自夸专家无佐证停 `medium`。

## 5. 注入（少见——仅对确实沉默的轴）

self-report 通常直接 ground D2/D3/D4/D6，故注入应是例外（这正是用本源的理由）。若某来源确实从不触某轴，
从 card-schema.md 注入分布抽，置 `source: "injected"` / `confidence: "low"`——且**逐卡采样，不按档锁死**。

## 6. 发现 / 招募（不可规模化那步，做成可重复）

发现不能是爬虫；做成 **seed 列表 + 搜索配方**——见 [`recruitment/seeds.md`](recruitment/seeds.md)。两条入口：

1. **策选 seed**——具名实践者，按其锚定的 *极点* 列（over-trust/ship-fast、skeptical/rigorous、non-technical/blind）。
   挑欠锚定的极点，取下一个人。
2. **搜索配方**——找新鲜第一人称帖：
   - dev.to（Forem API，免 key）：`GET https://dev.to/api/articles?tag=vibecoding&top=30`，再
     `GET /api/articles/{id}` 取全文 `body_markdown`。筛第一人称"我怎么用…"帖；跳过工具营销。
   - HN（Algolia，免 key）：`GET https://hn.algolia.com/api/v1/search?query=<workflow>&tags=comment`
     ——注意 `tags=comment` 上别加 `numericFilters=points>N`（400）。高量低信噪——用于 skeptic/senior 之声与原话，狠筛。
   - 这两者也兼任 **bulk 采样**（anchor A）；这里只用来 *找候选*，再读其本人长篇第一人称。

两条路都喂同一 L0→emit 管线，路线只决定 *看谁*。

## 7. 源-产物分工（三方）

| 来源 | spoke | observed vs stated | grounds | 最适合 |
|------|-------|--------------------|---------|--------|
| GitHub footprint | extract-github（未来薄 skill） | observed | D1, D2, D5 | builder personas，expert/competent 端 |
| Stack Overflow | extract-so（未来薄 skill） | observed | D1, D3, D5 | blind/surface 求助者 |
| **blogs / interviews / talks** | **extract-selfreport（本 skill）** | **stated** | **D2, D3, D4, D6** | **态度/交互锚；刻度校准** |
| dev surveys (SO/JetBrains) | (weights) | aggregate | distribution | 采样权重 |
| dev.to / HN bulk | (sampler A) | mixed | candidates | 广度 / 比例 |

三类抽取 spoke 互补：没有单一源 ground 全六轴，但**每轴都被至少一个源观测或自述 ground**，
而 self-report 是唯一能 ground 信任轴(D4) 的。

## 8. 范例（真实，取自公开第一人称源）

### A — authentic，skeptical/rigorous 极点（入库；有佐证 → high）
Simon Willison，跨年个人博客 + 2026 大会炉边。显式具体工作流；几十年公开可测产出佐证 → `stated+observed`。

```json
{
  "id": "selfreport-example-a",
  "authenticity": "authentic",
  "era": {"value": "post_vibe", "basis": "AI-coding essays 2024-09 → 2026-03 (agentic engineering)"},
  "dimensions": {
    "D1_evaluation_capability": {"value": "expert", "source": "grounded", "basis": "stated+observed", "confidence": "high"},
    "D2_acceptance_bar": {"primary": "modern-correct", "flags": ["tests","scope","security"], "source": "grounded", "basis": "stated", "confidence": "high"},
    "D3_interaction_style": {
      "delegation": {"value": "spec-driven", "source": "grounded", "basis": "stated", "confidence": "high"},
      "supervision": {"value": "reviews", "source": "grounded", "basis": "stated", "confidence": "high"},
      "on_offtrack": {"value": "fix-self", "source": "grounded", "basis": "stated", "confidence": "high"}
    },
    "D4_trust_model": {"value": "skeptical", "source": "grounded", "basis": "stated+observed", "confidence": "high"},
    "D5_domain": {"area": "dev-tooling", "depth": "deep", "stack": ["python","sqlite","django"], "weak": [], "source": "grounded", "basis": "stated+observed", "confidence": "high"},
    "D6_autonomy_expectation": {"value": "collaborative", "source": "grounded", "basis": "stated", "confidence": "medium"}
  },
  "provenance": {
    "sources": [
      {"url": "simonwillison.net/2025/Mar/19/vibe-coding", "type": "blog"},
      {"url": "simonwillison.net/2025/Dec/18/code-proven-to-work", "type": "blog"},
      {"url": "simonwillison.net/2026/Mar/14/pragmatic-summit", "type": "conf-talk"}
    ],
    "self_report": true,
    "evidence_quotes": [
      {"quote": "I won't commit any code to my repository if I couldn't explain exactly what it does to somebody else.", "source": "simonwillison.net/2025/Mar/19/vibe-coding"},
      {"quote": "Your job is to deliver code you have proven to work ... bundle the change with an automated test ... That test should fail if you revert the implementation.", "source": "simonwillison.net/2025/Dec/18/code-proven-to-work"},
      {"quote": "I start by saying ... 'use red-green TDD' ... the chances of you getting code that works go up so much if they're writing the test first.", "source": "Pragmatic Summit 2026-03"},
      {"quote": "it was faster for me to step in and finish the project rather than keep on trying to get there with prompts.", "source": "simonwillison.net/2025/Mar/11/using-llms-for-code"}
    ]
  },
  "behavioral_prediction": "Spec-driven skeptic: precise instructions + 'use red-green TDD', reviews every diff, takes over when it stalls. 体感 driven by whether the change ships WITH a passing test he can explain; files sharp reproducible issues; rejects untested output outright."
}
```

### B — authentic，over-trust/blind 极点（入库；非技术，认错有佐证）
Leo Acevedo / EnrichLead，2025 年 3 月第一人称帖 + 公开复盘。

```json
{
  "id": "selfreport-example-b",
  "authenticity": "authentic",
  "era": {"value": "post_vibe", "basis": "EnrichLead launch + 'under attack' posts 2025-03"},
  "dimensions": {
    "D1_evaluation_capability": {"value": "blind", "source": "grounded", "basis": "stated+observed", "confidence": "high"},
    "D2_acceptance_bar": {"primary": "ship-fast", "flags": [], "source": "grounded", "basis": "stated", "confidence": "high"},
    "D3_interaction_style": {
      "delegation": {"value": "vibe-dump", "source": "grounded", "basis": "stated", "confidence": "high"},
      "supervision": {"value": "hands-off", "source": "grounded", "basis": "stated+observed", "confidence": "high"},
      "on_offtrack": {"value": "retry", "source": "grounded", "basis": "stated+observed", "confidence": "high"}
    },
    "D4_trust_model": {"value": "over-trust", "source": "grounded", "basis": "stated", "confidence": "high"},
    "D5_domain": {"area": "web-backend", "depth": "shallow", "stack": ["cursor-generated","javascript"], "weak": ["security/auth","api-keys"], "source": "grounded", "basis": "stated+observed", "confidence": "high"},
    "D6_autonomy_expectation": {"value": "agentic", "source": "grounded", "basis": "stated", "confidence": "high"}
  },
  "provenance": {
    "sources": [
      {"url": "x.com/leojr94_ (archived) 2025-03-17", "type": "tweet-thread"},
      {"url": "vibegraveyard.ai/story/enrichlead-vibe-coded-saas-shutdown", "type": "blog"}
    ],
    "self_report": true,
    "evidence_quotes": [
      {"quote": "my saas was built with Cursor, zero hand written code. AI is no longer just an assistant, it's also the builder.", "source": "x.com/leojr94_ 2025-03-17"},
      {"quote": "guys, i'm under attack ... random things are happening ... I'm not technical so this is taking me longer that usual to figure out.", "source": "x.com/leojr94_ 2025-03-19"},
      {"quote": "When he tried to use Cursor to fix the problems, the AI 'kept breaking other parts of the code.'", "source": "vibegraveyard.ai/.../enrichlead"}
    ]
  },
  "behavioral_prediction": "One-line production-grade dumps, zero review, treats AI as 'the builder'. 体感 high as long as 'it works tho' (even while insecure / fabricating data); cannot detect or articulate real problems; on failure emits panicked vague reports ('random things happening'), not structured issues; abandons when unfixable."
}
```

### C — 正交案例（expert × over-trust — 别让 D1 拉动 D4）
vibe 模式的 Karpathy（"vibe coding"一词的出处推文）。能力 `expert`，但**主动** `hands-off` + `over-trust`。
这是核心原则 #7 的标准证明，也是为何 `card_to_persona()`（spec-0006/T2）必须用 grounded 的 D2/D4
**覆盖** harness 的 `derive_trust(expert)=skeptical` / `derive_d3(expert)=rigorous`——否则这个真实人物会被
模拟成他自己的反面。

```json
{
  "id": "selfreport-example-c",
  "authenticity": "authentic",
  "era": {"value": "post_vibe", "basis": "coined 'vibe coding' 2025-02-02"},
  "dimensions": {
    "D1_evaluation_capability": {"value": "expert", "source": "grounded", "basis": "stated+observed", "confidence": "high"},
    "D2_acceptance_bar": {"primary": "ship-fast", "flags": [], "source": "grounded", "basis": "stated", "confidence": "high"},
    "D3_interaction_style": {
      "delegation": {"value": "vibe-dump", "source": "grounded", "basis": "stated", "confidence": "high"},
      "supervision": {"value": "hands-off", "source": "grounded", "basis": "stated", "confidence": "high"},
      "on_offtrack": {"value": "retry", "source": "grounded", "basis": "stated", "confidence": "high"}
    },
    "D4_trust_model": {"value": "over-trust", "source": "grounded", "basis": "stated", "confidence": "high"},
    "D5_domain": {"area": "ml-ai", "depth": "deep", "stack": ["python","pytorch"], "weak": ["web-frontend/css"], "source": "grounded", "basis": "stated", "confidence": "medium"},
    "D6_autonomy_expectation": {"value": "agentic", "source": "grounded", "basis": "stated", "confidence": "medium"}
  },
  "provenance": {
    "sources": [{"url": "x.com/karpathy 2025-02-02 (transcribed via simonwillison.net / pragmaticengineer.com)", "type": "tweet-thread"}],
    "self_report": true,
    "evidence_quotes": [
      {"quote": "I 'Accept All' always, I don't read the diffs anymore. When I get error messages I just copy paste them in with no comment, usually that fixes it.", "source": "x.com/karpathy 2025-02-02"},
      {"quote": "I ask for the dumbest things like 'decrease the padding on the sidebar by half' because I'm too lazy to find it.", "source": "x.com/karpathy 2025-02-02"},
      {"quote": "Sometimes the LLMs can't fix a bug so I just work around it or ask for random changes until it goes away. It's not too bad for throwaway weekend projects.", "source": "x.com/karpathy 2025-02-02"}
    ]
  },
  "behavioral_prediction": "Fire-and-forget vibe-dumper who CAN judge but opts out: one-line requests, accepts everything unread, retries/works-around on failure. 体感 high while it 'mostly works' and ships fast; gives vague feedback despite expert capability. Demonstrates D1 ⟂ D3/D4."
}
```

### D — 被拒，promotional（不入库）
一个"vibe-coding 教练"博客，每篇都漏斗到付费课程；"工作流"是编号销售漏斗（"我的 5 步法 10x"），
无具体 diff/test/卡住 细节，重 CTA。激励驱动且无细节。

```json
{
  "id": "selfreport-example-d",
  "authenticity": "suspect",
  "reject_reason": "promotional: course-funnel content, incentive-biased, no concrete first-person workflow (no diff-reading / when-stuck / acceptance specifics)",
  "action": "not admitted; re-source from non-incentivized first-person material"
}
```
