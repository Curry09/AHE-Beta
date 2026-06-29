本仓在做 **harness 自进化**。直接对轨迹做自进化，会把轨迹特征带进 harness、以 benchmark 分数为优化目标而过拟合，只能针对具体问题局部打补丁，难有结构性改进。本仓的根本做法是**训练信号与测试分离**：训练信号取「模拟真实使用」分布上的**用户体感**，benchmark 全程 **held-out**，只在事后验证体感驱动的进化是否带来真实能力提升——不进训练、不进发版门禁。

为此模拟一条「**用户使用 → 开发者迭代**」的闭环：**a｜用户侧** user agent 按 persona + 种子场景多轮使用 harness，产出体感评分（观测信号）与 issue（bug/需求）；**b｜开发者侧** 纯 trunk（单 main）无门禁——开发者 agent 是带 git 工具的 nexau agent，领 issue 后自己 checkout main → 改 harness → commit → 打 vK tag → push，直接推进主干（坏 commit 靠后续多轮迭代回正）；**c｜回灌** dev 直推后下一局用户侧自然解析到更新后的 main HEAD，循环。

被进化对象 harness 不是单个 agent，而是「可启动程序 + 黑盒对话契约」，内部 1 个或 N 个 nexau 的编排由其自带 entry 决定，源码独立托管于 Gitea；开发者 agent 直接在单 main 主干上 commit/push（无 branch/merge/release）。观测上记录 issue 数量随时间的曲线：长期不降说明 harness 在退化，过早归零说明 persona 多样性不足、探索停止。

