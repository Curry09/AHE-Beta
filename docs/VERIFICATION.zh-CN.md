# 验证当前代码

[English](VERIFICATION.md) | 简体中文

在仓库根目录执行以下命令，检查当前代码和公开实验定义。PR 的 CI 还会检查跨仓接口，完整开发流程见[贡献指南](../CONTRIBUTING.zh-CN.md)。

```bash
uv sync --locked --extra experiments --extra dev --extra harbor-evaluation
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m pytest -q
.venv/bin/python backend/scripts/check_nexau_dependency.py --installed
.venv/bin/python backend/scripts/check_experiment_repository.py
tools/spec-driven-development/spec validate
```

仓库检查覆盖所有公开实验和批次定义。单独检查某个配置时，可使用离线命令：

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py check \
  --config examples/experiments/u8-mixed-e2b.json --offline
```

离线检查验证配置和材料声明，不创建云资源或调用模型。材料下载后由准备阶段核验；后端访问、模型响应及完整实验需要分别通过实际运行验证。

实际运行步骤见[迭代教程](tutorials/evolution32.zh-CN.md)，结果以该次运行的状态、日志和收集产物为准。材料哈希及环境身份见[任务清单](../examples/tasks/evolution32/manifest.json)。独立 Harness 评测的安装与运行方式见[评测说明](../evaluation/README.zh-CN.md)。
