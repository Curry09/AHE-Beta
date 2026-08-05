# Reference: GitHub Persona Extraction

<!-- Spec-0037/T5: D7 默认 inject；禁从 PR 速度派生 impatient；枚举只引用 hub -->

GitHub 足迹的取证方法（按维）、trace-floor + 跨层一致性真实性门、态度轴注入、endpoint 速查、
三个范例、招募 profile。实际抽取时读本文件。

维度**枚举、`D5.area` 受控词表、注入分布、卡形状、真实性裁决词表**一律在唯一公共契约
[`../card-schema.md`](../card-schema.md)。本文件只写 GitHub 这类**观测型**来源**不同**的部分。

## 1. 按维从 GitHub 足迹 ground

GitHub 是 `observed` 源：能 ground 的维带 `basis: "observed"`。**它只可靠观测得到 D1/D5**；
态度轴（D2/D4/D6/D7 + 多数 D3）默认 `injected`（见 §3）。

### D1 evaluation_capability — *强（可验证）*
`blind | surface | competent | expert`（枚举见 card-schema.md）
- **从（GitHub）ground：** issue body 的技术深度（精确 repro、根因推理）+ PR 的真实实质
  （真逻辑修复 vs docs/版本 bump）。读 diff 意图，不读计数。
- blind = 无代码痕迹；surface = 出 app 但从不审深度；competent = 真 bug 修复；
  expert = 维护库 / 深跨模块修复。**标 `grounded` / `basis: "observed"`。**

### D5 domain — *强（area+depth+stack）*
`{area, depth, stack, weak}`；`area` 取 card-schema.md 受控词表（单 token）。
- **从（GitHub）ground：** repos/PR 的实际技术 → `area` + `stack`（具体技术数组，如 `["typescript","node"]`）；
  `depth ∈ {shallow|working|deep}` 从实质。`weak` = 有效能力降一档的子域，从证据 ground（明显回避/做错的域），
  否则 inject 0–2 或 `[]`。**标 `grounded` / `basis: "observed"`。**
- `area` 判定：看**这个库*是*什么**，不看它*恰好被谁用*（消歧见 recruitment/domains.md）。

### D2 acceptance_bar — *弱 → 默认 injected*
`primary ∈ {ship-fast|functional|modern-correct|type-safety-purist}`，`flags ⊆ {tests,types,scope,security,style,a11y,perf}`
- **默认 `injected`。** repo 里 CI/tests/strict-tsconfig 存在与否是**行为**，不等于本人陈述的验收线——
  不要据此标 grounded（那是从产出反推态度）。
- **例外（可 grounded）：** 仅当 issue/PR 里有**本人一手的验收陈述**（明说其标准，如
  "我不会合并没测试的改动"、"任何 `any` 都不可接受"）→ `grounded` / `basis: "stated"`，且**每个 flag
  各需一条对应 quote**（无 quote 的 flag 丢弃，勿凑）。纯自述封顶 `confidence: medium`（见 card-schema.md
  「`stated` → confidence 规则」）。

### D3 interaction_style — *弱 → 多为 injected*
`delegation ∈ {vibe-dump|loose|spec-driven}`，`supervision ∈ {hands-off|reviews|micromanage}`，`on_offtrack ∈ {abandon|retry|correct|fix-self|file-issue}`
（语义：supervision=过程卷入；on_offtrack=质量失败策略，**不驱动等待耐心**——见 card-schema.md。）
- **delegation：** 可从 issue 写法**弱观测**（极简一句 → `vibe-dump`；模板化带 repro → 偏 `spec-driven`）；
  有清晰痕迹→ `grounded` / `observed`（confidence 保守），否则 inject。
- **on_offtrack：** `fix-self` 唯当**本人真的提交了修复 PR**（真实行为，`observed`）；`file-issue` 唯当
  真写了结构化 bug 报告。否则 inject。**不要**把「提交很快」读成 impatient——那是 D7。
- **supervision：** GitHub 观测不到「他对 **agent 进行中**要不要可见感」→ 默认 `injected` / `low`。

### D7 time_temperament — *无 → 默认 injected*
`patient | steady | impatient`
- **默认 `injected` / `low`。** 足迹几乎看不到「干等多久受得了」。
- **禁止**从 PR/commit 频率、issue 关闭速度、贡献量反推 `impatient` 或 `patient`。
- **禁止**与 on_offtrack 锁死（fix-self ≠ patient；abandon ≠ impatient）。走契约注入分布，独立采样。
- **例外：** 仅当有本人一手等待陈述（极罕，如 issue 里明说「我等半小时就放弃」）才 `grounded` / `stated`。
  等待气质真人锚由 `extract-selfreport-persona` 提供。

### D4 trust_model — *无 → 默认 injected*
`over-trust | balanced | skeptical`
- **默认 `injected` / `confidence: low`。** GitHub 观测不到「他有多信 **agent**」。
- **不要** 从 CVE 卫生 / auto-merge / 审查习惯反推 grounded——那是脆弱外推（原则 4）。
- **例外：** 仅当有本人一手信任陈述（罕见）才 `grounded` / `stated`。信任轴的真人锚由
  `extract-selfreport-persona` 提供。

### D6 autonomy_expectation — *无 → 默认 injected*
`advisory | collaborative | agentic`
- GitHub 观测不到「他期望 agent 扮什么」→ 默认 `injected` / `low`。有 automation 强依赖（CI/CD/bots/
  "automate …"）可作**弱先验**偏置采样，但仍标 injected。

## 2. 真实性门（trace-floor + 跨层一致性）

观测型源的门是 **trace-floor + 一致性**（与自述型的 performative/promotional 门相反；裁决词表见 card-schema.md）。
先跑 Step 1（floor）再跑 Step 2（consistency），都在 map 维之前。

| 裁决 | 触发 | 动作 |
|------|------|------|
| `insufficient_evidence` | 低于取证下限：自有 repos + 真实 PR + 已诊断 issue 合计 < ~3，尤其 0 repo 且 0 PR | **不入库**；路由到非 GitHub 源（此类型——blind newcomer、vibe user——活在 GitHub 之外） |
| `authentic` | 浅层信号（profile/repos）⇄ 深层信号（issue/PR 实质）跨 **≥2 个非空层**一致 | 入库（D1/D5 标 `observed`） |
| `contaminated` | 学习者浅层 ⊥ 专家深层 PR；不可信的跨栈速度；AI 格式痕迹（`id=` 围栏、过度模板化） | **隔离，永不入** |
| `suspect` | 部分/含糊 | 隔离待人工 |

`authentic` 需 **≥2 个非空层**——返回 0 结果的层永不计入 grounding。永不把 `contaminated`→`authentic`，
也永不靠注入补齐把 `insufficient_evidence`→`authentic`。
**volume 检查**：大计数（1000+ PR）是污染提示；唯当深实质**单域一致**才过；跨不相干栈的高量 → `contaminated`。

## 3. 态度轴注入（本源默认——D2/D4/D6/D7 + 多数 D3）

GitHub 观测不到态度轴与等待气质。当某轴确实沉默时，从 **card-schema.md「受控注入分布」逐卡独立采样**
（与已 grounded 的 D1/D5 正交），置 `source: "injected"` / `confidence: "low"`（注入维**不带 basis**）。

- 具体比例（delegation / supervision / on_offtrack / trust_model / autonomy / **time_temperament** / D5.weak）
  见 card-schema.md，不在此重列（轮辐式：契约是唯一真源）。
- **正交强制**：`on_offtrack` ⊥ `time_temperament`——禁止「fix-self 必配 patient」或「abandon 必配 impatient」。
- 有弱先验时偏置采样（自称 vibecoder → over-trust + vibe-dump；库维护者 → 偏 spec-driven）——但**仍标 injected**；
  **弱先验不得用于 D7**（无可靠足迹信号）。
- **采样，不按档锁死（强制）**：逐卡真实抽一次，不是从 D1 确定性映射。若每张 `surface` 卡都成
  `ship-fast+over-trust+hands-off`，就是锁死了——重抽。批后目测分布是否塌缩。

## 4. GitHub endpoint 速查

```
GET /users/{u}                                              # L0 profile (created_at→era, bio)
GET /users/{u}/repos?sort=pushed&per_page=100               # L1 langs, own/fork ratio, themes
GET /repos/{owner}/{repo}/contents                          # L2 tsconfig/CI/tests/CHANGELOG/release（行为，非验收陈述）
GET /repos/{owner}/{repo}/contents/{path}                   #    钻具体文件
GET /search/issues?q=author:{u}+type:issue&sort=created     # L3 issue bodies → D1 深度；一手验收陈述才 ground D2
GET /search/issues?q=author:{u}+type:pr&sort=created        # L4 PR 实质 → D1, D5；本人提交修复 → on_offtrack=fix-self
```
注：`/search/issues` 返回 `body`/`title`/`repository_url`——读 body，不只看标题。Search API 未认证限流低，
规模化需认证。**剥每个 PII 字段**（`name`、`company`、`location`、`email`、`blog`、`twitter_username`）。

## 5. 范例（观测型：D1/D5 grounded observed，态度轴 injected）

### A — authentic（入库）
句柄经 L0–L4 深挖；浅层（14 年老兵、TS bio）⇄ 深层（维护 134★ 类型安全 DI 库，Turborepo +
release-please；105 issue 带精确 TS repro；246 PR 含手动 CVE backport）。**一致 → authentic。**
D1/D5 由足迹 grounded(`observed`)；D2 有一条**一手验收陈述** quote → grounded(`stated`, medium)；
on_offtrack=fix-self 由**真实提交的 PR** grounded(`observed`)；delegation 由 issue 写法弱观测；
**D4 信任 / D6 自主 / supervision / D7 等待气质 无一手证据 → injected(`low`)**（旧版从 CVE 卫生推 skeptical 的写法已删）。
D7 与 fix-self **独立**——勿因本人修 PR 就标 patient。

```json
{
  "id": "gh-example-a",
  "authenticity": "authentic",
  "era": {"value": "pre_vibe", "basis": "account created 2012-08; first repos 2013"},
  "dimensions": {
    "D1_evaluation_capability": {"value": "expert", "source": "grounded", "basis": "observed", "confidence": "high"},
    "D2_acceptance_bar": {"primary": "type-safety-purist", "flags": ["types"], "source": "grounded", "basis": "stated", "confidence": "medium"},
    "D3_interaction_style": {
      "delegation": {"value": "spec-driven", "source": "grounded", "basis": "observed", "confidence": "medium"},
      "supervision": {"value": "reviews", "source": "injected", "confidence": "low"},
      "on_offtrack": {"value": "fix-self", "source": "grounded", "basis": "observed", "confidence": "medium"}
    },
    "D4_trust_model": {"value": "balanced", "source": "injected", "confidence": "low"},
    "D5_domain": {"area": "dev-tooling", "depth": "deep", "stack": ["typescript","node"], "weak": ["timezones/DST"], "source": "grounded", "basis": "observed", "confidence": "high"},
    "D6_autonomy_expectation": {"value": "collaborative", "source": "injected", "confidence": "low"},
    "D7_time_temperament": {"value": "steady", "source": "injected", "confidence": "low"}
  },
  "provenance": {
    "layers": ["L0","L1","L2","L3","L4"],
    "evidence_quotes": [
      {"quote": "skipLibCheck ... not a long term solution; I don't accept any implicit any in this codebase", "source": "github.com/.../issues/11552"},
      {"quote": "backport esbuild 0.28.1 ... fixes GHSA", "source": "github.com/.../issues/NNNNN"},
      {"quote": "I'm willing to submit a PR", "source": "github.com/.../issues/MMMMM"}
    ]
  },
  "behavioral_prediction": "Gives precise constrained tasks, submits his own fix when the agent stalls; 低体感 on any/implicit-magic (his one STATED standard). 其信任/自主/等待气质为注入先验，非观测所得——真人信任与 D7 锚须由 selfreport 提供。"
}
```

### B — contaminated（拒）
浅层：2024 账号、leetcode/hackathon repos、bio "continuously learning"。深层：80 PR 深修 redis
sentinel、oxc（Rust）语义绑定、strapi 竞态；一条 issue 带 `id=` 围栏。**学习者浅层 ⊥ 跨栈专家速度 +
AI 格式 → contaminated。**

```json
{
  "id": "gh-example-b",
  "authenticity": "contaminated",
  "reject_reason": "cross-layer contradiction: learner profile vs Rust/redis expert PRs; AI-format issue; implausible velocity",
  "action": "isolated, not admitted to persona library"
}
```

### C — insufficient_evidence（拒）
0 public repos、0 PR、账号 2024-08、仅一条 issue（"BUILD: issue loading the python library" — 一段
ipython traceback，无诊断）。低于 trace-floor → 一致性检查无从跑；D2/D3/D4 会 ~100% 注入。
**拒为 `insufficient_evidence`，不入库。**

```json
{
  "id": "gh-example-c",
  "authenticity": "insufficient_evidence",
  "reject_reason": "0 repos, 0 PRs, 1 undiagnosed issue — below trace floor; cannot ground D1/D5; gate cannot run",
  "action": "not admitted; route this user type (blind newcomer) to Stack Overflow / off-GitHub sourcing"
}
```

反模式（本门要拦的）：把近空账号标 `authentic`、维多为注入、`provenance.layers` 列空层（`L1`,`L4`）。
该 *类型*（blind traceback-paster newcomer）对多样性有价值，但**不能从空 GitHub 账号诚实抽出**——
交 `extract-stackoverflow-persona` / 初学者论坛。

## 6. 源-产物分工（三方）

| 来源 | spoke | observed vs stated | 可靠 grounds | 最适合 |
|------|-------|--------------------|--------------|--------|
| **GitHub footprint** | **extract-github（本 skill）** | **observed** | **D1, D5** | builder personas，expert/competent 端；D1×D5 覆盖网格 |
| Stack Overflow | extract-stackoverflow-persona | observed | D1, D5（+ delegation 弱观测） | blind/surface 求助者 |
| blogs / interviews / talks | extract-selfreport-persona | stated | D2, D3, D4, D6, D7 | 态度/交互/等待气质锚；**唯一能可靠 ground D4 与 D7** |
| dev surveys (SO/JetBrains) | (weights) | aggregate | distribution | 采样权重 |

三类抽取 spoke 互补：没有单一源 ground 全轴，但**每轴都被至少一个源观测或自述 ground**。
关键分工：**观测型源（GitHub/SO）ground 能力/领域，自述型源 ground 态度与等待气质**——别指望观测型给出真 D7。

## 7. 招募 profile（可插拔——L0 前挑）

域覆盖是**库级**目标，与逐卡抽取**解耦**：绝不为凑目标弯折某卡的 D5。recruitment profile 只指引
*下一个去抽谁*。profile 是 [`recruitment/`](recruitment/) 下的插件文件，换/加一个不碰核心 skill。

一个 profile 声明：
- `priority_domains` — 该目标须覆盖的 D5 受控词表子集
- `pools` — **多源**：`github`（repos / skill-profiles）供本 skill，`stackoverflow`（tags）供
  `extract-stackoverflow-persona`。一份 profile、同批域、D1 两端：GitHub 填 expert/competent，SO 填 blind/surface。
- 跨贡献者阶梯招募（core maintainer → drive-by reporter）的规则，避免填一个域时把 D1 塌到 expert。

可用 profile：
- [`recruitment/swe-bench.md`](recruitment/swe-bench.md) — 库 / 源码编辑类域（Python）
- [`recruitment/terminal-bench.md`](recruitment/terminal-bench.md) — ops / systems / CLI 类域
- [`recruitment/domains.md`](recruitment/domains.md) — 域登记（每个受控词表 token 的锚 repos + 消歧）

消费方式：挑下一个欠填的 `priority_domain` → 去其 pool → 取一个 issue-reporter/贡献者 → 照常跑
**L0–L5 + 门**。卡按自身实质入库；profile 只决定 *看谁*。若卡 `D5.area` 落在 `priority_domains` 外，
标 **off-target**（可凭实质入库，但不计入该目标覆盖）；也别堆已满的域。

## 8. 库分布纪律（库才是真正的对象）

单卡只是样本；驱动正确、可泛化的 harness 改进的是**卡的分布**逼近真实使用人群。故判库、不只判卡：
- **格覆盖**：要紧的格是 `D1 tier × D5 domain`（在目标 `priority_domains` 内）。每个在意的格需 **≥ ~3–5 卡**
  才让其体感均值是信号。GitHub 占 `competent`/`expert` 行；SO 占 `blind`/`surface` 行。
- **边际平衡**：任一轴无单值主导（若 80% 卡是 `infra-devops` 或 `surface`，覆盖已聚簇 → 补薄格）。
- **克隆检查**：批后查注入轴（D2/D3/D4/D6/D7）。若某档塌到一种组合（每张 `surface` = 同一组合，或
  `abandon` 总配 `impatient`），即锁死 → 重抽（§3）。
- **可用 ≠ 计数**：可用是联合门——计数达标 **且** 边际平衡 **且** 过克隆检查。
