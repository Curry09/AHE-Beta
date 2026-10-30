# 历史研究资料

新实验使用 `backend/scripts/experiment.py` 和 `examples/experiments/` 中的可运行配置。
本目录保存冻结研究记录、配置模板与旧实现，不是另一套受支持的实验入口。

[English](README.md)

清理基线为完整 commit `6d213f6f1383f6aed89111ddc83a076ba3f93976`。
[inventory.json](inventory.json) 记录原路径、目标路径和原文件哈希。
公开模板与对应的历史冻结配置是不同记录，不将它们当作重复文件覆盖。

查看或复现实验时，在独立 checkout 中使用记录的源码版本、依赖和原冻结配置。
N1 旧试点应显式指定原路径
`evaluation/harness-suite-20260920/configs/n1-e2b-20260922.json`；旧 launcher
的默认路径后来指向了公开 v2 示例。任务归档、云快照和凭证仍按原流程准备。
文件归档成功不代表这些外部资源仍存在，也不代表已重新验证实验可复现。

归档源码保持原记录，其相对路径对应原 checkout，不应在这里直接执行。
默认测试和 lint 排除冻结源码。当前独立 Harbor 评测位于 `evaluation/`，Harness 适配器位于 `evaluation/harness/`，
开发工具位于 `tools/dev/`。

私人原始轨迹和实验产物包放在源码仓外。本次清理不管理或删除云端运行资源。
