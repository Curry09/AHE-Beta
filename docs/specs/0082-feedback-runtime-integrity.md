---
number: "0082"
title: 反馈源码、direct 证据与超时边界一致性
issue: 0
slug: feedback-runtime-integrity
summary: 按试用 SHA 绑定需求源码，保留 direct 实际执行记录，给内部预算留出收尾余量，并有界重试无提交的分诊。
tasks:
- id: T1
  title: 需求角色按试用源码快照取证
  status: done
  priority: P1
  tags: []
  depends-on: []
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/demand/source.py
  - backend/ahe_beta/demand/agent_runtime.py
  - backend/ahe_beta/demand/evidence_contract.py
  - backend/ahe_beta/loop/feedback_pipeline.py
  - backend/ahe_beta/loop/orchestrator.py
  - backend/ahe_beta/experiment/controllers/feedback.py
  - backend/agent_defs/triage_agent/agent.yaml
  - backend/agent_defs/architect/agent.yaml
  - backend/agent_defs/divergent_pm/agent.yaml
  scope: 只读提交导出，跨线程传播；历史报告绑定来源 SHA。
  acceptance: seed 工作树不动；角色读取 full SHA；缺失提交不得回退。
- id: T2
  title: 产品预算与基础设施截止分离
  status: done
  priority: P1
  tags: []
  depends-on: []
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/harness/budget.py
  - backend/ahe_beta/harness/launcher.py
  - backend/ahe_beta/experiment/context.py
  - backend/ahe_beta/experiment/schemas/experiment-v2.json
  - backend/tests/test_experiment_local_backend.py
  scope: schema 2 冻结预算与收尾余量，两后端共用传递路径。
  acceptance: 收尾回复可在余量内返回；强停来源可查；旧配置身份不变。
- id: T3
  title: 保存 direct 实际收到的执行记录
  status: done
  priority: P1
  tags: []
  depends-on:
  - T2
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/loop/sim_user.py
  - backend/ahe_beta/demand/session_timeline.py
  - backend/tests/user/test_direct_session.py
  scope: 在现有 sim_user 适配器保存收到的完整进度与回复步骤，查询阶段统一投影 timeline/beat/step。
  acceptance: direct 与模拟交互对收到的步骤同样完整落盘，长正文和中间索引不丢失；查询共用摘要/展开上限；不伪造 SimTrace 或用户中途评阅；保留授权边界。
- id: T4
  title: 有界分诊收尾与完整验收
  status: done
  priority: P1
  tags: []
  depends-on:
  - T1
  - T2
  - T3
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/demand/triage.py
  - backend/tests/test_feedback_runtime_integrity.py
  - backend/tests/test_experiment_config_v2.py
  - backend/tests/test_experiment_engine.py
  - docs/CONFIGURATION.md
  - docs/CONFIGURATION.zh-CN.md
  scope: 缺提交正常返回补一次八迭代调用，文档与独立验证。
  acceptance: 最多两次；无提交仍失败；本地实进程与独立 E2B 验证；旧实验不改写。
---

# 0082 · 反馈源码、direct 证据与超时边界一致性

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

将需求角色的源码视图绑定到用户实际试用的完整提交 SHA；给产品内部请求预算保留独立的基础设施收尾余量；保存 direct 请求中已收到的进度、回复步骤和终止来源。分诊正常返回但没有结构化提交时，只补一次有界收尾，仍保留失败门禁。

## Motivation

N8 全 direct 对照在第二轮分诊退出：首个调用耗尽迭代后未提交 disposition，恢复门禁阻止继续交付。恢复时发现需求角色读取 seed 工作树，而用户已试用后续提交；即使随后提交成功，其源码归因仍可能错误。旧 N8 也存在这一源码错位，不能归因于 persona 复用。

direct 原先只有任务和终态评阅，没有 SimTrace；timeline/beat 工具无法读取已收到的执行进度。产品默认预算和 launcher 绝对截止同为 1800 秒时，外层可能抢先强停，使产品来不及提交超时说明。上述问题分别属于源码身份、证据可见性和监督截止，不应通过开放运行目录、伪造轨迹或放宽恢复门禁解决。

## Guide-level explanation

普通及追加轮次在反馈阶段导出试用 SHA 的只读源码视图，角色读取它，交付 checkout 不变。处理历史积压报告时，分诊读取报告来源 Session 的 SHA。角色记录保留源码 SHA 与导出目录；导出目录在阶段结束后删除，可凭 SHA 重建。

公开 schema 2 可声明以下 runtime 配置片段：

```json
{
  "runtime": {
    "harness": {
      "request_budget_seconds": 3600,
      "termination_grace_seconds": 60
    }
  }
}
```

任务正文中的“3600 秒”不等于配置预算。launcher 将显式预算传给消息及兼容产品环境，外层在 3660 秒后才强停。产品是否实现内部预算仍由所选 Harness 决定。未配置时不改变旧冻结输入，只为既有 launcher 上限和可识别的产品环境期限增加默认 60 秒余量。

新 direct Session 保存 `execution_record` 和实际步骤，与模拟交互一样完整保存平台收到的内容，timeline/beat/step 查询时再按共同上限投影。persona 仍只接收终态回复并评阅一次，不在中途收到进度或新增互动。未收到的内部执行未知，旧 direct 记录不会被补造。

## Reference-level explanation

### 源码身份

`HarnessSource` 用 ContextVar 绑定仓库及 full SHA，通过 `git archive` 懒导出到临时目录，无 `.git` 或交付运行文件，文件与目录只读。首次真实读取验证提交存在及 SHA 完整；错误直接阻止角色运行，不回退工作树。反馈阶段共用一个导出视图；线程池和模型线程复制上下文。单条历史报告可嵌套绑定自己的 SHA，结束后恢复本轮上下文。

`run_agent_def` 逐调用设置 NexAU 本地 sandbox 的 work_dir，避免以共享环境变量传递并发角色的源码目录。源码身份写入 invocation evidence。缺失旧 envelope 身份时，只从 Session provenance 或可信观测收据补读，不修改旧 Session，也不从用户自由文本猜 SHA。报告没有可用身份时继续标为 unavailable。

### 预算与终态

`runtime.harness` 可选；填写时要求正数 `request_budget_seconds`（最多 86400），可选正数 `termination_grace_seconds`（最多 300，省略为 60）。local/e2b 使用同一冻结环境映射，不继承宿主机设置，不给旧规范化配置增加默认字段。

launcher 将显式预算写入 message 的 `budget_seconds`，并设置 `HARNESS_TASK_BUDGET_SECONDS`、`HARNESS_CALL_TIMEOUT`、`HARNESS_TURN_TIMEOUT` 兼容变量；Docker 在构造运行参数前完成映射。外层终止期限为显式预算加余量。无显式预算则为既有 1800 秒上限与有效旧环境期限的最大值加余量；无效旧变量保留原有 fallback 行为，新的公共变量严格拒绝无效值。

request outcome 保留产品预算、基础设施期限、余量及终止来源。强停记为 infrastructure；产品正常协议回复记为 harness_reply。基础设施超时只证明未及时收到回复，不宣称 API 故障或活锁已确认。

### Direct 证据

在现有 `loop/sim_user.py` 的 direct 适配器中收集 launcher 实际收到的 stdout 观测和原生回复步骤，按既有模拟交互的落盘原则完整保存收到的列表、正文和元数据。缺少原生步骤时，仅从真实 progress 帧导出；原始帧仍在 events 中完整保存。异常结束也在关闭连接前保存。不单独新增 records 模块，不设置 direct 专属的记录条数或正文字数上限。

两种模式共用 `demand/session_timeline.py` 的查询限制：beat 最多返回 80 项，工具摘要 220 字符、结果摘要 280 字符；step 单次展开最多 6000 字符。direct 的 L2 stdout 摘要最多 8 项、每项 160 字符，只返回声明的摘要字段，不能把完整 raw 帧顺带带入查询结果。截断只发生于查询投影，原始中间 step_i 不重新编号，超过查询限制的正文仍保存在 Session 中。Harness 或上游生产者自己未输出或已截断的内容不能补造。

direct 投影明确 `interaction_mode: direct`、`reviewer_visibility: terminal_reply_only`，beat 使用现有真实请求和回复，不创建 SimTrace 或 goal ledger。L2/L3/L4 权限沿用现有工具边界，不扩大原始 Session 文件权限；观测包 not_supported 仍为 not_supported，不能用新记录推断绝对路径文件是否存在。

### 有界收尾与恢复

仅首个分诊调用正常返回但缺少 `dispositions` 数组时，再调用一次同角色，最多 8 次迭代，提示证据不足应提交 needs_info。第二次以原报告及可用证据重新开始，不携带第一次未保存的推理。异常不吞掉，不无限重试，不强制接受或合成 disposition；两次仍无提交沿用原失败门禁与检查点恢复。

## Drawbacks

导出源码增加短暂磁盘占用，缺失提交会显式失败。余量增加最坏等待时间；有界收尾仍可能失败且多消耗一次模型调用。完整保存收到的长日志可能增大 Session 体积，查询仍有截断；这些记录不等于完整模型或子 Agent 轨迹。只读文件模式和现有工具 jail 不等于恶意代码的 OS 隔离。

## Rationale and alternatives

不 checkout/reset 共享交付仓库，避免与 OpenAgents 并发修改冲突。不允许读取 `.openagents/worktrees` 来寻找版本，以保持证据边界并防止读取错误运行产物。不统一把外层期限设为无限，也不根据任务自然语言偷偷修改预算。不给 direct 伪造模拟用户决策或评分，保持原交互对照口径。不把缺提交自动当成 needs_info；该判断必须由角色显式提交。

## Prior art

现有冻结 user_sha、RecoveryStore 阶段门禁、角色 UsageContext、Session transcript、launcher progress 和请求状态提供实现所需的身份与观测。Spec-0080 只处理画像复用身份；Spec-0081 的独立任务环境设计仍待实施。

## Unresolved questions

本次不判定旧 N8 受源码错位影响的提案是否都错误，也不改写既有结果。旧实验已暂停并归档；其冻结 controller 不自动升级。独立验证通过只证明修复路径可用，不能证明五轮实验已经恢复或完成。

## Future possibilities

可用修复后的冻结 controller 重新执行对照，并审计旧提案的源码依据；完整内部轨迹和独立 E2B 任务沙箱须分别设计。更多重试策略应基于实测失败类别，不能扩展为无限重试。

