# Synthesizer 提案分组

提案分组将相关需求分配给同一个 Synthesizer，减少重复处理，并保留需要一起讨论的上下文。分类器只决定哪些提案适合共同综合；提案的发布、关闭和准入仍由原有流程负责。

## 配置

在实验 JSON 中设置以下策略，再准备并启动新实验：

```json
{
  "policies": {
    "synthesizer_grouping": true
  }
}
```

这是合入完整实验定义的配置片段。该策略默认为 `false`，启用值在 `prepare` 时固定，并由 local 和 E2B 后端传递给控制器。宿主或凭证文件中的 `SYNTHESIZER_GROUPING` 不覆盖实验配置。已有 run 继续使用其冻结设置。

分组也适用于单用户实验。Synthesizer 数量由 `roles.synthesizer` 指定；U1 产生多条相关提案时，同样可以启用。完整字段见[配置说明](CONFIGURATION.zh-CN.md#运行策略)。

## 调度过程

非末轮按以下顺序处理需求：

1. 等待本轮全部 Triage 完成，收集非 PM 的开放提案。
2. 调用一次分组模型，输入提案 ID、标题及最多 1200 字符的摘要。
3. 校验返回的 `{"groups": [[1, 2], [3]]}`，确保每个输入 ID 恰好出现一次。
4. 将各组拆成每批最多 6 条的任务。同组批次由同一个 Synthesizer 实例顺序处理，不同组可并行。
5. 将综合结果交给 Owner 准入，再等待代码交付。

Divergent PM 保持独立的 Owner 准入路径。单条来源保留给 Owner，不强制生成综合提案。每个批次仅能引用自己的来源，沿用 `source_proposals` 和 `covers` 校验。

## 失败处理与记录

分组模型沿用 Synthesizer 的连接配置，输出上限为 16384 token，请求超时为 300 秒，SDK 不自动重试。请求失败、输出截断、JSON 无效或 ID 重复／遗漏时，调度器回退到按 ID 排序、每批最多 6 条的串行综合。

某个 Synthesizer 批次失败时会记录错误，其余批次继续，未处理的开放来源仍留在队列中。读取 Gitea 队列时会遍历分页；分页读取失败会报错，不使用不完整的提案列表继续分组。

分组输入、模型输出、耗时、回退原因和批次结果保存在本轮角色记录的 `synthesizer_grouping/` 下，用量进入现有 Token 统计。分组记录写入失败会告警，提案处理仍继续执行。

每批 6 条是数量限制，不保证满足任意模型的上下文窗口。同组批次仍各自调用模型，不共享连续对话；分组本身也不保证提案已经完成语义去重。实际效果应结合提案和交付结果评估。

## 开发验证

安装开发依赖后，可运行相关回归测试：

```bash
uv run --locked --extra experiments --extra dev pytest backend/tests/demand/test_grouped_synthesizer.py backend/tests/loop/test_synthesizer.py backend/tests/test_stage_resume_e2e.py
```
