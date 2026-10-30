# Harness Meta-Spec

## Observability lifecycle

### 两类目标

- **用户侧状态反馈**：帮助用户在使用中理解当前状况、决定下一步；依据是决策时刻真实
  可见的信息是否准确、及时，并支持所需判断。
- **设计开发侧诊断观测**：帮助维护者还原经过、区分原因、验证改动；依据是对应版本的
  记录和说明能否回答具体诊断问题。

按信息服务谁、支持什么判断区分两类目标，不按发现者角色、输出格式或底层事件来源区分。
可以共用事件与实现，但日志存在不代表用户收到反馈，状态提示也不代表诊断证据足够。

### 诊断记录与开发职责

诊断记录、关联方式与阅读说明属于本 harness，随功能一起演进。当前 NexAU 起点由
`observability.py` 和 `OBSERVABILITY.md` 维护；换运行时可替换它们，不要求维持内部事件字段。
`params.yaml` 声明 `observations: artifact-observations-v1`，运行器提供
`HARNESS_OBSERVATION_DIR`；制品发布相对文件清单 `manifest.json` 与其 `reading` 入口。
清单标注 complete/partial。框架只处理传输、版本、完整性与授权，不包装制品私有函数。

功能的 SDD Spec / Objective Contract 在既有章节内分别说明“用户反馈影响”：用户何时
需要知道什么、支持什么决定；以及“诊断观测影响”：维护者需还原或区分什么、现有证据
是否足够。分别说明改动和验证，无影响可简短说明理由，不强制增加事件或章节格式。
Developer 同步维护受影响的用户输出/帮助、诊断记录/阅读说明和测试。两类目标可以在
同一票交付，评审分别验收，不能以一项通过关闭另一项。历史日志按历史版本解读，测试
新日志绑定实际 HEAD；“输出了一条成功日志”不能代替功能通过。

维护者的具体诊断问题因覆盖不足无法查明时，提出诊断观测补强，保留已查范围、未知事实、
对维护判断的影响、期望辨别能力及验证场景；不要求先证明尚不可见的根因，也不能臆造它。
用户反馈不足属于普通产品需求，不使用诊断补强入口。用户反馈需求无需先查清内部根因，
诊断补强也无需先证明用户不满意；只有实际无法选方案或验证时才声明依赖与阻塞。相关目标
保留独立验收和状态，不擅改冻结目标。宿主的导出、权限或留存故障属于基础设施诊断，
由环境维护者处理，不要求本 harness 修改宿主。

记录必须有界、默认最小化，不保存提示全文、工具参数/返回全文、凭证、隐藏提示或受保护的
评测参考数据；写入失败不能改变任务结果或无限阻塞。退出/崩溃未完成记录应明确标为 partial，
而不是装作完整。

## 1. Purpose and authority

本文件是 harness 的项目级 Meta-Spec：它给后续 Spec Writer、Developer 和维护者提供
一个共同的起点，说明当前制品的骨架、主要控制点、术语和演化原则。

它不是 SDD Spec，也不是实现冻结清单。Issue 的目标、取舍和验收以对应的 SDD Spec
或 Objective Contract 为准；代码和测试是当前行为的最终事实。harness 仓库和 NexAU 依赖都属于可
修改范围；当新的 Spec 有意改变本文描述的边界时，应以新的 Spec、实现和验收结果
为准，并在合并后修正本文受影响的章节。

## 2. Terminology and naming standard

### 2.1 Artifact terms

- **Meta-Spec**：项目级当前基线。记录共享骨架、职责、控制点、原则和更新规则；不冻结实现。
- **SDD Spec（Spec group）**：`docs/specs/NNNN-slug.md` 中一个 feature 的自包含设计契约，记录目标、动机、方案、取舍、任务和验收。
- **Objective Contract**：v0.2 单 issue 的紧凑设计契约，落在 `docs/objectives/issue-*.md`；它是该 issue 的冻结实现目标，不等同于项目 Meta-Spec。代码和 prompt 中的“compact Spec”是它的兼容简称。
- **Implementation**：代码、配置和测试的实际变更。
- **Derived View**：由 Spec 或代码生成的视图，例如 `OVERVIEW.md`、`ARCHITECTURE.md`；不能反过来作为源数据手工维护。

同一概念只使用一个正式名称：使用 `Meta-Spec`、`SDD Spec`、`Objective Contract`、
`Implementation`、`Derived View`。不要把 Meta-Spec 称为“运行时 Spec”，也不要把
Objective Contract、Task 或实现方案混称为 SDD Spec。

历史兼容说明：既有历史 Spec 或其 Derived View 中出现的 `RUNTIME.md` 是旧维护文档名，
已由 `META_SPEC.md` 取代。历史记录保留原文以维持决策可追溯性；新增或修改制品不得继续使用
该名称，除非是在明确的迁移说明中引用它。

### 2.2 Causal and evidence terms

以下字段沿用 OpenAgents v0.2 因果 Spec 契约，使用英文 snake_case：

- `ownership`：哪个组件实际拥有目标行为；
- `delivery`：改动如何进入目标组件和执行路径；
- `control_effect`：机制如何改变用户可观察结果，而不只是被加载或被调用；
- `evidence`：支持判断的源码、配置、运行或测试事实；
- `assumptions`：尚未由当前证据确认的前提；
- `failure_modes`：机制可能失效或伪装成功的方式；
- `scope_coverage`：原目标进入契约的范围，取 `FULL`、`PARTIAL` 或 `NONE`；
- `evidence_level`：证据强度，取 `HYPOTHESIS`、`STRUCTURAL` 或 `BEHAVIORAL`。

`scope_coverage=FULL` 不表示功能已经实现；尚未实现的效果仍可使用
`evidence_level=HYPOTHESIS` 诚实表示。

### 2.3 Topology terms

- **Spec topology**：Spec 之间和 Task 之间的 `depends-on` / `relates-to` 关系；源数据在 Spec frontmatter。
- **Code topology**：实际代码的 import 和 docstring 关系；由 `spec graph` 生成。
- **Execution DAG**：某次 v0.2 批次运行时根据 issue 依赖和文件冲突计算出的执行图；不是永久的 Spec 关系。
- **Dependency relation**：表示一个节点必须等待另一个节点；不要把所有关联都称为 dependency。

### 2.4 Normative language

- **MUST / 必须**：安全或已经承诺的外部契约；改变时必须先明确新契约并验证；
- **SHOULD / 应**：当前推荐的默认做法，合理的 Spec 可以覆盖；
- **MAY / 可以**：允许的实现选择；
- **OBSERVED / 当前事实**：代码或测试观察到的行为，不自动构成设计要求。

除非标注为 `MUST` 或 `SAFETY`，本文中的当前文件、符号和调用链都只是导航信息，
不能被解释为 Developer 的固定实现清单。

### 2.5 Terminology is an evolution invariant

新增或修改 Meta-Spec、SDD Spec、Objective Contract、角色 prompt、代码文档和
Derived View 时，必须使用本节定义的正式名称、字段和关系词。若确实需要引入新术语，
先在本节定义其含义、所属层级、与现有术语的关系以及过渡期兼容别名，再在其他制品中使用；
不得在迭代中悄悄创造同义词或用旧词表达新的语义。

## 3. Current product boundary

本制品是一个可启动的 terminal coding assistant。外部客户端通过进程协议发送用户
消息并接收状态、过程和最终回复；内部使用 NexAU Agent 执行模型调用和工具操作。
客户端不应依赖内部 agent 拓扑。

当前主要调用链为：

```text
params.yaml
  -> entry.py
      -> agent.yaml / agents/main.md
          -> NexAU Agent.run
              -> configured tools / workspace
      -> protocol reply, status, progress and usage events
```

这是一份当前实现的导航，不要求未来继续保持相同的文件名或调用方式。

请求终态使用 NexAU 的 `after_agent` 停止原因和 `after_tool` 完成工具结果，
不以非空回复、错误文本或模型自述推断完成。`completed` 仅表示本次运行通过
`complete_task` 成功提交答案，不证明任务正确或通过客观验收。迭代/上下文边界、
未调用完成工具的回复及缺失执行证据标为 `incomplete`，保留部分结果和会话供用户
继续；运行错误标为 `crashed`，用户打断标为 `interrupted`。输出消息通过 `type`
区分回复、进度、状态和错误；最终回复包含 `text`、`status` 和
`termination_reason`。客户端必须读取终态，不能以收到回复
作为成功证据。该判定不延长预算、不自动追加解题轮次，也不改变现有的迭代、
模型请求、工具和 token 上限。

### Autonomous and interactive execution conditions

收到明确目标后应自主推进；后续用户输入是可选的控制、授权和补充通道，不能假定用户一定发送继续。
运行器在 message 中提供稳定 task_id/message_id、followup_input 和显式任务预算。
入队时以 remaining_budget_seconds 锚定本机 monotonic 截止，同任务只允许取更早的期限；
排队、控制、后续输入或重连均不能续租。wall timestamp 仅用于审计。
期限到达后仅允许取消、保留部分结果和收尾，不再开始新解题调用；停止标为 incomplete 并给出原因。
人工输入没有声明时保持 unknown，不推断预算。内置命令的 builtin_command 确认只属于该消息，
不代表任务完成。最终任务回复关联 task_id/message_id，并包含合法 status/termination_reason。

当前 max_iterations=100、max_tokens=32768；外层长预算不保证模型一定耗尽它。
max_context_tokens 是输入阈值，可显式下调；总容量声明的静态检查不等于可靠动态 token 计量或压缩。
可识别的确定性 context overflow 返回 incomplete，不追加相同完整 Agent.run 重试；
SDK 自身可能已经进行多次 HTTP 尝试，诊断需区分这两层。原生异步取消路径保持可用。

## 4. Repository skeleton

| 路径 | 当前职责 | 变更提示 |
|---|---|---|
| `params.yaml` | 声明启动命令和外部协议名称 | 改动可能影响 launcher/client |
| `entry.py` | 进程入口、协议适配、请求生命周期、回复封装 | 用户可见行为和 NexAU 适配的主要交汇点 |
| `agent.yaml` | NexAU Agent 配置、模型参数、工具绑定、sandbox 类型 | 可按需要调整；不要把当前值当成永久方案 |
| `agents/main.md` | Agent 的产品行为和工作指引 | 行为目标优先由 issue Spec 决定 |
| `tools/*.tool.yaml` | 工具描述和工具契约 | 工具实现可来自 NexAU 或本仓库 |
| `HELP.md` | 面向最终用户的命令和可观察行为说明 | 用户可见行为变化时同步检查 |
| `scripts/` | 本地启动、冒烟和检查入口 | 优先复用作验证入口 |
| `tests/` | harness 自身的行为和协议回归 | 新行为应增加可观察的回归覆盖 |
| `docs/specs/` | SDD 设计制品（如该 harness 采用本目录） | 具体决策、历史和验收放在对应 Spec |

## 5. Ownership and changeability

下表描述当前职责归属，不是禁止修改的边界：

| Surface | 当前主要控制点 | 当前性质 |
|---|---|---|
| 启动和输入协议 | `params.yaml`, `entry.py` | `COMPAT`：可改，但要说明客户端影响 |
| session、interrupt、排队 | `entry.py` 的 `session_id` / `agent_id` 与 NexAU Agent 接口 | `OBSERVED`：可重构，需保持或重新定义用户语义 |
| 模型和工具执行 | NexAU Agent、`agent.yaml`、tool binding | `CURRENT`：harness 与 NexAU 均可修改 |
| workspace 位置和写入范围 | `SANDBOX_WORK_DIR`、sandbox 配置 | `SAFETY`：可重新设计，但必须验证越界和副作用 |
| 回复、状态、过程事件 | `entry.py`、tracer、`HELP.md` | `COMPAT`：可改，但要更新验证和客户端约定 |

标记含义：

- `SAFETY`：当前安全要求，改变时需要明确安全影响和测试；
- `COMPAT`：对外兼容面，改变时需要迁移或明确新的契约；
- `CURRENT`：当前职责或接入方式，可以被新的 Spec 改写；
- `OBSERVED`：源码/测试观察到的实现事实，不自动等于设计要求。

不要把“当前控制点”写成“永远只能在这里修改”。真正的判断来自当前 issue
的因果链、仓库证据和验收结果。

## 6. Evolution principles

### 6.1 Shared principles

1. 先建立当前系统的最小可用模型，再提出改动；Meta-Spec 用于避免从悬置状态开始。
2. 不把历史实现、当前文件名或现有调用链自动视为永久架构。
3. harness 和 NexAU 均可修改；跨仓库改动要明确新的 ownership、delivery 和验证面。
4. SDD Spec 或 Objective Contract 负责本次目标和设计取舍，Meta-Spec 只提供长期背景和导航。
5. 源码、测试和实际运行结果优先于过期的 Meta-Spec；发现冲突时修正文档。
6. 不为了文档完整而复制整个 NexAU、整个仓库或每个 issue 的局部细节。
7. 术语规范是演化不变量：所有后续制品沿用本文件的正式名称和字段；术语变化必须先更新词汇表并说明兼容关系。

### 6.2 Spec Writer

- 关注目标结果的因果链，不把“文件存在、prompt 被引用或配置已加载”当作效果证明。
- 区分行为 ownership、实际 delivery 和 control effect。
- 候选方案使用同一证据标尺，并明确假设、失败模式和独立证伪方式。
- 可以推翻本文中的当前判断；推翻时引用新的源码、运行或测试证据。

### 6.3 Developer

- 以冻结的 Objective Contract（v0.2）或对应 SDD Spec 为本次目标契约，以本文件为项目导航，不机械复制现有实现。
- 先定位实际控制点，再决定修改 harness、NexAU 或两者。
- 不因为本文描述了某个现状就放弃更好的设计；如果改变了共享边界，要更新 Spec 和本文件。
- 只修改完成目标所需的范围，并用相关测试或黑盒行为验证结果。

### 6.4 Acceptance

- 关注用户可观察行为和真实运行结果，不只检查文件、函数或 prompt 是否存在。
- 对协议、安全边界和 session 等兼容面，验证变更后的新契约，而不是默认旧行为永远正确。

## 7. How to use and update this file

开始工作时先读本文件的骨架、ownership 和相关角色原则；随后仍需按 issue 范围
核实源码、依赖和测试。本文不替代必要的深度调查。

仅在以下情况更新本文：

- 项目级启动链路、职责边界或关键控制点改变；
- harness/NexAU 的集成方式改变；
- 协议、workspace、安全、session 或用户可见行为形成新的长期契约；
- 发现会让后续开发者反复误判的稳定事实或历史陷阱。

通常不因以下变化更新本文：

- 保持控制面和行为不变的内部重构；
- 单个 issue 的局部实现细节；
- 临时实验、调参或一次性排障信息。

更新时保持“小范围修正”：说明当前状态、控制位置和验证依据；不要把新的实现
细节扩写成永久约束。代码与 Meta-Spec 应在同一变更中提交，验收确认文档没有
误导后续开发。涉及术语的变更必须同时检查受影响的 Spec、角色材料和 Derived View，
避免同一概念在不同制品中出现未声明的异名。

## 8. Specs and topology

SDD Spec 是 feature 级详细决策和历史的承载物；v0.2 Objective Contract 是单 issue 的冻结目标；
Meta-Spec 只保留跨 issue 的共同地图。
新增 Spec 不要求重写本文全文。

如果项目使用 OpenAgents 的 Spec 工具：

- `docs/specs/` 中的 Spec 源数据经过 `spec render` 生成 `OVERVIEW.md`，其中的跨
  feature 依赖/关联图应随 Spec 源数据重新渲染；
- `spec graph` 根据实际代码 import 和 docstring 生成 `ARCHITECTURE.md`，它是
  代码拓扑，不是 Spec 关系图；
- v0.2 的 `docs/objectives/issue-*.md` 是单 issue 冻结契约，批次 DAG 由运行时按
  issue 的依赖和文件冲突动态计算，不等同于永久的全仓 Spec 拓扑。

因此，Spec 增长时应更新受影响的 Spec 关系源并重新生成对应视图；只有项目级
骨架或共同原则变化时才更新本文件。

## 9. Known gaps

- 本文件描述的是当前基线，可能落后于未合并分支；冲突时以当前代码、测试和最新
  已批准 Spec 为准。
- NexAU 的实际版本、公开接口和内部实现可能变化；涉及依赖控制点时仍需检查当前
  解释器加载的版本和源码。
- 现有文件布局是导航线索，不是 Developer 必须遵循的实现清单。
- Meta-Spec 的渐进式升级（按多轮实验自动扩展或细化共享地图）暂缓。未形成独立
  SDD Spec、明确的 ownership/delivery/control_effect 和对照实验前，不把一次性实验
  观察或单个 issue 的局部细节继续写入本文件。
