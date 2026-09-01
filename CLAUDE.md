本地每次都要pull一下远端仓库再开始做事。

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

  SWE-bench 场景按 spec-0051 使用**每会话一个临时容器**：从同一 runnable seed image 启动，persona 的 `read_file`/`run_shell` 与 harness 均只操作容器内 repo，不把 repo `docker cp` 到宿主。harness 不设 240 秒整轮超时，慢请求由 90 秒 persona 心跳决定续等或打断；仅真实崩溃/基础设施绝对上限 fail-closed。会话仍保留主观体感与接受决定，但技术通过只认随后由官方 SWE-bench harness 在新鲜 instance 容器产生的客观结果；两者与最小审计事件分别落入 session JSON。

- **b｜开发者侧（交付面，spec-0032 现行）**：由 OpenAgents vigil（独立 CLI 常驻进程）承担。需求面 Owner 准入的票带 `openagents` 交接令牌，vigil 发现后走「盖 ready → curator 排依赖 → worktree/分支 → 实现 → 评审循环 → PR → conflict/CI/review 闸 → 合并进 main」。CI/评审是**工程质量闸**（harness 仓结构冒烟，绝不跑 benchmark），与已去掉的体感门禁维度不同；体感仍纯观测、benchmark 全程 held-out。坏改动在 PR 处被打回、不落 main。

- **c｜闭环（spec-0050）**：非末轮在 Owner 准入后**等待本轮准入票终态**（合进 main 或明确卡死）才开下一轮用户。末轮只跑用户交互，不再提案、不再交付。第 N+1 轮体感相对第 N 轮归因于第 N 轮已封口产物。一张票 `needs-human`/超时则实验停在该轮。同一轮内用户与多票交付仍可并行。

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

### 运行时：需求面 nexau + 交付面 OpenAgents（spec-0032）
需求面角色为「同一 nexau 运行时 + 不同 agent 定义（prompt+工具）」，固定角色定义置于 `agent_defs/`：
- **用户 agent**：扮演用户，多轮使用 harness，产出体感与 issue（report 平面）。
- **triager / synthesize / divergent**：生成器，产不可领 proposal（spec-0029 三平面）。
- **Owner**：唯一准入——admit 打 `openagents` 交接令牌 / merge / decline / hold，covers 级联在此。

交付面 = OpenAgents vigil：以独立 CLI 接入（不 vendor 不 import），coding 后端为 claude CLI；对 Gitea 经其 forge/Gitea driver（OpenAgents spec-0074）。两面只通过 issue 标签（openagents/ready）与 main SHA 交互。运行形态（spec-0033）：**容器围堵为缺省**——vigil 跑在专用容器（deploy/vigil 镜像，容器内自 clone harness 仓、零宿主挂载），网络只挂 internal vigil-net、外网经 egress 代理 allowlist（仅 Anthropic API），claude 凭证（ANTHROPIC_API_KEY 或 CLAUDE_CODE_OAUTH_TOKEN）与 Gitea token 只经容器 env；`VIGIL_MODE=subprocess` 为无围堵的宿主直跑，仅限盯屏联调。

> 无体感门禁角色——体感只作观测，benchmark 全程 held-out。

### 被进化对象：harness 作为可启动程序
harness 不建模为单个 agent 定义，而是「可启动程序 + 黑盒对话契约」：启动后接收用户消息、返回回复；内部为 1 个或 N 个 nexau、如何编排，由其自身入口脚本决定（支持多 agent harness）。
- 用户侧仅通过 `HarnessInterface`(send/reset/close) 与之交互，不感知内部结构。
- harness 自带入口 `entry`，自行依赖 nexau，不复用本仓 `nexau_runtime`，保持独立（后续可替换为 CC/codex）。
- harness 源码为**独立 git 仓，托管于 Gitea**：主干 main + 交付面的 per-issue 分支/PR（vigil 管理），merge commit 即观测锚点（vK tag 体系已退役）。`harness_template/` 为 v0 种子（含 `.gitea/workflows/smoke.yml` 结构冒烟 CI），用于初始化该仓。

### 状态去向
- **issue/PR → Gitea**：用户 agent 经 `IssueTracker` 接口提交，由 Gitea 负责发号/状态/标签/comment；交付面 vigil 按 `openagents`→`ready` 标签接手，PR 也落同一 Gitea 仓（看板经 /api/delivery 观测）。
- **体感 + session → 本地**：写入 `data/sessions/`，作为体感曲线与回归基线的数据源。

### 闭环
`loop/orchestrator` 跑需求面：每轮先用户（测当时 `origin/main` 快照）→ 非末轮才生成两拍 + Owner 准入 + 等待本轮 admitted 票关闭且无 `needs-human` → 再解析 sealed SHA。末轮只用户。卡死抛 `RoundDeliveryBlocked`，不开下一轮。交付面 vigil 仍是常驻执行器，但不再与下一轮用户叠跑；`TOTAL_ROUNDS=1` 不启 vigil。`loop/metrics` 记录 issue 曲线与三平面漏斗。一次实验的可还原切片在 `backend/data/role_runs/<run_id>/`（spec-0049），`_reset_to_initial` 不得删除。并行隔离实验用 `backend/scripts/experiment.py`（spec-0047）；`./run.sh` 单例入口已弃用，并拒绝 attach 实验托管的 vigil。

### 目录结构
前后端分目录（参考 MiroFish）：后端全在 `backend/`，`frontend/` 占位待建，项目级文档/工具与配置留根。
```
backend/                 # 后端（编排框架）
  auto_designer/         # 包（编排框架本体）
    models.py            # 共享数据结构（两侧共用）
    nexau_runtime.py     # 单一 nexau 适配：加载一份 agent 定义并跑（角色共用）
    harness/             # interface.py(黑盒对话契约) + launcher.py(取某版 harness 跑其 entry)
    user/                # user_agent + sim/WorkspaceRuntime（本地 fixture / 每会话 Docker）+ session_store
    evaluation/          # 官方 SWE-bench fresh-container 客观验收与 accept validity 派生
    tracker/             # base.py(IssueTracker接口) + gitea.py(含 PR 观测读路径) + fake.py
    dev/                 # 边界/围堵原语：harness_boundary + workspace_jail + repo_guard 等（agentic_developer 已随 spec-0032 退役）
    loop/                # orchestrator.py + metrics.py + checkpoint.py + run_state.py + runner.py
    web/                 # 只读观测看板 FastAPI（/api/overview /api/delivery /api/sessions ...）
  tests/                 # 测试（pytest testpaths=backend/tests）
  agent_defs/            # 需求面角色 nexau 定义（数据）：user_agent/ triage_agent/ designer/ divergent_pm/ owner/
  harness_template/      # v0 harness 种子（独立程序）：entry.py + agents/ + params.yaml + .gitea/workflows/smoke.yml
  deploy/gitea/          # 基建：docker-compose.yml(Gitea+act_runner+egress-proxy+双网络) + bootstrap.sh
  deploy/vigil/          # 交付面围堵盒（spec-0033）：Dockerfile + entrypoint.sh(自 clone) + build.sh
  scripts/               # bootstrap + 实验入口 + runnable SWE-bench seed 构建/验收脚本
frontend/                # 前端：React+Vite+TS 只读观测看板（消费 backend web API）
docs/specs/              # 设计 specs（spec-driven-development 源，项目级）
tools/                   # vendored spec CLI（外来工具，不纳入 lint）
backend/data/            # 运行产物(.gitignore)：sessions/ harness_runs/
```
根目录配置：`pyproject.toml`（管 backend 子树）、`.github/`、`.gitignore`、`.commitlintrc.yml`、`CLAUDE.md`。

### spec 路线
- **spec-0001 用户侧**：models、HarnessInterface+Fake、UserAgent、IssueTracker 接口+Fake、本地 SessionStore、run_session。可独立测（不依赖真 Gitea/harness）。
- **spec-0002 Gitea 接入与基建**：docker(sqlite)+token+标签方案、GiteaTracker、harness 仓初始化。
- **spec-0003 开发者侧与闭环（初版，已被 0005/0007 取代）**：harness launcher、developer_agent、test_agent（体感门禁）、release（合并+tag）、orchestrator+metrics。
- **spec-0004 Harbor 运行与可恢复 checkpoint**：所有 agent 在单沙盒一波跑（方案 A，整条 run = 1 个 harbor task），每轮边界吐增量 checkpoint artifact、喂回即从断点幂等续跑；checkpoint 维护用户侧/开发者侧/编排中间态。harbor 只包外层 rollout 生命周期，逐轮真人对话仍走 spec-0001 自立协议。
- **spec-0005 / spec-0007 纯 trunk 开发者侧（已被 0032 取代）**：开发者侧改为带 git 工具的 nexau agent 直推 main，去掉 fix 分支/merge/release/体感门禁；体感退化为观测、benchmark held-out。闭环回灌简化为「main 最新 SHA」纯观测游标（此语义沿用至今）。
- **spec-0032 开发者侧换轨 OpenAgents（现行）**：需求面/交付面二分——Owner 准入打 `openagents` 交接令牌，OpenAgents vigil（独立 CLI 常驻，forge/Gitea driver 见其 spec-0074）接管 ready→分支/PR→CI/评审→合并；nexau 直推 dev 退役，PR 门禁为工程质量闸（held-out 约束不变）。
- **spec-0033 交付面容器化围堵（现行）**：vigil 关进专用容器（零宿主挂载、容器内自 clone——两面唯一媒介本就是 Gitea），internal 网络 + egress 代理 allowlist，落地 spec-0021/0022「无凭证+出口 allowlist」；观测游标改跟 origin/main（server-side merge 后本地 main 非真身）。

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
  - 类型：feat / fix / refactor / chore / docs / test / ci / style / perf / build / spec（spec 制品撰写/修订）
- **代码检查**：Ruff（行宽 100）
- **Git 钩子**：lefthook —— pre-commit（lint）+ commit-msg（commitlint）
- **Git 推送**：首次推送分支用 `git push -u origin <branch>` 设置 upstream tracking
- **自动提交**：每完成一处改动即 `git add` + `git commit` + `git push`，无需征求确认（用户已长期授权）。
- **CI**：CI 不过就反复修复重推直到全绿。
- **代码注释**：中英文皆可，不强制区分，以清晰表达为先。
- **Python 函数参数**：禁止位置参数（`/` 语法）；private 函数（`_` 开头，不含 dunder）参数禁止默认值，调用方必须显式传参。
