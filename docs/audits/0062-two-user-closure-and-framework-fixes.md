# 双用户闭环实验结果与框架修复

实验 `spec61-two-user-glm53-glm52-20260908` 于北京时间 2026-09-08 23:48 完成归档。
它完成了一次“两个用户并行 → 设计/Owner → 开发交付 → 两用户再次并行”的闭环，
但有一次明确记录的人工纠正，不能认定为全自主闭环成功。

## 实验结果

| 用户 | 第一轮 | 第二轮 |
| --- | --- | --- |
| Leo | accepted，体感 4 | accepted，体感 4 |
| Ronacher | abandoned，体感 1 | abandoned，体感 1 |

Owner 准入的 #6、#7、#8、#11、#12 均交付，PR #17、#16、#15、#14、#13 均已合并。
初始 harness SHA 为 `3a64ccbea8882e36c882cf767a5e6e240483014f`，
封口 SHA 为 `e3372074f5888c042e883801c740fe768b25ac26`。
第二轮 Ronacher 的结束反馈 #18：约 21 分钟主要停留在调查；用户明确催促修复后，
仍未交付代码、测试或最终答复。体感没有改善；这不是官方 benchmark 技术判定。
本实验未启用 benchmark 评估，交付 CI 为冻结配置中的 skip；不能称全 CI 或技术验收全通过。

用户/被测 harness 使用 glm-5.3-flash；需求与交付角色使用 glm52_250k_yzx_fork_wr_0907。
运行时 auto-designer 源码是 `12759e5bc31cfb09a3a05298a1e69b373bbc050a`，OpenAgents 是
`9a4edaf0f8832945abd966cb4d82025ab87d9e86`；交付镜像为
`auto-designer-vigil:observability-spec61-1dda04a`。之后的源码修复不归因给本次运行。

## 观测层验证

四个会话都有对应版本的观测入口和阅读说明。Leo 两次 complete，Ronacher 两次 partial；
放弃导致的部分记录没有被伪装成完整观测。应读取会话 manifest 的 `runs[].status` 和
`runs[].artifact.harness_sha`，不是猜测顶层字段。

两版的框架指纹均为 `29995b3e6dac56e6516a241329922956771e3c59de92cb3d419a4be5a1c57c62`。
READING 从 2042 字节变为 5031 字节，摘要由
`18fb675898d7b1699f5357d0ef90c7ea3ddf4a39e82e1cd5b3e405a4356268f3` 变为
`e555bf86228c495c023cb0cdc0db65630c5c53857dd4220ab430ca6e32b4ca7c`。
这证明该次演进中 harness 的阅读说明可随实现更新，固定收集层能收取两版，不意味着所有格式均已验证。
需求侧产生了诊断补强提案 #9、#10，纳入结构提案 #11 并经 PR #14 交付。
它验证了补强提案链条确有使用，不证明每个角色都充分读日志或诊断质量必然提升。

## 人工纠正及永久修复

issue #8 的 Spec 因并行改号，仅自引用变化便让旧设计摘要失配。失败标记写在 issue，
读取却跟随关联 PR；读不到标记又被当成事实变化，失败被反复撤销。外层还仅识别旧
needs-human，未能对 automation-failed 及时停轮。

人工恢复先核验原/现设计仅改号、当前 head 审批有效及工程闸符合原配置，再短暂停调度，
只修正这张票的审批摘要并留审计，然后恢复原运行器，由正常流程合并。没有强制合并、
修改功能实现或替换运行中框架。

永久修复见本仓 Spec-0062 和 OpenAgents Spec-0088：明确自引用编号从语义审批摘要中分离；
保留原始摘要和旧审批精确匹配；失败标记按所属对象读取，缺失或失效不能触发复活；
本轮闸识别新旧失败标签，闭票也不能覆盖失败。修复只落源码和离网回归，尚未新建镜像重跑。
2026-09-09 最终全量回归：OpenAgents 1223 passed，auto-designer 856 passed；针对性回归
分别 235 和 38 passed。两仓 Ruff check、Spec 和 graph 检查通过（Spec 仍有跨历史组文件重叠等提示）。

## 本地证据入口

实验根目录：`/root/src/auto-designer-experiments/spec61-two-user-glm53-glm52-20260908`。

- `journal.jsonl`：完成、停止、归档生命周期。
- `telemetry/gitea-snapshot.json`：终局 issue/PR 快照。
- `telemetry/manual-interventions.jsonl`：人工干预意图、实施、恢复调度。
- `archive/harness.bundle`：Git 归档；封口在 `refs/remotes/origin/main`，本地 main 仍为 seed。
- `data/role_runs/830a5ee045c744669ee99a6b10b2fee9/observations/`：随版观测与阅读说明。
- `archive/bundle/`：数据与 harness 源码的保留副本。

无需重新启动已停止的 Gitea 即可核查上述结果；不把凭据写进审计文档。
