# auto-designer

A research framework for evolving coding-agent harnesses through simulated user feedback.
Python 3.12+ · Linux / WSL2 · MIT. Start with the offline demo below; live experiments need separately configured models and infrastructure.

auto-designer 模拟用户使用 Harness，把使用轨迹转为需求，再交给独立的 [OpenAgents](https://github.com/Curry09/OpenAgents) 实现。每轮交付封口后，用户试用新的 Harness；末轮只试用，不再交付。体感、技术验收和 held-out benchmark 分开记录。

本仓是**实验控制器**；OpenAgents 是**交付 CLI**；`backend/harness_template/` 是**被进化产品的初始源码**。实验迭代得到的 Harness 应作为带版本的独立产物发布。

## 安装与离线试用

需要 Git、Python 3.12+ 和 uv。在本仓根目录执行：

```bash
uv sync --locked --extra dev
uv run --locked python backend/scripts/offline_demo.py
uv run --locked --extra dev pytest -q
```

演示使用合成人格和脚本 Harness，打印使用过程及结束原因，不调用模型、不创建 issue、不启动容器。它验证用户模拟入口，不代表真实进化闭环已通过。

当前采用源码运行，尚未提供 auto-designer 的 PyPI 安装入口。`uv.lock` 固定 NexAU 提交及兼容依赖；更换版本后需同步两仓验证。

## 联合使用与文档

- [联合 Quickstart](docs/QUICKSTART.md)：两仓安装、离线契约检查、真实实验入口和停止/恢复。
- [配置说明](docs/CONFIGURATION.md)：模型角色、凭证、交付流和默认质量门。
- [当前架构](docs/ARCHITECTURE.md)：需求面、交付面和产物的边界。
- [公开快照](docs/EXPORTING.md)：只发布粗粒度进度，原始会话留在本地。
- [联合发布清单](docs/RELEASING.md)：版本冻结、待完成的真实验收和公开操作。
- [贡献指南](CONTRIBUTING.md)、[安全说明](SECURITY.md)、[第三方来源](THIRD_PARTY.md)、[变更记录](CHANGELOG.md)。

前端开发需要 Node.js 22：在 `frontend/` 执行 `npm ci`、`npm test`、`npm run build`。实时 API 面向本地受信任环境；静态 Pages 是另一条公开发布路径。

## 支持范围与研究材料

首轮整理验证范围为 Python 核心、离线模拟、两仓配置契约、前端测试和构建。Docker/Gitea 真实交付、付费模型、E2B scaling 与 benchmark 需要独立验收，不能用单元测试替代。

`docs/specs/` 保存设计契约和任务映射；`evaluation/` 与带日期的脚本保存研究工作流。历史实验配置可能包含特定机器路径和任务来源，应按各自版本使用，不能直接当成通用示例。人物画像及第三方任务的逐项再分发审查仍在进行，见 THIRD_PARTY.md。

## License

Project code is licensed under the [MIT License](LICENSE). Third-party material retains its own terms; see [THIRD_PARTY.md](THIRD_PARTY.md).
