# 给已完成实验追加轮次

[English](experiment-continuation.md) | 简体中文

使用完整的当前实验归档创建新 run。子实验先处理父实验末轮用户反馈，等待准入工作交付完成，再开始自己的用户试用。它继承最终 Harness tree 和末轮 task/persona/interaction 配对；模型、角色、后端及策略由子配置决定。

继续使用 check/prepare/run/status/stop/resume/collect/destroy。`resume` 恢复同一个 run；追加创建新身份和新仓库。只支持带新 continuation export 的当前 schema 2 / workload contract 1 归档。此前冻结的 controller 和缺少该 export 的归档不会被追溯升级。

## 1. 安装并选择父实验

在仓库根目录使用 Python 3.12+ 和 uv。父实验需要由能产生当前 continuation export 的 controller 准备，并已达到 `COMPLETED`。[U1 教程](u1-experiment.zh-CN.md)说明怎样在本地 Docker 或 E2B 创建父实验。

```bash
uv sync --locked --extra experiments
RUNS_DIR="$PWD/.experiments"
WORK_DIR="$(mktemp -d)"
PARENT_RUN_ID=REPLACE_WITH_COMPLETED_PARENT_RUN_ID
ADD_ROUNDS=2
```

父实验使用自定义 `--runs-dir` 时，将 RUNS_DIR 换成实际根目录。保持同一 shell，保留生成文件直到 prepare 完成输入冻结。

## 2. 收集可继承的父归档

基础设施操作使用父实验的显式凭证 profile。collect 不需要模型凭证。

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" status "$PARENT_RUN_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py --json --runs-dir "$RUNS_DIR" collect "$PARENT_RUN_ID" --secrets-file .env.experiment > "$WORK_DIR/parent-collection.json"
```

收据必须同时满足 `collection_state: COMPLETE`、`controller.experiment_complete: true` 和 `continuation_ready: true`。`COMPLETE` 只说明收集一致，停止或失败的实验也可能具有这个收集状态。最终 tree 不可用或可运行材料改变时，归档不能继承；保留普通结果并检查收据。缺失或不可验证的原生观测会如实保留为证据缺口。

归档包含绑定末轮精确 SHA 的 `runtime/continuation-export.json`，以及任务材料、persona 卡、会话和 forge 证据。创建子资源之前会核验外层归档 SHA 和逐文件摘要。父计算资源销毁后，保留的完整归档仍可使用。

## 3. 生成完整的 local 和 E2B 子配置

下面复制两份当前 U1 定义，将 Harness/workload 输入替换为父来源，保留模板完整的模型、角色、runtime 和策略。脚本从父末轮读取 session 数，不假设父实验是 U1；归档路径写为绝对路径，移动子 JSON 不改变含义。

```bash
uv run --locked --extra experiments python - "$WORK_DIR" "$ADD_ROUNDS" <<'PYCODE'
import hashlib
import json
import sys
import tarfile
from pathlib import Path

work_dir = Path(sys.argv[1]).resolve()
additional_rounds = int(sys.argv[2])
if additional_rounds < 1:
    raise SystemExit("ADD_ROUNDS must be a positive integer")
receipt = json.loads((work_dir / "parent-collection.json").read_text(encoding="utf-8"))
if not (
    receipt.get("collection_state") == "COMPLETE"
    and receipt.get("controller", {}).get("experiment_complete") is True
    and receipt.get("continuation_ready") is True
):
    raise SystemExit("Parent must be complete and continuation_ready")
parent_archive = Path(receipt["archive"]).resolve()
with parent_archive.open("rb") as handle:
    archive_sha = hashlib.file_digest(handle, "sha256").hexdigest()
if archive_sha != receipt["archive_sha256"]:
    raise SystemExit("Parent archive differs from its collection receipt")
with tarfile.open(parent_archive, "r:gz") as archive:
    export = json.load(archive.extractfile("runtime/continuation-export.json"))
sessions = len(export["boundary"]["sessions"])
for backend in ("local", "e2b"):
    template = Path(f"examples/experiments/u1-{backend}.json")
    config = json.loads(template.read_text(encoding="utf-8"))
    config["name"] = f"continuation-{backend}"
    config["harness"] = {"source": "continuation"}
    config["workload"] = {"source": "parent"}
    config["continuation"] = {"archive": str(parent_archive), "sha256": archive_sha}
    config["rounds"] = {
        "count": additional_rounds,
        "sessions_per_round": sessions,
        "max_parallel_users": sessions,
    }
    destination = work_dir / f"child-{backend}.json"
    destination.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(destination)
PYCODE
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$WORK_DIR/child-local.json" --offline
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$WORK_DIR/child-e2b.json" --offline
```

三个输入声明必须一起出现：`harness.source=continuation`、`workload={"source":"parent"}`、`continuation={"archive":...,"sha256":...}`。继承 workload 不再填写任务包、persona 库、persona ID 或 interaction_plan。每个新增轮按原顺序重复父末轮配对，任务内容、persona 内容和 `direct`/`simulated_user` 交互保持固定。`sessions_per_round` 必须等于父边界人数；可以降低 `max_parallel_users`。有 pending report 时至少需要一个 Triage 和一个 Synthesizer。

离线 check 返回父身份、边界、配对、报告与证据缺口。它不启动模型/provider、不准备任务环境，也不证明任务通过。生成的 local 和 E2B 文件是两个可选子配置，选择其中一份运行。

## 4. 准备并启动新 run

在 prepare 之前修改所选子配置的模型与策略。子显式 profile 提供当前模型/provider 凭证；父凭证和 grants 不继承。local 需要 Docker/Compose，并新建 localhost Gitea；E2B 需要其 API key 和自己的 Gitea.com 账户。继承的 source archive 和依赖 lock 仍按正常任务环境流程准备。

```bash
CONFIG="$WORK_DIR/child-local.json"
# CONFIG="$WORK_DIR/child-e2b.json"
cp examples/experiment.env.example .env.continuation
chmod 600 .env.continuation
# Fill the child model and provider credentials before continuing.
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --secrets-file .env.continuation
uv run --locked --extra experiments python backend/scripts/experiment.py --json --runs-dir "$RUNS_DIR" prepare --config "$CONFIG" --secrets-file .env.continuation > "$WORK_DIR/child-prepared.json"
CHILD_RUN_ID="$(uv run --locked --extra experiments python -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_id"])' "$WORK_DIR/child-prepared.json")"
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" run "$CHILD_RUN_ID" --secrets-file .env.continuation
```

prepare 在新身份下原子冻结所选父输入及当前 controller/OpenAgents 源码。子 seed commit 的 Git tree 与父边界相同；父 Git 历史不导入，因此子 commit SHA 是新的。`manifest.lineage` 记录该关系和配置差异。

`continuation-bootstrap` 将父 pending reports 映射到新仓，经过共享反馈 pipeline 并封存结果。它不算新增用户轮，不复制父用户执行记录。已关闭、拒绝或已交付报告保留为背景证据。零准入会明确记录 `no_admissions` 并封口，不能据此声称发生代码交付；交付卡死时不会提前开始新用户。即使 `rounds.count: 1`，初始化也会启用交付。

`rounds.count` 表示**新增用户轮数**。父末轮为逻辑 R5 时，默认 `ADD_ROUNDS=2` 产生子本地 R1/R2，对应逻辑 R6/R7。本地 R1 的新反馈先交付，再开始本地 R2；本地 R2 仍只试用。父会话、评分和用量不计入子新增用户统计。可选工程 CI 由子配置决定；模板默认关闭，E2B CI 仍不支持。

## 5. 观察、停止和恢复子实验

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" status "$CHILD_RUN_ID" --secrets-file .env.continuation
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" logs "$CHILD_RUN_ID" --tail 100 --secrets-file .env.continuation
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" stop "$CHILD_RUN_ID" --secrets-file .env.continuation
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" resume "$CHILD_RUN_ID" --secrets-file .env.continuation
```

status 单独展示初始化，普通轮显示 `local_round` 与 `lineage_round`。stop/resume 操作该子 run 和它的冻结输入。已完成初始化通过对账恢复，不重复创建报告、调用模型或交付；初始化中断则先恢复独立 checkpoint 域，再进入新用户轮。父已完成账本保持不变。

## 6. 收集、再次追加和清理

等待子实验达到 `COMPLETED`，再收集它自己的末轮 export。

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py --json --runs-dir "$RUNS_DIR" collect "$CHILD_RUN_ID" --secrets-file .env.continuation > "$WORK_DIR/child-collection.json"
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" destroy "$CHILD_RUN_ID" --confirm --secrets-file .env.continuation
```

再次追加时，把子完整收据用作 `parent-collection.json`，设置 `ADD_ROUNDS=1`，重复第 3–4 步创建另一个新 run。逻辑 R7 结束的子实验成为下一父来源，下一本地 R1 显示逻辑 R8。下一来源只选直接父的末轮用户与反馈；祖先保留身份/hash 摘要，不递归嵌套整个父归档。

destroy 处理指定子 run 的资源并保留证据；父资源用自己的 run ID 和 profile 单独清理。`grade --round` 和 batch 继续使用各 run 的本地轮号与本次预测。[配置说明](../CONFIGURATION.zh-CN.md)、[Spec-0079](../specs/0079-experiment-continuation.md)及独立[验收记录](../validation/experiment-continuation.md)分别记录实现契约与实际覆盖。本教程描述操作流程，命令本身不代表真实双后端交付已经验收。
