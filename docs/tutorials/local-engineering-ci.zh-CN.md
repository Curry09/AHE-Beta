# 启用本地工程 CI

[English](local-engineering-ci.md) | 简体中文

本地 Docker + localhost Gitea 可为每个实验运行专属 Gitea Actions runner。准备前设置 `runtime.local.ci_enabled: true`，继续使用 `backend/scripts/experiment.py`。CI 默认关闭；E2B + Gitea.com 不支持此 runner 契约。

工程 CI 检查 Harness 的代码结构和制品。builtin 的 [smoke 工作流](../../backend/harness_template/.gitea/workflows/smoke.yml)编译 Python、检查必要文件，并拒绝私密运行态文件。CI 不调用模型、不运行 benchmark。官方 SWE 会话 `grade` 和独立 Harness 留出评估继续作为事后流程。每个 run 使用自己的 Docker daemon 和 job 存储执行可信 Harness 工程代码。

## 1. 安装并复制本地配置

在 Linux 或 WSL2 的仓库根目录执行，需 Python 3.12+、uv、Docker 和 Docker Compose。Docker 必须支持嵌套 CI daemon 使用的 privileged 容器；后端 preflight 检查实际就绪。所有命令使用同一个 shell。沿用现有[凭证模板](../../examples/experiment.env.example)；runner 注册 token 由后端私密创建，不写入此文件。

```bash
uv sync --locked --extra experiments
if [ ! -e .env.experiment ]; then
  cp examples/experiment.env.example .env.experiment
fi
chmod 600 .env.experiment
WORK_DIR="$(mktemp -d)"
CONFIG="$WORK_DIR/experiment-local-ci.json"
```

按[配置说明](../CONFIGURATION.zh-CN.md)填写 `.env.experiment` 中的模型凭证。已有填写完成的受保护文件时继续使用它。下列命令复制现行 local U1 模板并启用 CI。副本位于临时目录，所以把原任务、persona 路径转为绝对路径；builtin Harness 无需改写路径。准备前检查生成配置中的模型、轮次和任务；此模板运行五轮，实验过程会使用模型。

```bash
uv run --locked --extra experiments python - "$CONFIG" <<'PYCODE'
import json
import sys
from pathlib import Path

template = Path("examples/experiments/u1-local.json").resolve()
config = json.loads(template.read_text(encoding="utf-8"))
config["name"] = "u1-local-ci"
config["runtime"].setdefault("local", {})["ci_enabled"] = True
workload = config["workload"]
for field in ("task_package", "persona_library"):
    workload[field] = str((template.parent / workload[field]).resolve())
destination = Path(sys.argv[1]).resolve()
destination.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(destination)
PYCODE
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --offline
```

离线检查验证配置及本地材料，不能证明 Docker、注册、Actions checkout 或状态回传可用。保留临时目录直到准备阶段冻结其内容；长期使用时选择持久配置路径。

## 2. 选择镜像并冻结实验

默认使用 `gitea/act_runner:0.2.11` 和固定摘要的 `catthehacker/ubuntu` job 镜像。可选的 `runtime.local.runner_image` 与 `runtime.local.ci_job_image` 覆盖要求 `ci_enabled: true`，并使用显式版本标签或 SHA-256 摘要。无版本引用和 `:latest` 会被拒绝。省略两个字段即可使用默认值。准备阶段记录此 run 的实际 image ID。

后端还按实际 image ID 固定内部 `docker:27.5.1-dind` daemon 配方。runner 通过内部 `DOCKER_HOST` 端点连接此 run 的 daemon；daemon 不发布宿主端口，runner 不挂载宿主 Docker socket。每个 daemon 独占自己的 job 容器、工具缓存和存储，因此 runner 生成的名称只在本 run 内使用。job 的 `host` 网络模式指的是位于 run 的 CI 网络上的私有 daemon 网络命名空间。daemon 在本地 Docker 主机上以 privileged 运行；此配置面向可信代码，不提供恶意代码隔离。

自定义 Harness 需包含 `.gitea/workflows/*.yml` 或 `.yaml` 工作流，使用不带筛选条件的 `pull_request` 事件：不筛选分支、路径或事件类型。至少提供一个使用 `runs-on: ubuntu-latest` 的无条件 job，包含可执行的 `run` 或 `uses` 步骤。此 job 及其所有步骤省略 `if` 和 `continue-on-error`，job 还需省略 `strategy`。这些条件让预检查能够确认每个 PR 都可获得必要检查。专属 runner 将 `ubuntu-latest` 映射到冻结 job 镜像；镜像必须提供工作流所用工具，包括 checkout action 所需 Node 和 smoke 探针所需 Python。缺少兼容工作流时准备失败。prepare 后修改原配置或 Harness 不改变已有 run；输入变化时准备新 run。

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py prepare --config "$CONFIG" --secrets-file .env.experiment
RUN_ID=REPLACE_WITH_PRINTED_RUN_ID
uv run --locked --extra experiments python backend/scripts/experiment.py run "$RUN_ID" --secrets-file .env.experiment
```

后端 preflight 核验所属 runner 的注册、daemon、镜像、存储和网络身份，然后创建临时技术探针仓库与真实 PR。工作流执行 checkout 和 Python smoke；只有该 PR 当前 head SHA 至少有一项检查且结果为 `success` 才算就绪。探针反馈不是用户反馈。后端只移除自己创建的临时探针仓库。

只有经过核验的就绪收据与已启用 CI 的 run 匹配，OpenAgents 才接收 `ci: agent`。注册、工作流、API 失败或超时会阻止启动并保留诊断，不把已启用的 run 降级到 `skip`。后续实验使用配置中的模型；技术 CI 探针本身不使用模型。

## 3. 查看当前 CI 证据

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py status "$RUN_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py logs "$RUN_ID" --follow --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py collect "$RUN_ID" --secrets-file .env.experiment
```

状态中的 CI 独立于实验、资源和收集状态，包含非敏感 runner 身份与就绪证据。runner 容器运行本身不能证明就绪。使用 status 返回的实际 Gitea 地址查看 Harness PR 检查。OpenAgents CI 门禁跟随 PR 当前 head：零检查或 pending 会等待，失败要求修复，新提交必须取得自己的结果。旧 head 的绿灯不能让新 head 通过。

收集的 forge 证据包含 main 与 PR 当前 SHA 及提交状态，以及 CI 就绪收据。runner 注册秘密和私密注册文件不复制到收集产物。完整收集表示证据已保存，不能说明实验或每个 PR 成功。

## 4. 停止、恢复并清理同一 run

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py stop "$RUN_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py resume "$RUN_ID" --secrets-file .env.experiment
```

stop 先停止 controller 与 Vigil，再暂停专属 runner，处理所属 job 并停止私有 daemon。Gitea 数据、runner 注册和 daemon 存储会保留以供恢复。resume 复用原注册身份，核验原镜像、存储、网络和身份后重新执行就绪探针，不重新注册 runner、不升级冻结代码、不导入历史轮次。如果无法核验所有权或确认停止，后端保留状态不明的资源并报告错误。

终态收集完成后查看状态，再销毁所属执行资源：

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py collect "$RUN_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py status "$RUN_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py destroy "$RUN_ID" --confirm "$RUN_ID" --secrets-file .env.experiment
```

destroy 只处理已核验属于此 run 的 job 和资源，移除其私有 daemon 和 CI job 存储。Gitea 仓库/数据卷及 runner 私密注册卷会保留，资源收据列明名称和原因。runner 私有卷包含注册凭据，应与私密运行数据一起保存。其他实验的 daemon、runner、job 和已有 Gitea 服务不属于此次清理。job 清理失败不能报告为 `DESTROYED`。

这些命令描述实现契约。实际离线和真实运行覆盖由 [CI 验收报告](../validation/local-engineering-ci.md)记录；文档步骤本身不是完整真实 CI 实验的证据。人工构造的红绿探针只能证明工程状态行为，不能证明模型自动修复或 benchmark 改善。
