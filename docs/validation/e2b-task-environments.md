# 任务环境验收记录

日期：2026-11-01。代码基于 main `cc17cc8` 加本次未提交工作区；M04 模型试用使用统一入口冻结的控制器源码和材料。

本记录覆盖任务材料发布、32 项最终任务定义与真实 Docker 准备/收集检查、32 项主任务镜像与 4 项配套服务镜像的公开下载和工具启动核验，以及 M04 的真实模拟用户试用、产物收集和独立复跑。四组六轮实验及两轮需求/交付链路尚未完成本次验收。

## 材料与公开示例

任务材料已发布到主仓 [Evolution task materials v1](https://github.com/Curry09/auto-designer/releases/tag/evolution32-task-materials-v1)，Release ID 为 `430367618`。37 项运行输入共 251,473,655 字节，另有 `materials.lock.json`、`SHA256SUMS` 和 README，共 40 个文件。已使用 GitHub 身份重新下载全部文件，核对 39 条校验和、全部输入的 SHA-256，以及锁文件对应的 32 份任务定义和指令身份。

主仓仍为私有，匿名 Release 下载待仓库公开后再验。验证时仅把已下载且校验通过的文件放进独立的内容寻址缓存；任务定义仍使用最终 HTTPS URL，通用下载器没有 GitHub 认证分支。GHCR 镜像的匿名下载已独立完成。

四份配置及一份批次均通过实际 `experiment.py check --offline`：

| 配置 | 每轮会话 | 模拟交互 / direct | Triager | 轮数 |
| --- | ---: | ---: | ---: | ---: |
| U8 mixed | 8 | 6 / 2 | 4 | 6 |
| U8 direct | 8 | 0 / 8 | 4 | 6 |
| U16 mixed | 16 | 12 / 4 | 8 | 6 |
| U32 mixed | 32 | 25 / 7 | 16 | 6 |

每组用户及 Developer 并发均为 4，Synthesizer/Divergent 各 1，mechanical Owner，grouping=false；R1–R5 交付、R6 只试用。U8 对照只改变六个任务的交互覆盖和派生实验身份。画像复用、逐轮配对和模型预算的合同检查共 82 项通过；[双语教程](../tutorials/evolution32.zh-CN.md)提供安装、凭证、检查、启动、状态、收集、停止/恢复及批次命令。

四份配置还分别通过真实 CLI `prepare`，冻结任务、builtin seed、控制器及固定 OpenAgents 来源，并再次通过 `verify_materials`、catalog 和 session-plan 读取校验。共生成 384 个待运行会话的六轮计划；四项资源状态均为 `ABSENT`。此步骤复用了上述已验证 Release 字节缓存，未创建 E2B/Gitea 资源或调用模型。

### 32 项实际环境检查

最终每项都通过生产 `DockerTaskEnvironmentManager` 创建独立环境，执行初始化及就绪检查，再执行静默、收尾、实际产物读取和所属资源清理。全部任务在 Actor 启动前的导出补丁均为 0 字节，任务配方身份与最终 `task.json` 一致。初始化时已有的数据库、源文件和服务观测可收集；需要解题才产生的输出记录为尚未生成，不填造答案或记作任务通过。

检查发现并修正了几项实际准备问题：

- M01、M03、Pretrain 原先已提供的初始文件未全部计入 Git。现由固定配方创建可复现的准备提交，保留原源码/数据字节与前后版本来源；两次新环境准备得到相同 Git tree，初始补丁为空，控制改动只导出被修改的文件。Pretrain 的损坏 shard 保持原输入，未预先修复。
- WAL、VBA、React 保留原本不含 Git 的环境；React 使用原生 Node 收集器。完整源码归档保留运行依赖、空目录、权限及内部相对链接，拒绝外部链接和越过归档根后再返回的链接。终态评阅另有有界只读源码预览，不依赖任务镜像安装 Git/Python。
- KV 的原生负载发生器和独立采集 companion、Payments 的 Kafka/播种/客户 companion 均完成真实就绪、收尾与采集。KV 的原始测量只留管理侧，公开摘要单独投影；未执行热替换时如实保留 `not_triggered`，不算性能成功。
- M05/M09 使用已核验的 Python 3.12 工具镜像；M02 保留操作者确认的原始不完整两文件输入。

32 项汇总收据 SHA-256：`bc6f2ba8c0a67903d7b0cebbedb8a15bb6c3066513195e623e30e3d124bd4dd8`。逐项环境身份及收据哈希见[清单](../../examples/tasks/evolution32/manifest.json)的 `environment_validation`；材料检查、环境检查和模型解题分别记录。

### E2B 大文件传输

使用生产 `upload_frozen_inputs` 向新建 E2B 环境上传完整 M03 bundle：102,107,257 字节、94.416 秒，远端完整 SHA-256 为 `6133e2d634e424756bbec8b4dac4537ea0dc2a1e27cf5d0f2796ce61ea8126b7`，与本地及 Release 一致。进程内存峰值只增加约 7 MiB；manifest 原始字节也一致。该检查未执行 bootstrap 或调用模型，所属临时环境已删除。

文件上传使用公开 SDK 的签名上传地址及 HTTPX 文件流，为连接、读、写设置有限 I/O 等待；这不是整次传输的严格总时限，也不改变任务预算。签名地址不进入日志或错误，相关回归及真实本地 HTTP 读超时检查共 53 项通过。它修复了当前 SDK 二进制流分支忽略请求等待配置的问题。

### 最终回归

| 检查 | 结果 |
| --- | --- |
| 全量 pytest | 2915 passed，3 skipped，810.80 秒 |
| 显式开启上述 3 项真实 Docker 检查 | 3 passed，13.35 秒 |
| 全仓 Ruff 检查及格式检查 | 通过 |
| Spec validate / render / graph | 通过，生成视图已更新 |
| 依赖锁离线检查及已安装 NexAU 固定提交检查 | 通过 |
| 公开实验目录合同 | 10 份实验配置、3 份批次，0 错误 |
| 本次 11 份文档的 178 个本地链接 | 0 失效 |

默认跳过项需要显式设置 `RUN_SPEC_0084_DOCKER=1`：两项验证真实评分容器的正反例及私有断言隔离，一项验证任务进程及后代停止后仍可导出冻结文件。它们已单独启用并全部通过，未调用模型。原始任务指令与 M04 固定配方保持发布字节，不自动格式化，由材料 hash/inventory 检查；其余维护代码执行全仓 lint/format。

上述结果完成材料、配置、准备、环境及回归层验证；本记录开头标明的完整两轮需求/交付验收和四组六轮正式运行仍分别保留，不能由这些检查推算通过。

## 运行条件

| 项目 | 本次条件 |
| --- | --- |
| 任务 | M04，`dbt-direction-negotiation` |
| 源码 | `fivetran/dbt_salesforce`，`2e99cce10766c16c08aaf5c1fef8e6d17b857171` |
| 工具 | Python 3.13.18、Git 2.39.5、SQLFluff 3.4.0；版本和依赖另有锁定清单 |
| 模式 | 本地 Docker + 本次专属 localhost Gitea，单轮、单任务 |
| 任务容器 | 2 CPU、4096 MiB |
| 用户 | 原 persona `sr-08-nat-bennett`，expert、协作式模拟用户 |
| Harness | 当前 builtin seed，`max_tokens=32768`，`max_iterations=100` |
| 模型 | 用户、Harness 均为 `glm-5.3-flash` |
| 总任务预算 | 未设置 |
| 交付角色 | 本次只有末轮用户试用，不启动需求与 OpenAgents 交付 |

原公开案例的四个文件按原包校验；源码按其 SOURCES 中的固定 revision 补齐，117 个 Git blob 与原 tree 一致，SQL 文件名清单相符。环境就绪检查验证真实源码、工具和任务输入，不生成 ADR、试点代码或答案。

试用分两段保存。第一段 `20261031T153554Z-587b12f0` 因操作者要求切换模型服务而停止，保留为未完成记录。第二段 `20261031T163945Z-7a378f75` 使用 Tensoris，显式继承先前工作区补丁及可见对话，要求重新验证旧测量、完成交付；122 个恢复文件的哈希逐项检查通过。第二段是续接会话，不是从空白重新解题，也没有迁移在途模型请求或隐含会话内存。

## 真实试用和收集

第二段会话 `op-e039cf61523e8c5d237c3ea8901ffaa1` 通过原生入口完成，最终状态为 `COMPLETED / STOPPED / COMPLETE`：任务结束、所属计算服务停止、归档完整。任务容器按生命周期清理；原始云端快照和其他用户服务未改动。

Tensoris 共完成 57 次调用：Harness 32 次、用户 25 次，调用错误为 0。模拟用户最终接受交付，体验为 4/4；反馈中的任务判断为 `fulfilled`。这些是模拟用户的结果，不等同于独立官方评分。

| 收集项 | 字节数 | SHA-256 |
| --- | ---: | --- |
| 完整工作区补丁 | 67,338 | `1d01e313b37ed355e5d3150fd57007e02d879ecbbb8846f5a6833a9b682566c4` |
| ADR | 6,890 | `7de5d526c6fdf417ec5006f1dc2c747f0cd7f695aa7275ef82e59dcf765c25c2` |
| 试点归档 | 5,625 | `2862c3454dd4a2f8e4e75865bb56722b94aed3750eee3d15fd1492ef281057c4` |

收据绑定 run、round、slot、session、task digest 和 Harness SHA。两项必需产物均成功收集；试点归档含 `record.md`、workflow 建议稿和逐文件校验清单，内部文件哈希再次核对通过。源码、配置和脚本由完整补丁保留，不依赖报告中的文字转述。

停止计算服务后固定保存的最终归档为 8,198,405 字节，SHA-256：`c864a5ea754002be78f028da96ae70675360dc1c4902dbd4f7b87a1e38268bdf`。

## 独立复跑

另建断网 Docker 容器，只提供固定源码 bundle 和最终完整补丁，不复用 Actor 工作区、进程、缓存或先前生成的测试结果。任务代码仅在容器内执行。使用同一工具文件系统、2 CPU、4096 MiB。

| 检查 | 实际退出码 | 耗时 | 结果 |
| --- | ---: | ---: | --- |
| 两个选定试点文件 lint | 0 | 4.314 秒 | 通过 |
| 改动文件正常，运行门禁 | 0 | 3.672 秒 | 通过 |
| 注入有违规的 SQL，再运行门禁 | 1 | 4.213 秒 | 正确拒绝 |
| 恢复基线模型、无 SQL 改动 | 0 | 0.072 秒 | 正确通过 |
| 校验器进程失败，返回 17 | 2 | 0.047 秒 | 正确区分工具故障 |
| 全部 28 个模型，JSON 输出 | 1 | 32.728 秒 | 发现存量问题，见下文 |
| 全部 28 个模型，普通文本输出 | 1 | 30.939 秒 | 与 JSON 中的模板错误一致 |

两个试点是 `stg_salesforce__account.sql` 和 `salesforce__owner_performance.sql`。负例删除、模型恢复后再次检查其哈希，确认控制实验没有改变最终提交的两个文件。

全仓结果共有 409 条问题，其中有 **8 条 TMP 错误**：四个 `salesforce_history` 模型各两处 `target` 模板变量未定义，PRS 为 0。因此，Actor 报告中的“全仓 TMP=0”没有复现；409 也不能全部解释为普通风格债务。模拟用户终检抽查了文件、源码和工作区状态，lint 结果主要依据 Actor 已展示的执行记录，未独立发现此遗漏。

切换前的部分代码还有缺失列宏、`star` 参数不匹配等问题，切换后的 Actor 已修复相关 stub；恢复哈希全部一致，不能将原有代码缺口归因为文件在恢复时丢失。本次结论是**环境与收集链路可运行，试点及门禁可复现；模型报告仍存在未核实的全仓声明**。未将模拟用户接受改写成全仓无错误，也未改写其原始评分。

dbt 编译、数据库执行、多 adapter 兼容性和真正的上游 CI 执行未验证。workflow 仅作为建议稿交付。

另有一个真实的收集负例：预先存在旧试点压缩包、但当前无试点目录时，finalize 清除旧包且不伪造本次产物。该控制用于防止旧产物被误收为当前交付。

## 公开镜像

任务镜像使用统一仓库与命名规则：`ghcr.io/mmjzmy/auto-designer-tasks:<任务 key 小写>-v1`。M04 为：

```text
ghcr.io/mmjzmy/auto-designer-tasks:m04-v1
ghcr.io/mmjzmy/auto-designer-tasks@sha256:dd714c8ff7d7431836e5c133c52691dff3fc996134fbfdc18a0782b38a2d27ee
```

镜像 title 和 description 均为 `M04 task environment`。公开版只简化元数据：15 个文件系统层、全部非标签配置和工具版本与试用镜像一致；实际任务定义使用 digest。

在新建的干净 E2B 环境验证匿名冷下载：镜像此前不在缓存中，Docker 使用空凭证配置，5.894 秒完成下载；实际 config ID 为 `sha256:10395f71dd71ee3577c24dbb12723a7acaf3c2678893cf988acc481f9eed6aaf`，与发布记录一致。随后以 2 CPU、4096 MiB、断网任务容器运行工具探针通过；临时 E2B 环境已删除。此检查不调用任何 Agent 或模型，不恢复旧实验控制器，也不是 E2B 上的一次完整 M04 解题。

M04 镜像配方见 [M04/environment/Dockerfile](../../examples/tasks/evolution32/M04/environment/Dockerfile)，全部镜像身份、Release 与最终任务包见[任务材料清单](../../examples/tasks/evolution32/manifest.json)。M02 保留已确认的原始不完整输入，作为鲁棒性场景。

## 32 项镜像发布核验

32 项主任务镜像和 4 项配套服务镜像均已发布到公开的 `ghcr.io/mmjzmy/auto-designer-tasks`。下表使用可读标签，运行时应使用清单中固定的 registry manifest digest。平台为 Linux amd64。

每项检查使用空 registry 凭证配置，确认镜像在该环境此前不存在，匿名拉取后核对 config ID，再在断网、只读容器中执行工具探针。探针容器为 2 CPU、4096 MiB；这是发布检查资源，不替代任务自身的资源声明。同组可以复用已下载的共享层，下载耗时不代表逐项全部层均无缓存。全部临时 E2B 检查环境已删除。

| 任务 | 镜像标签 | 匿名下载（秒） | 工具启动 |
| --- | --- | ---: | --- |
| O03 | `o03-v1` | 23.473 | 通过 |
| O09 | `o09-v1` | 4.230 | 通过 |
| O14 | `o14-v1` | 37.252 | 通过 |
| M03 | `m03-v1` | 18.231 | 通过 |
| O01 | `o01-v1` | 3.031 | 通过 |
| kv-live-surgery | `kv-live-surgery-v1` | 14.701 | 通过 |
| tinydb | `tinydb-v1` | 21.185 | 通过 |
| M01 | `m01-v1` | 27.041 | 通过 |
| O05 | `o05-v1` | 2.510 | 通过 |
| O06 | `o06-v1` | 3.093 | 通过 |
| vf2-speedup-networkx | `vf2-speedup-networkx-v1` | 42.573 | 通过 |
| pretrain-shard-corruption | `pretrain-shard-corruption-v1` | 24.588 | 通过 |
| 091-add-receipts-bookkeeping | `091-add-receipts-bookkeeping-v1` | 10.892 | 通过 |
| flask-restful | `flask-restful-v1` | 0.659 | 通过 |
| M05 | `m05-v2` | 24.363 | 通过 |
| M09 | `m09-v2` | 0.664 | 通过 |
| O02 | `o02-v1` | 2.439 | 通过 |
| O04 | `o04-v1` | 8.311 | 通过 |
| astroid-1030 | `astroid-1030-v1` | 3.967 | 通过 |
| sqlfluff-3608 | `sqlfluff-3608-v1` | 3.932 | 通过 |
| marshmallow-2123 | `marshmallow-2123-v1` | 2.655 | 通过 |
| payments-pipeline-fix | `payments-pipeline-fix-v1` | 3.333 | 通过 |
| wal-recovery-ordering | `wal-recovery-ordering-v1` | 3.233 | 通过 |
| vba-userform-port | `vba-userform-port-v1` | 9.884 | 通过 |
| react-lead-form | `react-lead-form-v1` | 5.355 | 通过 |
| 080-convert-novel-epub | `080-convert-novel-epub-v1` | 43.078 | 通过 |
| cookiecutter | `cookiecutter-v1` | 0.680 | 通过 |
| tqdm | `tqdm-v1` | 0.688 | 通过 |
| M02 | `m02-v1` | 0.622 | 通过 |
| M04 | `m04-v1` | 5.894 | 通过 |
| M07 | `m07-v1` | 0.655 | 通过 |
| M10 | `m10-v1` | 0.619 | 通过 |

配套服务镜像独立计数，不占用上述 32 个主任务名额。此处验证服务镜像下载及其所需程序/输入，完整服务拓扑与任务联调属于后续任务包验收。

| 配套服务 | 镜像标签 | 匿名下载（秒） | 工具启动 |
| --- | --- | ---: | --- |
| kv-live-surgery-loadgen | `kv-live-surgery-loadgen-v1` | 2.229 | 通过 |
| payments-pipeline-fix-customer | `payments-pipeline-fix-customer-v1` | 1.041 | 通过 |
| payments-pipeline-fix-kafka | `payments-pipeline-fix-kafka-v1` | 2.678 | 通过 |
| payments-pipeline-fix-seeder | `payments-pipeline-fix-seeder-v1` | 1.791 | 通过 |

### 源码绑定与发布处理

20 项共用基础环境的任务通过本地断网工具检查；其中 9 项 SWE 任务及 M01、M03 还逐项验证了冻结源码的离线初始化、Python 模块实际来源及独立 pytest 进程绑定。Astroid 的构建依赖路径只作用于初始化命令，运行期依赖保持原值；具体初始化参数记录在清单中。

发布前检查覆盖最终文件系统、镜像历史层和配置。KV 与 Pretrain 使用已核验的最终文件系统生成干净层，去除旧构建层中已经删除但仍可恢复的隐藏输入；任务所需文件内容、权限、链接和数据哈希已核对。M01、M03 将原工具环境整理为独立镜像，源码仍通过固定材料恢复。清单记录对应来源和验证凭据。

这些检查证明镜像可公开获取、工具可启动及所列源码绑定成立。除前文的 M04 真实试用外，本次发布阶段未调用模型、解题或执行完整 32 任务实验。

任务定义组装时补做了委托书运行时核对：M05 要求 Python 3.11 以上，M05/M09 的原任务执行选择是 Python 3.12。两项现使用 `v2`，在原基础层上仅加入已核验的 CPython 3.12.14 解释器和 PATH 配置；新镜像的 login-shell `python`、`python3` 与 SQLite 3.53.1 均通过本地及 E2B 检查。原 `v1` 保留，清单记录前后身份。未预先执行 M05 的生产数据库准备，也未为 M09 安装 PDF renderer。
