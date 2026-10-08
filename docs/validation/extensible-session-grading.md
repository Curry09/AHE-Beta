# Spec-0083 可扩展会话评分验证记录

日期：2026-10-08（北京时间）。本组扩展已发生用户会话的产物采集和独立事后评分，不重新运行 Harness，不更新原用户接受记录，也不替代 Spec-0065 的独立 Harness benchmark 运行。

## 验证状态

第一版代码、离线回归和部分真实 Docker 评分已完成；受管原测量采集仍依赖未完成的 Spec-0081。以下清单区分实际官方执行、边界替身测试与尚未满足的前置；未完成的检查不宣称通过。改动位于 `feat/unified-experiment-entry`，提交前尚未 commit。

| 范围 | 当前证据与限制 |
| --- | --- |
| 公共 plan / CLI | 已接入；旧 dataset 参数退役，所有 scorer 共用必填 `--plan`。README、Quick Start、配置说明及评分教程的中英版本同步更新。 |
| direct / simulated 共用采集 | 已实现有界二进制文件采集及完整 prediction 绑定；实际 runner 的清理/最终化/采集顺序回归通过，不补造历史缺失产物。 |
| SWE 官方 4.1.0 | 本组新接线执行官方容器正负控制，结果分别为 completed / true 与 completed / false；公开 plan CLI 也完成真实归档评分。 |
| Terminal production-planning | 实际原官方 verifier、干净数据库与 SQL 重放：参考解 20/20、reward=1；空 SQL reward=0，正负控制均符合预期。 |
| Terminal kv-live-surgery | 原 loadgen 可信测量采集依赖 Spec-0081 受管环境，未完成；JSON fixture 不代表完整支持。 |
| TUA 010-pivot-product-revenue | 实际官方固定 Excel 任务正负控制 reward=1/0；补齐验收副本目录权限后重测通过，不推广为整个 TUA suite 支持。 |
| NL2Repo tinydb | 实际官方 tinydb 镜像、原测试与后处理得到正控制 204/204、负控制 0/204；通过率 1.0/0.0，无二值阈值，passed 保持 null。 |
| custom | 实际隔离容器固定脚本正负控制分别 completed / true 与 completed / false；标记 custom，不冒充官方评分。 |
| 完整 E2B / N8 | Spec-0081 尚未完成，本组不重启历史 N8 以补证据，不宣称完成公开 N8 全路径。 |

## 自动回归与证据边界

生产验证入口为 `backend/scripts/e2e-spec-0083-session-grading.sh`。专项范围包括当前格式两后端归档、direct/simulated 相同采集合同、plan 材料和 adapter 校验、错误基线/来源/会话/轮次/ generation、篡改/缺失/超限产物、收集前后清理顺序、重复与中断评分，以及原实验不可变。

```bash
bash backend/scripts/e2e-spec-0083-session-grading.sh
# 使用仓外准备的固定控制材料，执行真实注册 adapter：
bash backend/scripts/e2e-spec-0083-session-grading.sh \
  --official /absolute/path/to/controls.json /absolute/path/to/new-control-results
```

默认模式仅跑离线测试，明确提示未执行真实评分器。可选官方模式需要 Docker 和完整材料，不下载任务或启动用户会话。`controls.json` 是验收脚本私有输入，不是新增公开实验入口；其字段为 `plan`（指向当前 grading plan）和非空 `controls` 数组。每项指定 `name`、原任务来源的 `task_id/task_digest/source`、按材料路径/hash 固定的 `artifacts`、以及 `expected.status/passed`（可另指定 score）。SWE 控制另指定 `instance_id`、`patch_file/patch_sha256`。路径相对 controls 文件所在目录解析。验收脚本直接调用生产 adapter，保存真实 raw reports；只有所有声明的预期匹配才写 `complete=true`。输出目录必须是新目录。

实际执行结果：

| 检查 | 结果 |
| --- | --- |
| `.venv/bin/python -m pytest -q backend/tests` | **2235 passed**，460.93 秒；包含既有 SWE、续跑及独立 Harness 评测回归。 |
| `bash backend/scripts/e2e-spec-0083-session-grading.sh` | **266 passed**，131.94 秒；脚本明确提示未运行真实评分器。 |
| Ruff check / format | 全部通过，306 个 Python 文件格式一致。 |
| spec validate / render / graph | 校验通过，生成视图已同步；已有跨 spec 引用提示仍是 warning。 |
| 脚本语法、内嵌 driver 语法、`git diff --check` | 通过。 |
| 新 plan 对真实已完成 SWE run 的只读离线调用 | 两个会话均为 `ready`；`ok=true`、`environment_status=not_checked_offline`，未写评分 attempt。 |

真实离线调用使用 `/home/wydlinux/spec0075-live-20261003/requests-control/runs` 中的 `20261003T111409Z-027c617f`，选择第 1 轮。私有 plan、结果及固定控制材料位于仓外 `/home/wydlinux/spec0083-validation-20261008/`；最终结果为 `swe-offline-final.json`。此处没有生成官方分数。

公开模板按实际 grading-plan-v1 schema 校验，并验证材料引用、任务选择、教程命令、移除全局时限覆盖、原 Session 不回写及历史 Session 字段只读恢复。首次完整测试曾因并行编辑源码触发冻结保护，且发现 Quick Start 遗留旧命令；停止源码编辑并更新全部公开入口说明后，上述完整重跑通过。

初次离线验证时 Docker 尚不可用；用户启用 Docker 后，已执行下述真实容器控制。所有原始尝试与失败记录保留在仓外 `/home/wydlinux/spec0083-validation-20261008/`。KV 缺可信原测量，仍未配置伪造控制。

Spec-0083 的 T1、T2、T5 已标 done；T3 的受管采集、T4 的真实官方核验及 T6 的真实验收仍保留 pending。Spec-0081 前置未完成，本组没有通过新跑任务或替身测量绕过。

离线测试中的模拟 evaluator、Docker 边界或 fixture reward 只证明接线及分类。它们不能证明某个官方任务可在当前 Docker 主机执行，更不能证明 Harness 产生过官方成功结果。真实官方正负控制使用独立控制材料；控制材料不是模型交互产物。

## 固定的首批官方来源

| Adapter | 固定来源 | 支持范围约束 |
| --- | --- | --- |
| SWE | `swebench==4.1.0` | 原官方报告分类及 resolved 语义；空预测不计已完成。 |
| Terminal | `harbor-framework/terminal-bench-1` / `452bf305c6daa62fc59061d22133a7cbc7c1572e` | 首批 production-planning 与 KV；未覆盖 mode/version 明确拒绝。 |
| TUA | `facebookresearch/TUA-Bench` / `3497fd320abcafaf4797424192c891a593fd7964` | 首批 010-pivot-product-revenue；标准答案及外部依赖须固定。 |
| NL2Repo | `multimodal-art-projection/NL2RepoBench` / `781a1da1ee41fb8edb0bed22f586d69111610edf` | 首批 tinydb；原测试来自官方 task image，不是三个 grader 元数据文件或 Agent 自写 tests。 |

材料和镜像身份必须写入评分 attempt。任务仓库的 revision 本身不能证明本地文件就是该版本；评分端校验选中的实际官方文件。NL2Repo 原通过率与操作者指定的二值阈值分开显示；custom 没有统一官方标准。

## 结果解释

`completed / passed=false` 表示正式评分有效执行后给出的任务失败。缺材料、合同不成立、基础设施不可用、解析失败、超时和官方跳过均单列，并保持 `passed=null`。没有二值规则的连续分数也保持 null，不能据此生成 `valid_accept`。

保留官方 raw reports 和官方分母；本系统的 coverage、状态和 acceptance 诊断不能替代官方汇总。原实验为 COMPLETE、用户接受或测试进程 exit=0，均不足以单独认定官方任务成功。


## 2026-10-08 后续模块清理

删除原 `evaluation/swebench.py` 及包级导出；官方 CLI 执行器合并进 `adapters/swebench.py`，以私有 `_SWEbenchRunner` 类与公共适配器区分职责；独立 runner 文件已删除。删除 `from_env()`、旧接受判定函数、会话 evaluator 注入及即时评分事件，控制器不再设置在线评分开关。新会话只记录交互及产物，客观结论和接受关系只存在于独立评分报告。历史 Session 的存储字段保持可读，不重写归档。新增两种交互模式的生产 runner 回归，验证遗留宿主环境变量不会开启评分。

清理后相关回归 **773 passed、2 skipped，148.51 秒**。范围包括 evaluation、loop、user、全部 grading 测试、统一控制器环境、Session 模型、需求证据合同，以及独立 `evaluation/tests`。两个 skip 均因未安装可选 `tau2`，属于既有 Harness benchmark 适配器测试。Ruff check / format、spec validate 与四个相关验证脚本的 bash 语法检查通过，生成视图已同步；生产源码中不再出现旧 evaluator、旧接受函数、`from_env()` 或即时评分调用。真实归档的新路径离线检查通过，结果保存为仓外 `swe-offline-cleanup.json`。

前述 2235/266 为首次实施版本的验证记录。本次清理后没有再次执行完整后端全量测试；上述回归覆盖改动的执行与调用边界。真实 Docker 验证见下文；Spec-0081 受管测量限制不变。


SWE 单文件合并后相关回归 **160 passed，104.84 秒**，覆盖全部评分层测试、原会话事后评分、归档生产接线及 direct/simulated 采集边界。Ruff check/format 通过；真实归档的新入口离线校验通过，结果为仓外 `swe-offline-single-file.json`。独立 runner 模块及导入无残留，原有评分规则、镜像冻结、输入合同及原始报告解析保持同一实现。


## 2026-10-08 Docker 实测

Docker 27.5.1 已连接。此批直接使用当前生产注册 adapter、官方固定任务材料及隔离 Docker 容器；不启动 Harness 或模型，不把控制材料当作历史用户产物。验证脚本先完成 **290 passed，154.39 秒**，然后进入实际官方控制。

| 实测 | 结果与原始证据 |
| --- | --- |
| SWE psf__requests-6028 | `official-attempt-1/control-1` 非修复 patch：completed / false / 0；`control-2` 官方 gold patch：completed / true / 1。 |
| 公开 grade --plan | `public-grade-real-retry.json`：exit=0、ok=true，两个原会话 completed，1 passed、1 failed；`public-grade-retry-immutability.json` 验证 595 个原冻结文件字节未变。两项原用户未接受，独立 acceptance_assessment 为 not_applicable，不虚构有效接受。 |
| NL2Repo tinydb | `nl2repo-real-attempt-1/summary.json` complete=true；正例 204 passed / 204，分数 1.0；负例 0 passed / 204，分数 0.0。保留官方分母与连续分数，passed=null。 |
| custom | `custom-real-attempt-1/summary.json` complete=true；固定脚本正例 1/true、负例 0/false。使用本地不可变 Python 3.12 镜像 ID，不更改脚本或规则。 |
| Docker 二进制采集 | `docker-artifact-proof/proof.json`：24 字节二进制原样导出并绑定 hash/receipt；拒绝超限、缺失、symlink 和 FIFO；测试容器移除。该测试身份为控制 fixture，不声称原 N8 产物采集成功。 |
| Docker 后台写入停止 | `docker-writer-proof/proof.json`：先确认真实后台 heartbeat 更新，再执行 quiesce；写入停止、进程退出或成为 zombie，测试容器移除。 |

公开 SWE CLI 第一次与其他容器控制并行，官方 4.1.0 报告生成过程中遍历 Docker 容器，遇到另一个测试刚删除的容器，inspect 返回 404；该尝试为 crashed，保留在 `public-grade-real.json`。串行重试成功；不将官方报告阶段基础设施错误计为任务失败。本次 SWE 验证已改为串行执行，但未宣称解决官方 SDK 对宿主机并行容器生命周期的竞争。

SQL 官方环境首次构建超过 task.toml 的 600 秒上限，结果为 timed_out，未执行 SQL 验收。原始 `official-attempt-1/summary.json` 保持 complete=false，不以其两个 SWE 控制成功声称全组通过。基础镜像由官方 registry 直接下载、逐层核验压缩 digest 与解压 diff_id 后通过 docker load 缓存；配置 digest 核验通过，未修改官方 Dockerfile，记录为 `python313-verified-cache/receipt.json`。随后 SQL 与 TUA 实测完成，结果如下。

各次 Terminal / TUA / custom / NL2Repo 控制与参考解、权限探针均有成功的容器清理凭据；`final-cleanup-proof.json` 逐个核对本次 12 份 receipt，确认对应容器已不存在。已有 `auto-designer-gitea` 服务保持运行；未执行 Docker prune。真实官方控制证明固定验收规则接线正常，不能证明历史 Harness 已解决这些任务，也不代表完整官方 suite 或 E2B/N8 已跑通。


后续完成结果：

| 实测 | 结果与证据 |
| --- | --- |
| Terminal production-planning | `production-real-attempt-2/summary.json` complete=true；官方参考解三份 SQL 在独立 verifier 中 reward=1、20/20 tests passed；空 SQL reward=0。实际官方 Dockerfile 和 tests 未改写。 |
| TUA 010-pivot-product-revenue | `tua-real-attempt-1/summary.json` 与修复后的 `tua-real-attempt-2/summary.json` 均 complete=true；冻结标准答案 reward=1，无效 workbook reward=0。 |
| TUA 验收副本权限 | 第一次官方脚本的 EXIT trap 无法写 `/logs/artifacts`，不影响 reward，但丢失官方副本。本组初始化该目录并允许非 root verifier 写入；重测正例 verifier.log 无权限错误，`tua-artifact-permission-proof/proof.json` 实际以 image 的 agent 用户写入并导出成功。保持官方脚本、镜像、reward 规则及隔离限制。 |
| 权限修复后的回归 | `backend/tests/evaluation/test_grading_adapters.py`：19 passed，2.06 秒；Ruff check / format 通过。其余前述实测发生于目录权限补齐之前；SWE 不使用此容器初始化逻辑。 |

五类 adapter 的 **10 个正负控制** 均得到声明的预期结果。SWE 控制保留在第一组 partial summary 中；该组因随后 SQL 冷构建超时仍 complete=false。其余四类各自新尝试的 summary 均 complete=true，不能覆盖或删除失败历史来制造全组成功。

KV live-surgery 仍缺 Spec-0081 管理侧可信原测量，未实测；T3/T4/T6 保持 pending。当前结论仅覆盖上述固定任务、材料及 Docker 主机；E2B 原环境收集、完整混合 run 生命周期和整个官方 benchmark suite 不在这 10 个控制的证明范围内。本次实测完成时，代码及文档尚未 commit/push。
