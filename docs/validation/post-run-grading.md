# Spec-0075 实验后 SWE 评分验收

日期：2026-10-03。本组实现 `experiment.py grade`，评分已封口用户任务的完整补丁，不是对 Harness 新留出任务的泛化测试。评分与原演化实验分开保存；官方数据集的隐藏测试和 gold patch 不进入实验配置、用户或需求上下文。

## 验证范围

```bash
bash backend/scripts/e2e-spec-0075-post-run-grading.sh
```

脚本使用真实任务材料编译、Session runner、Git 补丁导出、SessionStore、Orchestrator、恢复账本、round seal、engine 终态收据、collect_archive、归档绑定，以及 SWEbenchEvaluator 的预测生成和报告解析。模型、工作区 provider、forge 和官方 Docker evaluator 是明确的边界替身。local/E2B 参数化代表两种冻结配置和同一归档消费路径，不代表真实 Docker/E2B 实验，也不代表任何补丁实际通过官方测试。

生产链测试先跑两轮混合任务，中间含实际 Git 交付提交及中断恢复，保存八个会话；再通过 engine 完成归档，默认评分末轮的两个 SWE 会话。各会话产生大于 12000 字符的完整 Git 补丁。普通会话不适用，重复评分产生新 attempt，原 manifest、Session、checkpoint、预测和原归档字节不变。实时会话文件后来改变时，评分仍读取已核验归档。

专项反例包括不可评分旧会话、成功空补丁与导出失败、保存失败/冲突、相对原 Git 基线的已提交/暂存/新文件导出、绑定错误、任务或数据集基线错误、恶意/损坏归档、官方报告 error/missing/unknown、超时和依赖不可用。离线校验没有 Docker、模型、provider 调用和写文件。

还覆盖当前 generation 与归档的绑定：当前运行已恢复、控制器 nonce 改变、状态未知、收集不完整或评分期间开始续跑时拒绝成功评分；不可变 recovery output 中的无效会话也不能通过改动 trace 或派生状态被升级为有效。

实测前专项脚本执行 **187 passed，54.48 秒**；官方实测修复后全仓锁定依赖回归 **1734 passed、2 skipped，264.15 秒**（已安装 evaluation extra）。新增加载/收集失败反例也通过。两个 skip 是既有可选 tau2 依赖未安装。Ruff lint / format 全仓通过（519 个文件），脚本 `bash -n` 和 `git diff --check` 通过。未运行的检查不宣称通过。

## 实际环境边界

此前只验证了脚本化官方边界与 Docker 补丁导出。2026-10-03 的后续验收安装锁定 `swebench==4.1.0`，下载原始官方数据和 instance 镜像，通过真实 `grade` CLI 执行官方测试；本节将这两类证据分开。

另行使用已有 `python:3.12-bookworm` 镜像，在真实 Docker 容器中验证生产 `DockerWorkspaceRuntime`：捕获原始 Git 基线；模拟已提交修改、暂存文件与未忽略的新文件；导出 **18592 字节**补丁并在全新基线 checkout 中应用后逐文件核对。原 Git index SHA 不变，验证 Git textconv 已禁用，`.venv/`、`__pycache__/` 等运行产物和被忽略文件未混入补丁；测试容器在 finally 中清理。证据位于 `/home/wydlinux/spec0075-validation-20261003/docker-prediction-proof.json`。这证明容器内完整预测导出，不是官方 evaluator 成绩。

旧 N4 实验由冻结控制器执行，没有新完整预测回执；不从截断轨迹或当前任务目录重构补丁，也不改它们的 Session 或原收集归档。需要新实验生成符合新合同的预测，才能执行完整评分。

已对 Spec-0073 完成的真实 Local 和 E2B N4 归档进行只读离线复核：末轮各四个会话，两个 ordinary 为 `not_applicable`，两个 SWE 为 `ungradable / missing_prediction`，passed/failed 均为零。复核使用外部生成的明确标记为 synthetic 的匹配数据集，仅测试历史归档绑定和缺预测拒绝，不作官方数据或评分证据。原 manifest、归档及收集回执 SHA 不变，未生成 evaluation 目录，未调用 provider、模型或 Docker evaluator。记录在 `/home/wydlinux/spec0075-validation-20261003/legacy-validation.json`。

固定的官方 4.1.0 将空预测列入 `empty_patch_ids`，跳过其测试；因此完整的空预测输入可通过 integrity 校验，但评分为 `not_evaluated / official_empty_prediction`、passed 为 null、fresh 为 false，不能计完整评分或伪称测试失败。[官方固定版本报告逻辑](https://github.com/SWE-bench/SWE-bench/blob/v4.1.0/swebench/harness/reporting.py)支持此分类。

## 官方 Docker 评分实测（后续验收）

使用官方 Verified 的 `psf__requests-6028`（repo=`psf/requests`，base=`0192aac24123735b3eaf9b08df46429bb770c283`）做正反对照。官方 gold patch 仅由隔离验收 Harness 施加到正对照工作区；负对照只新增无关文件。二者不是模型生成的解答，不用于训练或需求，也不能作为模型能力成绩。

任务从真实固定 Git revision 冻结；真实 Docker 工作区、direct Session runner、SessionStore、Orchestrator 和 RecoveryStore 生成两份补丁与封口记录；engine 和 collector 生成完整归档；随后公开 CLI 在新的官方 instance 容器中运行官方 evaluator。用户评审/对照 Harness 与 forge 使用明确的验收替身，没有调用模型、Vigil 或真实 Gitea；评分子进程、官方测试和报告没有替换。

首次评分正确返回 `ok=true`、`completed=2`、`passed=1`、`failed=1`，证明测试失败仍可完成评分操作。保留日志与原报告。重复评分产生独立 attempt，仍为 **1 passed / 1 failed**；对原 manifest、runtime、journal、Session、checkpoint、预测、归档及其他原文件共 **642** 个逐一计算 SHA-256，评分前后完全一致。证明文件为 `requests-control/live-proof.json`，前置摘要为 `original-before-hashes.json`。官方容器已自动移除，自建工作区容器也已清理。

同时对公开示例 `pvlib__pvlib-python-1478` 实测：它属于官方 dev split，不是 Verified/Lite。镜像中 NumPy 2 导致加载 conftest 时访问已移除 `np.Inf`，pytest 根本没有执行任务测试；官方 4.1.0 仍把它汇总为 unresolved。修复 evaluator 后，重新从同一归档评分，两个对照都记录为 `crashed / official_test_start_failed`，CLI exit 1，passed/failed 均为零。环境没有被修改，官方原报告原样保留，不能把该结果称为任务失败或修复成功。加载/收集失败也可能由补丁造成，分类不把所有这类错误归因于基础设施。

原始证据保存在 `/home/wydlinux/spec0075-live-20261003/`，其中 `requests-control/` 包含正反对照的输入、归档、CLI 输出和官方日志；`pvlib-rechecked.stdout.json` 保存原示例重新分类后的结果。评估资料留在仓外，不作为用户反馈或运行配置提交。
