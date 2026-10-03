---
number: '0075'
title: 统一入口的实验后官方 SWE 评分
issue: 0
slug: post-run-swe-grading
summary: 保留完整会话补丁，校验冻结任务与归档后独立运行官方 fresh-container 评分，结果不回流演化或改写原实验。
tasks:
- id: T1
  title: 完整会话补丁与不可变预测回执
  status: done
  priority: P1
  tags: []
  depends-on: []
  relates-to: []
  parallel: false
  files:
  - backend/auto_designer/user/patches.py
  - backend/auto_designer/loop/sim_user.py
  - backend/tests/user/test_prediction_artifacts.py
  - backend/auto_designer/user/sim/runtime.py
  scope: 两条生产runner原子保留完整补丁与相对receipt，兼容旧Session与错误导出
  acceptance: 长补丁与空补丁保真，冲突/非法路径拒绝，direct和simulated均保存，恢复不覆盖
- id: T2
  title: 已收集输入绑定与独立官方评分
  status: done
  priority: P1
  tags: []
  depends-on:
  - T1
  relates-to: []
  parallel: false
  files:
  - backend/auto_designer/experiment/grading.py
  - backend/auto_designer/evaluation/swebench.py
  - backend/tests/test_experiment_grading.py
  - backend/tests/evaluation/test_swebench.py
  scope: 严格读终态归档，匹配计划/恢复/预测与官方dataset，复用evaluator并独立保留每次评分
  acceptance: 错配/篡改/未知report拒绝，完整失败状态，local/E2B归档同路径，无模型/provider调用或原run写入
- id: T4
  title: 双语教程与历史能力状态
  status: done
  priority: P1
  tags: []
  depends-on: []
  relates-to: []
  parallel: false
  files:
  - docs/tutorials/post-run-grading.md
  - docs/tutorials/post-run-grading.zh-CN.md
  - docs/CONFIGURATION.md
  - docs/CONFIGURATION.zh-CN.md
  - docs/QUICKSTART.md
  - docs/QUICKSTART.zh-CN.md
  - README.md
  - README.zh-CN.md
  - docs/audits/unified-entry-capability-migration-20261003.md
  - CLAUDE.md
  scope: 说明显式本地dataset和哈希、安装evaluationextra、两后端评分、旧预测边界及不回流演化
  acceptance: 英中命令一致，held-out泛化与用户任务评分区分，历史缺口如实更新
- id: T3
  title: 统一评分CLI与完整生产验收
  status: done
  priority: P1
  tags: []
  depends-on:
  - T2
  - T4
  relates-to: []
  parallel: false
  files:
  - backend/auto_designer/experiment/cli.py
  - backend/tests/test_experiment_cli_v2.py
  - backend/tests/test_experiment_grading_e2e.py
  - backend/scripts/e2e-spec-0075-post-run-grading.sh
  - docs/validation/post-run-grading.md
  - backend/scripts/check_experiment_repository.py
  scope: 接线grade选轮/离线验证/JSON，真实冻结/会话/收集到评分接线及完整回归
  acceptance: 
    生产链生成补丁后collect再grade，原Session/manifest/checkpoint/archive不变，结果与模拟官方边界准确分类
---

# 0075 · 统一入口的实验后官方 SWE 评分

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

为统一实验命令增加 `grade RUN_ID --dataset PATH --dataset-sha256 SHA`：在已停止且完整收集的实验中，校验冻结任务、轮次会话及完整补丁，独立调用官方 SWE-bench fresh-container evaluator。默认评分末轮的全部 SWE 会话；可显式选择一个已完成轮次。ordinary 会话单列为不适用，不补造评分。实验后的结果保存在独立 evaluation 目录，不改原 manifest、Session、checkpoint、Issue、seal 或原归档。

## Motivation

统一入口已可执行混合任务和批次，但官方评分仍只有底层 evaluator，没有与 run 材料绑定的公开命令。会话目前只持有 diff hash；direct 的 review 只显示截断补丁，不能据此还原完整预测。直接恢复旧 controller 的在线评分开关会让评分进入演化期间的上下文，同时 E2B 不提供 fresh Docker instance。因此选择两后端完成 collect 后统一在操作者的 Docker 主机做事后评分，并为新会话保存完整预测。

此命令评的是该轮用户任务补丁，不是对 Harness 的新 held-out 泛化测试，也不能据一个任务成绩宣称通用提升。原来的独立 benchmark 工具继续用于真正 held-out 测试；官方 test_patch、gold patch 和评分结论均不进入用户/需求/交付的冻结输入。

## Guide-level explanation

先运行并收集实验，然后准备一份本地官方数据集（JSON/JSONL/parquet），明确 SHA-256。数据集不进入实验 JSON 或任务包；操作者安装锁定 evaluation extra 并在本机使用 Docker。E2B 实验也是取其完整归档后本机评分，不在云端运行嵌套 Docker。

```bash
uv sync --locked --extra experiments --extra dev --extra evaluation
uv run --locked --extra experiments --extra evaluation python backend/scripts/experiment.py grade RUN_ID --dataset /path/to/verified.parquet --dataset-sha256 EXPECTED_SHA256 --offline
uv run --locked --extra experiments --extra evaluation python backend/scripts/experiment.py grade RUN_ID --dataset /path/to/verified.parquet --dataset-sha256 EXPECTED_SHA256
# 可选 --round 1；默认 config.rounds.count；--timeout-seconds 默认 1800。
```

offline 仅验证已收集输入、绑定及数据集，不调用 Docker、模型、Gitea 或 E2B，也不写评分产物。正式评分逐会话运行 fresh evaluator；输出严格区分 completed/pass、completed/fail、missing prediction、unavailable、crashed、timed_out。缺预测不当作空补丁；已成功导出且 hash 相符的空补丁可以评分。旧冻结 controller 未保存完整补丁时明确不可评分，需要新 run，禁止从截断轨迹或当前远端代码猜测补丁。已 destroy 的完整实验仍可评分，不重新启动实验资源。

官方 4.1.0 将空预测单列 `empty_patch_ids` 并跳过实例测试。成功保存的空补丁通过输入校验，但正式报告为 `not_evaluated / official_empty_prediction / passed:null / fresh:false`，不计完整评分；它既不是缺预测，也不是 evaluator 崩溃。与 resolved/unresolved 同时出现的矛盾报告拒绝。[固定版本的官方报告逻辑](https://github.com/SWE-bench/SWE-bench/blob/v4.1.0/swebench/harness/reporting.py)是此分类的依据。

## Reference-level explanation

### 会话预测保存

新增 `user/patches.py`，在模拟和 direct 两条生产 session runner 的 workspace export 成功后，按 `store.root.parent/predictions/<session_id>.patch` 原子保存完整 UTF-8 补丁（不依赖可变 cwd 或 provider 目录），Session.workspace_evidence 持有 `prediction` receipt：contract_version=1、session_id、path=`predictions/<session_id>.patch`、sha256、bytes。没有工作区或 export 失败则无 receipt 并保留失败证据。写入失败不得伪造 receipt；冲突同 session ID 不覆盖已有不同补丁。完整保存发生在 Session 最终落盘前；恢复复用原 Session/patch。direct 给用户 review 的截断预览保持现有含义。

两条 runner 在 Harness 第一次使用工作区前冻结 Git HEAD 为 `workspace_evidence.diff_base_commit`。最终导出相对该初始提交的完整 diff，包含 Harness 的提交、staged edits 与未被 Git ignore 的新文件；采用临时 index，不改变实际 Git index 或工作区。基线捕获失败不生成可评分 receipt，SWE 评分要求该 base 与冻结任务 Git revision 相同，防止将相对修改后 HEAD 的空 diff 当作最终预测。未声明新基线的旧 exporter 继续自身既有语义，但其结果不声称符合新评分合同。

导出明确禁用 Git ext-diff 与 textconv，保证得到可应用的原始补丁而非展示文本；临时 index 添加文件时排除 `.venv/`、`__pycache__/` 和 `*.py[cod]` 等运行产物。这些文件原本就不属于冻结任务源码；任务没有自己的 ignore 规则时也不能把依赖环境打进预测。不改用户实际 index、ignore 文件或 Git 配置。

### 已收集输入的绑定

`experiment/grading.py` 只读 matching schema2/workload-contract1 run、验证原材料和 RecoveryIdentity，再读取 `archive/collection.json` 与 artifacts.tar.gz。要求 collection COMPLETE、consistent=true、terminal=true，archive SHA 和内部 collection/file inventory 与外部 receipt 相符；拒绝路径逃逸、链接、重名成员和 checksum 漂移。以归档字节为权威，不读取仍可变化的 live session、当前仓库或重新 collect。只接受归档 manifest 与当前冻结身份匹配、collection controller nonce 与归档 recovery/supervisor 终态一致的输入；任何归档不支持的旧结构明确报错，不隐式改写材料。

将计划 binding 与 recovery 的 round.user_sha、users unit 的 key/session_id/完成状态匹配；逐 Session 核对 persona、task_id/digest/kind、run_id、round_no/slot、harness_sha、session_id。选择的轮次必须 sealed，原 COMPLETE 不等于所有用户有效。prediction 路径必须为本 session 唯一预期路径，hash/bytes 必须与完整归档补丁、workspace diff hash 相符。invalid/infrastructure session 不升级为有效完成；报告其原状态与评分适用性。

同时核对当前宿主 runtime 的实验终态、collection COMPLETE 及可获得的最新 controller nonce，拒绝已经 resume/RUNNING、PROVISIONING、UNKNOWN 或 PARTIAL 的旧归档；旧 archive 文件保留不表示仍可用于当前 generation。读取和开始 attempt 前再次检查，发生变化拒绝，不为校验调用 provider。评分资格所用的 sim_trace 是否存在、evaluation_status、interaction_status 必须与不可变 recovery output 的规范化状态一致，不能通过改动 Session 的派生状态升级 invalid 会话。

### 数据集与 evaluator

读取本地 dataset 的固定字节并验证用户给定 SHA（读取前后变化拒绝）；JSON/JSONL/parquet 必须在选中 instance_id 上唯一匹配，且 repo/base_commit 与 frozen SWE package 的 Git repo/revision 相同。拷贝选中的原官方 row 到评分 attempt 内，隐蔽 test/gold 字段只在此目录及 evaluator fresh container 中使用。失败输入在调用 evaluator 前拒绝。现有 SWEbenchEvaluator 复用官方 CLI（锁定 swebench 4.1.0）；正式执行先确认依赖和 Docker 可用。官方 report 只有明确将目标 instance 列为 resolved 或 unresolved 且不在 error/incomplete/missing 集合时才成为 completed；未知/malformed report 为 crashed，不能解释为正常不通过。官方 4.1.0 有时会在 pytest 加载 conftest 或收集失败后仍汇总为 unresolved。若其原始 test_output 的正式测试区间含明确加载/收集失败诊断，分类为 crashed / official_test_start_failed，不计正常失败分数；这类错误可能来自环境或补丁，不重写官方测试与判分。fresh 是官方隔离运行合同，记录 evaluator 版本/命令、patch/dataset hashes 和官方原始报告，不自造官方成功。

### 独立结果与重复操作

`run_dir/evaluation/<unique-attempt-id>/` 保存冻结评分 intent、各预测/官方 row、evaluator logs/reports、汇总；单独锁序列化本 run 的评分，不写 run runtime/journal。为避免读到未落完的管理操作，短暂只读打开已经存在的 operation lock 并取共享锁，执行期释放该锁，开始 attempt 和发布总结前核对同一宿主 generation；发生 resume 等变更则留下不完整 attempt 并拒绝成功总结。offline 不创建锁文件或目录。每次正式调用创建新 attempt，历史结果不覆盖；进程中断留下不完整 attempt，不将其视为成功。评分 intent 不复制凭证或 secrets_file。结果含原 run/config/catalog/plan/archive hashes、round、session/task/persona/Harness SHA、原用户接受/有效性与评分状态，不改任何用户体感或 acceptance。CLI 不读取 --secrets-file；摘要不包含 dataset 行的 gold/test 内容。

### Task DAG 与所有权

T1 完整预测 → T2 归档绑定与官方评分 → T3 统一 CLI 与生产验收；T4 教程与迁移清单独立开展，最终 T3 验证文档/示例一致。每个 Task files 在 frontmatter 分配，新增集成脚本 `backend/scripts/e2e-spec-0075-post-run-grading.sh`。关键验收包括超过 12000 字符完整补丁、同 session 冲突、空补丁与缺补丁、错误 task/round/SHA、损坏/链接归档、数据集错基线、官方失败/error/timeout、评分重复调用、原实验字节不变以及 local/E2B-shaped 归档共用读路径。离线测试在模型/provider/官方 Docker 边界替身，真实 Docker 验收单列，不将替身 report 称为官方成绩。

## Drawbacks

完整补丁增加存储；官方 images 和 fresh Docker 评分需要磁盘、网络及时间。历史只有 hash 的 Session 无法补回预测；首版不能迁移或修复旧 run。评分不在 E2B 执行，操作者需要可运行 Docker 的主机。逐会话评分首版串行，批次用户自行对成员调用相同命令。

## Rationale and alternatives

直接开 controller 内 objective evaluation 虽能复用旧路径，却把评分与演化隔离、运行资源、失败恢复揉在一起；不选。只给一个独立 hbench 命令没有原 run 会话补丁绑定，无法回答用户试用是否技术通过。从当前任务仓或截断输出重构预测没有可审计来源；拒绝。使用终态归档及 frozen materials，将评分与既有单 run 生命周期解耦，保留一个用户入口和独立研究评估边界。

## Prior art

现有 SWEbenchEvaluator 已封装官方单 prediction CLI；独立 evaluation/harness_bench 已有 held-out 运行，不替换它。现有 collect 的 terminal inventory、Orchestrator logical binding/round seal 与 Session immutable evidence 可以复用，不能只凭文件名或用户接受宣称有效。

## Unresolved questions

本次没有依赖未确定选择。若 live Docker/官方 image 不可用，仍完成可重复的离线接线验收并明确尚未实测；不补造成绩。

## Future possibilities

后续可加入多 attempt 比较、批次评分调度、跨版本 held-out 套件及独立评分看板。历史 continuation、工程 CI、seed 输入适配分别设计，不在本组借评分开启旧入口。
