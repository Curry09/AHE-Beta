# Spec-0076 seed / 文本任务输入验收

日期：2026-10-03。新能力是把明确提供的 seed 卡或文本转换成既有 ordinary task package；后续仍使用同一 workload、材料冻结与 local/E2B 生命周期。它不恢复历史 runner，不导入旧运行结果，也不证明旧环境或任务本身已通过。

## 转换与冻结

```bash
bash backend/scripts/e2e-spec-0076-seed-task-import.sh
```

专项 **126 passed，3.75 秒**。其中核心转换测试覆盖真实历史七张文本卡、Git/文本混合、固定 revision、选卡、中文/CRLF、setup 引号/换行、逐条独立 shell、非法输入、现有输出/符号链接/竞争拒绝和写入失败清理。转换期间不调用网络、模型、provider 或执行 setup。旧卡中的 oracle、env.test_cmd、gates、provenance 哨兵既不进入生成包，也不进入正式冻结材料；原始输入仍保留。

生产集成使用现有材料编译器、任务 catalog/session plan 和 SHA 校验。真实历史七卡转换后冻结为七项 ordinary 任务，按现行 persona 数量约束配置同轮七会话；生成路径数组、source README 和每项指令进入已有哈希合同。原转换包修改不影响已冻结 run；修改冻结 setup 则被拒绝。Git 获取边界使用本地固定提交 fixture，此部分不是远端 Git 网络或实际实验。

从新教程原文执行公开示例和文本转换，再把返回的绝对 task_packages 数组写入 local/E2B N1 模板副本，两份 check --offline 均 exit 0 / ok=true。转换没有读取 secrets，未创建 forge、云资源或运行模型。中英 Bash 代码块一致，命令解析和相对文档链接检查通过。tasks.json 只是相对输出目录的索引，不是新的运行入口。

全仓锁定依赖回归 **1807 passed、2 skipped，246.50 秒**；两个 skip 为既有未安装的可选 tau2 依赖。Ruff lint/format 全仓通过（526 个文件）；专项脚本 bash -n、spec validate 及 Git diff --check 通过。

## 真实 Docker 边界

在 `/home/wydlinux/spec0076-live-20261003/` 留存独立实证。通过公开 CLI 生成两个材料：纯文本 scratch 指令，以及显式 env.setup 的旧卡（包含 Python 环境检查、pip --version 和带引号/分号的 printf）。实际冻结源与当前 controller，调用生产 `_prepare_task_build`，在已有 `python:3.12-bookworm` 的独立 Docker 容器内执行原生产 `TASK_BOOTSTRAP`；使用固定 uv 0.11.28，不替换 bootstrap 或 setup 执行。

两个 bootstrap 都输出 ready，并在各自 `/workspace/<task_id>/repo/.venv/bin/python` 中执行检查。旧 setup 的引号内容按原文输出，pip 来自任务 venv。纯文本没有旧 setup，因此引号检查不适用。随后通过生产 DockerWorkspaceRuntime 写入并运行一个小 Python helper，导出完整新增文件补丁；.venv 和 __pycache__ 未混入预测。冻结材料哈希在执行前后仍通过 verify_materials。

真实证据为 `docker-bootstrap-proof.json`，关联 run `20261003T113511Z-4efc3905`，并保留转换收据、冻结材料、bootstrap 日志和补丁。自建两个容器在 finally 中移除，没有修改现有 Gitea 服务或其他用户容器。

此测试证明当前 Docker 任务准备与工作区边界可使用生成包。它没有运行模拟用户/真实模型、OpenAgents/Vigil、Gitea 反馈或多轮实验；不是 local 完整演化成功，更不是 E2B 云端实测。E2B 使用同一任务包的配置离线检查已通过，真实云端文本实验仍未验收。已有工程 CI runner 和历史 continuation 的迁移仍属后续工作。下节另行记录本次完成的真实 local 全链路，不回写上述 Docker 边界。


## 真实 local 用户实验

追加实证位于 `/home/wydlinux/spec0076-full-live-20261003/`。从公开 CLI 导入 `examples/seed-inputs/library.json` 的 plaintext-checklist 和 `instruction.md` 的 weekly-notes，使用前者 simulated_user、后者 direct，两个真实 persona、单轮两会话并行。四面模型配置均为 `claude-opus-5-5`；使用仓外已有私密 profile，模型小请求探测通过，然后执行公开 check/prepare/run/collect/destroy，未替换任何模型、provider、工作区或 controller。

run `20261003T115105Z-81ecc091` 到达 COMPLETED / collection COMPLETE；两项 task/persona/digest/interaction 与冻结分配一致，材料哈希仍有效。各自产生完整补丁（1534、16681 字节），补丁 SHA 和收据一致且没有任务 venv/cache。归档 SHA-256 为 `8795b9051c7a3cf4b633e79415cf70e35fcc8e7694c810c5793c4eeb44b24fd8`。两项补丁还原到各自 scratch 初始源，在无网络、无凭证 Docker 中复验：checklist 的 UTF-8、空行、空白裁剪和顺序对照通过；weekly-notes 的 10 项 unittest 全通过。

模拟用户接受 checklist、体感 3 分，但 accept_validity 为 unverified_accept，反馈执行展示有摩擦；direct review 接受 weekly-notes、体感 4 分，并发布一条反馈 issue。不可把这些反馈改写为全部确认通过。本次仅单轮输入链路验收，末轮不执行 triage/synthesis/代码交付；不宣称多轮演化、E2B provider 或模型自动修复已验证。

清理到 DESTROYED，当前 run 标签的容器残留为零；保留自己的 Gitea 数据卷，现有无关 Gitea 服务继续运行。`final-proof.json`、原始收据、会话、补丁、独立复验日志均保存在上述仓外目录，不携带私密凭证进入提交。
