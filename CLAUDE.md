## 项目设计

### 底座
1. `harbor` 作为 rollout 底座。
2. `nexau` 作为 agent 实现，同时兼容 claude code / codex 接入。

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
1. 分支合并策略。
2. 体感 1-4 的评分细则。
3. 真实数据盘点（确认蒸馏模块的输入）。

## 设计理念
1. **奥卡姆剃刀**：如无必要，勿增实体。保证代码和架构的最小化、最简洁，先搭最小可用版本（MVP）再迭代。
2. **模块解耦**：不同模块之间职责清晰、边界明确，互相解耦。
3. **结构化管理**：文件分文件夹管理，展示出良好的层次结构。
4. **证据驱动**：一切提到的概念、数据、结论都要有真实可查的来源，需实际查看来源内容并在对应位置给出引用，不臆造。
5. **以成果为中心**：面向交付成果测试与验收，而非停留在代码细节。

## 技术栈
- Python

## 代码规范
- **提交信息**：遵循 Conventional Commits —— `<类型>(<范围>): <描述>`
  - 类型：feat / fix / refactor / chore / docs / test / ci / style / perf / build
- **代码检查**：Ruff（行宽 100）
- **Git 钩子**：lefthook —— pre-commit（lint）+ commit-msg（commitlint）
- **Git 推送**：首次推送分支用 `git push -u origin <branch>` 设置 upstream tracking
- **CI**：CI 不过就反复修复重推直到全绿。
- **代码注释**：中英文皆可，不强制区分，以清晰表达为先。
- **Python 函数参数**：禁止位置参数（`/` 语法）；private 函数（`_` 开头，不含 dunder）参数禁止默认值，调用方必须显式传参。
