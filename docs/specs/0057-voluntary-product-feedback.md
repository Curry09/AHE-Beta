---
number: "0057"
title: 自主产品反馈与交互主动作并行
issue: 0
slug: voluntary-product-feedback
summary: 在原有用户动作中附带自主产品反馈，保留继续、等待、接受或放弃的语义；反馈可达性不依赖工具能力或纠偏策略，格式异常仅警告，不按低分自动提单。
tasks:
  - id: T1
    title: 主动作伴随反馈与既有提单兼容
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/user/sim/loop.py
      - backend/ahe_beta/user/sim/prompt.py
      - backend/ahe_beta/user/sim/clauses.py
    scope: 意图区分当前任务与产品反馈接收者；main_act 和 waiting_act 支持可选 report_issue，正文精确去重并在既有收尾阶段创建 issue。
    acceptance: 合法反馈不替换主动作，不新增模型调用；缺省或非法反馈不自动提单；correct persona 可自愿反馈且无需自行接管任务。
  - id: T2
    title: 动作兼容与持久化回归
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/tests/user/sim/test_feedback.py
      - backend/tests/user/sim/test_heartbeat.py
      - backend/tests/user/sim/test_prompt.py
    scope: 覆盖继续、接受、等待与终止报告；验证不同能力 persona 的同等可达性和 session 到 needs-triage 的持久化。
    acceptance: 盲评及专家 persona 均可报告；重复正文仅一条 issue；非法反馈和低分沉默不更改合法主动作；既有终止反馈可继续使用。
---

# 0057 — 自主产品反馈与交互主动作并行

## Summary

用户的主动作可伴随一条自愿的产品反馈，不必为反馈暂停、放弃或改变接受结果。
可达性不取决于 workspace 工具权限；框架保留真实报告与沉默，不根据体感分数制造 issue。

## Motivation

任务最终完成与使用体验值得改进可以同时成立。旧机制虽然有非终止的
report_issue 工具，但它只出现在部分 persona 的感知工具栈中，意图/动作阶段
又禁止工具。file_issue 则同时承担退出语义，使继续解决任务的用户很少报告。
报告体验不需要读代码能力，也不应该要求用户停止工作或证明产品根因。

## Guide-level explanation

意图阶段说明两个接收者：harness 消息推进当前任务；产品反馈供开发者改善
后续使用，不承诺立即修复当前任务。是否报告由 persona 自主选择，允许沉默。
不能根据低评分、抱怨、反复纠正或 gap 自动创建用户报告。

main_act / waiting_act 的原有 JSON 可额外携带
`"report_issue": {"body": "用户自己的反馈"}`。继续、等待、打断、接受或离开
均可同时报告，主动作和目标语义不变。字段缺省/null 表示没有报告；不额外
增加模型调用。所有 persona/client 均可使用，包括无工作区工具的 blind persona。
保留旧的感知阶段 report_issue 工具和终止报告路径以兼容已有交互。

正文描述实际经历、期望及影响，必要时说明后来已解决。无需技术诊断、证明
复现性或提供开发方案。原任务困难本身不是必须提单的理由。

## Reference-level explanation

复用 issue_notes → 会话结束时 tracker.create_issue → issue_refs 的既有路径。
原始 act 调用 trace 保留反馈选择和正文；tracker 保存正式正文；会话 issue_refs
关联正式问题供 triage 使用。后续历史注明已记录且等待收尾提交，防止模型误以为
正在由开发团队处理。相同正文在同一会话内精确去重，语义近似不擅自合并。

反馈字段格式错误只记带阶段/轮次的 warning，不触发主动作重试、改变 accept、
强制退出或从抱怨推断正文。正常字段无论主动作为何均不改变接受依据或目标。
本次不改变现有会话收尾提交时机、tracker 外部故障恢复或终止报告语义。

T1 负责 loop、prompt 与纠偏条款，T2 依赖 T1 并负责反馈、心跳和 prompt 回归测试。
具体文件分配见 frontmatter。离线验证脚本为 `backend/scripts/e2e-spec-0056-0057-user-semantics.sh`。

### 验证边界

覆盖继续+报告、接受+报告、心跳等待+报告；blind/expert 同等可提交；报告关联
到持久化 session 并进入 needs-triage；重复正文不重复建单；低分且无报告时保持
无 issue；非法反馈不阻止合法主动作。单元测试验证机制，不证明真实模型会更
自主、更准确地反馈；后续真实回放同时观察有效反馈和过度提单。

## Drawbacks

同一会话内仅去除完全相同的正文，近义重复仍可能存在。反馈在收尾时提交，突然进程崩溃时的
外部 tracker 恢复不在本改动范围。提示可达也不能保证模型愿意反馈。

## Rationale and alternatives

没有采用低分强制提单，因为它会把评分规则制造的文本误当用户意见；没有追加一次必答反馈模型调用，
因为它增加延迟并改变用户报告意愿。保留旧 report_issue 工具和终止提单路径，新增可选字段只补足动作阶段的可达性。

## Prior art

复用现有 issue_notes、终止报告及 tracker/session 关联机制，不引入新的报告队列或反馈角色。

## Unresolved questions

暂无本次提交必须决策的开放项；真实反馈率和误报率留给独立交互观察。

## Future possibilities

后续可改善提交失败后的恢复和重复报告检索，但不把低分或抱怨自动转换成正式报告。
