# Harbor Index 统一评测框架

[English](README.md) · [完整中文教程](docs/harbor.zh-CN.md)

在仓库根目录只维护一个 [`evaluation.yaml`](../evaluation.yaml)，密钥放被忽略的 `.env`。支持 v0、u8、u8-direct、u16、u32、Claude Code 和 Meta-Harness，可选直接解题或带用户模拟。

请按完整教程在独立虚拟环境安装 `evaluation/requirements.lock` 和本目录；运行材料从 [Release](https://github.com/Curry09/auto-designer/releases/tag/harbor-evaluation-framework-v1.0.0) 下载。

```bash
python -m evaluation validate
python -m evaluation prepare
python -m evaluation run
python -m evaluation report runs/<运行ID>
```

恢复用 `resume`；仅补体验分用 `review`；符合条件的裁判失败用 `regrade` 恢复。已有有效得分不会触发自动重新解题。运行输出、完整 trace 和真实凭证不进入源码仓库。

独立于自进化入口 `backend/scripts/experiment.py`。本次整理完成离线验证，未以此版本启动新的付费端到端评测。新第三方 Harness 仍需实现适配器。
