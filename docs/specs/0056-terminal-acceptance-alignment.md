---
number: "0056"
title: 终止接受的目标原子提交与 Persona 证据对齐
issue: 0
slug: terminal-acceptance-alignment
summary: 保留用户主观接受的自由，同时让目标账本、Persona 验收依据和客观评估成为三个互不覆盖、可审计的结果面；终止动作的 close 必须原子提交到目标账本，但不替代客观 evaluator。
tasks:
  - id: T1
    title: 终止动作与目标账本原子提交
    status: done
    priority: P0
    files:
      - backend/ahe_beta/user/sim/goals.py
      - backend/tests/user/sim/test_goals.py
    depends-on:
      - 0054/T4
    scope: accept/accept_with_reservations 携带 close/close_with_reservations 时，框架将声明关闭的目标以 actor=terminal 的状态事件提交为 met；保留用户动作，不因未闭合目标强制改成 give_up。
    acceptance: 终止 TurnLog 的 goal_after 与最终 goal_ledger 一致；B0 不因模型忘记额外 status 更新而保持 open；未知目标、动作与 effect 不匹配、空 goal_ids 均产生可审计 warning。
  - id: T2
    title: Persona 验收依据与能力对齐
    status: done
    priority: P0
    files:
      - backend/ahe_beta/user/sim/prompt.py
      - backend/ahe_beta/user/sim/persona_client.py
    depends-on:
      - 0053/T4
    scope: terminal act 可输出 acceptance_basis(mode, evidence_refs, reason)。mode 表达 subjective、independent、delegated 或 waived；框架根据 D1/D3 生成 expected/alignment 观察字段。该检查不阻止用户接受，不把强 Persona 强行变成测试机器人。
    acceptance: blind/RUNS 的主观接受可被标记 aligned；competent/expert 或 idiomatic/rigorous 在没有 independent/delegated 依据时标记 weak；缺失字段不能伪造成已验证。
  - id: T3
    title: 可见初始完成条件与客观结果分轨
    status: done
    priority: P0
    files:
      - backend/ahe_beta/models.py
      - backend/ahe_beta/loop/sim_user.py
      - backend/ahe_beta/demand/evidence_contract.py
      - backend/ahe_beta/demand/session_timeline.py
      - backend/tests/demand/test_terminal_evidence.py
    depends-on:
      - 0051/T4
      - 0054/T2
    scope: B0 初始化时只依据用户可见 task/reproduction 生成低分辨率 done_if，允许 Persona 后续带理由 revise；objective evaluator 继续独立运行并派生 accept_validity。
    acceptance: 初始 done_if 不读取 benchmark gold；user_outcome、goal_acceptance、terminal_audit、objective_evaluation 和 accept_validity 分开持久化；evaluator skipped/unavailable 仍是 unverified_accept。
  - id: T4
    title: 终止一致性回归
    status: done
    priority: P0
    files:
      - backend/ahe_beta/user/sim/loop.py
      - backend/tests/user/sim/test_loop.py
      - backend/scripts/e2e-spec-0056-0057-user-semantics.sh
    depends-on:
      - T1
      - T2
      - T3
    scope: 覆盖 close 提交、残留 B0、强 Persona 无证据、objective skipped/failed 与旧 session 兼容；不增加自动测试门禁。
    acceptance: 同一 trace 可以同时表达 persona accepted、persona_alignment weak、objective unverified/failed；下游不得把任一主观字段投影为 objective pass。
---

## Summary

用户主观接受、目标账本、Persona 验收依据与独立技术验证分轨记录。显式终止关闭写入目标事件历史，
默认完成条件只使用用户可见题面；框架审计字段的自洽性，不替用户决定接受或继续。

## Motivation

“用户愿意结束”与“代码已经客观正确”是两个不同事实；“该 Persona 是否按自己的能力和验收标准做了判断”是第三个事实。系统不得让其中任何一个字段覆盖另外两个字段。

因此 `accept` 仍是 Persona 的自由动作。框架只负责把显式 `goal_effect=close` 作为主观目标账本的原子提交，并记录终止一致性与验收依据；独立 evaluator 仍决定技术结果。缺证据只能降低可审计性或 Persona 对齐度，不能替用户强行继续，也不能伪造成通过。

## Guide-level explanation

用户在 `accept` 或 `accept_with_reservations` 中声明 `goal_effect` 的关闭目标，并可说明
`acceptance_basis`。主观相信、自己检查、委托 harness 检查和明确豁免分别表示
`subjective / independent / delegated / waived`；没有声明时记为 `unreported`，不能补造证据。

例如用户明确关闭 B0，却没有另发一条 `status=met` 更新，框架仍应在最终 trace 中保留这个关闭声明，
而不是留下相互矛盾的 action 与目标状态。目标关闭不表示代码一定正确。

## Reference-level explanation

```text
user_outcome       = Persona 是否选择结束
goal_acceptance    = 当前目标是否被 Persona 主观声明关闭
terminal_audit     = 动作、目标提交和验收依据是否自洽
objective_evaluation = fresh evaluator 的技术结果
accept_validity    = user_outcome 与 objective_evaluation 的派生关系
```

`terminal_audit` 是观察性审计；它的 warning 不改变 action。`accept_validity` 继续 fail-closed：客观评估未运行、失败、超时或不新鲜时，不得为 `valid_accept`。

初始 `done_if` 是低分辨率启发式：仅根据题面中的复现、预期行为或测试描述选择通用完成条件，
不读取 gold patch 或隐藏测试。用户可以带理由修订；这不是覆盖所有任务含义的正式验收规格。

`GoalLedger.commit_terminal_effect` 对显式 close 追加 `actor=terminal` 事件，记录前后状态。
动作/effect 不符、空目标列表及未知目标仅警告；最终 turn 的 `goal_after` 与 ledger 同步。
`audit_acceptance_basis` 根据能力/验收门槛记录 expected、alignment、引用及 warning；这些是声明层面的
观察字段，不执行引用真实性验证。序列化和设计侧证据投影保留这些字段，旧 session 缺字段时仍可读取。

文件归属与 DAG：T1 负责 ledger/audit 原语；T2 负责 prompt 与输入契约；T3 负责持久化与证据投影；
T4 集成主循环并回归。具体文件见 frontmatter；T4 依赖 T1–T3。离线验证入口：
`backend/scripts/e2e-spec-0056-0057-user-semantics.sh`，不启动模型、容器或 benchmark evaluator。

## Drawbacks

显式字段增加少量上下文；启发式完成条件可能过于笼统；证据引用存在不代表证据已被验证。
消费者必须同时读取 warning 与 objective 状态，不能只按 `met` 或 alignment 做技术成功统计。

## Rationale and alternatives

否决“缺证据就禁止 accept”的方案：它会改变用户意愿并把目标账本变成工程门禁。
也不采用仅在最终汇总中修改 B0 的方案，因为其无法还原每次终止声明。
追加事件和独立审计既保存主观选择，也暴露证据缺口。

## Prior art

延续已有可修订目标账本、语义动作目录及 fresh evaluator 的独立结果记录方式。

## Unresolved questions

暂无本次提交必须决策的开放项；真实模型的接受质量仍需 trace 审阅，不能由单元测试推断。

## Future possibilities

可以进一步研究完成条件的表达及证据引用可读性，但不将主观接受转换成客观通过。
