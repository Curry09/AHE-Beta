# Reference: Harness-Seed Harvesting（extract-harness-seed 薄 skill 的来源特异细则）

本文件只承载 `extract-harness-seed`（closed issue + merged fix PR / 高票 Q&A 源）的抽取细则：
oracle 分层、harbor 可复现分层、difficulty 校准、harvest mechanics、范例。**卡的字段 schema /
枚举 / domain 词表 / 两道门原则 / held-out 存放约定见唯一公共契约
[`../seed-card-schema.md`](../seed-card-schema.md)，此处不重复。**

## 1. capability 识别（从「修复揭示的真实所需」判定）

分类法本身在契约 §capability。判定要点：从 *resolution* 揭示任务真正需要什么去标，而非从诉求表面。

- `intent-inference` — 原诉求含糊（"变快点"/"不工作"），修复显示真实意图须被推断/澄清。
- `correctness-edgecase` — 修复是系于微妙情形（off-by-one、null/空、引号、顺序、竞态）的小 diff。
- `long-output` — 解决是整文件重写 / 多文件改 / 大产物。压测截断、丢块、"其余不变"式偷懒。
- `tool-use-verification` — 只有真跑测试/构建/复现才知对。压测 harness 是否真跑核实 vs 宣称完成。
- `scope-discipline` — merged fix 刻意最小；诱人的更大改动会破坏邻近行为。
- `env-setup` — 任务就是把依赖/构建/配置弄通（CI、打包、工具链）。
- `error-recovery` — thread 显示迭代：首修失败、二修成功。压测有效调试环 vs 放弃/空转。
- `explanation-teaching` — 提问者低能力；成功 = 一个他能据以行动的答案。

一卡可标 2–3 个，但选它最干净隔离的**主**能力。

## 2. oracle 分层（强 → 弱；取制品支持的最强档）

契约 §枚举 `oracle.tier` 列出取值。各档来源与保真：

| tier | 是什么 | 从何 harvest | 可自动 | 保真 |
|---|---|---|---|---|
| `executable-test` | 一条随修复 FAIL→PASS 的具体测试 | fix PR **新增/改**的测试 | ✅ | 最高 |
| `test-suite` | 修复 commit 上既有套件通过 | 跑套件 @fix vs @parent | ✅ | 高 |
| `sandbox-run` | 脚本化跑复现期望输出/行为 | 由 issue 的 repro + 期望构造 | ✅/半 | 高–中 |
| `rubric` | 必备属性清单 | 需求 + accepted answer | ⚠️ judge | 中 |
| `llm-judge` | 比对 harness 输出与参考解 | merged diff / accepted answer 作参考 | ⚠️ 噪 | 低–中 |
| `none` | 无 harness-独立 check（纯设计/观点） | — | — | **排除** |

规则：优先 `executable-test`（fix PR 加回归测试即理想种子）；`rubric`/`llm-judge` 可入但
`oracle.confidence` 封顶 `medium` 并标低保真；oracle 须**独立于 harness**（绝不用 harness 自身输出
定义成功）；`provenance.resolution_quote` 记**逐字**解决原句（测试名 / 断言 / accepted answer 关键句）。

## 3. harbor 可复现门（契约 §两道门原则第 2 道的分层）

| tier | 条件 | 动作 |
|---|---|---|
| `easy` | 单仓、标准包管理、hermetic 单测 | admit |
| `medium` | 需可容器化服务（postgres/redis）或 vendored 数据 fixture | admit（写进 env spec） |
| `hard` → **拒** | live cloud、特定 OS、特定硬件、超大数据、live 三方 API、flaky/timing/network 测试 | 拒，或降 oracle 为 `rubric` 并标 `env.reproducible: "hard-rubric-only"` |

`env` 供 harbor 消费：`base_image` / `repo_at`(父 commit SHA) / `setup`(确定性、pin 死) /
`test_cmd` / `external_deps`(`none`|`containerizable:[...]`|`live(REJECT)`) / `budget`。**pin 一切**
（lockfile、镜像 digest），无 "latest"、无 unpinned 网络安装。

## 4. difficulty & scope 校准

- `difficulty`: `trivial|easy|medium|hard` — 按修复的**概念深度**判，不按行数（3 行竞态修复算 `hard`）。
- `scope`: `single-file|multi-file|cross-module|repo-wide`。
- 二者驱动**配对**：`pairing_constraints.min_capability` 随难度升（`hard` ABI 种子需 `expert`；
  `trivial` 语法种子配 `surface`），并让**归因**干净（`hard` 种子上低体感可能是任务难而非 harness 差，
  oracle 消歧）。

## 5. 从何 harvest (source-product)

| 来源 | 最擅长 | oracle 产率 | 备注 |
|---|---|---|---|
| closed issue + **带测试的 merged fix PR** | 金种子 | `executable-test` | SWE-bench 配方，**非 benchmark** 实例 |
| 无测试的 merged fix PR | 逻辑种子 | `test-suite` / `sandbox-run` | 跑套件 @fix vs @parent |
| accepted / 高票 SO 答案 | 低端 & how-do-I 种子 | `sandbox-run` / `rubric` | 配 blind/surface persona |
| feature request + 落地的 PR | `scope-discipline` 种子 | `rubric` / `test-suite` | 注意可复现性 |

与 persona 同域采集，故 seed 与 persona 能同域配对；但**从不同实例** harvest，排除 held-out benchmark。

## 6. harvest mechanics（operator SOP）

**两类字段两条规则**：FACT 逐字转录/命令派生，绝不发明；JUDGMENT 按本 skill §1–§4 准则判定。
字段到来源的对应见契约卡形状注释。

### 6.1 发现 query（找金制品）

先定 domain（由 harvest 所在仓决定，是 FACT），再找一个 **closes issue 且加/改测试的 merged PR**：

```bash
# 1. 某仓引用了 closed issue 的 merged PR
gh search prs --repo pytest-dev/pytest --state closed --merged \
  --match body "fixes #" -L 50 --json number,title,url,closedAt
# 2. 只留动了测试文件的（executable-test 候选）
gh pr view <N> --repo pytest-dev/pytest --json files \
  -q '[.files[].path | select(test("(^|/)tests?/|test_.*\\.py$"))]'
```

### 6.2 `repo_at` — 父（未修复）commit，由命令求（注入侧要求真实 SHA、拒占位）

要复现的状态 = base-before-merge = 合并 commit 的第一父：

```bash
MERGE=$(gh pr view <N> --repo OWNER/REPO --json mergeCommit -q .mergeCommit.oid)
gh api repos/OWNER/REPO/commits/$MERGE -q '.parents[0].sha'   # -> repo_at（真实 40 位 SHA）
```

`repo_at` 必须**在 harvest 时解析为真实 SHA**；卡里留 `<parent-commit-...>` 等占位是未完成的采集——
0010/T2 注入侧会**拒收占位**（占位在物化时才炸，前移到注入边界暴露）。验 PASS 的 commit 是 `MERGE` 本身。

### 6.3 `not_in_benchmark` — 机检（绝不"大概没事"）

- **日期规则**：只当 PR `merged_at` 晚于 benchmark 采集 cutoff 才 admit（SWE-bench 实例多在 cutoff 前）。
- **ID 规则**：载 benchmark 实例表，断言 `f"{repo}-{issue_number}"`（及 SWE-bench `OWNER__REPO-NNNN` 形）**不在**其中。

记下过的是哪条规则；两条都判不了 → **不**置 `true`，扣住该卡。

### 6.4 `external_deps` — 读，别猜

```bash
gh pr diff <N> --repo OWNER/REPO | grep -E '^\+\s*(import|from) '   # 测试的依赖
ls .github/workflows && grep -RnE 'services:|postgres|redis|docker' .github/workflows
```

仅 stdlib/in-repo → `none`；需容器可供的 postgres/redis 等 → `containerizable:[...]`（repro `medium`）；
需 live cloud / 三方 API / 设备 / 特定 OS → `live(REJECT)`（§3 → 拒或降级）。

### 6.5 reproduce-once（真正的 S7 检查，校验器做不到）

```bash
git clone https://github.com/OWNER/REPO && cd REPO
git checkout <repo_at>      && <setup> && <test_cmd>   # 期望: fail
git checkout <merge_commit> && <setup> && <test_cmd>   # 期望: pass
```

只有 `FAIL@parent → PASS@fix` 才证明 `repo_at`/`test_cmd`/`oracle` 可信；不符即某 FACT 错，修，别 admit。

## 7. 范例

### A — admit（easy, executable-test）

closed dbt-core issue：长名 generic test 节点丢 `depends_on`；merged PR 加 `test_long_name_resolution`。
单仓、pip 可装、hermetic 测 → easy；FAIL→PASS 测 → executable oracle。**Admit。**

### B — reject（不可复现）

Spark-on-AKS issue：只在 live Azure Cosmos DB 上复现。需 live cloud → harbor 无法确定性搭起。
出被拒卡：`{"reject_reason": "harbor_repro_gate: requires live Azure Cosmos DB + AKS", "action": "not admitted; 若 env-setup 欠覆盖，改找 in-repo hermetic 等价实例"}`。

### C — admit（rubric oracle，低保真）

accepted SO 答案「React 离页前警告未保存编辑」。无单仓/单测，但 accepted answer 定义必备项 →
`sandbox-run` 不可得 → `rubric` oracle，标 `oracle.confidence: medium`、`env.reproducible:
hard-rubric-only`、`gates.harbor_repro_gate: downgraded`。**Admit，低保真。**

## 8. 库的覆盖对象

同 persona 库，真实对象是一个**分布**——此处覆盖 `domain × capability`。追踪哪些格已填；一个无可复现
种子的能力是 harness 盲点。别过度挖单仓/单能力；追欠覆盖格（尤其 `tool-use-verification` 与
`long-output`，旧的纯聊天 sim 无法压测的两格）。
