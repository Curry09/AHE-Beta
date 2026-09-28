# Third-party code and research material

根 LICENSE 适用于项目自有代码及有权按 MIT 分发的贡献，不替代第三方材料的原有条款。以下是来源盘点，不是所有研究数据都已获再分发许可的声明。

| 范围 | 来源与许可处理 | 当前状态 |
| --- | --- | --- |
| `tools/spec-driven-development/vendor/openagents/` 与 spec skill | 来自 Curry09/OpenAgents；两仓现采用 MIT。随 vendored 代码保留 OpenAgents LICENSE | 已补许可副本；精确上游源提交仍需追溯，不能把本次联合基线冒充 vendoring pin |
| NexAU | `pyproject.toml` 固定官方 Git 提交，安装时获取，未把依赖源码复制入本仓 | 依赖的 LICENSE/NOTICE 随其上游分发 |
| Python / frontend npm dependencies | 来源、版本与哈希在锁文件；各包许可证分别适用 | 发行资产需附依赖许可汇总，npm 安全告警另行处置 |
| `backend/persona_library*.json` 与 `tools/persona-distill/` 中来源资料 | 包含公开 GitHub/自述资料的链接及派生人格描述 | 逐条检查引用、授权与分发范围待完成；不暗示真实人物参与或背书 |
| `backend/seeds*.json`、`evaluation/` 与 benchmark 配置 | 自有生成逻辑与外部任务/数据分开；遵循任务仓和数据集原条款 | 在公开源码/研究数据前逐类确认；模型/评测分数不是许可依据 |
| `backend/harness_template/` | 项目自有 seed Harness，依赖另按上游许可 | 适用项目 MIT；独立生成的 Harness release 应携带许可及来源提交 |
| 实验轨迹与模型输出 | 可能包含用户输入、代码、服务信息和第三方任务 | 不作为默认演示数据；公开前单独审查与脱敏 |

离线 quickstart 使用 `user/sim/demo.py` 中构造的合成人格与脚本响应，不读取人物资料库。正式公开前应完成待办；无法确认权限的材料应移出公开分发范围并同步修正加载入口。
