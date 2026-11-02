# Specs

本目录是 AHE-Beta 的设计活快照，由 `spec-driven-development` skill 管理（vendored from OpenAgents，**单 markdown 文件形态**）。

- 每个 spec 组 = 一个单文件 `NNNN-slug.md`：
  - **YAML frontmatter**（机器读，结构化源）：组元数据 `number/title/issue/slug/summary` + `tasks[]`（每个 Task 的 `id/title/status/priority/depends-on/files/scope/acceptance` 等结构字段）。
  - **Markdown 正文**（人/agent 读）：组级 rust-RFC 9 段总览（Summary / Motivation / Guide-level explanation / Reference-level explanation / Drawbacks / Rationale and alternatives / Prior art / Unresolved questions / Future possibilities），单 spec 自包含地讲清整个 feature，DAG + 文件分配收进 Reference-level。
- `OVERVIEW.md`（全局看板：TL;DR 速览 / 看板 / 关系图 / 文件冲突 / 各 feature 详情）与 `ARCHITECTURE.md`（对代码的唯一映射，由 `spec graph` 从 `backend/ahe_beta/` 的 import 图 + docstring 生成）均**自动生成，勿手改**——改源（组 md 的 frontmatter/正文、或代码 docstring）后重跑 `render`/`graph`。
- prose 字段用**精简、精确、学术化**的语言，不堆比喻。frontmatter `summary` 是组级人话 TL;DR，`spec new` 必填、`validate` 强制非空。
- 必填总览段（`validate` 强制非空）：**Summary / Motivation / Reference-level explanation / Rationale and alternatives**。
- 只驱动 CLI，不手写/手改 md 结构：

  ```bash
  ./tools/spec-driven-development/spec new <slug> --issue <N> --title "<标题>" --summary "<人话 TL;DR>"
  ./tools/spec-driven-development/spec reserve-number --issue <N> --slug <slug>  # 现有 PR 改号前预留
  ./tools/spec-driven-development/spec add-task <NNNN> --id T1 --title ... --priority P1 --files ... --scope ... --acceptance ...
  ./tools/spec-driven-development/spec validate
  ./tools/spec-driven-development/spec render                                      # 生成 OVERVIEW.md
  ./tools/spec-driven-development/spec graph --package-root backend/ahe_beta  # 生成 ARCHITECTURE.md
  ./tools/spec-driven-development/spec abandon <NNNN> <Tx> --reason "..."          # 从快照移除 Task（历史在 git）
  ```

  > 组级正文（9 段）与既有 Task 的改动**直接编辑组 md 文件**即可（`spec amend`/`set-overview` 已退役，per-task 历史交给 git）。

## 编号规则

- 共享 Git 仓库中，`spec new` 从本地与远端主分支、已有预留号取下一号，并在远端 `spec-reservations/NNNN` 原子预留后创建文件；远端不可用时停止创建。纯本地目录沿用最大号 + 1。
- 一个组 ≤ 6 个 Task；超了就拆组。
- 同组内各 Task 的 `files` 必须互不相交（便于并行实现无冲突）。
- `backend/scripts/check-spec-number-conflicts.py` 校验本地 + open PR 间不撞号（匹配 `NNNN-slug.md`）。
