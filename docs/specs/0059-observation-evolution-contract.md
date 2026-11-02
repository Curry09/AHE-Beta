---
number: "0059"
title: 观测文件入口与设计角色按需取证
issue: 0
slug: observation-evolution-contract
summary: 让 Triage、独立 PM 与 Architect 通过普通文件工具按职责查阅制品自己的观测文件，保留原有需求产物与角色分工。
tasks:
  - id: T1
    title: 制品观测文件的只读入口和访问审计
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/observation_provider.py
      - backend/ahe_beta/demand/agent_runtime.py
      - backend/ahe_beta/guards/workspace_jail.py
    scope: 注册 session 关联 manifest；普通文件工具读取已声明文件；保留文本格式、行号、查询与权限审计。
    acceptance: 无需解释事件 schema 即可读取改名后的日志与说明；跨 session、未声明文件和符号链接不可读取；无日志可正常运行。
  - id: T2
    title: 独立 PM 和结构综合按需取证与证据引用延续
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/divergent.py
      - backend/ahe_beta/demand/architect.py
      - backend/ahe_beta/demand/proposal_view.py
      - backend/ahe_beta/demand/evidence_contract.py
      - backend/ahe_beta/demand/session_timeline.py
      - backend/tests/loop/test_architect.py
      - backend/agent_defs/architect
      - backend/agent_defs/divergent_pm/systemprompt.md
      - backend/agent_defs/triage_agent/systemprompt.md
    scope: PM 以体验索引独立观察；Architect 仅核实可见提案引用的 session；综合输出确定性继承来源引用，兼容旧证据工具。
    acceptance: PM 不等待 Triage 批准；Architect 引用不因 3000 字展示上限或来源合并丢失；无新增审核门禁。
  - id: T3
    title: 边界回归与真实模型单链路回放
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/tests/demand/test_observation_provider.py
      - tools/dev/replay/replay_observation_synthesis.py
    scope: 验证普通工具读取和来源链，固定证据回放 PM、Architect，审计实际读取及产物。
    acceptance: 离线测试通过；真实模型结果保留输入、输出、访问与耗时，区分机制可达与实际下钻。
---

# 0059 · 观测文件入口与设计角色按需取证

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

为设计侧提供制品观测文件的只读入口。PM 独立从用户体验发现产品机会；Architect 从
已有提案综合结构关系；Triage 继续处理单条报告。角色按需要使用已有文件工具取证，
各自的任务、输出 schema 和提交条件不变。

## Motivation

真人开发者先从用户反馈产生疑问，再找对应版本、请求的日志、源码和说明来核实。
日志是制品的一部分，事件名称、内容和查询方式会随实现改变。若编排器事先固定每一种
内部事件的字段及解读，就会与被进化制品深度耦合；只给用户可见对话，又无法区分正常
慢操作与内部恢复等不同原因。本改动固定证据定位和读取边界，把内容解释交给角色。

## Guide-level explanation

角色输入仍以用户证据或提案为主，附加一小段可用 manifest 地址。模型可用 `read_file`
读入口及说明，再用 `list_directory`、`search_file_content`、分页 `read_file` 找具体证据。
不要求每轮查看日志，不通过额外模型进行日志归类，不强制提交新的诊断表格。

例如，用户报告“长时间没有回应”。日志可能显示一次模型输出错误和恢复，也可能显示
正常长工具执行。PM 据此判断等待体验，Architect 据此判断两个提案是否涉及同一机制；
内部重试证据本身不等价于“产品必须向用户展示重试明细”。缺失日志时保留不确定性，
仍可基于用户证据提出有效需求。

这里供角色查证的是维护者诊断证据。用户当时能否理解状态并决定下一步，属于 0035 的
用户侧状态反馈目标；0061 的诊断观测补强入口仅处理维护者的取证缺口。两类目标与验收
分别保留，PM 发现用户反馈不足时仍提交普通产品提案，不需要先补齐内部日志。

## Reference-level explanation

T1 提供无模型的 ObservationProvider，并由公共 agent runtime 按每次调用绑定。
底座只约定 `<observation_root>/<session_id>/manifest.json`，清单含同名 `session_id`
及 `files: [{path: "相对路径", ...}]`。其余元数据、阅读说明、格式、事件名由制品自有。
发行版本、request 关联和日志含义应由制品在清单或声明的说明文件内记录。
默认根为 sessions 同级的 observations，可由 `AHE_BETA_OBSERVATION_ROOT` 指定。

工作区 middleware 让普通文件工具只读已声明文件，保留原文、行号和查询定位。新事件
不需要改框架解析器；文件重命名只需要制品更新清单。未声明文件、其他 session、符号
链接不被读取。搜索只针对授权文件；输出有长度限制，读取支持 offset/limit。已知环境
凭证在返回文本中消隐。原始凭证、persona 提示、oracle 等不应被发布者导出到观测包；
Provider 不声称能从任意日志内容自动识别全部秘密。失败或缺失不伪装成空成功。

T2 按职责绑定范围：Triage 为当前 report 的 session；PM 为本次体验索引的 sessions；
Architect 为可见 proposal/ready 明确引用的 sessions；Owner 无原始观测。Architect
兼容 0055 的 L2/L3/L4 引用下钻，权限由工具执行。3000 字正文展示截断不丢证据句柄；
综合产物确定性继承所选来源引用，以免原提案关闭后观测链断开。

Architect 不再默认接收旧 runtime_agg：该聚合器解释既有 transcript 字段、回复文字及
固定源码常量，不能代表演进后制品的内部事实。受控回放已观察到模型将缺失字段产生的
零计数用作归因佐证，因此本次移除此默认输入；旧统计代码可保留供历史诊断，角色按需
查阅对应制品的真实观测。

Provider 读取记录角色、session、文件、行范围或搜索词与成功/拒绝状态，复用
`evidence_access.jsonl`；角色 trace 保留工具结果。普通文件工具的操作本身被记录，
不新增要求模型填写“取证理由”才能继续的门禁。旧 timeline/beat/step 仍接受 reason。

T3 验证不同日志格式、改名文件、读取隔离、缺失降级、线程上下文与引用延续，并以固定
证据做真实模型回放，分别报告能否读取、是否主动读取及产物质量。任务和文件分工见
frontmatter。本次范围是设计侧消费接线；现有历史运行未采集的内部日志不能被补造。
完整新实验的制品日志采集、容器收尾导出须由相应制品/启动契约接入后再声称覆盖。

实际验证：150 项相关测试通过；真实 GLM-5.3 回放中，PM 进行了 8 次原生文件读取及
2 次时间线读取，Architect 进行了 7 次原生文件读取。Architect 在 204.268 秒提交一条
结构提案；PM 在 360 秒回放时限后晚到提交，不计为成功。回放发现的零计数误读已用于
移除上述旧聚合默认输入，未宣称修正后的模型生成质量已再次测得提升。
完整本地记录：`backend/data/observation-replays/0059-pm-architect-20260908/AUDIT.md`。

## Drawbacks

真实模型可能选择不查日志，也可能查到日志但归因错误；可达性不能证明设计收益。
文本返回预算可能截断长行，审计需结合原文件。当前文件入口只覆盖显式配置的导出目录，
不自动发现宿主上任意日志，也不自动转换已有 NexAU trace 数据库。

## Rationale and alternatives

选择薄文件入口，是因为演进需要容纳制品自己的诊断语言。固定事件类型的专用函数会使
每次内部改变都要求同步改编排器。给角色整个 sessions/宿主目录会扩大无关输入。
只有一份静态开发手册也不够：文档可以随制品演进，但每次运行仍需将文档、日志和版本
正确关联并让角色读得到。这里将演进中的说明文件作为普通制品文件读取，底座只守定位。

## Prior art

复用 0024 的按需时间线、0043 的角色认知契约、0049 的调用持久化以及 0055 的证据边界。
延续已验证的 Triage 普通文件工具观测回放，不改变 Triage 的报告规范化目标。

## Unresolved questions

原生 NexAU 日志在每个新实验中的收集与导出覆盖率，需要后续按运行入口检查。当前测试
不将受控回放等同于真实闭环全部内部事件已落盘。

## Future possibilities

制品可在自身 meta-spec 和开发 spec 中演进诊断事件、关联方式与阅读说明；之后用用户
实验中的真实排障问题检验其是否降低不确定性。底座无需预先规定每一种诊断事件。
