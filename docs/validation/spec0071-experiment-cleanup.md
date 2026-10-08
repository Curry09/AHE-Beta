# Spec-0071 仓库清理验收

验证日期：2026-10-03。工作分支：`feat/unified-experiment-entry`。清理基线：`6d213f6f1383f6aed89111ddc83a076ba3f93976`。本次修改尚未提交或推送；之前的 N1 实跑记录仍属于原版本。

## 已实现的范围

- 公共入口保持为 `backend/scripts/experiment.py`，命令仅为 check/prepare/run/status/logs/stop/resume/collect/destroy。两份当前示例分别使用 local + localhost Gitea 和 E2B + Gitea.com。
- ordinary/SWE 控制器移入包内；新运行按冻结 manifest 的模块配方启动。旧 v2 运行仍使用自己冻结的原脚本，保留身份和哈希；缺少冻结脚本时拒绝启动。当前源码不保留旧路径 wrapper。
- v1 启动、容量/健康代码及相关专属测试退出当前源码；共享 manifest/journal、隔离、恢复及资源检查测试保留。旧命令与旧 schema 在 provider 调用前拒绝，并指向冻结 checkout/研究说明。
- 22 个维护工具移入 `tools/dev/`，明确输入和在线行为；角色配置不混用宿主凭证，Git 凭证不进入命令参数或失败输出。三份探针提供离线输入预检。
- 历史模板、dated evaluation 和旧材料移入 `research/archives/`；活评分适配器保留在 `evaluation/adapters/`，不导入 research。归档不声称在当前 checkout 可直接运行。
- 静态前端标注历史快照、UTC 记录时间和当时状态，保留原 RUNNING 证据；live API 行为保持。
- 英中 README、QuickStart、Configuration、N1 教程与当前 Spec 映射同步。当前公开 schema 仍只支持单任务；不支持 N4/N8 多任务或历史产物追加轮。

## 文件清单与历史测试

[迁移清单](../../research/inventory.json)记录 317 个原文件：175 个归档、106 个维护、32 个迁移、4 个删除。175 个归档文件与基线逐字节一致，以 SHA-256 校验；删除的 4 个文件是根 `run.sh` 和三个个人模型快捷 shell。新建文件不伪造旧版本来源。

退出默认 pytest 的测试仅属于已归档实现：v1 config/runtime/CLI/capacity/health、一次性 main 迁移、旧审计 runner，以及 dated VPS/pilot/timeout 研究测试。相关测试随源码归档，原位置记录于 inventory。活 Orchestrator、路径隔离、并发、恢复和 adapter 测试保留并修复导入；新增检查覆盖旧 schema 拒绝、模块/旧冻结脚本启动、公共 JSON 自动发现、归档哈希与开发工具配置隔离。不能将当前测试数量与清理前直接相减来判断功能覆盖。

## 自动验证

依赖由 `uv sync --locked --extra experiments --extra dev` 核验，环境为 Python 3.12.13 / uv 0.11.28。

| 检查 | 结果 |
| --- | --- |
| 完整 pytest | 1304 passed，2 skipped |
| `e2e-spec-0071-experiment-cleanup.sh` | 目录检查通过；清理/工具/评分测试 61 passed、2 skipped；v2 入口矩阵 186 passed |
| 0047 保留共享原语与隔离验收 | 31 passed |
| 开发工具输入与隔离复核 | 38 passed；22 个模块 `--help` 均通过，无 provider 调用 |
| 两仓配置合同 | 使用 OpenAgents `a752e8830a13f44d97a3043d1f3e8dd16bd8d8aa`，配置 writer/parser 通过 |
| 两仓证据合同 | 同一 OpenAgents：gzip/ZIP 读取、14 类拒绝、retry reuse、旧证据恢复均通过，无网络或模型调用 |
| Ruff | `check .` 和 `format --check .` 通过（478 个维护文件；冻结源码排除） |
| 前端 | 15 个测试通过；普通构建和 Pages 构建通过 |
| Spec | validate 无错误；render/graph 已重新生成，重复生成内容一致 |
| 当前文档链接 | 17 份文档中的 93 个本地链接均存在 |
| Shell 与工作树 | 维护脚本 `bash -n` 通过；`git diff --check` 通过 |

两项 pytest 跳过分别位于 `evaluation/tests/test_harness_v0_adapters.py:66` 和 `:98`：未安装可选 `tau2` 包，不是断言失败。它们需要独立评分环境，不为这次离线仓库清理安装或执行官方评测。

Spec validator 仍输出跨组文件重叠和旧文档裸引用提示；它们不阻止校验。本次已修复 37 份旧 spec 中受迁移影响的当前映射，inventory 的 moved/archived/removed 原路径在这些 living `files` 中残留为零。其余历史契约与未实现的研究计划未包装成当前功能。

## 实跑覆盖与限制

此次没有启动模型、创建 Gitea 仓库或 E2B 沙箱，没有修改或停止现有实验资源。当前 WSL 的 `docker info` 报告 Docker 命令不可用，因此未执行重构后的 local/E2B live smoke，也没有新的真实 stop/resume 验收。两后端构建输入和启动逻辑由离线测试覆盖；这些测试不证明云端可达性或真实镜像构建成功。

[之前的 N1 验证报告](spec-0069-new-user.md)保留为历史基线，不能当作这次迁移后的实跑证据。本次也未运行官方 SWE-bench/Tau-bench 评分，未核实历史云端快照仍可用。默认开发前端 API 仍读取 `backend/data/sessions`，尚未自动绑定 v2 run；本次只澄清该限制，没有扩大为实时 run 选择功能。

## 后续能力审计补充

[2026-10-03 能力迁移审计](../audits/unified-entry-capability-migration-20261003.md)确认：旧功能并未全部接入 schema 2，另有单轮 local 启动误判和交付认证类型映射问题。多数缺口在 0069 已出现，0071 删除旧入口后无法继续使用旧旁路。本报告的测试结果不变，但它只证明本次目录清理和已有 v2 合同通过，不能证明旧功能迁移完整。上述业务修复尚未实施。

## 开发者复核

在仓库根执行：

```bash
uv sync --locked --extra experiments --extra dev
bash backend/scripts/e2e-spec-0071-experiment-cleanup.sh
uv run --locked --extra experiments python backend/scripts/experiment.py check --config examples/experiments/synthesizer-n1-local.json --offline
uv run --locked --extra experiments python backend/scripts/experiment.py check --config examples/experiments/synthesizer-n1-e2b.json --offline
PYTHONPATH=backend uv run --locked python -m tools.dev.probes.probe_persona_wait_matrix --check-inputs
```

检查 `examples/experiments/` 只含两份当前定义、原 launcher 路径已消失，并查看 [研究索引](../../research/README.zh-CN.md)和[维护工具说明](../../tools/dev/README.md)。前端静态模式的 mixed16 记录应显示“历史快照 / 当时状态 RUNNING”，原采集时间不随构建刷新。

实际新用户验证仍需可用 Docker/模型配置，或 E2B/Gitea.com 凭证与建仓名额。按 [N1 教程](../tutorials/n1-experiment.zh-CN.md)从 prepare 开始，以新 run 验证用户会话与产物收集；不要用重算旧 hash、重建旧身份的方式冒充 resume。恢复的在线验收须使用本次创建的 run，并记录 stop/resume 所处阶段。


## 2026-10-08 合并前完整测试依赖修复

统一入口 PR 的完整 pytest 初次只安装 dev，结果 8 failed、2250 passed、2 skipped；八项失败均为未安装 experiments 中的 e2b 或 pyarrow。Test job 的安装、pytest、目录检查和 offline demo 现在统一选择 locked experiments + dev；双语 CONTRIBUTING 的完整测试命令同步更新。没有把可选实验依赖强加到核心安装，也未跳过相应测试。

仓外新建独立环境，仅以 uv sync --locked --extra experiments --extra dev 安装，与新 CI 相同；相关 E2B、SWE parquet 及 persona 探针回归 14 passed、58 deselected，6.00 秒，不调用真实模型或云资源。最终完整测试以新 CI 提交的结果为准。
