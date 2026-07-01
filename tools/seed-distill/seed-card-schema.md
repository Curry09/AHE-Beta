# Seed Card Schema — 唯一公共契约 (hub)

> 本文件是种子场景蒸馏侧的 **唯一 source-agnostic 公共契约**。所有「薄抽取 skill」（spoke，
> 如 `extract-harness-seed/`、未来的 `extract-log-seed/` / `extract-so-seed/`）只描述
> 「从某类真实源 harvest 一张种子卡 + 过两道门 + ground 哪几字段」，**字段 schema / 枚举 /
> 词表 / 卡形状 / 两道门原则 / held-out 字段存放约定一律引用本文件**，彼此不依赖。契约改一处，
> 全员生效；加新真实源只是新增一个薄 skill，不碰别人。
>
> 对应 spec：`docs/specs/0010-seed-scenario-pipeline/`（T1 采集、T2 注入 SeedSource）。
> 卡 → `models.SeedScenario` 的注入映射（含 held-out 字段剥离）归 `0010/T2`（`card_to_seed`），
> 不在本契约内。与 persona 侧 [`../persona-distill/card-schema.md`](../persona-distill/card-schema.md)
> 对称镜像；`domain` 词表与 persona `D5.area` 共享同一 14 token 受控词表。

## 铁律

1. **轮辐式**：本文件是 hub，抽取 skill 是 spoke。spoke 只依赖本契约，**spoke 之间彼此不依赖**
   （杜绝 skill→skill 引用与多副本 schema 漂移）。
2. **Harvest，不 author**：种子卡从**已解决**的真实制品沉淀（closed issue + merged fix PR、
   高票 Q&A）。真实世界的那次解决 *即* 沉淀好的 oracle——你转录它，不发明它。绝不虚构任务。
3. **非 benchmark**：`source.not_in_benchmark` 恒为真——绝不从 held-out benchmark 实例采卡
   （污染训练目标与测试目标）。这是**契约级硬约束**，入库前 `validate_card` 拒违约卡。
4. **保留真实诉求原貌（不 sanitize）**：`task.prompt` 保留用户真实的表述与规格层级
   （欠规格、含糊、缺上下文都保留）——*诉求如何被提出* 本身就是压测 intent-inference 的信号。
5. **held-out 字段随卡采集、注入时剥离**：`oracle`/`env.test_cmd`/`gates` 是 benchmark 侧客观
   判分制品，随卡忠实沉淀（供 harbor 侧平行评测），但注入 SeedScenario 时落 sidecar、**绝不进
   训练环**（红线由 0010/T2 落实，本契约在此声明；见 §held-out 字段存放约定）。

## 卡记录形状 (card record)

一条卡是一个 JSON 对象；`source` · `task` · `oracle` · `env` 为必填，其余按下表：

```json
{
  "id": "seed-<repo-short>-<issue_number>",     // 稳定去重键（source-hash / repo+issue）
  "source": {
    "type": "closed_issue+fix_pr",              // 来源制品类型（见 §枚举 source.type）
    "repo": "owner/repo",                        // 真实来源仓（owner/repo）；纯文本源可 "n/a"
    "issue_url": "https://github.com/.../issues/NNN",   // 可选
    "fix_ref": "https://github.com/.../pull/MMM (merged)",
    "not_in_benchmark": true                     // 恒为真（铁律 #3），否则 validate_card 拒
  },
  "task": {
    "prompt": "用户真实提出诉求的原话（自然、可能欠规格）",   // 即注入 SeedScenario.description 的原文
    "context": "用户会真的给出的最小情境"
  },
  "domain": "dev-tooling",                        // 单一 token ∈ §domain 受控词表（与 persona D5.area 共享）
  "capability_probed": ["correctness-edgecase"],  // ⊆ §capability 分类法
  "difficulty": "medium",                          // ∈ §difficulty
  "scope": "single-file",                          // ∈ §scope
  "autonomy_required": "collaborative",            // ∈ §autonomy_required
  "oracle": {                                      // held-out（注入时落 sidecar）
    "tier": "executable-test",                     // ∈ §oracle.tier
    "spec": "path::node（FAIL@parent → PASS@fix）",
    "reference_solution": "fix PR diff 摘要或 url",
    "confidence": "high"                           // ∈ §confidence
  },
  "env": {
    "reproducible": "easy",                        // ∈ §env.reproducible
    "base_image": "python:3.11",
    "repo_at": "<parent-commit-sha>",              // 父（未修复）commit 真实 SHA；注入时须已解析（占位拒收）
    "setup": ["pip install -e ."],                 // 部署命令；注入时按 0009/T3 venv 前缀化
    "test_cmd": "pytest tests/test_x.py::test_y",  // held-out（注入时落 sidecar）
    "external_deps": "none",                        // ∈ §env.external_deps
    "budget": {"timeout_s": 600, "mem_gb": 4}
  },
  "pairing_constraints": {"domain": "dev-tooling", "min_capability": "competent"},
  "gates": {"oracle_gate": "pass", "harbor_repro_gate": "pass"},   // held-out（注入时落 sidecar）
  "provenance": {
    "resolution_quote": "定义成功的、来自 closing PR/answer 的逐字原句",
    "source": "https://github.com/.../pull/MMM"
  }
}
```

被拒卡（未入库，不进种子库）形状：

```json
{"id": "seed-...", "reject_reason": "harbor_repro_gate: requires live Azure Cosmos DB",
 "action": "not admitted; 若该能力欠覆盖，改找 in-repo、hermetic 的等价实例"}
```

## 枚举 (controlled values)

```
source.type        : closed_issue+fix_pr | merged_fix_pr | accepted_so_answer | feature_request+pr
capability_probed ⊆ { intent-inference, correctness-edgecase, long-output,
                      tool-use-verification, scope-discipline, env-setup,
                      error-recovery, explanation-teaching }
difficulty         : trivial | easy | medium | hard
scope              : single-file | multi-file | cross-module | repo-wide
autonomy_required  : advisory | collaborative | agentic
oracle.tier        : executable-test | test-suite | sandbox-run | rubric | llm-judge | none(排除)
confidence         : low | medium | high        （rubric/llm-judge 封顶 medium）
env.reproducible   : easy | medium | hard-rubric-only     （hard 且不可降级 → 拒）
env.external_deps  : none | containerizable:[...] | live(REJECT)
gates.*            : pass | downgraded | fail(排除)
```

### capability 分类法 (what seeds must cover)

库的真实对象是**对分类法的覆盖度**（`domain × capability` 的分布），不是任务堆。每卡至少标一个
`capability_probed`；一个没有可复现种子的能力就是 loop 永远无法改进的盲点。

| capability | 何时压测它 | 暴露的失败 |
|---|---|---|
| `intent-inference` | 诉求欠规格 / 含糊 | 猜而不澄清 |
| `correctness-edgecase` | 成功系于微妙 / 边界情形 | 貌似对实则错 |
| `long-output` | 需大 / 整文件 / 多文件输出 | 截断、丢块 |
| `tool-use-verification` | 须真跑 / 测 / 核实才知对 | 不核实就宣称完成 |
| `scope-discipline` | 最小修复才对，过度改动破坏他处 | 过度工程 / 附带破坏 |
| `env-setup` | 须把依赖 / 构建 / 配置弄通 | 跑不起来 |
| `error-recovery` | 首次尝试失败、需调试环 | 放弃 / 空转 |
| `explanation-teaching` | 低能力用户须能据此行动 | 对但不可用 |

### domain 受控词表 (controlled vocabulary，与 persona D5.area 共享)

`domain` 取**单一 token**（库覆盖度可度量），由 harvest 所在仓决定（FACT，不事后编造）；真正跨域时
用 `cross-stack`。这与 persona 侧同表，保证 seed 与 persona 能**同域配对**。

```
web-backend | web-frontend | scientific-computing | data-viz | ml-ai |
data-analysis | dev-tooling | data-eng | infra-devops | databases |
systems-runtime | security | mobile | cross-stack
```

## 两道门原则 (the two gates)

每张卡入库前须过**两道门**（`gates.oracle_gate` 与 `gates.harbor_repro_gate` 皆须非 fail）：

1. **oracle 门**：成功须 **harness-独立** 且可判（理想为可执行）。只能靠体感判的任务拒。分层见
   §枚举 `oracle.tier`——优先 `executable-test`（fix PR 新增的回归测试是理想种子）；`rubric`/`llm-judge`
   可入但 `oracle.confidence` 封顶 `medium` 并标低保真；无任何 harness-独立 check 的（纯设计/观点）
   `tier=none`→**不是种子**。
2. **harbor 可复现门**：harbor 须能**确定性地** (a) 搭起环境、(b) 在其中跑 harness、(c) 跑 oracle，
   且在 budget 内。取消项：live cloud（AKS/Cosmos/BigQuery）、特定 OS（macOS）、特定硬件
   （Android/GPU-only）、超大数据、live 三方 API、flaky/timing/network 测试。可容器化服务
   （postgres/redis）与 vendored fixture 可入（tier `medium`）。不可复现 → 拒，或降级为 `rubric`
   oracle 并标 `env.reproducible: "hard-rubric-only"`。

FACT 字段（`repo_at`/`test_cmd`/`not_in_benchmark`/`resolution_quote`/urls/`external_deps`）**逐字转录
工具原始输出或由命令派生，绝不发明**；JUDGMENT 字段（`task.prompt`/`domain`/`capability_probed`/
`difficulty`/`scope`/`oracle.tier`…）按薄 skill 的准则判定。

## held-out 字段存放约定 (红线)

`oracle` / `env.test_cmd` / `gates` 是 **benchmark 侧**客观判分制品。它们**随卡采集**（供 harbor 侧
平行评测复用），但在注入 `models.SeedScenario` 时由 0010/T2 的 `card_to_seed` **剥离到 sidecar**，
`SeedScenario`（及其 `to_dict` / `{version, seeds}` 信封 JSON）**绝不含**这三键。

依据 CLAUDE.md「benchmark 全程 held-out：不参与训练，不参与发版门禁」——训练信号只取自「模拟真实
使用」分布上的用户体感，oracle 客观判分归 harbor 侧的平行评测系统，二者**物理隔离于注入边界**。
在采集侧**保留**这些字段（而非丢弃）是为了让种子卡可复用于客观评测；held-out 纪律靠**注入边界剥离**
达成，不靠采集侧删字段。

## 符合性规则 (conformance)

1. `source` / `task` / `oracle` / `env` 必填；`oracle.tier != none`。
2. `source.not_in_benchmark` 恒为真（铁律 #3；否则 `validate_card` 拒）。
3. `domain` ∈ §domain 受控词表且为**单一 token**；`capability_probed` ⊆ §capability 分类法。
4. 两道门 `gates.oracle_gate` / `gates.harbor_repro_gate` 皆非 `fail` 才入库；被拒卡只作
   `{reject_reason, action}` 记录、不入种子库。
5. `provenance.resolution_quote` 为真实解决制品的**逐字**原句（oracle 的证据）。
6. 卡记录**不得**含任何 benchmark 分数 / 轨迹派生字段（白名单外的顶层键即拒）。
7. 遇未知键：读侧前向兼容（忽略不报错、原样保留），便于 schema 演化（Postel 法则）。
