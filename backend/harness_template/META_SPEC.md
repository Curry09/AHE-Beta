# Harness Meta-Spec

## 1. Purpose and authority

本文件是 harness 的项目级 Meta-Spec：它给后续 Spec Writer、Developer 和维护者提供
一个共同的起点，说明当前制品的骨架、主要控制点、术语和演化原则。

它不是 issue Spec，也不是实现冻结清单。Issue 的目标、取舍和验收以对应的 SDD
Spec 为准；代码和测试是当前行为的最终事实。harness 仓库和 NexAU 依赖都属于可
修改范围；当新的 Spec 有意改变本文描述的边界时，应以新的 Spec、实现和验收结果
为准，并在合并后修正本文受影响的章节。

## 2. Current product boundary

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

## 3. Repository skeleton

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

## 4. Ownership and changeability

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

## 5. Evolution principles

### 5.1 Shared principles

1. 先建立当前系统的最小可用模型，再提出改动；Meta-Spec 用于避免从悬置状态开始。
2. 不把历史实现、当前文件名或现有调用链自动视为永久架构。
3. harness 和 NexAU 均可修改；跨仓库改动要明确新的 ownership、delivery 和验证面。
4. Issue Spec 负责本次目标和设计取舍，Meta-Spec 只提供长期背景和导航。
5. 源码、测试和实际运行结果优先于过期的 Meta-Spec；发现冲突时修正文档。
6. 不为了文档完整而复制整个 NexAU、整个仓库或每个 issue 的局部细节。

### 5.2 Spec Writer

- 关注目标结果的因果链，不把“文件存在、prompt 被引用或配置已加载”当作效果证明。
- 区分行为 ownership、实际 delivery 和 control effect。
- 候选方案使用同一证据标尺，并明确假设、失败模式和独立证伪方式。
- 可以推翻本文中的当前判断；推翻时引用新的源码、运行或测试证据。

### 5.3 Developer

- 以冻结的 Issue Spec 为本次目标契约，以本文件为项目导航，不机械复制现有实现。
- 先定位实际控制点，再决定修改 harness、NexAU 或两者。
- 不因为本文描述了某个现状就放弃更好的设计；如果改变了共享边界，要更新 Spec 和本文件。
- 只修改完成目标所需的范围，并用相关测试或黑盒行为验证结果。

### 5.4 Acceptance

- 关注用户可观察行为和真实运行结果，不只检查文件、函数或 prompt 是否存在。
- 对协议、安全边界和 session 等兼容面，验证变更后的新契约，而不是默认旧行为永远正确。

## 6. How to use and update this file

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
误导后续开发。

## 7. Specs and topology

SDD Spec 是详细决策和历史的承载物，Meta-Spec 只保留跨 issue 的共同地图。
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

## 8. Known gaps

- 本文件描述的是当前基线，可能落后于未合并分支；冲突时以当前代码、测试和最新
  已批准 Spec 为准。
- NexAU 的实际版本、公开接口和内部实现可能变化；涉及依赖控制点时仍需检查当前
  解释器加载的版本和源码。
- 现有文件布局是导航线索，不是 Developer 必须遵循的实现清单。
