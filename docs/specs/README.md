# Specs

本目录是 auto-designer 的设计活快照，由 `spec-driven-development` skill 管理。

- 每个 `<NNNN-slug>/` 是一个 spec 组，基本单位是 Task（`tasks/T*.yaml`）。
- `OVERVIEW.md`（全局看板）与各组 `<NNNN-slug>/summary.md`（人读方案）均由 `spec render` 自动生成，**勿手改**。OVERVIEW 含名词解释、全局看板、关系图、文件冲突、**设计文件结构**（各 Task `files` 并集铺成的目录树，标注归属 Task）、各 feature 详情。
- `glossary.yaml`（仓级名词表）是 OVERVIEW 中**唯一可手工维护**的源：列 `term/category/def`，渲染进「名词解释」段；改名词解释改它后 re-render，仍不手改 OVERVIEW。
- prose 字段（尤其 `summary`，会原样进 `summary.md`）用**精简、精确、学术化**的语言，不堆比喻。
- 每组写一段组级 `overview` 导语：渲染在 `summary.md` 开篇与 OVERVIEW 各 feature 段，讲清本组在闭环中的位置、交付什么、串起各 Task 的数据流脊柱。没有它，summary 一上来就是 Task 依赖图，读着发懵。
- 只驱动 CLI，不手写/手改 YAML 树：

  ```bash
  ./skills/spec-driven-development/spec new <slug> --issue <N> --title "<标题>"
  ./skills/spec-driven-development/spec set-overview <NNNN> --file overview.md   # 组级导语（多行/含 mermaid 用 --file）
  ./skills/spec-driven-development/spec add-task <NNNN> --id T1 --title ... --files ... --scope ... --acceptance ...
  ./skills/spec-driven-development/spec validate
  ./skills/spec-driven-development/spec render
  ```

## 编号规则

- 组号 = 当前最大号 + 1，由 `spec new` 自动分配。
- 一个组 ≤ 6 个 Task；超了就拆组。
- 同组内各 Task 的 `files` 必须互不相交（便于并行实现无冲突）。

## 现有组

- `0001-user-agent-harness-usage` — 用户 agent 使用 harness 的最小链路（用户侧 a）。
