# 一次分组，按组综合

多个 Synthesizer 直接读同一份待办，会重复处理同一来源；按 issue 编号切批，又会拆散相关提案。
前置分类只回答一个问题：哪些提案适合一起综合？分类结果不拥有关闭、合并或改写提案的权限。

非末轮的顺序为：全部 triage 完成 → 一次分组 → Synthesizer 按组工作 → Owner → 等待交付。
PM 继续独立到 Owner。分组输入仅含非 PM 的开放 proposal/ready 的 ID、标题和最多 1200 字符规范化摘要。
模型只返回 `{"groups": [[1, 2], [3]]}`；代码检查每个输入 ID 恰好出现一次，再切成最多 6 条的批次。
每个组由同一个已有 Synthesizer 实例顺序处理；不同组可以并行。各批次只暴露自己的来源，沿用
Synthesizer 既有的 `source_proposals` / `covers` 校验、发布和关闭逻辑。单条来源不做强制综合，保留给 Owner。

一次模型请求使用 Synthesizer 的连接配置，输出预算为 16384 token，请求超时为 300 秒，SDK 不重试。
请求失败、输出截断、非法 JSON、重复或遗漏 ID 时，回退到按 ID 排序、每批最多 6 条的串行综合。
某批 Synthesizer 失败会记录错误，其他批次继续；仍开放的来源留在队列中。Gitea 开放队列读取会遍历分页，
后页失败不会伪装成一份完整输入。

## 启用

正式入口 `backend/run.py` 和 `backend/scripts/run_swebench_closed_loop.py` 共用
`auto_designer.demand.grouped_synthesizer`。启用环境变量为：

```sh
SYNTHESIZER_GROUPING=1
N_TRIAGERS=16
N_SYNTHESIZERS=2
N_DEVELOPERS=8
```

审计实验配置使用 `execution.synthesizer_grouping: true`，编制使用
`roster.triager: 16`、`roster.synthesizer: 2`、`roster.developer: 8`；交付并发容量也应设为 8。
启动器据此导出环境变量，沿用现有 `NO_PROXY=*` 直连策略。未开启时保留原有编排。
历史实验 pack 保留其独立快照；后续冻结正式实验时应包含本模块和已确认的最新开发镜像。

## 可验证的边界

- 分类器只读，不把同组视为可合并或可关闭。
- 两个 Synthesizer 不会同时领取同一条冻结的来源；同组大于 6 条时仍由同一实例顺序处理。
- 每批独立调用模型；同一实例不意味着跨批共享对话，也没有额外的跨组引用或语义去重系统。
- 6 条只是数量上限，不是 token 窗口保证。错误分类仍可能拆散相关提案，正式效果需要实验验证。
- 分组用量进入现有 usage 记录；分组输入、输出、耗时、回退原因与批次结果保存在本轮
  role run 的 `synthesizer_grouping/`。记录写入失败只告警，不丢弃提案工作。

两轮历史只读模型回放均完整返回，每轮 27 条提案无遗漏、无重复。第一轮 9 组、6285 输出 token、
约 81 秒；第二轮 13 组、10143 输出 token、约 129 秒。这验证了调用预算和基本分组输出，
不等于已验证后续开发效果。

当前离线回归入口为：

```sh
uv run --locked --extra dev pytest backend/tests/demand/test_grouped_synthesizer.py backend/tests/loop/test_synthesizer.py backend/tests/test_stage_resume_e2e.py
```

角色与恢复阶段使用 `synthesizer`。冻结 pack、配置和回放结果不原地更新，需要使用时由开发者准备相应输入。历史模型回放与当前源码的真实模型验收分别记录。
