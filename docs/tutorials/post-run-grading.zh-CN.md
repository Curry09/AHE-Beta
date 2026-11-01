# 对已完成的用户会话评分

[English](post-run-grading.md) | 简体中文

`experiment.py grade` 评估已收集、已封口轮次中用户会话产生的结果。本地和 E2B 实验共用命令，由独立的私有评分计划选择规则并固定材料。direct 和模拟用户会话都可评分，但原始执行及产物回执必须满足适配器的合同。

这里验收演化过程中已经尝试的任务，不重新调用 Harness，也不是在新任务上测通用能力。后者使用独立的 [Harness 评测工具](../../evaluation/README.md)。评分不反馈到演化，不修改用户评阅，也不更新 Gitea issue。

## 1. 收集实验并准备评分主机

完成 [U1](u1-experiment.zh-CN.md) 或[多用户教程](multi-user-experiment.zh-CN.md)，收集已停止控制器的完整归档。指定轮次必须已封口，收集必须有经过核验的终态 `COMPLETE` 回执。归档完整不证明交互有效或任务成功，这些事实单独核验。

E2B 实验先下载归档，再在有 Docker 的主机评分。不重启 E2B，不运行嵌套 Docker，不调用模型；无需模型、Gitea 或 E2B 凭证。已销毁计算资源的实验，只要仍保留冻结 run 目录和完整归档，就可评分。

```bash
uv sync --locked --extra experiments --extra dev --extra evaluation
RUNS_DIR=.experiments
RUN_ID=REPLACE_WITH_COLLECTED_RUN_ID
PLAN=/absolute/path/to/grading-plan.json
```

批次成员的 `RUNS_DIR` 应设为子实验根目录，例如 `.experiments/.batches/<batch_id>/children/u1`。保留原冻结控制器与输入；升级当前 checkout 不会升级既有 run，也不能补造回执。

## 2. 准备私有评分计划

从模板开始：

| 模板 | 用途 |
| --- | --- |
| [swebench.json](../../examples/grading/swebench.json) | 公开 pvlib SWE 示例 |
| [mixed-benchmarks.json](../../examples/grading/mixed-benchmarks.json) | 分别配置生产计划、Excel 和 TinyDB 的规则 |
| [custom.json](../../examples/grading/custom.json) | 操作者自定义文件验收器 |

这些是模板，不包含官方数据集或完整 benchmark 材料包。须替换材料路径、占位 hash、镜像 digest 和任务/产物 ID。任务 ID 必须已存在于冻结 run，计划不能添加任务或替换来源。同一任务至多选择一个 grader；未选择的任务记为 `not_configured`。

只评 SWE 时，计划例如：

```json
{
  "schema_version": 1,
  "materials": {
    "dataset": {
      "path": "/absolute/path/to/official-dev.parquet",
      "sha256": "REPLACE_WITH_THE_FILE_SHA256"
    }
  },
  "graders": [
    {
      "adapter": "swebench",
      "contract_version": 1,
      "task_ids": ["pvlib__pvlib-python-1478"],
      "inputs": {"dataset": "dataset"},
      "timeout_seconds": 1800,
      "config": {}
    }
  ]
}
```

`materials` 声明本机普通文件及 SHA-256，不接受目录；任务包应打成 tar。相对路径以 plan 所在目录为基准。`inputs` 将适配器输入名称映射到材料名称。`timeout_seconds` 是每个选中会话的时限，没有 CLI 全局覆盖选项。`config` 为适配器专用配置。run、task digest、session 和实际试用 Harness SHA 从已验证归档读取，不由操作者手抄。

用 `sha256sum /path/to/material` 检查字节，并核对可信来源。hash 固定内容，但不能证明任意文件就是官方材料。命令不会发现或下载数据集。gold patch、隐藏测试、标准答案和私有计划不要放进公开任务输入或 issue 证据。评分 attempt 可能包含隐藏材料，不应作为用户反馈公开。

公开 pvlib instance 属于 [SWE-bench dev split](https://huggingface.co/datasets/princeton-nlp/SWE-bench/tree/e48e2bd1e9fecd5bbd641e9414ac59da9f2e69f6/data)，不在 Verified 或 Lite。固定 dev parquet 的 SHA-256 为 `d758d54540aa4140d0274ed0cc93b8288aa6f323c3c603e2557e7666a47fc41b`。instance 必须唯一匹配冻结仓库和 base commit。

旧 `grade --dataset ... --dataset-sha256 ...` 接口已退役。只评 SWE 也必须传 `--plan`，数据集改为计划中的材料。

## 3. 先检查输入，不执行评分器

```bash
uv run --locked --extra experiments --extra evaluation \
  python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" \
  grade "$RUN_ID" --plan "$PLAN" --offline
```

省略 `--round` 时选择 `config.rounds.count`，即配置末轮，不会自动退到更早轮次。轮号必须为正数且已封口。

离线检查核对计划/材料、原归档/会话身份和适配器要求的证据。不创建容器，不调用模型/provider，不写评分 attempt。通过不代表 Docker 或官方环境一定可运行，也不代表测试通过。

完整 SWE prediction 须保留原基线、路径、字节数和 hash 回执。其他产物使用原会话的 `workspace_evidence.evaluation_artifacts` 回执，绑定原试用 Harness SHA 与已收集字节。计划不能把后来补进去的文件变成原执行证据。缺失、截断、超限仍无法有效验收，也不能从旧日志或最新远端代码补造。

v2 任务包可声明公开的工作区文件产物及大小上限，v3 容器任务还可通过环境驱动采集声明的服务产物。声明中不包含隐藏测试或答案。受管服务测量需要相应运行时能力和原运行的可信回执；评分时按适配器要求核对，缺少能力或证据时保留不可评分状态，不能用普通文件替代。任务环境格式见[配置说明](../CONFIGURATION.zh-CN.md#任务包)。

例如，新自定义文件任务可在实验开始前向 version 2 任务包添加以下声明。`output` ID 对应 `custom.json` 的 `artifact_map`；任务必须实际生成此文件。这里的大小上限是操作者显式选择，不是自动推导的 benchmark 默认值。

```json
{
  "artifacts": {
    "version": 1,
    "exports": [
      {
        "id": "output",
        "source": "workspace",
        "path": "output.json",
        "content_type": "application/json",
        "required": true,
        "max_bytes": 1048576
      }
    ]
  }
}
```

这只是任务包片段，完整任务仍需 instruction/source/setup 等字段。NL2Repo 的 `generated_repository` 同样须声明为采集前实际生成的归档；评分不会从当前远端仓库目录重新打包。

当前容器执行器对单个材料/产物及 tar 展开总大小设 256 MiB 上限、tar 文件数 10000、验收日志 16 MiB。这是执行器资源边界，不是官方 benchmark 规则。任务包仍需显式设置 `max_bytes`；超限拒绝，不会截断后判成功。

## 4. 执行所选评分器

```bash
uv run --locked --extra experiments --extra evaluation \
  python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" \
  --json grade "$RUN_ID" --plan "$PLAN"
```

当前在本机逐会话串行评分。Docker 镜像下载、构建、测试可能耗费较多磁盘与时间；任务产物中的代码不在宿主执行。

| 适配器 | 执行及证据要求 |
| --- | --- |
| `swebench` | 锁定官方 4.1.0 CLI，在 fresh instance 环境验收完整 prediction 和匹配数据行。 |
| `terminal-bench` | 固定官方任务包及 verifier mode；生产计划在干净数据库重放提交 SQL。KV 须有原运行独立 loadgen 的可信测量，不能重新跑负载代替。 |
| `tua-bench` | 使用官方 verifier/reward 和固定标准答案；仅支持能完整重建的事后环境，不静默替代缺失原环境证据。 |
| `nl2repo` | 使用官方后处理、命令、计数及 task image 中的原测试。报告原通过率，无二值规则时 `passed=null`；操作者阈值单列。 |
| `custom` | 隔离容器执行固定脚本，写 `/logs/verifier/result.json`，如 `{"passed": true, "score": 1}`；明确标记 custom。 |

适配器名称不表示支持整个 suite 所有任务或版本。未知来源和未覆盖执行模式明确拒绝。当前检查命令见[验证方法](../VERIFICATION.zh-CN.md)；fixture 测试不能称为官方 benchmark 成绩。

官方任务包 tar 根保留固定任务的 `task.toml`、`tests/`、`environment/`。Terminal/TUA 要求 `build_official_environment: true`，构建冻结环境并在验收前记录镜像身份。NL2Repo/custom 指定不可变镜像。外部答案和依赖也要固定；仅固定测试脚本不等于固定其中下载的 URL 内容。

## 5. 阅读独立报告

每次正式执行创建 `<runs-dir>/<run_id>/evaluation/<attempt_id>/`，保留冻结计划、材料身份、逐会话日志/原报告和归一化汇总。中断 attempt 保持不完整，重跑创建新 attempt；原归档、Session、manifest、checkpoint、seal 不改写。

| 状态 | 含义 |
| --- | --- |
| `completed` | 有效执行评分，得出成败或没有二值结论的连续分数 |
| `not_configured`、`unsupported` | 未选择规则，或不支持来源/合同 |
| `missing_artifact`、`ungradable` | 缺产物，或不满足证据/环境合同 |
| `unavailable`、`crashed`、`timed_out` | 评分基础设施、执行或解析失败 |
| `not_evaluated` | 官方跳过评分，例如 SWE 空预测 |

非 completed 的 `passed` 为 null，基础设施故障不计普通任务失败。完整 SWE 空补丁记为 `not_evaluated / official_empty_prediction`，不是缺补丁或已完成失败。原官方报告与分母和覆盖率诊断分开；报告应保留官方分母以及跳过、错误等状态。

退出码 `0` 和 `ok: true` 表示完整评分，可能包含有效任务失败，不代表所有任务通过。性能应查看逐会话结论和 score。

独立报告增加 `acceptance_assessment`，不改原接受记录。`valid_accept` 要求有效交互、原用户接受、核验执行合同且 `passed=true`；接受但客观失败为 `false_accept`；缺验收或仅连续分数为 `unverified_accept`；未接受为 `not_applicable`。direct 读取原已完成 review，不依据 Harness 自述成功。

实验配置的 `evaluation.official_grading` 仍为 `false`，使隐藏评分器与演化隔离。这个事后命令和独立 Harness benchmark 框架保持各自流程。
