# Specs

本目录是 auto-designer 的设计活快照，由 `spec-driven-development` skill 管理。

- 每个 `<NNNN-slug>/` 是一个 spec 组，基本单位是 Task（`tasks/T*.yaml`）。
- `OVERVIEW.md`（全局看板）与各组 `<NNNN-slug>/summary.md`（人读方案）均由 `spec render` 自动生成，**勿手改**。
- prose 字段（尤其 `summary`，会原样进 `summary.md`）用**精简、精确、学术化**的语言，不堆比喻。
- 只驱动 CLI，不手写/手改 YAML 树：

  ```bash
  ./skills/spec-driven-development/spec new <slug> --issue <N> --title "<标题>"
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
