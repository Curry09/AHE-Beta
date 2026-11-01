# 第三方来源与许可说明

[English](THIRD_PARTY.md) | 简体中文

根目录的 [MIT 许可证](LICENSE)适用于 auto-designer 的原创代码及按该许可提交的贡献。第三方代码、依赖和研究材料保留各自的许可证、版权与来源声明。本文记录这些材料的来源，并说明它们与项目许可证的适用关系。

## 代码与依赖

| 组件 | 来源与版本 | 许可与来源声明 |
| --- | --- | --- |
| NexAU | [hzhua/nexau](https://github.com/hzhua/nexau)，提交 `28511d9f0362191a6c378fd441b2be55309a9e32` | [Apache-2.0](https://github.com/hzhua/nexau/blob/28511d9f0362191a6c378fd441b2be55309a9e32/LICENSE)。通过固定提交的 Git 依赖安装，保留其许可证及相关声明。 |
| 内置 Spec 工具 | [Curry09/OpenAgents](https://github.com/Curry09/OpenAgents)，位于 `tools/spec-driven-development/` | MIT。内置副本保留了 [OpenAgents 许可证](tools/spec-driven-development/vendor/LICENSE)。 |
| Meta-Harness 实验产物 | [stanford-iris-lab/meta-harness-tbench2-artifact](https://github.com/stanford-iris-lab/meta-harness-tbench2-artifact)，提交 `57fefdb2ff84af3fd81b69d67814acbe69bd0743` | 内置快照未附单独的许可证文件，包元数据也未声明许可证。本项目的 MIT 许可证不授予这些上游文件的使用或分发权利。来源和修改记录见下文。 |
| 其他 Python 与前端依赖 | 版本和来源记录在 [uv.lock](uv.lock)、[evaluation/requirements.lock](evaluation/requirements.lock) 和 [frontend/package-lock.json](frontend/package-lock.json) | 各依赖保留自己的许可证；安装或打包依赖不会将其许可改为 MIT。 |

Meta-Harness 快照位于 `evaluation/harness/meta_artifact/`。其[上游 README](evaluation/harness/meta_artifact/README.md)注明基于 KRAFTON AI 的 Terminus-KIRA 和 Harbor 的 Terminus-2 框架。[来源记录](evaluation/harness/meta_artifact/provenance.json)保存了上游提交、文件哈希及本项目所做的兼容性调整。

## 运行时分发

评测运行时压缩包包含固定版本的 CPython 和 NexAU，所包含组件继续适用上游许可证及相关声明。Claude Code 从官方指定版本的发行包安装，适用其自身条款。

再分发 NexAU 时，应附带 Apache-2.0 许可证及适用的版权和来源声明；上游提供 `NOTICE` 时应保留相关内容，修改上游文件时应注明修改。将 NexAU 打包进运行时压缩包或容器镜像时，同样适用这些要求。

## 任务与基准材料

任务包、基准定义、源码仓库、测试、数据集和容器镜像可能适用不同的上游许可。项目的 MIT 许可证适用于自有接入代码，不替代这些材料的原有条款。

- [迭代任务材料](examples/tasks/evolution32/README.zh-CN.md)包含来自 SWE-bench、Terminal-Bench、TUA-Bench、NL2Repo 及项目自定义的场景。[材料清单](examples/tasks/evolution32/manifest.json)、任务定义和来源记录保存了输入、源码版本、哈希与镜像信息。
- [Harbor 评测](evaluation/README.zh-CN.md)通过 `evaluation.yaml` 选择任务来源。Harbor Index 的来源信息位于 [evaluation/benchmarks/harbor_index/](evaluation/benchmarks/harbor_index/)，其他 Harbor 任务包保留随包提供的许可条款。
- [历史研究材料](research/README.zh-CN.md)沿用归档及索引中记录的来源与版本。

材料可以从公开仓库、镜像仓库或 Release 获取，并不等于已获得其再分发授权。使用或分发具体源码、数据集、任务或镜像时，应遵循该材料随附的许可条款。

## 用户画像与来源引用

[用户画像示例](examples/personas/)和[画像提取工具](tools/persona-distill/)包含依据公开开发者资料、文章及其他引用来源形成的描述。原始引文、代码和其他来源材料保留各自权利。引用用于说明模拟画像的依据，不表示相关人物参与或认可实验。

[离线演示](backend/auto_designer/user/sim/demo.py)使用合成人格与脚本响应。

## 实验记录与模型输出

实验记录可能包含第三方任务代码、源数据、对话和生成内容。材料被用于实验，不会改变其原有权利或适用条款；项目的 MIT 许可证也不构成对这些内容的统一授权。私密信息的处理方式见[安全说明](SECURITY.zh-CN.md)。
