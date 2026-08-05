# Persona Card Schema — 唯一公共契约 (hub)

<!-- Spec-0037/T3: D7 time_temperament + supervision/on_offtrack 语义注记；与 0006/T1 轮辐契约并存演进 -->

> 本文件是 persona 蒸馏侧的 **唯一 source-agnostic 公共契约**。所有「薄抽取 skill」（spoke，
> 如 `extract-selfreport-persona/`、`extract-github-persona/` / `extract-stackoverflow-persona/`）
> 只描述「从某类来源提取 + ground 哪几维」，**枚举 / 词表 / 卡形状 / 注入分布 / 真实性门原则一律引用本文件**，
> 彼此不依赖。契约改一处，全员生效；加新来源只是新增一个薄 skill，不碰别人。
>
> 对应 spec：`docs/specs/0006-persona-pipeline.md`（T1 采集、T2 注入 sim）；人轴语义演进见
> `docs/specs/0037-persona-time-temperament-reframe.md`（D7 / 过程卷入 / 质量失败 ⊥ 等待）。
> 卡 → sim `dimensions.Persona` 的注入映射归 `0006/T2` + `0037/T4`（`card_to_persona`），不在本契约内。

## 铁律

1. **轮辐式**：本文件是 hub，抽取 skill 是 spoke。spoke 只依赖本契约，**spoke 之间彼此不依赖**
   （杜绝 skill→skill 引用与多副本 schema 漂移）。
2. **证据或弃**：每个 grounded 维度都要能追到一条 `evidence_quotes`；ground 不了就 inject，并降置信。
3. **维度正交**：D1–D7 相互独立，**永远不要从一维派生另一维**（含 `on_offtrack` ⊥ `time_temperament`）。
   一个 `expert` 同时 `over-trust` / `Accept-All` 是真实且常见的（见 selfreport reference 例 C /
   Karpathy）；不要让高 D1 把 D2/D4 拉向严谨。
4. **不引入 benchmark / 轨迹派生字段**：卡只装「从真实数据采集到的画像」，不得掺入任何 benchmark 分数、
   轨迹特征或下游 sim 的派生量（保证训练信号真实、与测试目标不互污染）。

## 卡记录形状 (card record)

一条卡是一个 JSON 对象：

```json
{
  "id": "<source-hash>",               // 句柄/来源 hash，存派生画像，不存 PII
  "authenticity": "authentic",          // 真实性裁决，见 §真实性门
  "era": {"value": "post_vibe", "basis": "<日期/依据>"},
  "dimensions": {
    "D1_evaluation_capability": {"value": "...", "source": "...", "basis": "...", "confidence": "..."},
    "D2_acceptance_bar":        {"primary": "...", "flags": ["..."], "source": "...", "basis": "...", "confidence": "..."},
    "D3_interaction_style": {
      "delegation":  {"value": "...", "source": "...", "basis": "...", "confidence": "..."},
      "supervision": {"value": "...", "source": "...", "basis": "...", "confidence": "..."},
      "on_offtrack": {"value": "...", "source": "...", "basis": "...", "confidence": "..."}
    },
    "D4_trust_model":           {"value": "...", "source": "...", "basis": "...", "confidence": "..."},
    "D5_domain":                {"area": "...", "depth": "...", "stack": ["..."], "weak": ["..."], "source": "...", "basis": "...", "confidence": "..."},
    "D6_autonomy_expectation":  {"value": "...", "source": "...", "basis": "...", "confidence": "..."},
    "D7_time_temperament":      {"value": "...", "source": "...", "basis": "...", "confidence": "..."}
  },
  "provenance": {
    "layers": ["L0", "..."],            // 可选：观测型来源的取证层（GitHub）
    "sources": [{"url": "...", "type": "..."}],  // 可选：自述型来源清单
    "self_report": true,                 // 可选：是否第一人称自述
    "reputation": "...",                 // 可选：可独立佐证的公开声誉
    "evidence_quotes": [{"quote": "...", "source": "..."}]
  },
  "behavioral_prediction": "<一句话：该 persona 如何用 harness、什么驱动其体感>"
}
```

被拒卡（未入库）形状：

```json
{"id": "...", "authenticity": "suspect|contaminated|insufficient_evidence",
 "reject_reason": "...", "action": "not admitted; ..."}
```

### 每维封套 (per-dimension envelope)

除 D2（用 `primary` + `flags`）、D3（三个子轴各自封套）、D5（结构化 `area/depth/stack/weak`）外，
每维携带统一四元：

- `value`（或 D2 的 `primary`+`flags`）：取值，见下方枚举。
- `source`：`grounded`（有证据）| `injected`（无证据、采样补）。
- `basis`：`observed`（看其所做）| `stated`（看其所说，self-report）| `stated+observed`（自述且有观测佐证）。
- `confidence`：`low | medium | high`。

## 维度枚举

```
D1 evaluation_capability : blind | surface | competent | expert
D2 acceptance_bar.primary: ship-fast | functional | modern-correct | type-safety-purist
   acceptance_bar.flags  ⊆ {tests, types, scope, security, style, a11y, perf}
D3 interaction_style.delegation  : vibe-dump | loose | spec-driven
   interaction_style.supervision : hands-off | reviews | micromanage
     （语义=过程卷入：对助手进行中可见感的需要；不是产品按钮）
   interaction_style.on_offtrack : abandon | retry | correct | fix-self | file-issue
     （语义=质量失败后的策略；不驱动等待耐心）
D4 trust_model           : over-trust | balanced | skeptical
D5 domain.depth          : shallow | working | deep
D6 autonomy_expectation  : advisory | collaborative | agentic
D7 time_temperament      : patient | steady | impatient
     （对等待/空转的耐受；与 on_offtrack 正交）
era.value                : pre_vibe | post_vibe        (按发布日期切分，约 2025-10)
```

> 授权尺度（只读/可写/可跑）**不进卡库**：那是会话/产品策略，由 sim 从自主性期望半派生。

### D5.area 受控词表 (controlled vocabulary)

`area` 取**单一 token**（库覆盖度可度量）；真正跨域无中心时用 `cross-stack`。具体技术栈进 `stack`，不进 `area`。

```
web-backend | web-frontend | scientific-computing | data-viz | ml-ai |
data-analysis | dev-tooling | data-eng | infra-devops | databases |
systems-runtime | security | mobile | cross-stack
```

（`data-analysis` = pandas/numpy/excel/notebook 数据整理，区别于 `data-eng` 管线与 `scientific-computing` 数值/符号库。）

`stack` = 实际使用的具体技术（如 `["typescript","node"]`）。`weak` = 有效能力降一档的子域（如 `["timezones/DST"]`），
是塑造行为的强信号（让一个本来 competent 的用户漏掉某类领域 bug）；ground 不到就 inject 0–2 个或留 `[]`。

## 受控注入分布 (controlled injection)

当某来源对某轴**确实沉默**时，从下列分布**逐卡独立采样**（与已 grounded 的维度正交），
置 `source: injected` / `confidence: low`：

- `delegation`：vibe-dump 25% / loose 45% / spec-driven 30%
- `supervision`：hands-off 30% / reviews 45% / micromanage 25%
- `on_offtrack`：abandon 20% / retry 20% / correct 30% / fix-self 15% / file-issue 15%
- `trust_model`：over-trust 30% / balanced 45% / skeptical 25%
- `autonomy_expectation`（D6）：advisory 35% / collaborative 40% / agentic 25%
- `time_temperament`（D7）：patient 25% / steady 50% / impatient 25%
- `D5.weak`：按 `area` 注入 0–2 个合理弱项或 `[]`。

**正交强制**：`on_offtrack` 与 `time_temperament` 必须独立采样——禁止「abandon 必配 impatient」或「file-issue 必配 patient」的按档锁死。

有弱先验时可偏置采样（自称 vibecoder → over-trust + vibe-dump；库维护者 → skeptical + spec-driven）。
比例为起始默认，可按目标用户分布调。

**采样，不要按档锁死（强制）**：注入是「逐卡真实抽一次」，不是「从 D1 确定性映射」。若每张 `surface` 卡都成了
`functional+balanced+reviews+retry`、每张 `blind` 卡都成了 `ship-fast+over-trust+hands-off`，就是按档锁死了——
重抽。各注入维独立抽（弱先验只微调赔率），批后目测分布是否塌缩。

## 真实性门原则 (authenticity gate，双向)

真实性门是**双向**的，按来源类型选对应一侧；每条 grounded 维度都必须**先过门再 map**。

- **观测型来源**（看其所做，如 GitHub 足迹）：门是 **trace-floor + 一致性**。低于取证下限（自有 repo + 真实 PR +
  已诊断 issue 合计过少，尤其 0 repo 且 0 PR）→ `insufficient_evidence`，不入库；浅层画像 ⊥ 深层产出 /
  实现不可信的跨栈速度 / AI 格式痕迹（`id=` 围栏、过度模板化）→ `contaminated`，隔离永不入库；
  ≥2 个**非空**层一致 → `authentic`。高 volume 是污染提示而非质量信号。
- **自述型来源**（看其所说，如博客/访谈/演讲/长推）：门是 **performative / promotional / second-hand**。
  课程营销 / 影响者带货 / 激励驱动 → `promotional` 拒；第三方转述、非本人原话 → `second_hand` 拒（去找一手）；
  AI SEO 流水文、零具体个人细节 → `contaminated` 隔离；第一人称但无任何工作流细节 → `insufficient_evidence` 拒。
  **夸张不等于失真**：真实第一人称的夸张（"我从不读 diff"）真实传达了一种 *立场*——抽出立场、标 `stated`、
  置 `confidence: medium`，不要拒。

裁决取值：`authentic | suspect | contaminated | insufficient_evidence`。各来源的门细则写在对应薄 skill，
本契约只立**原则与裁决词表**。

## `stated` → confidence 规则（自述型来源）

- 纯自述 grounded：`source: grounded` + `basis: stated` + **`confidence` 封顶 medium**。
- 升到 `high` + `basis: stated+observed`：仅当有观测痕迹佐证（公开可测产出 / 知名维护者履历 / 在线产品）。
- 「认错弱点」（"我不是技术出身"）造假动机低 → 可 `high`；「自夸专家」造假动机高 → 无佐证停在 `medium`。

## 符合性规则 (conformance)

1. 单值维（D1/D4/D6/D7 + D3 三子轴）用键 `value`；D2 用 `primary`+`flags`；D5 用 `area/depth/stack/weak`。
2. `D5.area` ∈ 上方受控词表，且为**单一 token**。
3. `source: grounded` 的维度必须有至少一条对应 `evidence_quotes`。
4. `source: injected` 的维度 `confidence` 必须为 `low`。
5. 卡记录**不得**含任何 benchmark / 轨迹派生字段。
6. 遇未知键：读侧前向兼容（忽略不报错），便于 schema 演化。
7. `D7_time_temperament` 缺省时注入侧回落 `steady`（旧卡兼容）；新卡应显式写出。
