# 贡献指南

[English](CONTRIBUTING.md) | 简体中文

欢迎提交问题报告、文档改进和代码修改。建议先阅读 [README](README.zh-CN.md) 了解项目流程，再通过[架构说明](docs/ARCHITECTURE.md)了解主要模块。设计规格以 [docs/specs](docs/specs/README.md) 下的英文版本维护，原始中文版本保存在 [docs/specs-zh-CN](docs/specs-zh-CN/README.md)。

## 报告问题

使用[问题报告模板](.github/ISSUE_TEMPLATE/bug_report.md)，说明提交版本或发行版本、运行环境、复现步骤，以及预期行为和实际结果。日志只需提供复现所必需的部分，并移除凭证和私密内容。安全漏洞请通过[安全说明](SECURITY.zh-CN.md)中的渠道报告。

## 准备修改

每个 PR 尽量围绕一个问题或功能展开。新增功能或调整跨模块行为时，请先创建或更新相关设计文档，再开始实现。[Spec 指南](docs/specs/README.md)说明了文档创建和编号预留方式。

新增的代码注释、docstring 和 Spec 统一使用英文。注释应说明代码本身难以表达的意图、约束和行为。

修改依赖时，请在同一 PR 中提交更新后的锁文件。修改交付接口或证据传输流程时，还需结合对应版本的 OpenAgents 验证，并记录两个仓库的提交版本。OpenAgents 仓库内的修改请参阅其[贡献指南](https://github.com/Curry09/OpenAgents/blob/main/CONTRIBUTING.zh-CN.md)。

## 运行本地检查

使用 Python 3.12+，在仓库根目录运行以下命令。所安装的依赖包含 CI 使用的实验与 Harbor 评测测试依赖：

```bash
uv sync --locked --extra experiments --extra dev --extra harbor-evaluation
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m pytest -q backend/tests
PYTHONPATH=. .venv/bin/python -m pytest -q -c /dev/null -p no:cacheprovider evaluation/tests
```

CI 并行运行各组后端测试。评测测试单独运行，以使用评测模块随附的用户模拟引擎。

修改 Spec 后，执行校验并重新生成索引：

```bash
tools/spec-driven-development/spec validate
tools/spec-driven-development/spec render
tools/spec-driven-development/spec graph --package-root backend/ahe_beta
```

生成的 `docs/specs/OVERVIEW.md` 和 `docs/specs/ARCHITECTURE.md` 应与原始 Spec 一并提交。这两个文件由 CLI 生成，请通过修改原始 Spec 更新它们。

常规检查无需模型 API 密钥。如果修改需要真实模型验证，请记录模型与框架版本、命令、费用和结果，并在分享验证材料前移除私密内容。其他检查命令见[验证说明](docs/VERIFICATION.zh-CN.md)。

## 提交 PR

提交信息采用 [Conventional Commits](https://www.conventionalcommits.org/)，例如 `fix(runtime): preserve resume identity`。PR 描述应说明要解决的问题、修改后的行为及已完成的检查；如有相关限制或尚未完成的验证，也请一并说明。

请勿提交凭证、本机配置或原始实验轨迹。整理文档或调整仓库结构时，应保留既有实验结果的原意。

README、CONTRIBUTING 和 SECURITY 均提供英文版（`.md`）与简体中文版（`.zh-CN.md`）。修改时请同步两个版本的内容、命令和链接，并保留顶部的语言切换入口。

## 贡献许可

提交贡献表示你有权提供相关内容，并同意将原创贡献按本项目的 [MIT 许可证](LICENSE)分发。第三方材料保留各自的许可证和来源声明。引入第三方代码、用户画像或基准任务材料前，请先核对[第三方说明](THIRD_PARTY.zh-CN.md)。
