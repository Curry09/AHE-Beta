# 对已收集的 SWE 任务补丁评分

[English](post-run-grading.md) | 简体中文

`grade` 评估指定已封口轮次中，各 SWE 任务会话产生的完整补丁。它在实验收集后运行，本地和 E2B 实验共用 `backend/scripts/experiment.py` 入口。普通任务会话单列为不适用。

这里评的是用户在演化期间已经试过的任务。**它不是对 Harness 通用能力的新留出测试。** 后一个问题仍使用独立的[评估工具](../../evaluation/README.md)。评分不进入反馈、提案、交付决策或 CI 门禁，也不改用户体感与接受记录。

## 1. 准备已收集实验和评分主机

按 [N1](n1-experiment.zh-CN.md)或[多用户教程](multi-user-experiment.zh-CN.md)完成实验，收集已停止控制器的产物。评分要求经过核验的终态 `COMPLETE` 收集，以及已封口的指定轮次。收集 COMPLETE 本身不证明用户会话成功或官方测试通过；评分前会核对会话身份、任务绑定与恢复记录。

在有 Docker 的主机上评分。E2B 实验也先下载完整归档，再在本机评分，不在 E2B 中运行嵌套 Docker，也不重启实验资源。已销毁的实验只要保留冻结材料和完整归档，仍可评分。`grade` 不需要模型、Gitea 或 E2B 凭证。

在仓库根目录运行：

```bash
uv sync --locked --extra experiments --extra dev --extra evaluation
RUNS_DIR=.experiments
RUN_ID=REPLACE_WITH_COLLECTED_RUN_ID
DATASET=/absolute/path/to/official-dataset.parquet
DATASET_SHA256=REPLACE_WITH_VERIFIED_SHA256
```

批次成员应把 `RUNS_DIR` 设为子实验根目录，例如 `.experiments/.batches/<batch_id>/children/n1`，不能用外层批次根目录。保留原冻结控制器与输入；resume 不会升级它们。

## 2. 独立提供官方数据集

提供本地 JSON、JSONL 或 parquet 格式的官方数据集，并明确其完整字节的 SHA-256。每个选中的 SWE instance 必须唯一匹配一条记录，包括仓库和 base commit。任务基线不同、目标 instance 重复、数据集变化或校验和错误，都会在评分前拒绝。

用 `sha256sum "$DATASET"` 检查拿到的文件，并与可信来源核对。校验和固定的是文件字节，不能证明任意文件就是官方数据集。评分命令不会自动下载或搜索数据集。

公开示例的 `pvlib__pvlib-python-1478` 属于 [SWE-bench dev split](https://huggingface.co/datasets/princeton-nlp/SWE-bench/tree/e48e2bd1e9fecd5bbd641e9414ac59da9f2e69f6/data)，不在 Verified 或 Lite 中。请使用包含该 instance 的官方 dev 文件；仅指定任意 Verified 文件不会匹配这个示例。此次验收的固定数据集版本为 `e48e2bd1e9fecd5bbd641e9414ac59da9f2e69f6`，`data/dev-00000-of-00001.parquet` 的 SHA-256 为 `d758d54540aa4140d0274ed0cc93b8288aa6f323c3c603e2557e7666a47fc41b`。

将数据集放在不提交的实验材料之外。gold patch 和隐藏测试只能用于这次事后评估，不能放入任务指令、任务包、persona 输入、实验 JSON 或 issue 证据。选中的官方记录会复制到独立评分 attempt 目录，因此该目录包含隐藏评估材料，不应作为普通实验反馈公开。

## 3. 不调用 Docker，先校验输入

```bash
uv run --locked --extra experiments --extra evaluation python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" grade "$RUN_ID" --dataset "$DATASET" --dataset-sha256 "$DATASET_SHA256" --offline
```

离线评分核对冻结身份、已收集归档、会话补丁与数据集绑定。不调用 Docker、模型、Gitea 或 E2B，不写评分 attempt。离线校验通过不意味着补丁通过官方测试。

新控制器保存完整预测，并记录路径、SHA-256 和字节数回执。旧冻结控制器可能只保存 diff hash 或截断的 review 预览；不能从日志或当前远端代码猜回补丁来评分，需要新跑一次实验获取完整预测。缺失预测与成功导出的空补丁不同。

补丁相对会话初始 Git 基线导出，包含已提交、已暂存和非忽略的新文件。评分将 `diff_base_commit` 绑定到冻结 SWE 源码 revision；只有 hash 而没有这个基线绑定不足以评分。

固定版本官方 evaluator 将空预测放入 `empty_patch_ids`，不计为已完成测试，见 [SWE-bench 4.1.0 reporting](https://github.com/SWE-bench/SWE-bench/blob/v4.1.0/swebench/harness/reporting.py)。因此完整的空补丁回执可以通过预测完整性校验，但评分状态为 `not_evaluated`、原因为 `official_empty_prediction`，没有通过/失败结论，也没有新测试容器，不计为完整评分（`ok: false`）。

## 4. 运行官方新容器评分

```bash
uv run --locked --extra experiments --extra evaluation python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" grade "$RUN_ID" --dataset "$DATASET" --dataset-sha256 "$DATASET_SHA256"
# 选择更早的已封口轮次，并覆盖每会话超时：
uv run --locked --extra experiments --extra evaluation python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" --json grade "$RUN_ID" --dataset "$DATASET" --dataset-sha256 "$DATASET_SHA256" --round 1 --timeout-seconds 1800
```

省略 `--round` 时选择 `config.rounds.count`，即配置的末轮，不会自动退到更早的可用轮次。`--round` 必须为正数且已封口。`--timeout-seconds` 对每个评分会话生效，默认 1800 秒。首版逐会话串行评分，不调度整个批次。

锁定的 evaluation extra 提供官方 SWE-bench evaluator。Docker 必须可用且能获取所需镜像；镜像下载、构建和测试可能耗费较多磁盘与时间。每份适用的非空预测在官方新 instance 环境中运行，评分期间没有模型调用。

## 5. 读取结果，保留原实验

每次正式调用在 `<runs-dir>/<run_id>/evaluation/<attempt_id>/` 创建新目录，保留之前的 attempt。目录包含评分 intent、补丁、所选数据集记录、evaluator 日志和报告，以及绑定原 run、归档、计划、会话和 Harness 身份的汇总。中断的 attempt 保持不完整，重跑会创建另一个 attempt。

汇总区分官方已完成的通过/失败，以及缺预测、基础设施不可用、evaluator 崩溃和超时。未知或格式错误的官方报告不能解释为正常测试不通过。普通任务不作为 SWE instance 评分；无效会话也不会因归档完整或用户接受而变为有效。

退出码 `0` 和汇总的 `ok: true` 表示评分操作完成且结果完整，也可能包含官方测试不通过的会话，不表示所有预测通过。应查看汇总中单列的 passed 数量及逐会话结论。缺失或不可评分的预测不计为完整评分。

评分不改原 Session、manifest、checkpoint、seal 或收集归档，不更新 Gitea issue。将技术成绩与单独记录的用户体验对照，而不是用其中一个覆盖另一个。实验字段 `evaluation.official_grading` 继续保持 `false`，让演化循环不接触评分；这里的显式命令提供独立事后评分。

[验收报告](../validation/post-run-grading.md)分别记录 evaluator 替身的离线测试与实际官方 Docker 评分。这些命令说明支持的流程，不表示示例实验已经通过官方测试。

官方汇总可能在测试加载/收集失败时仍标记 unresolved；若正式测试日志包含明确的 pytest 启动失败，评分会记录 `crashed / official_test_start_failed`，不计正常任务失败。当前 `pvlib-1478` 官方镜像已复现 NumPy 2 与旧项目不兼容的加载错误，详见验收报告；不要据此解读 Harness 能力。
