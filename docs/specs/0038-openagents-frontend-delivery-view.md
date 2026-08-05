---
number: "0038"
title: OpenAgents 交付面独立页面与大楼结合预研
issue: 0
slug: openagents-frontend-delivery-view
summary: 前端新增 OpenAgents 独立交付面页面：以现有 Gitea-derived API 展示 openagents/ready/PR/needs-human/conflict/main 流程并支持轮次过滤；大楼结合暂不落代码，后续以单独设计任务重做园区/厂房关系。
tasks:
  - id: T1
    title: OpenAgents 独立页入口与 URL 状态
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - frontend/src/types.ts
      - frontend/src/App.tsx
      - frontend/src/components/TopBar.tsx
    scope: 新增 view=openagents 作为独立页签，沿用现有 query string 状态；TopBar 增加 OpenAgents 切换；OpenAgents 页支持轮次下拉，URL 保留 round 参数；不引入 react-router。
    acceptance: 顶部可在看板/大楼/OpenAgents 间切换；刷新 ?view=openagents&round=N 仍保持页面与轮次；默认看板和 view=building 行为不回退。
  - id: T2
    title: OpenAgents 数据聚合模型
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - frontend/src/components/openagents/openAgentsModel.ts
      - frontend/src/lib/issueMeta.ts
    scope: 新增纯前端聚合模型，复用现有 issueMeta 派生逻辑，把 /api/issues、/api/delivery、/api/commits、/api/state 汇总为 OpenAgents snapshot：openagents/ready issue、PR、needs-human、conflict、main commits、round sha 与 KPI。阶段判定遵循交接协议：同时带 openagents 与 ready 时归入 ready（vigil 已 intake），仅带 openagents 时归入 openagents。支持 round=all 或指定轮次过滤；不引入 mock，不新增后端 API。
    acceptance: null/connected=false/empty 三类状态都可安全且可区分处理，断连数据源的 KPI 显示未知而非 0；指定轮次时 issue 按 round-N 过滤、PR 按 closes_issues 关联过滤、commit 按 round_shas anchor 过滤；指定轮次所需的 issue 关联或 round SHA 不可用时不得回退展示全量数据；TypeScript build 通过。
  - id: T3
    title: OpenAgents 独立页面 UI 与样式
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - frontend/src/components/openagents/OpenAgentsView.tsx
      - frontend/src/styles.css
    scope: 新增 OpenAgents 独立页面，只读展示 openagents → ready → PR → needs-human/conflict → main 的交付面流程；页面复用现有 SidePanel 打开 issue/commit 详情，PR 仅外链到 Gitea。样式沿用现有 token 与深浅主题，不做操作按钮，不把 OpenAgents 内部 work_queue/timing/stream 作为首版依赖。
    acceptance: ?view=openagents 可查看独立页面；页面展示数据源状态、轮次状态、流程站点与空态；无真实数据时不显示假卡片；needs-human/conflict 有文字标签；npm run build 通过。
  - id: T4
    title: 大楼结合：园区/厂房关系重设计
    status: pending
    priority: P2
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - frontend/src/components/BuildingView.tsx
      - frontend/src/components/building/BuildingTower.tsx
      - frontend/src/components/building/FloorWorkspace.tsx
      - frontend/src/components/building/buildingModel.ts
    scope: 重新设计 OpenAgents 与 Agent Company 大楼的结合方式。目标是表达需求面大楼与 OpenAgents 交付面的空间关系，但不能把临时厂房/无人机/H 标志实现直接堆进现有大楼；需要先形成视觉方案与交互边界，再实现。候选方向包括园区视图、主楼侧后方交付建筑、或从交付面楼层跳转到独立 OpenAgents 页。样式文件与具体实现应在后续实现任务或新 spec 中单独分配，避免和本组已完成独立页样式任务重叠。
    acceptance: 有明确视觉方案后再动代码；默认大楼布局不被挤窄；OpenAgents 独立页仍可直接进入；大楼结合不引入新产品术语覆盖 OpenAgents 状态词；build 通过。
---

# 0038 · OpenAgents 交付面独立页面与大楼结合预研

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

本组为 auto-designer 前端补一个独立的 OpenAgents 交付面页面。它不是新的后端能力，也不是 OpenAgents 内部 UI 的搬运，而是在 auto-designer 现有只读观测面中，以 Gitea-derived API 展示 spec-0032 之后的交付流：`openagents` 交接令牌、`ready` 队列、OpenAgents 产生的 PR、`needs-human` / `conflict` 卡点，以及 main commit / round SHA 回灌。

当前已落地的是独立页面：顶部增加 `OpenAgents` 页签，URL 为 `?view=openagents`，支持 `round=N` 轮次过滤，右侧复用现有 SidePanel 查看 issue/commit 详情。页面不新增后端 API，不读取 OpenAgents 内部 `.openagents` 状态文件，也不提供 approve/retry/merge 等写操作。

大楼结合是本组的后续任务而非当前实现。刚性要求是：不能把临时厂房/无人机/H 标志等未成型视觉直接塞进现有 Agent Company 大楼；后续必须先形成园区/厂房关系的视觉方案，再实现，并保证默认大楼布局不被挤窄。

## Motivation

spec-0032 把交付面从 auto-designer 进程内 dev agent 换轨到外部 OpenAgents vigil。现有大楼视图和 SidePanel 虽然已显示「交付面 · PR」，但表达粒度仍偏碎：用户只能在 Issues、DeliveryPanel、Main commits 之间跳读，难以直接看到「Owner 准入后的活怎样进入 OpenAgents、怎样开 PR、哪里卡住、最后如何推进 main」。

需要一个独立页面先把 OpenAgents 交付面讲清楚：它服务于观察自进化进度，不服务于人工操作；它使用 auto-designer 已经拥有的观测 API，避免把 OpenAgents 内部运行时耦合进来；它保留 OpenAgents/Gitea 的真实状态词，避免用「入库/出货/红牌」等临时隐喻替代产品语义。

同时，用户希望后续把 OpenAgents 和 Agent Company 大楼结合起来，形成需求面大楼与交付面之间的空间关系。但之前的临时尝试暴露出问题：视觉方案不明确会导致布局挤压、厂房比例失真、隐喻文案过重。因此该方向必须作为独立 pending 任务重新设计，而不是保留失败实现。

## Guide-level explanation

用户仍可打开原有看板和大楼：

```text
/
/?view=building
```

新增 OpenAgents 页面：

```text
/?view=openagents
/?view=openagents&round=3
```

顶部页签为：

```text
看板 | 大楼 | OpenAgents
```

进入 OpenAgents 页后，页面展示五段只读流程：

```text
openagents → ready → PR → needs-human / conflict → main
```

- `openagents`：Owner admit 后打上的交接令牌。
- `ready`：OpenAgents/vigil 可处理或已 intake 后的工作队列投影。
- `PR`：`/api/delivery` 返回的 open PR。
- `needs-human / conflict`：交付面需要人工处理或 mergeability 明确冲突的卡点。
- `main`：最近 main commits 与 round anchor。

轮次下拉在 OpenAgents 页同样可用。选择某一轮时：issue 按 `round-N` 标签过滤；PR 按 `closes_issues` 关联到该轮 issue 过滤；commit 按 `/api/state.round_shas[N-1]` 匹配 anchor 过滤。选择「全部轮次」时展示当前可观测全量。

点击 issue 或 commit 仍使用现有 SidePanel 详情；点击 PR 打开 Gitea 外链。页面没有任何写操作。

## Reference-level explanation

**入口与 URL 状态（T1）**：`frontend/src/types.ts` 的 `ViewMode` 增加 `openagents`。`frontend/src/App.tsx` 的 `parseView` 识别该值，URL 同步逻辑写入 `view=openagents`，并保留 `round=N`。`frontend/src/components/TopBar.tsx` 增加 OpenAgents 页签；在该页展示轮次下拉，但不展示「运行中 / + 已完成」这组需求面历史过滤器，避免误解该开关会影响交付面数据。

**聚合模型（T2）**：`frontend/src/components/openagents/openAgentsModel.ts` 是纯前端模型层，不含 React。输入为 `IssuesResponse | DeliveryResponse | CommitsResponse | RunState` 与可选 round，输出 OpenAgents snapshot。它复用 `frontend/src/lib/issueMeta.ts` 的 `planeOf/roundOf/priorityOf/issueKind/ageDays`，保持与后端 issue schema 的前端兜底逻辑一致。

聚合口径：

- openagents issues：open issue 且 labels 含 `openagents`、不含 `ready`，表示 Owner 已交接但 vigil 尚未 intake。
- ready issues：open issue 且 labels 含 `ready`，或不含 `openagents` 但 `planeOf(issue) === "ready"`；若同时含 `openagents` 与 `ready`，`ready` 优先，表示 vigil 已 intake。
- needs-human issues：open issue 且 labels 含 `needs-human`。
- PR：`/api/delivery.pulls`，指定轮次时按 `closes_issues` 与该轮 issue 集合关联过滤。
- conflict PR：`pull.mergeable === false`。
- main commits：`/api/commits`，指定轮次时只保留命中对应 round SHA 的 commit。

`null` 表示仍在读取，`connected=false` 表示数据源不可用，已连接但数组为空才表示真实的 0/空态。指定轮次依赖 issue 关联来筛 PR、依赖 round SHA 来筛 commit；任一过滤依据不可用时，对应结果保持空且显示数据源/轮次不可用，不得降级成全量 PR 或 commit。

**页面与样式（T3）**：`frontend/src/components/openagents/OpenAgentsView.tsx` 渲染数据源状态、KPI、轮次状态条、流程站点和空态。`frontend/src/styles.css` 增加 OpenAgents 页面样式，沿用现有 CSS token、深浅主题、chip/empty/disconnected 等视觉语言。页面内可保留轻量流程/流水线视觉，但文案必须使用 OpenAgents/Gitea 状态词。

**大楼结合（T4 pending）**：相关文件列在任务中，但当前代码不应包含该方向的实现。后续实现前，需要先决定是园区视图、主楼侧后方交付建筑、还是交付面楼层跳转入口。验收重点是：默认大楼不被挤窄；OpenAgents 独立页仍可直达；视觉隐喻不覆盖真实状态词；不把未验证的布局实验留在主线。

## Drawbacks

首版仍是结果态/观测态页面，不是 OpenAgents 内部运行态页面。它看不到 vigil worker、SQLite queue、stage dwell time、agent stream 或 timing p50/p90；这些数据如果需要，需要后续定义结构化 API 或明确读取 OpenAgents 运行态文件的边界。

`/api/delivery` 当前只返回 open PR，因此页面不计算完成率、转化率或历史吞吐。指定轮次时 PR 过滤依赖 `closes_issues` 与 issue round 标签；如果 PR body 未声明 closes/fixes/resolves，则无法可靠归属到轮次。

OpenAgents 与大楼结合暂不落代码，意味着当前仍需要用户从顶部页签进入独立页面，不能在 Agent Company 大楼内直接看到交付面全貌。

## Rationale and alternatives

选择独立页优先，是因为当前已有 API 足以支撑一个稳定、低耦合、只读的交付面页面；而大楼结合属于视觉表达与空间关系问题，风险在布局和信息层级，不应阻塞交付面观测能力。

未选择直接接 OpenAgents desktop daemon。OpenAgents 仓已有 `openagents board` 与 Electron/React desktop，但它们面向 OpenAgents 自身运行态，且部分实时 stream 是进程内 ring buffer，不适合作为 auto-designer 首版稳定依赖。auto-designer 现阶段应优先读自己的 Gitea-derived API。

未选择在现有 SidePanel 内继续加更多 DeliveryPanel 内容。SidePanel 空间窄，适合摘要和详情，不适合展示跨 issue/PR/main 的交付流程。独立页能保留 SidePanel 作为证据区，同时给流程本身足够空间。

未选择立即把厂房/无人机/H 标志放进大楼。该方向用户仍认可为待探索，但需要更好的设计；临时实现已回滚，不应进入 spec 的 done 范围。

## Prior art

- spec-0032：需求面与交付面二分，Owner 通过 `openagents` 交接令牌把工作交给 OpenAgents vigil。
- spec-0034：Agent Company 大楼视图，强调需求面角色空间化展示，并保留交付面作为 OpenAgents/PR/main 推进语义。
- OpenAgents 自身已有 `openagents board` 和 desktop app 方向，可作为后续内部执行态可视化参考，但不是本组首版依赖。
- 当前 auto-designer 前端已有 `DeliveryPanel`、`SidePanel`、`issueMeta`、`/api/delivery` 等可复用基础。

## Unresolved questions

1. 大楼结合的最终空间关系：是园区视图、主楼侧后方厂房、还是从交付面楼层跳转到独立页。
2. 如果后续需要 OpenAgents 内部执行态，应该由 auto-designer 后端暴露新只读 API，还是复用 OpenAgents daemon/board 契约。
3. PR 历史与吞吐指标是否需要 `/api/delivery?state=all` 或 PR detail API 支撑。
4. 轮次归属是否应在后端提供显式字段，避免前端用 issue labels 与 PR closes 关系推断。

## Future possibilities

- T4 完成后，大楼页可变成更完整的「需求面大楼 → OpenAgents 交付面」园区视图，但必须先出视觉方案。
- 后端可新增只读 delivery history API，支持 merged/closed PR 与阶段耗时。
- 如果 OpenAgents 输出结构化事件流，前端可在独立页增加 worker/queue/stage/timing 面板。
- OpenAgents 页可支持按 issue/PR/main commit 的连线视图，展示从 proposal admit 到 PR merge 的端到端链路。

