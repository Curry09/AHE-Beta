# Spec-0084 验证记录

首次验收日期：2026-10-15；交互用户能力修订：2026-10-16。范围为反馈、执行条件和逐轮验收合同。本文区分确定性测试、真实 verifier 控制、实际后端链路与完整模型实验，不把其中一层当成全部跑通。2026-10-15收据对应`9bc3a8f`，下述能力修订单列验证，不能将旧canary当成新行为的模型实测。

使用说明：[English](../tutorials/evolution-feedback.md) / [简体中文](../tutorials/evolution-feedback.zh-CN.md)。

## 全量回归与恢复补查

主仓完整 `pytest -q`：**2448 passed，4 skipped**（525.75 秒）。其中两项是显式 Docker opt-in，随后设置 `RUN_SPEC_0084_DOCKER=1` 单独复跑，两项均通过；另外两项依赖可选 `tau2` 包，当前环境未安装。全量日志在本机 `/tmp/spec-0084-main-full-final.log`，真实 Docker 结果在 `/tmp/spec-0084-live-docker-final.log`。

全量收集后新增的统一入口恢复测试单独通过，随后补查状态显示：相关定向集 **57 passed，2 Docker opt-in skipped**。这些检查实际连接 `unified.main`、Orchestrator、SessionStore 和 RecoveryStore，覆盖已完成会话/评分恢复时不再等待 worker、实际新 Actor 必须等待有效 worker、评分提交双写中断后的签名收据恢复，以及 worker 就绪后不再残留等待标记。基础设施、模型和远端服务在这些接线测试中使用替身；真实后端证据另列。

公开离线验收脚本 **118 passed**。实际发布器与已提交 OpenAgents reader 的联合检查通过：gzip/ZIP 两种编码、七个角色的 14 个最终上下文、改写材料与伪造摘要拒绝、私有材料不进入角色上下文。它验证真实编解码和运行时调用，未调用模型。

固定已推送 reader 后，材料、公开示例、两后端入口相关测试及续跑证据视图共 **168 passed，1 skipped**（25.36 秒）。这项新增 skip 为真实 Docker 进程清理用例，已在启用 Docker 的独立运行中验证（该测试文件 **9 passed**）。CI 使用与新实验相同的 execution-evidence pin，无条件执行真实配置和 gzip/ZIP/执行证据合同检查；不再因正式发布 pin 尚空而退回旧 baseline 并跳过新合同。

## 反馈与只读边界

```bash
uv run --locked --extra experiments --extra evaluation --extra dev pytest -q \
  backend/tests/user/sim \
  backend/tests/user/test_direct_session.py \
  backend/tests/loop/test_sim_user.py \
  backend/tests/test_feedback_runtime_integrity.py
```

已通过 **264 项**（17.19 秒）。执行时使用已有、已安装依赖的 Python 环境，并设置 `PYTHONPATH=backend`；上面为同一组公开测试入口。

| 边界 | 可核验的行为 |
| --- | --- |
| 双模式反馈 | 缺失、字符串、布尔、浮点及越界评分不补成有效整数；保留独立任务判断；成功可以零票 |
| 主观检查（2026-10-15） | 当时交互中的final check在继续/接受前读取快照；该权限设计已按下文2026-10-16修订，当前交互用户使用实时工作区 |
| 终态隔离 | Actor 和工作区先结束、完整产物先采集；Reviewer 写文件、任意 shell 工具被拒绝 |
| 字节归属 | Reviewer 看到固定快照；失败后完整 prediction 仍保留；可信 finalizer 只运行一次 |
| 发布恢复 | 第二票已在远端创建但响应丢失时，恢复复用操作键，Actor/Reviewer 各只运行一次，最终仍只有两票 |
| 缺测统计 | nullable feeling 不回退旧分，derived 诊断不进入体验评分 |

前端最初 `SessionDetail.test.tsx` **7 项通过**；后续完整前端套件 **22 项通过**，生产构建通过。Ruff check/format 和 `git diff --check` 通过。这些检查不证明模型改善了任务求解能力。

全量测试进一步发现六个旧测试边界冲突，已仅修测试：两项旧断言要求终态复核先于冻结，现改为冻结与关闭后再复核；四项 Git 导出测试替身把容器命令映射到宿主机，现显式隔离容器专用 quiesce，防止在宿主机执行容器进程清理。两份测试文件 `test_experiment_grading_artifact_lifecycle.py` 和 `user/test_prediction_artifacts.py` 复跑 **53 passed**（25.19 秒），仍验证完整 patch、已提交/暂存/未跟踪改动及二进制产物归属；生产实现未为此改动。

七份相关文档的 38 个 Bash 示例通过语法检查，本地链接均可解析。

## 公开材料与验证入口

```bash
uv sync --locked --extra experiments --extra evaluation --extra dev
bash backend/scripts/e2e-spec-0084-evolution-feedback.sh
```

该脚本默认仅运行确定性合同测试，不调用模型或创建后端资源。它也提供 `--prepare-example` 和 `--grader-controls`，完整命令见教程。生成器使用真实文件 SHA、一次性 Ed25519 密钥和操作者提供的不可变镜像，不提供伪造 digest。

已经实际生成 local 示例，并通过公开 `experiment.py check --offline` 的配置、任务、计划及公钥绑定验证；未将此检查标成 `prepare/run` 成功。两份仓内基础 JSON 仍显式未配置评分，不能把它们的 `not_configured` 当作有验收。启用版由生成器单独产生。

## 真实 Docker verifier 正负控制

Docker 27.5.1 可用。`--grader-controls` 通过生产 `evaluation.service` 在真实隔离容器执行 custom 评分，固定镜像 ID：

```text
sha256:4143a73d5a9804c1bb2f93cc823a7c173dbc62964d4a5ccabcb1167229b0e2b9
```

| 控制 | 状态 | passed | 隔离 |
| --- | --- | --- | --- |
| 正确 answer JSON | completed | true | network=none，uid/gid=65534 |
| 错误 answer JSON | completed | false | network=none，uid/gid=65534 |

本机收据：`.experiments/spec-0084-verifier-canary/verifier-controls/summary.json`，`complete=true`，其中包含脚本、输入和输出 hash。目录被 Git 忽略；仓内保留生成和复测脚本。该结果证明私有 custom 评分规则能执行且能拒绝错误答案，控制输入由操作者提供，不是 Harness 的模型结果。

## 评分计划的前置检查

`registration` 现调用各 adapter 的 `validate_plan`：在启动 Actor 前验证固定 profile、私有材料、镜像声明和公开导出映射。它使用无 session、无产物的元数据请求，不伪造评分输出；正式评分时仍独立验证真实产物字节。

定向回归：`test_assessment_plan_preflight.py`、`evaluation/test_grading_adapters.py`、`test_experiment_round_grading.py` 和 `test_experiment_assessment_worker.py` 合计 **62 passed、2 skipped**（23.78 秒）。两项 skip 是明确需 `RUN_SPEC_0084_DOCKER=1` 的封存产物 Docker 测试，不能算通过。用真实普通模板生成的公开 `check --offline` 也已通过。

负控制覆盖：未固定镜像、错误脚本入口、缺少绑定材料、越界/未声明产物映射、benchmark 与 adapter 不匹配、SWE dataset 与公开基线不同、缺官方字段、不支持的 profile、需要原环境的 verifier mode，以及被伪装成工作区产物的受管服务测量。静态检查不启动 Docker；运行期缺少实际产物仍为 `missing_artifact`。

## 真实 E2B 管理链路及恢复

收据 `.experiments/spec-0084-e2b-rpc-canary/summary.json` 为 `complete=true`，记录 register/state/claim/download/submit、超时 claim 恢复、旧 worker/generation 拒绝、重复提交幂等、已完成签名收据跨 generation 复用和隐私白名单等 15 项检查。该沙箱已销毁，收据记录 `resource_state: DESTROYED`。

这次调用经过真实 E2B 固定管理 RPC，不调用模型、不创建 Gitea 仓库，也不是完整实验模型 canary。此前真实 Docker 控制与本次云端管理链分别证明自己的边界，不能合并宣称完整模型实验已经通过。

## 联合交付角色与真实模型控制

配套 OpenAgents 回归 **1481 项通过**，前端全套 **22 项通过**及生产构建通过。这些是回归验证，不是完整演化结果。

用户已授权本轮开发验收使用既有模型凭证。真实 `glm-5.3-flash` 角色控制的收据目录为操作者保存的 `validation-artifacts/spec-0084-0093-20261015/real-role-canary-authorized/`，包括 `results.json`、实际输入、receiver receipt 和脱敏审计记录：

| 控制 | 实际结果 | 能证明什么 |
| --- | --- | --- |
| 负例：声明无后续用户输入，候选却强制等待 `continue` | 返回 `REWORK`，93.77 秒 | 模型识别了违背执行条件的二次输入依赖；未把历史失败或 null 验收当成自动淘汰理由 |
| 正例：单次目标后交付 | 三次尝试均达到约 90 秒超时，未获得判定 | 不能宣称正负模型控制均通过，也不能把超时当成方案错误或验收通过 |

该负例是实际模型调用，不是 scripted 回复；正例缺测原样保留。密钥不写入文档、收据索引或实验材料。

最后一次正例发生在其他 Harness 请求已恢复可用后，使用已提交 reader `57eac90`，保持相同材料、提示和生产 advisory 限制，93.79 秒后仍超时。独立记录位于 `validation-artifacts/spec-0084-0093-20261015/real-role-canary-positive-final/`，无模型输出；不能据此区分模型思考、网关排队或网络原因。本轮不再追加重试。

## 首次本地 CLI canary 暴露的接线问题

首次完整入口尝试的冻结 run 为 `20261015T080154Z-18719bd9`，实验为 `FAILED`、收集为 `COMPLETE`、资源已 `DESTROYED`。这次尝试没有被改写成成功；后续验证使用新 prepare 身份。

它暴露两个接线缺口：真实 Triage/Divergent 的阶段绑定器没有接受 `objective_grading`，以及 worker 从 backend inspect 的顶层读状态、漏掉 local 的嵌套 `controller`。已补齐角色允许的阶段，并改为读取 `controller.state/running`；只有 controller 终态且无 pending 请求时才退出，未知状态或其他 worker 的待办不会被当作完成。

相关定向回归 **84 passed**（11.55 秒），覆盖实际角色绑定及 ledger 依赖、local/E2B 状态返回结构、矛盾/未知状态和终态仍有 pending 的情况。新 canary 的实际结果另列于下节；这批回归不替代它。

第二次冻结运行 `20261015T081811Z-14e21999` 的真实 Harness 生成了正确文件，但 Docker seed 的 shell 保活循环在清理时重生 `sleep` 子进程，导致产物冻结失败。评分如实返回 `missing_artifact / passed=null`，实验生命周期正常收尾；完整归档一致，资源已销毁。此尝试不能视为通过。保活已改为单进程 PID 1，Actor 清理规则未放宽；真实 Docker 测试覆盖三代忽略 TERM 的后台写进程被清理、容器仍运行、导出文件稳定。

## 真实模型与公开 CLI 完整链路

以下三次独立运行均通过公开 `check → prepare → run → assessment-worker → collect → destroy` 完成。它们使用 `glm-5.3-flash`、一个 ordinary 小任务、一个用户、一轮及 600 秒任务预算，配套 OpenAgents 固定为已推送候选 `57eac90a5702022c1ed2452b5b2b9918c235df39`。最后一轮确实执行独立评分；本次没有需求生成或代码交付轮次。

| 后端与交互 | Run ID | 独立评分 | 控制器 / worker | 归档 / 资源 |
| --- | --- | --- | --- | --- |
| local / Direct | `20261015T083612Z-2de11c2d` | completed，passed=true | exit 0 / exit 0，处理 1 项后自动退出 | COMPLETE，consistent，terminal / DESTROYED |
| local / simulated_user | `20261015T084608Z-7199552c` | completed，passed=true | exit 0 / exit 0，处理 1 项后自动退出 | COMPLETE，consistent，terminal / DESTROYED |
| E2B / Direct | `20261015T083637Z-210fdd12` | completed，passed=true | exit 0 / exit 0，处理 1 项后自动退出 | COMPLETE，consistent，terminal / DESTROYED |

两次 Direct 均只有一条 Harness 输入、零跟进、无用户协助；模拟交互允许后续输入，但本次同样只用一条 Harness 输入，因此不作为真实多次跟进的验收证据。三个会话均先冻结 Actor 产物，再执行只读终态评阅；体验为 4 分，报告计划为空，没有强制创建反馈 Issue。独立 custom verifier 对封存产物评分，安全摘要附有有效签名，`passed=true` 与主观体验分别保存。

本机收据分别在 `.experiments/spec-0084-live-local/summary-attempt-3.json`、`.experiments/spec-0084-live-local/summary-simulated.json` 和 `.experiments/spec-0084-live-e2b/canary-summary.json`。归档 SHA-256：

| 运行 | SHA-256 |
| --- | --- |
| local Direct | `55e6e8ff841b0e1ea81289d9907b2aad03778bcfb6119d96fe241cb5d397d5c0` |
| local simulated_user | `39ed803ff2242fb05add7795a3d612611d229747a3a3f0fe1515b9a22e571dec` |
| E2B Direct | `249a9e415e4db28c43d67d157f9acf17579b31672e788b126966c078adbdfa08` |

评分私钥、私有 plan、verifier 和 API 凭证未进入 controller 源码包或归档。E2B 另核验 15 项边界，包括合同 hash、600 秒预算、Actor 子进程停止、封存答案 hash、签名收据、未知归因不升级为确认事实和 continuation 材料保留；扫描了 855 个归档及内层源码文件。

E2B 第一次运行 `20261015T082216Z-b2e0b6a7` 因 Gitea 账户五仓配额而建仓失败，在 Actor 启动前结束；保留 PARTIAL 收集和销毁记录，后续使用新身份。通过运行所用的临时 Gitea 仓库已完成源码和技术探针记录备份后清理，账户恢复原四仓；三个通过运行的执行资源均已销毁。失败尝试没有被成功结果覆盖。

## 尚未由上述证据覆盖的范围

local 双模式和 E2B Direct 的小型模型链路已经通过，但未验证真实多轮演化、复杂 benchmark 求解改善、E2B 模拟交互或真实多次跟进。真实交付角色正控制仍超时，Spec-0084/T6 与 OpenAgents Spec-0093/T3 保持 in-progress；不能把负控制成功和确定性上下文检查替代正控制。当前仅支持可从冻结工作区产物重建的在线评分；原环境验收与受管服务可信测量不在支持范围内。

独立事后 `grade --plan` 和 `evaluation/` 下的 Harness 留出测试继续保留原边界。逐轮验收不自动淘汰、回退候选；交付 review/工程 CI 与用户任务的独立验收各自负责自己的结论。

配套 OpenAgents reader 已推送为审阅候选 `57eac90a5702022c1ed2452b5b2b9918c235df39`，兼容清单已固定该候选；正式发布 SHA 待联合审阅合并。

## 2026-10-16：恢复交互用户按 persona 核实和编辑的能力

用户确认模拟目标包括专家自行运行测试、写测试和按协作风格编辑代码。原先把`main_final_check`与终态Reviewer共用只读权限，误删了交互用户能力；更早的普通judge过滤也使工具表中的专家write_file无法实际到达。现将main/waiting judge恢复为persona工具栈，final-check使用同一实时工作区与读/跑/写能力，但不在该episode发布报告，仍最多四个工具调用且之后必须rejudge/reintent。开场和无工具决策阶段的边界保留。

只有终态Direct评阅绑定只读快照；模拟会话真正结束后也仍先停止写进程、冻结产物，再生成无工具收尾叙述和体验评分。交互中的用户写入可能属于最终协作产物，不能把其客观通过解释为Harness独立完成。

定向集**72 passed**（1.40秒），模拟用户、Direct、产物归属和评分接线相关回归**334 passed，1 skipped**（20.89秒）。skip为显式Docker opt-in；本次未调用真实模型。测试使用脚本化模型回复，但工具分发、文件写入、Python测试执行、会话循环、SessionStore及完整Git补丁导出均为实际实现。覆盖：

- main/waiting judge及final-check中，competent/expert的write_file实际执行；shallow不能调用该工具。
- 专家在final-check写入自己的测试脚本并通过真实Python子进程执行，Actor仍可继续交互。
- 一场完整模拟会话中，用户修改任务代码并运行自写测试；这些产物进入冻结补丁，用户工具轨迹可从SessionStore恢复。
- final-check仍执行四个工具后强制无工具收口；终态Reviewer的shell/写入被拒绝，冻结产物不被评阅修改。

这组测试不证明真实模型一定按persona意愿核实，也未实现逐行贡献归因；先前真实canary的结果继续按原提交保存。
