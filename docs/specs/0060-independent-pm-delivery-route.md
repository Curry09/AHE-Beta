---
number: "0060"
title: 独立 PM 路线与双轨交付协调
issue: 0
slug: independent-pm-delivery-route
summary: PM 独立交给 Owner，不进入 Synthesizer 的输入和证据授权；Synthesizer 综合交付路线提案；Owner 显式关联共享工作并保留独立验收。
tasks:
  - id: T1
    title: 双轨角色边界与协调契约
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/demand/synthesizer.py
      - backend/auto_designer/demand/owner.py
      - backend/auto_designer/demand/agent_contract.py
      - backend/auto_designer/loop/orchestrator.py
      - backend/agent_defs/synthesizer/systemprompt.md
      - backend/agent_defs/divergent_pm/systemprompt.md
      - backend/agent_defs/owner/systemprompt.md
      - backend/agent_defs/owner/tools/submit_admission.tool.yaml
      - backend/agent_defs/synthesizer/tools/submit_rfcs.tool.yaml
      - CLAUDE.md
    scope: 从 Synthesizer 输入及证据授权排除 PM；Owner 标注 delivery_overlaps 但不吞并独立目标。
    acceptance: PM proposal/ready 不进入 Synthesizer 输入；引用 PM 被按不可见来源拒绝，covers 不能关闭 PM；Owner 保持独立交接。
  - id: T2
    title: 角色与跨轮观测回归和实验审计
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/tests/demand/test_role_contract_flow.py
      - backend/tests/demand/test_owner.py
      - backend/tests/demand/test_observation_provider.py
    scope: 验证双轨无损交接和更名换格式的跨轮读取；审计真实两会话取证，区分读取兼容与自动发布缺口。
    acceptance: 相关测试通过；按角色记录取证成效与语义局限；不把单版本两会话误报成多轮闭环。
---

# 0060 · 独立 PM 路线与双轨交付协调

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

恢复独立产品路线：PM → Owner，与 Triage → Synthesizer → Owner 汇合。Synthesizer 不读取
PM 提案，不能引用或关闭 PM，也不能将 PM 的产品洞察重写为结构提案。Owner 识别
跨路线共享工作，用关联和独立验收表达，不恢复产品价值审核或随意的语义合并。

## Motivation

0059 两会话实验中，PM 的三条提案全部被结构提案吸收。综合减少了重复报告，但也让
PM 产品目标只能以结构方案的形式进入交付。例如“随时纠偏、查询和控制调查投入”被
进一步统一为阶段边界，证据并未证明这些能力必须共享该边界。独立发现不等于独立交付。

## Guide-level explanation

第一拍仍并行运行 Triage 与 PM，第二拍运行 Synthesizer，随后 Owner 批量接收两条路线。
这里的独立是语义路由和交付资格，不承诺 PM 完成后立即提前调用 Owner。

Synthesizer 只看到交付路线的开放提案和 ready 工作项。PM 的 provenance 为 `from-divergent`，
历史 `divergent` 同样被筛除，包括已准入的 PM 工作项。没有结构产物、Synthesizer 失败或
模型越权，都不会消除 PM。保留原有跨提案综合要求，不再额外计算“非 PM 来源数量”。

Owner 通过可选 `delivery_overlaps` 引用可见 proposal/ready，在 handoff 中说明共享工作
与各自验收边界。相关但目标不同的两票分别 admit；关联不创建依赖、不关闭票，也不自动
安排同一实现。交付侧决定任务拆分与实现复用。

## Reference-level explanation

Synthesizer driver 在组装任何输入前按 provenance 筛除 PM，正常调用与协议恢复调用复用
同一筛选结果。ProposalView、ready、可引用来源、covers 集合及 session 授权均由该
结果生成。若模型自行引用 PM 票号，既有来源检查返回 `foreign-source` 并记录
`rejected_proposals`；不增加 PM 特有的来源计数规则。有效结构票只继承其引用的可见
来源 session。PM-only session 不因存在一张 PM 票就获得 Synthesizer 的取证授权。

Owner 的 schema 新增可选整数数组 `delivery_overlaps`，driver 过滤自身、report、未知票
和非整数，并记录 invalid 元数据，不因协调字段非法而丢掉交接。关联随交接注释保存，
保留 automation 身份。原有精确重复兼容路径不变；非精确重复仍不能 merge。

T1 修改职责 prompt、schema、driver 与架构说明；T2 验证越权保护、真实固定产物回放和
跨版本观测读取。当前可复现检查见[验证方法](../VERIFICATION.zh-CN.md)。

## Drawbacks

交付票可能增多，OpenAgents 仍需要消费交接注释并协调共享实现。关联只能显式表达重叠，
不能机械保证模型发现全部重叠或交付侧不重复开发。PM 技术化表达也不能靠路由修改自动消除。

## Rationale and alternatives

拒绝继续让 Synthesizer 整体吸收 PM，因为这会把两种认知视角最终压成一种结构语言。
本组初版采用“可参考、不可吞并”，后按用户澄清改为输入隔离：Synthesizer 不需要先看 PM
再遵守一组使用例外。产品与结构视角只在 Owner 汇合，不恢复额外价值评审或实现层裁决。

## Prior art

0029 区分 discovery/delivery，0043 保留 PM 产品视角。0052 将开放来源吸收交给 Synthesizer；
本组收窄其输入与权限，排除 PM，并补充 Owner 的跨路线交付关联。0059 取证工具不变，
Synthesizer 的授权仍由可见提案引用派生，因此随输入筛选收窄。

## Unresolved questions

新 prompt 尚未做真实模型双轨对照与交付后效果评测。0059 的生产制品观测发布、版本校验与
旧包留存闭环也未因本组自动补齐；本组审计该缺口，不把实验专用导出器部署到生产。

## Future possibilities

在同一固定体验集上评估产品目标保真与重复交付，再跑至少两轮“交付合并→新版本用户”验证。
制品负责随版本更新日志和说明，平台只负责稳定外壳、受限导出、版本关联、留存与授权。
