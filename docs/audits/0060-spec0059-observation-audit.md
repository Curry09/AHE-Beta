# 0059 真实取证与跨轮演进审计

审计日期：2026-09-08。原实验平台 SHA：`5a6c515bb762b3b5aaf08a3622d8911b6c2691a4`。
实验根目录：`/root/src/auto-designer-experiments/spec0059-two-user-owner-20260908`。
以下运行事实来自冻结产物，不是使用 0060 新 prompt 重跑后的结果。

## 结论

0059 的按角色只读取证入口在这次实验中实际工作，并对问题解释有帮助；它不是设计质量
自动保证。读取协议允许新旧格式共存，但生产逐轮发布尚未接通，本实验也没有进行制品升级。
因此不能宣称“已经验证观测机制能随着多轮进化自动运行”。

## 实验边界

两局是同一 harness SHA `2f26d0c6a51b08c405cb5bad9193b79456e80870` 的独立会话，
不是两个迭代轮次。第一局接受 3/4，第二局放弃 1/4。9 条报告经 Triage，PM 产 3 条提案，
Designer 原流程归并为 3 条结构提案，Owner 全部准入，2026-09-08 06:27:47 +08:00 结束。
未启动 OpenAgents，未跑官方客观评测，用户自测/接受不等于官方通过。

来源：实验 `manifest.json`、`summary.json`、`*-outcome.json`、
`role-runs/index.jsonl`、`role-runs/evidence_access.jsonl`。

## 各角色是否用到了观测

| 角色 | 允许的实际访问次数 | 成效与局限 |
|---|---|---|
| Triage | native 41、用户时间线 L2 9、beat L3 6 | 为单条报告查证队列与长等待；#6 将静默期定位到模型调用挂起/失败。9 条全部处理，无 driver 失败。多条调查重复，51.4 分钟串行处理；调用多不等于效率或语义质量高。 |
| PM | native 9、L2 2 | 对照内部执行与用户判断，发现过早干预和过度等待的共同信息缺口。#11 的产品解释有实质证据支持；#10/#12 仍出现工具边界、write-first 等过早机制化表达。 |
| Designer | native 6 | 核实来源提案引用的日志后综合控制与状态问题；#15 从相关性进一步推出共享阶段边界，观测并未证明这种架构必要性。 |
| Owner | 无原始观测访问 | 按职责消费提案与继承证据，而非重查原始会话；无访问符合边界，不是能力缺失。原流程 3 条准入不能充当独立质量评审通过。 |

native 为文件工具访问事件，包含 manifest/说明/日志，不能当作独立日志数量。
Triage 另有 1 次过宽 `/root/src` 观测搜索被拒绝；访问审计明确记录 allowed=false。

用户心路仍走 `get_session_timeline`，它表达目标、修订和行为，不依赖当前制品日志字段。
原生文件说明内部执行，与用户可见记录互补，不应替代时间线。

## 观测带来的关键增量，以及不能推出的结论

第二局 `44b429791aee44b392d7a405e915a92c` 共 150 个原生事件，包含 5 次 LLM 错误结束，
耗时分别为 644.680、674.230、719.253、718.256、716.226 秒。用户认为仍在持续只读调查，
但长等待期间没有新 Tool span。它支持将“前段调查过长”和“后段调用失败、等待不可见”
分开解释，而不是把整个会话都归因于 agent 不愿编辑。

第一局 `cd30fbd31bf940658b3c2bd4bd18696e` 共 202 个事件，没有 has_error=true。
这只能说明导出的错误标记，不证明业务成功；“912 tests passed”来自用户会话自查记录，
不是原生元数据能单独验证的事实。原生日志没有完整工具参数、输出或任务答案。

PM 对陈旧活动重放的解释是日志与公开记录对照后的推断，不能只凭缺失 Tool span 就
无条件认定唯一根因。用户“若纠偏生效可能 15 分钟完成”是反事实自评，不是测得的五倍收益。
Designer 用两局相近中断时刻证明共享阶段原语的必要性，也超出了两样本证据的支持范围。

## 能否随着轮数迭代

读取层可以：`ObservationProvider` 每次 invocation 按授权 session 重新读 manifest，平台
不解析固定事件名或字段；旧 session 引用不会改指新日志。新格式只要有自己的文件清单与
说明，普通文件工具可以读取。新增两项测试覆盖连续版本文件名/内容格式不同、旧证据继续
可引用，以及新轮缺包时不会回退到旧轮包。

自动生产闭环尚不可以直接声称成立：

1. `backend/auto_designer/designer/observation_provider.py` 是消费者。生产用户 runtime
   `backend/auto_designer/user/sim/runtime.py` 收尾导出任务 patch 后删除容器，没有自动
   发布会话观测包的对应逻辑；仓库内观测 root 接线主要在读取器与离线回放脚本。
2. 本次由仓库外 `run-spec0059-two-user-owner.py` 包装 workspace close，先 docker cp
   固定 `/tmp/spec0059-observations/`，再按 session 发布 manifest。不是生产默认能力。
3. `spec0059_observation_entry.py` 依赖模板私有 `_make_step_collector`、`_run_supervised`
   及 span 字段。若新制品改变运行时/入口，这个固定适配器可能失效；它本身不会自动演进。
4. 读取器验证 session、相对路径和访问范围，但不强制验证 harness SHA、文件摘要或
   发布完整性。外壳没有版本校验闭环，旧证据与当前源码对照还需明确版本，不可混用。

正确分工：稳定的是会话关联、版本锚点、受限只读导出与用户心路接口；可演进的是制品
日志格式、文件名和阅读说明。发布能力要跟着被交付的 harness 版本走，平台不能继续靠
识别固定私有函数补日志。需在容器删除前安全导出，保留旧包，并在新包缺失时明确降级。
本次未实现这项生产接线，也未进行多轮真实升级实验。

## 0060 初版修改验证（5415202，后续输入隔离修订见下节）

使用冻结的 `post-generation-issues.json` 和原 Designer artifacts，在内存 FakeTracker
上调用修改后的真实 Designer driver，再用 `Owner(review=False)` 做机械交接回放：

- #1–#9 仍被两条有效结构提案吸收；
- PM #10/#11/#12 保持独立，连同结构 #13/#14 共 5 条交接；
- 原 #15 的来源全部为 PM，触发 `not-cross-delivery-proposal`，不创建结构票；
- 不调用新模型、不变更原 Gitea，不能用此结果宣称新 prompt 的语义质量或共享交付效果已验证。

自动化回归覆盖新旧 PM provenance、混合标签保护、PM-only 结构拒绝、模型非法 covers、
Owner 重叠关联与非法目标过滤、session 引用继承以及跨格式/缺包行为。

验证命令：

```bash
.venv/bin/python -m pytest backend/tests/designer backend/tests/loop/test_designer.py backend/tests/loop/test_orchestrator.py backend/tests/test_run_swebench_closed_loop.py -q
```

175 项通过；修改的 Python 文件 Ruff 检查通过；spec validate 通过（有跨历史 spec 文件
重叠等警告）。测试只证明角色硬边界和读取契约，不替代真实多轮质量评估或生产导出闭环验收。

## 后续澄清：Designer 不读取 PM

用户明确要求输入隔离，替代初版“可参考 PM 但不能吸收”的规则。当前实现从 Designer
的开放 proposal 和 ready 输入中排除 PM，包括历史 provenance；证据授权随可见提案
收窄。PM 独有引用不会给 Designer 开放观测权限。正常调用与协议恢复调用均受此约束。

初版的固定产物回放结果仅描述 5415202，不是当前新 prompt 的输出；原 Designer 产物
引用了 PM，若原封不动交给当前 driver，会因不可见来源被拒绝。不能把旧产物删掉几个
票号后当作新模型实验结果。当前验证为 176 项相关回归通过，尚未重跑真实模型设计流程。
