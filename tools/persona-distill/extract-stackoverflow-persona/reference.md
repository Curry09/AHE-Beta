# Reference: Stack Overflow Persona Extraction

Stack Exchange API 事实、targeting 配方、反转真实性门、态度轴注入、两个范例。实际抽取时读本文件。

维度**枚举、`D5.area` 受控词表、注入分布、卡形状、真实性裁决词表**一律在唯一公共契约
[`../card-schema.md`](../card-schema.md)。本文件只写 SO 这类**观测型**来源**不同**的部分。

## 1. Stack Exchange API (v2.3) 事实

- Base `https://api.stackexchange.com/2.3/`；**必带 `site=stackoverflow`**。
- **Auth（2026-06 变更）：** key/token 不再走 query params，走 header `Authorization: Bearer {KEY_OR_TOKEN}`。
  匿名低量可用；app key 提配额到 10k/day（stackapps.com 注册）。
- **Bodies：** 加 `filter=withbody`（默认省略 `*.body`）。
- **限流：** ≤30 req/s/IP；遵守 `backoff` 字段；`pagesize≤100`；匿名只能翻到 ~25 页；勿 <1min 重复语义相同请求。
- **Wrapper 字段：** 查 `has_more`、`quota_remaining`、`backoff`、`error_*`。

### Endpoint 速查
```
GET /questions?site=stackoverflow&tagged={tag}&sort=creation&filter=withbody&pagesize=50  # askers + bodies + tags + owner.reputation
GET /search/advanced?site=stackoverflow&q={phrase}&filter=withbody                        # blind-phrase 搜索
GET /users/{ids}?site=stackoverflow                                                       # reputation, creation_date, badge_counts
GET /users/{id}/questions?site=stackoverflow&filter=withbody                              # 问题历史
GET /users/{id}/answers?site=stackoverflow                                               # 0 answers + 低 rep = 纯消费者/新手
GET /users/{id}/tags?site=stackoverflow                                                  # 领域足迹
```
问题上的关键 per-item 信号：`owner.reputation`、`owner.user_id`、`owner.creation_date`、`tags`、`score`、
`answer_count`、`is_answered`、`view_count`、`body`。**`owner.reputation` 是最便宜的文化度探针。**

## 2. targeting blind / newcomer 提问者

- 按 **`owner.reputation` 低（≤ ~50）** + 近期 `creation_date` 过滤。
- 瞄 **GitHub 薄的域**（`tagged`）：`reactjs`/`next.js`/`html`/`css`（web）、`pandas`/`numpy`/`dataframe`
  （data-analysis）、`python`+beginner、`excel`/`vba`。
- Blind-phrase `search/advanced?q=`："why doesn't it work"、"how do i"、"not working"，及贴生 traceback 无诊断的。
- 交叉核验：`users/{id}/answers` 返回 ~0 + 低 rep = 纯求助者。
- 关闭/被踩问题是新手信号——但筛掉 spam/作业农场。

## 3. D1 从 reputation + 问题质量（**封顶 medium**）

- **blind**：rep ≈ 1–20；贴 error / "不行"；无 MRE；无诊断。
- **surface**：中等 rep；能*描述*问题但浅；复制粘贴导向；**无根因推理**。
- **competent / expert**：任一 **competent tell** 成立 → **出范围，隔离**
  （`action: out-of-scope, route to GitHub skill`）；绝不为收编而重标 `surface`。
  competent tells：精确 expected/actual；干净 MRE；对已知良基复现；已自建 workaround；隔离多个失败案例；
  精确机制/边界问题。*卡住 ≠ 低文化度*。

**每卡在 `provenance` 记 `owner.reputation`**——最便宜的文化度探针、D1 主要 ground（连同问题质量）。
`D1` 标 `grounded` 却无记录的 reputation 即不符合。**且 D1 grounded 封顶 `confidence: medium`**：单帖 +
rep 是弱信号，不足以 high；basis `observed`。

## 4. D3 从问题风格

- **delegation**：生代码+error dump、"就让它能跑" → `vibe-dump`；部分上下文 → `loose`；带 expected/actual 的
  干净 MRE → `spec-driven`（此处罕见，真的话可以）。delegation 从**实际问题文本**观测 → `grounded` /
  `basis: "observed"`（confidence 保守，单帖），不由档决定。
- **supervision / on_offtrack**：回应澄清评论/迭代 → `reviews` / `retry`；发完就消失 → `hands-off` / `abandon`。
  **无评论线程 → `injected`。** `file-issue`（卡住时写结构化报告）在 blind/surface 端**罕见**——只在问题本身
  读起来像刻意 bug 报告时才给。

## 5. 态度轴注入（本源默认——D2/D4/D6）

求助者极少暴露验收线或信任模型。从 **card-schema.md「受控注入分布」逐卡采样**，置 `source: "injected"` /
`confidence: "low"`（注入维**不带 basis**）：

- 具体比例见 card-schema.md（不在此重列——轮辐式：契约是唯一真源）。
- **SO 弱先验（blind-leaning）**：低端人群可偏置采样——接受第一个能跑的答案 → 偏 over-trust；
  "帮我全自动化不用我管" → 偏 agentic；"怎么写 X" → 偏 advisory。但**仍标 injected / low**。
- **D5.stack** 从 `tags` grounded（具体 tag → stack 数组），非注入。
- **D5.weak** 低端多 `[]`（blind 用户整栈皆浅，单个"弱子域"少加信号）；仅当问题露明显盲点才注 1 个。
- **采样，不按档锁死（强制）**：逐卡独立抽，别让每张 `surface` 都成 `functional+balanced+reviews+retry`、
  每张 `blind` 都成 `ship-fast+over-trust+hands-off`。批后查 spread；某注入维在一档塌成单值即锁死了——重抽。
  （SO 的自选择偏差使雷同刻板卡风险**最高**，见 SKILL.md 局限段——克隆检查在这里尤为关键。）

## 6. 反转真实性门（SO 特异）

**无 trace floor。** 单条连贯问题 + 低 rep 即可入库一张 `blind` 卡——低 trace 是目标，不是缺陷。

| 裁决 | 触发 | 动作 |
|------|------|------|
| `authentic` | 真诚、*凌乱的*卡住-人类问题；rep ⇄ 主题深度一致（低 rep ⇄ 新手主题） | 入库 |
| `contaminated` | rep≈1/新账号发过度光洁 AI 格式问题（模板分节、`id=` 围栏）；rep≈1 ⊥ 深专家主题 | 隔离，不入 |
| `suspect` | 作业农场 / spam / 含糊 | 隔离 |

凌乱是好的。这里的危险与 GitHub 相反：不是假专家 PR，而是**AI 生成/复制粘贴的问题**——对其背后账号显得太干净。

## 7. 卡 schema（同公共契约）

产出 card-schema.md 定义的**同一卡形状**，以便三个 spoke 并入一库：嵌套维带 inline `source`+`basis`+`confidence`，
单值维用键 `value`，`era` 为 `{value, basis}`，`provenance.evidence_quotes` 为 `{quote, source}`。完整符合性规则
（含 **`D5.area` = 单一受控词表 token**、grounded 维须有 evidence_quote、injected 维 confidence=low）见 card-schema.md。

SO 特异：`era.basis` = `owner.creation_date`；`evidence_quotes` = 问题 body 片段 + 问题 URL；
`provenance.layers` 用 SO 层，如 `["SO-profile","SO-questions"]`；**`provenance` 须含提问者 `reputation`**
（如 `"reputation": 1`）。卡也带 `D6_autonomy_expectation`（默认 `injected`，从措辞弱推）。

## 8. 范例 A — authentic blind newcomer（入库）

rep 1、账号 2025-12、tags `[python, pandas]`，问题贴 `KeyError` traceback 问"为啥不行"无隔离。
一张卡填 **blind + post_vibe + data-analysis** 缺口。D1 blind grounded(`observed`) 但**封顶 medium**
（单帖 + rep=1 是弱信号）；D5 grounded(`observed`)；delegation grounded(`observed`) 从问题文本；
**D2/D4/D6/supervision/on_offtrack 注入(`low`)**（无 basis）。

```json
{
  "id": "so-3f2a1c9d",
  "authenticity": "authentic",
  "era": {"value": "post_vibe", "basis": "owner.creation_date 2025-12"},
  "dimensions": {
    "D1_evaluation_capability": {"value": "blind", "source": "grounded", "basis": "observed", "confidence": "medium"},
    "D2_acceptance_bar": {"primary": "ship-fast", "flags": [], "source": "injected", "confidence": "low"},
    "D3_interaction_style": {
      "delegation": {"value": "vibe-dump", "source": "grounded", "basis": "observed", "confidence": "medium"},
      "supervision": {"value": "hands-off", "source": "injected", "confidence": "low"},
      "on_offtrack": {"value": "abandon", "source": "injected", "confidence": "low"}
    },
    "D4_trust_model": {"value": "over-trust", "source": "injected", "confidence": "low"},
    "D5_domain": {"area": "data-analysis", "depth": "shallow", "stack": ["python","pandas"], "weak": [], "source": "grounded", "basis": "observed", "confidence": "high"},
    "D6_autonomy_expectation": {"value": "advisory", "source": "injected", "confidence": "low"}
  },
  "provenance": {
    "layers": ["SO-profile","SO-questions"],
    "reputation": 1,
    "evidence_quotes": [
      {"quote": "i get KeyError and i dont know why it doesnt work, here is my code", "source": "stackoverflow.com/q/NNNNNN"}
    ]
  },
  "behavioral_prediction": "Pastes the error and asks 'why doesn't it work'; can't judge a fix, runs whatever the agent gives and accepts it if it stops erroring. 其信任/验收/自主为注入先验，非观测所得。"
}
```

## 9. 范例 B — AI 光洁、可疑（拒）

rep 1、账号 2026-01，但问题完美模板化（Description / Repro / Expected / Actual 分节、`id=` 围栏）且问
深 Rolldown-RSC 构建内幕。**rep≈1 ⊥ 专家主题 + AI 格式 → contaminated。**

```json
{
  "id": "so-9b7e22a1",
  "authenticity": "contaminated",
  "reject_reason": "rep≈1 account ⊥ deep RSC-internals topic; AI-format question (templated sections, id= code fences)",
  "action": "isolated, not admitted"
}
```

## 10. 库中的角色 + 招募

本 skill 存在是为**填低端**：`blind`/`surface` 档 + GitHub 薄的域（web/frontend、data-analysis、初学脚本）+
`post_vibe` newcomer。别在此收专家。对着库配额表用——精确拉 GitHub 产不出的 tier×domain 格。

**可插拔招募（解耦、可选）。** 要填*某 benchmark* 域的低端，消费 `extract-github-persona` 用的同一批
recruitment profile——它们多源且带 `pools.stackoverflow` **tag** 列：

- `../extract-github-persona/recruitment/swe-bench.md`
- `../extract-github-persona/recruitment/terminal-bench.md`

读 profile 的 `pools.stackoverflow` 表，再瞄那些 tag 下的**低 rep 提问者**。一份 profile、D1 两端：
GitHub 填 expert/competent，本 skill 填 blind/surface，同批 `priority_domains`。profile 只决定 *搜哪些 tag*；
卡仍按 SO 真实性门（§6）评级。

**分布纪律**（与 GitHub spoke 共享，见 `../extract-github-persona/reference.md` §8）：SO 占
`D1 tier × D5 domain` 覆盖网格的 `blind`/`surface` 行；判库看格覆盖 + 边际平衡 + 克隆检查，不看原始计数。
