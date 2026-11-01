# 导入 seed 卡库或纯文本任务

[English](seed-task-import.md) | 简体中文

如果你有明确提供的非 benchmark seed 卡库，或自己的 UTF-8 任务指令，可通过 `task import-seeds` 和 `task from-text` 生成 ordinary 任务包，再走现有 local/E2B 生命周期。转换不启动实验、不拉取 Git、不请求模型或 provider、不读取凭证，也不执行 setup。本教程将两个后端的配置副本完整推进到离线检查。

## 1. 安装并选择新的输出目录

在 Linux 或 WSL2 的仓库根目录操作，使用 Python 3.12+ 和 uv。安装依赖可能联网；安装完成后，转换和 `check --offline` 无需网络、凭证、Docker daemon 或 E2B 账户。下面的命令请在同一个 shell 中执行。

```bash
uv sync --locked --extra experiments
WORK_DIR="$(mktemp -d)"
```

转换器要求输出目录尚不存在，已有空目录或符号链接同样拒绝。上面的临时父目录存在，但 `seeds` 和 `text` 子目录尚不存在。请保留该目录直到 prepare 冻结材料；长期使用时，选持久化父目录和新的子目录名。

## 2. 转换明确提供的材料

[公开卡库](../../examples/seed-inputs/library.json) 只有一张合成的纯文本 checklist 卡，明确声明不是 benchmark。这是小型输入格式示例，不是历史研究卡集。[文本指令](../../examples/seed-inputs/instruction.md) 描述每周工作笔记工具；需要时替换成自己的任务，并在使用必需的非 benchmark 声明前确认来源。

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py --json task import-seeds examples/seed-inputs/library.json --output "$WORK_DIR/seeds" --seed plaintext-checklist > "$WORK_DIR/seeds-result.json"
uv run --locked --extra experiments python backend/scripts/experiment.py --json task from-text --instruction examples/seed-inputs/instruction.md --id weekly-notes --output "$WORK_DIR/text" --not-in-benchmark --interaction direct > "$WORK_DIR/text-result.json"
```

seed 示例默认使用 `simulated_user`；文本示例选择 `direct`。两个命令均支持 `--interaction direct|simulated_user`。较大卡库可重复 `--seed ID` 选择不同 ID，省略则按库内顺序导入全部卡；重复选择拒绝，输出仍按库内顺序排列。父级 `--json` 放在 `task` 前，便于保存机器可读结果。

卡库支持裸数组或包含 `seeds` 数组的对象。选中卡必须有安全且唯一的 `id`、`source.not_in_benchmark: true` 和非空 `task.prompt`。文件缺失、空库、选中卡无效或 benchmark 卡均拒绝；被拒卡和适配后的 SeedScenario 信封不是 seed 卡库输入。有仓库的卡要求 `source.repo` 为 owner/repo 标识（转为 GitHub HTTPS），或无凭证的 HTTPS owner/repo 地址；`env.repo_at` 为固定的 40 位小写 Git SHA。转换只校验声明而不 clone，源码由后续 prepare 核验。

两个示例都生成 ordinary v1 任务包及指令、setup、requirements 文件。无仓库任务生成本地 `source/` scratch 目录，其中 README 解释初始工作区。它使初始材料可哈希，不包含题目答案。`task.prompt` 原样进入指令，不追加 `task.context`；文本导入保留用户提供的 UTF-8 指令。

只输出允许映射的 prompt/source/setup。`oracle`、`env.test_cmd`、`gates`、`provenance` 不复制到包、索引或隐藏 sidecar；来源摘要只保留输入字节摘要、ID 和源类型。旧 `env.setup` 字符串按原顺序保留，后续在当前独立任务 venv 合同下执行。导入器不自动锁定这些依赖，不恢复旧 base image、外部服务、预算或配对元数据。prepare 前审阅生成的 setup 和 requirements；导入成功不证明原环境可复现。

## 3. 将绝对任务包数组复制到两个实验模板

每次命令的 JSON 结果都提供绝对 `task_packages` 数组。生成的 `tasks.json` 是以输出目录为基准的相对路径索引，保留来源摘要与顺序；它不是新的实验定义，不能把索引路径填入 `workload.task_packages`。请使用结果中的实际任务包路径，移动任务包后相应更新引用。

下面合并两次结果的数组，分别复制一个既有 U1 local/E2B 模板。代码移除旧单包字段和旧任务计划，更新为新数组；因为配置副本移到了其他目录，也将模板中的 persona 路径转为绝对路径。模型、persona、角色数量和五轮设置仍来自 U1 模板；每轮一个用户会话，轮转两项任务。如需其他分配，编写新的显式计划。

```bash
uv run --locked --extra experiments python - "$WORK_DIR" <<'PYCODE'
import json
import sys
from pathlib import Path

work_dir = Path(sys.argv[1]).resolve()
task_packages = []
for result_name in ("seeds-result.json", "text-result.json"):
    result = json.loads((work_dir / result_name).read_text(encoding="utf-8"))
    task_packages.extend(result["task_packages"])

for backend in ("local", "e2b"):
    template = Path(f"examples/experiments/u1-{backend}.json").resolve()
    config = json.loads(template.read_text(encoding="utf-8"))
    workload = config["workload"]
    workload["persona_library"] = str(
        (template.parent / workload["persona_library"]).resolve()
    )
    for key in ("kind", "task_package", "interaction_plan"):
        workload.pop(key, None)
    workload["task_packages"] = task_packages
    config["name"] = f"imported-tasks-{backend}"
    destination = work_dir / f"experiment-{backend}.json"
    destination.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(destination)
PYCODE
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$WORK_DIR/experiment-local.json" --offline
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$WORK_DIR/experiment-e2b.json" --offline
```

两次检查应正常退出并显示尚未冻结的分配预览。它们校验任务包、persona 引用和会话安排，不证明任务成功、Git 可用、setup 已执行或后端已就绪；这些检查不代表真实 local/E2B 实验已运行。

## 4. 继续 check、prepare 与 run

审阅生成材料后选择后端，按[配置说明](../CONFIGURATION.zh-CN.md)填写模型/provider 凭证，并满足[快速开始](../QUICKSTART.zh-CN.md)的基础设施要求。下面使用现有生命周期；在线检查和 prepare 可能请求 provider、拉取源码，run 使用模型与计算资源。

```bash
CONFIG="$WORK_DIR/experiment-local.json"
# CONFIG="$WORK_DIR/experiment-e2b.json"
cp examples/experiment.env.example .env.experiment
chmod 600 .env.experiment
# Fill model and provider credentials before continuing.
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py prepare --config "$CONFIG" --secrets-file .env.experiment
RUN_ID=REPLACE_WITH_PRINTED_RUN_ID
uv run --locked --extra experiments python backend/scripts/experiment.py run "$RUN_ID" --secrets-file .env.experiment
```

local 要求 Docker/Compose，并启动 localhost Gitea；E2B 要求 API key 和 Gitea.com 账户。等待 prepare 完成后使用打印的 run ID。按 [U1 教程](u1-experiment.zh-CN.md)查看进度、停止/恢复同一 run、收集和清理。转换增加的是现有生命周期的输入方式，不导入历史结果追加轮次。可选本地工程 CI 使用专属 runner 和私有 Docker daemon，见 [CI 教程](local-engineering-ci.zh-CN.md)；历史 continuation 仍需单独设计。
