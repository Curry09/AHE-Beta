## 项目设计

### 底座
1. `harbor` 作为 rollout 底座。
2. `nexau` 作为 agent 实现，同时兼容 claude code / codex 接入。

### 项目文档
飞书文档：https://sxddhcrtbqu.feishu.cn/wiki/P3dEw0vmhix6IXk7KpJc4O85nfc?from=from_copylink

### 要解决的问题
直接对轨迹做自进化，会把轨迹的特征带进 harness，只能针对具体问题做局部修改，难以产生结构性改进。根本原因是它直接以 benchmark 分数为优化目标，这会导致过拟合。

### 核心思路：训练信号与测试分离
- 训练信号用用户体感，在"模拟真实使用"的分布上优化。
- 测试用各类 benchmark，held-out，只在事后验证体感驱动的进化是否带来真实能力提升。
- benchmark 不进入训练，因此其特征不会被带入 harness；同时开发者 agent 可以做较大改动，效果由 benchmark 事后判定。

### 方法：模拟"用户使用 → 开发者迭代"的闭环

- **蒸馏模块**：从真实使用数据（CC/codex/nexau 的真实日志、issue tracker、社区反馈）蒸馏出 persona 库和种子场景库。persona 来自真实数据，不依据 benchmark 构造，以此保证体感信号的真实性，并避免训练目标和测试目标互相污染。

- **a｜用户侧**：user agent 按 persona 和种子场景使用 harness，产生一段使用过程（包含追问、绕路、卡顿、放弃等情况）。输出两类信号：① 体感评分（类似 cc 的 1-4 评分，作训练信号）；② issue（bug 或需求，来自使用中的具体问题点）。

- **b｜开发者侧**：开发者 agent 处理 issue 流并分流：
  - bug → release 分支，快速迭代。
  - 大 feature → feature 分支，完成后再合入。
  - 两分支定期合并（策略待定）；合并和发版前由测试 agent 内测，门禁只检查体感是否回归。benchmark 不参与发版判定。

- **c｜闭环**：发版后的新 harness 回到用户侧，循环。

### 约束
1. benchmark 全程 held-out：不参与训练，不参与发版门禁。
2. persona 来自真实数据，不依据 benchmark 或轨迹构造。
3. 发版门禁只用体感；benchmark 只用于观测。

### 观测指标
记录 issue 数量随时间的曲线，用于判断新 issue 的产生和已有 issue 的解决是否平衡：issue 长期不下降说明 harness 在退化；issue 过早归零说明 persona 多样性不足、探索停止。

### 待定项
1. 体感 1-4 的评分细则（评分维度与归一）。
2. 真实数据盘点（确认蒸馏模块的输入）。
3. 体感门禁的最小样本量 N 与回归判定方式（单点比较 vs 分布比较）。

## 架构（MVP）

### 单一运行时：nexau
MVP 仅接入 nexau 一种 agent 运行时；claude code / codex 兼容留待后续。所有角色均为「同一 nexau 运行时 + 不同 agent 定义（prompt+工具）」，固定角色定义置于 `agent_defs/`：
- **用户 agent**：扮演用户，多轮使用 harness，产出体感与 issue。
- **开发者 agent**：领取 issue，修改 harness 制品。
- **测试 agent**：用候选 harness 跑用户会话，做体感回归。

### 被进化对象：harness 作为可启动程序
harness 不建模为单个 agent 定义，而是「可启动程序 + 黑盒对话契约」：启动后接收用户消息、返回回复；内部为 1 个或 N 个 nexau、如何编排，由其自身入口脚本决定（支持多 agent harness）。
- 用户侧仅通过 `HarnessInterface`(send/reset/close) 与之交互，不感知内部结构。
- harness 自带入口 `entry`，自行依赖 nexau，不复用本仓 `nexau_runtime`，保持独立（后续可替换为 CC/codex）。
- harness 源码为**独立 git 仓，托管于 Gitea**：`release` + `feature` 分支，tag 即发布版本；开发者 agent 走真实分支与合并。`harness_template/` 为 v0 种子，用于初始化该仓。

### 状态去向
- **issue → Gitea**：用户 agent 经 `IssueTracker` 接口提交，由 Gitea 负责发号/状态/标签/comment；标签（bug/feature）驱动开发者侧分流。
- **体感 + session → 本地**：写入 `data/sessions/`，作为体感曲线与回归基线的数据源。

### 闭环
`loop/orchestrator` 串联 a（用户会话产 issue+体感）→ b（开发者改 harness 分支、测试 agent 体感门禁、合并发版）→ c（新版 harness 回到 a）；`loop/metrics` 记录 issue 数量随时间的曲线。

### 目录结构
```
src/auto_designer/
  models.py            # 共享数据结构（两侧共用）
  nexau_runtime.py     # 单一 nexau 适配：加载一份 agent 定义并跑（角色共用）
  harness/             # interface.py(黑盒对话契约) + launcher.py(取某版 harness 跑其 entry)
  user/                # user_agent.py + session.py(run_session) + session_store.py
  tracker/             # base.py(IssueTracker接口) + gitea.py + fake.py
  dev/                 # developer_agent.py + test_agent.py + release.py
  loop/                # orchestrator.py + metrics.py
agent_defs/            # 固定角色 nexau 定义：user_agent/ developer_agent/ test_agent/
harness_template/      # v0 harness 种子：entry.py + agents/ + tools/ + params.yaml
seeds/                 # 给定输入（先手写，后续由 distill 产出）：personas/ scenarios/
infra/gitea/           # docker-compose.yml(Gitea+sqlite)
data/                  # 运行产物(.gitignore)：sessions/ harness_runs/
```

### spec 路线
- **spec-0001 用户侧**：models、HarnessInterface+Fake、UserAgent、IssueTracker 接口+Fake、本地 SessionStore、run_session。可独立测（不依赖真 Gitea/harness）。
- **spec-0002 Gitea 接入与基建**：docker(sqlite)+token+标签方案、GiteaTracker、harness 仓初始化。
- **spec-0003 开发者侧与闭环**：harness launcher、developer_agent、test_agent（体感门禁）、release（合并+tag）、orchestrator+metrics。
- **spec-0004 Harbor 运行与可恢复 checkpoint**：所有 agent 在单沙盒一波跑（方案 A，整条 run = 1 个 harbor task），每轮边界吐增量 checkpoint artifact、喂回即从断点幂等续跑；checkpoint 维护用户侧/开发者侧/编排中间态。harbor 只包外层 rollout 生命周期，逐轮真人对话仍走 spec-0001 自立协议。

## 设计理念
1. **奥卡姆剃刀**：如无必要，勿增实体。保证代码和架构的最小化、最简洁，先搭最小可用版本（MVP）再迭代。
2. **模块解耦**：不同模块之间职责清晰、边界明确，互相解耦。
3. **结构化管理**：文件分文件夹管理，展示出良好的层次结构。
4. **证据驱动**：一切提到的概念、数据、结论都要有真实可查的来源，需实际查看来源内容并在对应位置给出引用，不臆造。
5. **以成果为中心**：面向交付成果测试与验收，而非停留在代码细节。
6. **以用户为中心**：在设计阶段，如果用户的需求有任何不明确的部分，都要向用户确认

## 技术栈
- Python

## 代码规范
- **提交信息**：遵循 Conventional Commits —— `<类型>(<范围>): <描述>`
  - 类型：feat / fix / refactor / chore / docs / test / ci / style / perf / build
- **代码检查**：Ruff（行宽 100）
- **Git 钩子**：lefthook —— pre-commit（lint）+ commit-msg（commitlint）
- **Git 推送**：首次推送分支用 `git push -u origin <branch>` 设置 upstream tracking
- **自动提交**：每完成一处改动即 `git add` + `git commit` + `git push`，无需征求确认（用户已长期授权）。
- **CI**：CI 不过就反复修复重推直到全绿。
- **代码注释**：中英文皆可，不强制区分，以清晰表达为先。
- **Python 函数参数**：禁止位置参数（`/` 语法）；private 函数（`_` 开头，不含 dunder）参数禁止默认值，调用方必须显式传参。
