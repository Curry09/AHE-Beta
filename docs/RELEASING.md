# 联合发布指南

auto-designer 与 OpenAgents 分别维护版本，通过[兼容清单](../release/compatibility.json)记录配套关系。联合发布应固定双方源码版本、依赖和运行材料，使用户能安装并运行同一组组件；两仓版本号无需相同。

## 固定配套版本

发布前核对以下来源：

| 内容 | 配置来源 |
| --- | --- |
| 控制器与初始 Harness | 发布提交及 `backend/harness_template/` |
| OpenAgents 配套版本 | `release/compatibility.json` 和实验中显式指定的 `source.openagents` |
| NexAU | `pyproject.toml`、`uv.lock` 与兼容清单中的固定 Git 提交 |
| Python、uv、Claude Code | 兼容清单的 `experiment_runtime` 与实际运行配方 |
| 任务输入、环境配方和镜像 | 任务材料清单、SHA-256 与镜像 digest |
| 独立评测材料 | `evaluation/requirements.lock`、任务来源记录和运行时发行包 |

`baseline_commit` 保存历史基线，不等于当前运行默认值。实验准备阶段优先从 `execution_evidence` 选择 OpenAgents 的 `reader_release_commit`，未设置时使用 `reader_candidate_commit`；没有该配置段时才使用 `observation_transport` 的对应字段。显式 `source.openagents` 可以选择其他不可变提交，但必须通过相同能力检查。

候选提交与正式发布提交应明确区分。准备正式联合版本时，将已验证的配套提交写入对应 `reader_release_commit`，同步相关传输配置，并重新构建、验证运行镜像。版本以清单为准，避免在教程中复制容易过时的提交值。

## 发布检查

在目标发布提交上完成检查，并在发行说明中记录结果与适用范围：

- 按锁文件安装依赖，运行 Python、前端及独立评测的检查。具体命令见[贡献指南](../CONTRIBUTING.zh-CN.md)和[验证说明](VERIFICATION.zh-CN.md)。
- 验证配套 OpenAgents 的配置接口和证据读取能力，包括 gzip、ZIP 及执行证据。CI 的跨仓检查位于 [.github/workflows/ci.yml](../.github/workflows/ci.yml)。
- 对目标运行后端验证材料准备、用户试用、需求交付、下一轮试用、停止／恢复及终态收集。模型、运行环境、两仓提交和镜像身份应随验证记录保存。
- 检查完整 Git 历史和发布资产中的敏感信息，处理发现的问题并轮换泄露凭证。材料来源及许可见[第三方说明](../THIRD_PARTY.zh-CN.md)。
- 验证用户实际获取到的源码、任务材料、运行时与镜像，包括校验和、下载权限和安装命令。
- 检查 CI 必需状态、私密漏洞报告入口及两仓间的文档链接。

代码测试、证据传输验证与完整模型实验分别记录。每项检查应说明实际使用的环境、版本和结果。

## 发布顺序

1. 合并并验证 OpenAgents 的配套改动，固定可供安装的源码提交或发行版本。
2. 更新 auto-designer 的兼容清单和锁文件，在候选发布提交上完成两仓联调。
3. 构建所需运行时、任务材料和镜像，生成校验和及材料清单。为发行包保留第三方许可证、版权和来源声明。
4. 创建草稿或预发布版本，从干净环境按文档验证下载、安装和运行。
5. 发布正式 tag 和 Release。双方发行说明互相链接，并注明兼容版本、验证范围与已知限制。

已发布的 tag 和固定材料不应原地替换。修复后的资产使用新版本，并保留旧版本的校验信息。候选提交或材料发生变化时，应重新完成受影响的检查。

## CI 与仓库访问

跨仓 CI 需要读取 OpenAgents。公开仓库可以使用工作流自带的凭证；若配套仓库仍为私有，则在 auto-designer 的 Actions secrets 中配置只读 `OPENAGENTS_READ_TOKEN`。凭证不写入源码或工作流正文。

CI 的 `workflow_dispatch` 可传入完整的 `observation_reader_commit`，用于验证另一配套提交；正式发布仍需将验证通过的版本写回兼容清单。修改源码 pin 后，应确认实际运行材料已经重建，且预检读取的是同一版本。

## 手动构建运行镜像

统一实验入口按冻结的锁文件获取 NexAU 和 OpenAgents，无需另备 SDK 源码。手动调用 `backend/deploy/vigil/build.sh` 时，则需要提供 OpenAgents 与 NexAU 两个 checkout；手动构建 SWE 运行镜像时，通过 `NEXAU_SOURCE` 指定 SDK checkout。

这些 checkout 应与发布清单中的提交一致。构建完成后记录镜像 digest，并在实际运行环境中核对镜像内源码和依赖版本。
