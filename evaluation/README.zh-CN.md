# Harbor 统一评测框架

[English](README.md) · [完整中文教程](docs/harbor.zh-CN.md)

在仓库根目录只维护一个 [`evaluation.yaml`](../evaluation.yaml)，密钥放被忽略的 `.env`。支持 v0、u8、u8-direct、u16、u32、Claude Code 和 Meta-Harness，可选直接解题或带用户模拟。

默认 `task_source: harbor_index` 使用固定版本的官方任务；也可选择 `task_source: harbor`，传入已准备好的标准 Harbor 任务包路径。任务名单、下载和裁判规则由对应 profile 解释，配置及执行层不套用 Index 规则；示例见完整教程。

请按完整教程在独立虚拟环境安装 `evaluation/requirements.lock` 和本目录；运行材料从 [Release](https://github.com/Curry09/auto-designer/releases/tag/harbor-evaluation-framework-v1.0.0) 下载。

```bash
python -m evaluation validate
python -m evaluation prepare
python -m evaluation run
python -m evaluation report runs/<运行ID>
```

恢复用 `resume`；仅补体验分用 `review`；符合条件的裁判失败用 `regrade` 恢复。已有有效得分不会触发自动重新解题。运行输出、完整 trace 和真实凭证不进入源码仓库。

独立于自进化入口 `backend/scripts/experiment.py`。已完成离线回归及标准 Terminal-Bench 任务 `fix-code-vulnerability` 的真实 E2B 验收：通过 `task_source: harbor` 使用当前 seed 与 GLM-5.3-Flash，原仓 367 项和任务附加 6 项测试全部通过，reward 为 1.0。记录见 `evaluation/verification/`。新第三方 Harness 仍需实现适配器。
