# Spec-0077 本地工程 CI 验收

日期：2026-10-03。工程 CI 只运行 Harness 的工程工作流，不调用模型或运行 benchmark。默认关闭；本组仅迁入 local + localhost。E2B + Gitea.com 的 CI 不在此范围。

## 首次真实探针与隔离修正

初版在 `/home/wydlinux/spec0077-live-20261003/` 留存 run `20261003T121235Z-6d41541d`。真实 Gitea 1.22.6、act_runner 0.2.11、固定 job 镜像已执行 main → 故意损坏 Python 的 PR → 修复后新 PR head 三段工作流，API 各自给出非空 success/failure/success 状态。`first-ci-proof.json` 保留三个不同提交 SHA 与上下文。公开 stop 到 STOPPED / collection COMPLETE，再 destroy 清理本次容器。该候选并未完成用户会话，不作为最终实现的成功实验。

实测发现 act_runner 默认的 `GITEA-ACTIONS-TASK-<ID>` 容器名和 `act-toolcache` 卷是全局命名；不同独立 Gitea 的 task ID 可相同，专属外层网络和容器标签不足以隔离这些名称。最终实现改用每个 run 专属的 Docker daemon 和数据卷，runner 不挂宿主 Docker socket，job 的 host 网络仅指内层 daemon 所在的隔离网络。首次候选的 red/green 成功不能替代修正后的重新验收。

## 最终实现验收

最终拓扑的两个并行 run 为 `20261003T123438Z-2d5c757a` 和 `20261003T123438Z-838edfa9`。`final-isolation-proof.json` 记录了两边同时出现相同的 `GITEA-ACTIONS-TASK-1_WORKFLOW-ci-readiness_JOB-smoke` 名称、workspace/env 卷和 `act-toolcache`，但 daemon 容器 ID 与外层存储卷不同。两边最终都通过真实红绿探针；前者只验证技术 preflight，没有启动完整用户实验，最终为 FAILED / PARTIAL，不计作完整实验成功。

后者通过公开入口 run → stop → resume → collect → destroy。stop 留下 STOPPED / COMPLETE 检查点；恢复再次执行探针，保持同一个 runner 注册 ID、runner 容器、daemon 容器及存储卷。恢复后的真实状态如下，每个 SHA 均有一项检查：

| 对照 | 当前提交 SHA | Gitea 状态 | 固定 OpenAgents 读取结果 |
| --- | --- | --- | --- |
| main | `4f175e8b4b9024e3c5592e8fdb8de530235926ec` | success | 不适用，PR 读取端只检查 PR |
| 故意损坏 Python 的 PR | `dc90a808f3ca604e79c6699944b975146404f6b7` | failure | fail / failure |
| 修复后的新 PR head | `b84ebfea882fae364e1238207487d9a625db3a21` | success | pass / success |

唯一用户会话 `op-efc94db58e97f149aeb538b5881884ad` 使用 `claude-opus-5-5`，完成 plaintext-checklist 任务；恢复复用已有完成会话收据，未重复执行用户任务。最终 COMPLETED / COMPLETE，归档保留完整 2335 字节补丁及会话 provenance。用户主观接受仍标为 `unverified_accept`，不能因此宣称功能正确率提升。单轮最终试用没有 triage/synthesis/非空 OpenAgents 交付，也未验证模型自动修复红灯。

归档中的 Harness 当前提交 `016eaa91c44c5cbbc11180532a84496aad1fac28` 有非空 success 状态。归档 SHA-256 为 `89527b78735cc4dc555b0a88427b985fbfce9d1d0234002bcd1d62b9538480b6`；补丁 SHA-256 为 `87a58be081cbdde138deb01002a04317d449aee081c1a371360505477c1b7c98`。重新计算二者吻合。逐个检查归档成员及内容，确认 secrets、infrastructure、`.runner` 和实际 reader token 未进入归档。

本次五个候选 run 均已通过公开 destroy 清理，所属容器为零；四个独立 daemon 候选的 CI Docker 数据卷均已删除，Gitea 数据和 runner 私密注册卷按合同保留。原有无关的 `auto-designer-gitea` 仍运行。最终证据为本机目录下 `final-proof.json`、`before-resume-ci.json`、`after-resume-ci.json`、`final-stop.json`、`final-resume.json`、`final-collect.json` 和 `final-destroy.json`；这些运行产物不提交仓库。

## 实测发现与修正

- shell dotenv 会给 token 加引号，而 Docker `--env-file` 不解释引号，导致真实 OpenAgents reader 收到错误凭证并返回 401。现在生成独立的 0600、无符号链接 reader 文件，只包含字面 Gitea token，不复制整个模型／E2B profile。
- 同一 PR 提交的状态在读取端偶尔暂时显示 pending。现在只对同一 head 的 pending/无检查做有界等待；提交改变或相反终态仍失败。
- act_runner 在完成后自动删 job，`ps` 与 `inspect` 之间会出现容器消失的竞态，真实 resume 因此失败。现在逐项检查，并只在重新成功查询确认对象消失时跳过；连接错误、仍存在对象操作失败和所有权改变仍报错。stop 的移除操作也遵循这一规则。修正后公开 resume 重新通过上述真实探针。
- 全仓回归发现本机锁定 Python 缺少可选 pidfd API。补上 Linux x86_64/aarch64 的稳定进程句柄调用，仍复核 nonce 并保护无关进程；不退回直接按 PID 发信号，不支持的内核仍报告失败。

## 离线回归与边界

全仓 `pytest -q`：**1943 passed，2 skipped**（260.82 秒）；跳过项是已有的两个 `tau2` adapter 检查，本环境未安装可选 `tau2`，不是 CI 测试被跳过。容器竞态修正后的 helper、真实进程清理和 workspace 定向回归：**43 passed**。端到端合同脚本：**244 passed**。Ruff lint/format、公开配置与示例检查、spec validate、shell 语法及 diff 空白检查均通过。完整输出保留为 `final-full-pytest.log`、`final-race-regressions.log` 和 `final-contract.log`，不把定向检查累计成全仓用例数。

本组真实验收只覆盖 local + localhost、固定默认镜像与可信工程代码。E2B + Gitea.com 工程 CI、自定义 runner/job 镜像和模型自动修复流程没有在本组实测，不能用人工红绿技术对照替代这些能力的验收。
