---
number: "0080"
title: 同一 persona 的独立会话编排
issue: 0
slug: reusable-persona-sessions
summary: 以现有 round/slot/session 身份区分并发会话，允许复用同一 persona 和配对，保持冻结计划、恢复及追加归档一致，不复制 persona 卡片。
tasks:
  - id: T1
    title: 配置与配对编译器允许画像复用
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/config.py
      - backend/ahe_beta/experiment/workload.py
      - backend/tests/test_experiment_config_v2.py
      - backend/tests/test_experiment_workload.py
    scope: 放开会话数量和配对中的 persona 唯一限制，保留选择集合唯一及原序列化、哈希算法。
    acceptance: 一张画像的不同任务与重复完整配对均可编译；未知 ID/错误长度/重复库 ID 仍拒绝；旧 N1/N4 输出和哈希不变。
  - id: T2
    title: 独立会话执行与部分失败恢复
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/loop/orchestrator.py
      - backend/tests/loop/test_orchestrator.py
      - backend/tests/loop/test_recovery.py
      - backend/tests/test_reusable_persona_sessions.py
    scope: Orchestrator 按既有 round/slot 完整 binding 核验和执行，去掉 persona 级去重，验证 client/工作区/Issue 归属。
    acceptance: 相同画像与完整配对的两个并发 slot 有不同 key/session/client/工作区；故障仅重跑失败局、报告幂等，乱序或重复 slot 仍拒绝。
  - id: T3
    title: 重复配对的归档及继承往返
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/materials.py
      - backend/tests/test_experiment_continuation_workload.py
      - backend/tests/test_experiment_continuation_contract.py
      - backend/tests/test_experiment_continuation_export.py
      - backend/tests/test_experiment_continuation_source.py
    scope: 继承 preview 使用画像唯一集合；末轮重复配对完整导出、核验、投影和新增轮编译。
    acceptance: collect 到 child 的往返保持全部 slot 顺序和数量，画像卡只冻结一次；父归档字节不变、未知画像/摘要矛盾仍拒绝。
  - id: T4
    title: 文档及独立会话验收
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - docs/CONFIGURATION.md
      - docs/CONFIGURATION.zh-CN.md
      - docs/tutorials/multi-user-experiment.md
      - docs/tutorials/multi-user-experiment.zh-CN.md
      - backend/scripts/e2e-spec-0080-reusable-persona-sessions.sh
    scope: 更新画像选择与执行列表语义，并记录恢复/观测/归因验收及 direct 评阅范围。
    acceptance: 中英文不再要求同轮画像唯一；live/report/L1 保留独立 session，脚本核验重复画像并发/恢复/继承，不能把复用画像当独立真人样本。
---

# 0080 · 同一 persona 的独立会话编排

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

允许同一 persona 在一轮中对应多个独立会话，包括同一任务的重复试用。persona 表示不可变画像，现有 `round_no + slot` 表示会话位置；继续以包含完整 binding 的 operation key 派生 session ID。放开画像复用限制，不增加 participant 表、卡片别名、运行开关或另一套编排。

## Motivation

当前配置要求 `sessions_per_round <= len(persona_ids)`，普通与继承的计划编译器及 Orchestrator 又分别拒绝同轮重复 persona。实际工作区、恢复 unit、live、SessionStore 和证据已经以 session ID 区分，画像唯一约束比执行身份需要更强。

历史 N8 的八个任务并不对应八张不同画像：pvlib 与 astroid 都使用 `sr-15-swyx`；排程和 TinyDB 的 direct 路径也回退到这张画像。Excel、KV、SQLFluff、Superset 分别使用 kellan、xe-iaso、ronacher、kenton-varda，因此八个会话使用五张画像。为了做只改变交互方式的对照，不应新增三张不同画像，也不应复制画像并修改 ID。

统一入口已经冻结 slot、task、persona、interaction 和 task digest。采用已有会话身份放开重复，可以在不改既有序列化形状和哈希算法的情况下恢复原配对，并支持同画像同任务的独立复测。

## Guide-level explanation

`workload.persona_ids` 仍是所选画像的唯一集合；persona 库的 ID 也必须唯一。每轮 `interaction_plan` 是有序会话列表，允许重复 persona 或完整配对，例如：

```json
{
  "workload": {
    "persona_ids": ["sr-15-swyx"],
    "interaction_plan": [
      [["sr-15-swyx", "task-a"], ["sr-15-swyx", "task-b"], ["sr-15-swyx", "task-a"]]
    ]
  },
  "rounds": {"count": 1, "sessions_per_round": 3, "max_parallel_users": 2}
}
```

这是配置片段，完整定义仍须提供后端、材料、角色和模型。三个位置分别是 slot 0/1/2，即使 slot 0 和 2 的配对完全相同，也会产生不同 session ID、恢复 unit 和工作区。默认轮转允许画像库小于每轮会话数；仍检查每轮长度、所选 ID、slot 顺序和并发上限。

报告与看板显示画像和独立 session/slot，不能把画像相同当成同一会话，也不能把复用画像解释为多个独立真人样本。多个反馈是否有共同机制仍由现有需求角色判断，不在入口按 persona 自动合并。

N8 混合及全 direct 两组显式使用相同有序配对。direct 仍是一条冻结任务消息加结束后一次 persona 评阅，过程中不发追问、heartbeat、转向或接受消息；现有 direct 代码会提交报告，即使终态 verdict 为 accept。本组不改变报告生成、评分或验收口径。

## Reference-level explanation

### 输入与身份

修改 `config.load_config_v2`，移除“会话数不能超过画像数”的限制；保持 schema 对 `persona_ids` 的 uniqueItems、非空库、未知字段、round count、并发及所有材料检查。

`workload.interaction_plan` 不再对 persona 去重。`compile_session_plan` 的继承分支也按有序 pair 保留重复，继续验证 task/persona 存在、task digest 与 interaction 一致。每个 binding 的六个字段保持不变，slot 必须等于其列表位置，不接受乱序、缺位、重复编号或 bool 冒充整数。

Orchestrator `_logical_plan` 同步取消 persona 唯一检查，保留其他结构检查。会话 key 继续使用 `operation_key(run_id, "users", binding)`；binding 的 slot 已经确保重复配对的 key 不同。Session provenance、UsageContext、client 创建和 task runtime 的归属沿用原实现，不增加对 persona 卡片的可变状态。

只放宽新配置可接受的配对范围。旧有效输入经过新的默认编译器，产生与原来完全相同的 plan、config hash、binding hash 和 session key。已准备 run 继续使用其冻结 controller，不原地更新。

### 执行、恢复与归档

每个 slot 建独立 client、工作区和 attempt；线程之间只共享不可变画像。失败恢复只重跑未完成的 session unit；不因同 persona 另一个 slot 已完成而跳过，也不把它的 Issue 或文件作为本 slot 的结果。

SessionStore 与 live 按 session ID 保存；角色证据授权和 grouped architect 按来源 session/报告处理。不对 persona 计数重新解释 Metrics，也不添加画像级执行去重。

continuation export 按 slot 保留全部末轮配对，source 以 session ID 验证完成用户集；画像材料只冻结有序唯一的卡片集合。继承 preview 的 `persona_ids` 改为从 `source.personas` 获取，而非从每个 pair 重复列出。父重复配对按原顺序编入每个新增轮，禁止通过画像去重缩短边界或改变 session 数。

### 对照与验收

改变 interaction 会改变 task digest、catalog/plan hash 及 session key，这是身份正确派生的结果。配对审计比较源码、指令、环境、模型、初始 Harness、画像卡和有序 slot；只允许 interaction 及其派生身份、各 run 坐标不同。不能要求两组共享 session ID，不能复用一组已完成会话。

四个任务分别承担配置/编译、执行/恢复、归档/继承及文档/验收，文件分配以 frontmatter 为准。端到端脚本为 `backend/scripts/e2e-spec-0080-reusable-persona-sessions.sh`。不把旧实验产物的转调脚本作为公开入口。

| 验收 | 必须观察的结果 |
| --- | --- |
| 新配置 | 一张画像三个 slot 可校验；库中重复 ID、未知 ID、错误计划长度和乱序 slot 仍拒绝 |
| 旧输入 | 既有 N1/N4 编译输出、哈希和 key 不变 |
| 独立执行 | 相同 persona/任务的两个并发 slot 各有 client、session ID、attempt 和可写工作区，文件修改不串局 |
| 故障恢复 | 一个 slot 完成、另一个中断，只重跑后者；Issue 幂等且来源 session 不混淆 |
| 归档往返 | 末轮重复配对 collect→source→子 run 保留顺序和数量，画像卡只冻结一次，父字节不变 |
| 反馈与观测 | live/L1/report 关联多个不同 session；direct 终态评阅不变，不把报告数当作投诉数或官方通过率 |

## Drawbacks

同一画像的多次会话相关性更高，不能按独立用户样本计算统计显著性。入口展示执行归属，但实验分析仍需说明画像与任务的重复结构。

放宽约束会让之前被拒绝的配置可运行，因此必须同步修改所有后续去重检查，避免 prepare 成功后在执行或继承阶段才失败。

## Rationale and alternatives

选择现有 slot 作为执行位置，因为当前哈希、恢复和工作区已经以它区分会话。新增 participant 模型会重复已有概念并扩大 Session/provenance/归档契约，当前无需引入。

不复制 persona 卡片或给卡片加别名。复制会伪造“不同用户”，并使对照多出画像身份差异；相同画像的复用应如实保留在来源记录中。

不增加 allow_duplicate_persona 开关：唯一画像不是执行安全前提，保留一个默认拒绝的开关会让相同机制出现两套语义。选择集合保持唯一，执行列表可重复，边界已经清晰。

## Prior art

当前 Orchestrator 的完整 binding key、prebuilt 的 session/attempt 目录、不可变 SimPersona、session ID live 标签及 continuation 的 slot/session 校验已提供所需执行身份。历史 direct runner 采用所选 simulated persona 的首张画像，其 N8 实际取值是 `sr-15-swyx`；两组新配置将该回退显式冻结。

## Unresolved questions

接口设计已确定：画像选择集合唯一，会话列表可重复，不新增运行实体或开关。富任务环境属于单独环境方案；本组完成不能单独证明原 N8 的文件、服务和环境已经恢复，也不能据此启动不具备环境验收记录的八场景实验。

## Future possibilities

可在分析界面增加按画像、任务及 slot 展示重复试用的视图。独立统计重复次数或随机种子应在有明确实验需求时单独设计，不在本组附带修改评分、报告策略或抽样方法。

