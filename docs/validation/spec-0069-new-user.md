# Spec-0069 新用户路径验证记录

本文件记录实际验证，不把教程中的目标流程当成已跑通结论。正式 SWE-bench 评分不属于此次闭环验收。

## 固定输入

- 统一入口：`backend/scripts/experiment.py`，schema_version 2。
- local 与 e2b 示例共用 pvlib `3f397ed44075b01f4ba535750356859195a51b2d`、`sr-15-swyx`、builtin seed 与五轮语义。
- OpenAgents reader：兼容清单中的实际固定提交；NexAU：`5cd791b1382f1163621c9ff0b50c2cf01c4ba923`。
- Python 3.12.13、uv 0.11.28、Claude Code 2.1.284、E2B SDK 2.51.0、pyarrow 21.0.0。
- 测试使用显式受保护 env，报告不含凭证、签名 URL 或原始用户正文。

## 验证进度

| 检查 | 当前记录 |
| --- | --- |
| 两份公开示例的离线材料/schema 检查 | 2026-09-30 两份 `experiment.py --json check --config … --offline` 均 exit 0 |
| 锁定依赖安装及任务环境安装 | `uv sync --locked --extra experiments --extra dev` 成功；修正 pytest-mock 后，干净 pvlib 基线及全新 Python 3.12.13 任务环境的 155 个 ModelChain 测试全部通过，其中 35 个使用 mocker，任务源码无修改 |
| 自动化检查 | 所有运行中修正后的完整 pytest：1299 passed、2 skipped；Ruff 和 diff whitespace 检查通过 |
| local 五轮 | run `20260930T084214Z-10f53992` 在 18:55（Asia/Shanghai）完成 R1–R5；工作中 stop/collect/resume 成功，R4 真实交付通过验收并合并 PR #2，R5 实际使用新封口版本；controller exit 0、残留进程 0 |
| E2B + Gitea.com 五轮 | run `20260930T074517Z-47a764e1` 在 17:03（Asia/Shanghai）完成 R1–R5，controller exit 0、五轮封口、残留进程 0；没有准入需求，未执行代码交付 |
| 工作中 stop/resume，身份与交付不重复 | E2B 的 R1 工作中 stop 成功、resume 保留 sandbox/repository/manifest 后完成五轮；本地 stop 成功，修复后 resume 保持原端口、仓库 ID 和冻结 profile。停止时没有在途交付票，不能据此宣称验证了交付中断续跑去重 |
| 实际 reader 的 gzip/direct 与 ZIP/R2 | 两路径均由实际固定 OpenAgents reader 完成上传、下载、解码自检；技术探针不计为用户反馈 |
| 周期收集、终态 hash、一致性及计算资源释放 | E2B 周期 PARTIAL、停止和最终 COMPLETE 均 consistent=true；最终沙箱自动 DESTROYED、仓库保留，销毁后公开 collect 再次成功，归档 SHA-256 已独立重验。本地停止及最终收集 COMPLETE，所属容器已移除、Gitea 数据卷保留；销毁后公开 collect 再次成功 |
| 官方 SWE-bench 评分 | 未执行 |

实际运行应追加 run ID、输入/源码 hash、启动和完成时间、实际资源 receipt、R1–R5 session/seal/交付记录、stop/resume 前后身份、收集 SHA-256 与资源终态。闭环失败时记录具体阶段和保留资源，不以 canary 或旧 wrapper 结果替代本入口的完整验收。

自动化检查的两个 skipped 来自 public-bench-pilot 的 TAU adapter 用例：当前环境没有可选的 tau2 包，测试使用 importorskip；NexAU 可正常导入。本次 pvlib 实验与统一入口用例均没有因此跳过。

## 2026-09-30 实际启动记录

所有启动、停止、续跑和资源释放均使用公开的 `backend/scripts/experiment.py`，运行目录和凭证位于仓库外。四个模型角色的在线探测均成功；本次使用用户选定的 `claude-opus-5-5`。

首次云端尝试 `20260930T073238Z-14e24a06` 在 Gitea.com 建仓阶段失败。API 返回 HTTP 403，用户网页确认当前账户已达到 5 个仓库上限；这不是模型调用或证据格式错误。通过 `destroy --confirm <run-id> --discard-uncollected` 释放该次 sandbox。用户授权后，仅删除一个描述明确为 synthetic compatibility probe 的早期空测试仓库，删除前保存仓库元数据、issue 和评论备份；其余仓库保留。

重试使用 run `20260930T074517Z-47a764e1`，实际 sandbox `i48owoppcq9z9t04wy1n8`，4 CPU / 8192 MB，Gitea.com repository ID `145360`。准备时冻结了未提交工作树：基线提交 `bbdbf2113034ad06030cbcfda8515140d7984dd7`，controller source archive SHA-256 `65715daacc7bc30fb088348a96b6c221d5f32430b95fa6dd0a43b661125b3919`；manifest SHA-256 `cc856796a9bc347d6459c333004a929abcadc13a8289e8605891537e45baf2bc`。固定 OpenAgents 为 `a752e8830a13f44d97a3043d1f3e8dd16bd8d8aa`。

云端技术自检返回 `status=ready`，实际 reader 声明支持 `same-origin-v1` / `gitea-com-r2-v1` 与 gzip / ZIP；ZIP/R2 探针解码后 SHA-256 为 `17fcb9cbaf13396c25578c24103cc080a6d21d2e4209872294993f84bceee031`。该技术 issue 已关闭，不作为用户反馈。

15:56（Asia/Shanghai）在 R1 用户阶段调用 `stop --grace-seconds 30`。停止 receipt 为 `STOPPED`、`cleanup_complete=true`、`residual_processes=0`；沙箱继续保留，终态归档标为 COMPLETE，其 SHA-256 为 `25682522409c089518b0ed9cb8afa4dd420a0d5d81005badbc864c66bfe3d1fd`。15:57 调用 `resume`，保留上述 run、manifest、sandbox、repository 身份，controller nonce 从 `82bca739f4944c47b6d3972acfa1067c` 变为 `3820944ae3464a4c9660757f58e5cf7a`，启动模式为 resume。COMPLETE 只表示停止时的完整收集，不表示五轮实验完成；续跑后收集状态恢复为 PARTIAL。

本地 prepare 的 run 为 `20260930T073310Z-143b01d4`。Docker 重启后服务恢复，实际 Engine 27.5.1 / Compose 2.32.4；冷启动下载 `python:3.12.13-bookworm` 耗时约 45 分钟，之后构建完成；未使用已有的 Python 3.12.12 镜像替代固定版本。

## 实测发现与修正

云端 R1 的 session 为 `op-468c1b45b1a88d950c1fd90a17294cd5`，evaluation_status 为 valid、user_outcome 为 accepted、accept_validity 为 unverified_accept；正式评分禁用，因此 objective_passed 为空。R1 没有反馈 issue 或准入票，Harness sealed SHA 保持 `d208bac3a5a3caff5981db83af7195db30b58288`，随后进入 R2。封口成功不意味着该轮产生代码改进，也不把模型自述的测试数量当成独立评分结论。

R1 暴露了环境配方漏装 pytest-mock，用户要求补装后才执行依赖 mocker 的测试。示例现已加入 `pytest-mock==3.15.1` 与两个真实 SHA-256 hash，原有 20 个依赖版本保持不变。修正后锁文件 SHA-256 为 `09e5f1a2a2db40a645e566fe869fa42c9caead422c15dab3e89e8334455bf74b`；在干净任务基线及全新 venv 中执行全部 ModelChain 测试，155 passed，0 failures/errors，包含 35 个 mocker 用例。此结果只验证基线环境可用，不是新需求的 SWE-bench 评分。上述正在运行的 E2B 实验继续使用原冻结锁（`35aaa4a67a6f35c4c32e6ea0a711c2e47c0ab98a0e6293f3b5bba0f595de138e`）；没有替换既有 manifest 或材料。另行 prepare 本地运行以冻结修正后的配方。

教程已修正两处与 CLI 实际行为不一致的描述：run 在启动阶段完成后才输出最终 receipt，中途可另开终端 status；Gitea 浏览地址从 `resources.json` 的 url/owner/repo 获取。新增账户仓库配额排查，未将本次账户的五仓上限当成所有账户的固定额度。

本地首次准备还暴露了构建期间提前显示 PREPARED、日志等到命令退出才写入的问题。现已记录 PREPARING 和未完成标记，并在操作锁下准备；只有准备成功才允许 run 访问 provider。CLI 会提前向 stderr 输出 run ID，本地还输出实时 `logs/prepare.log` 路径；超时或失败保留部分日志。实际子进程阻塞时日志已增长、未完成 prepare 无法启动 provider、并行 status 不阻塞等测试通过。启动 receipt 也改为记录当前 RUNNING controller，避免夹带启动前 ABSENT 观察；status 的 Gitea 字段只保留 url/owner/repo/repository_id。运行中的实验仍保留修正前的冻结 controller source，未修改其 manifest；上述修正另由完整自动化检查验证。

代理镜像原默认值 `ubuntu/squid:6.13` 不存在，Docker 返回 manifest unknown，阻止本地 prepare。这已更换为经 registry 实际验证的 `ubuntu/squid:6.6-24.04_beta@sha256:6a097f68bae708cedbabd6188d68c7e2e7a38cedd05a176e1cc0ba29e3bbe029`，prepare、Compose 和旧入口共用固定默认值。Canonical 使用包含 Ubuntu 版本及 channel 的 tag 命名，而非单独 Squid 版本号。[Canonical 镜像说明](https://hub.docker.com/r/ubuntu/squid)。实际拉取的镜像是 Ubuntu 24.04.3 LTS / Squid 6.13；独立的所属 Compose 探针验证允许 HTTPS 目标返回 200、未授权目标返回 403，探针容器及网络已清理。本地后端和旧基础设施测试合计 42 passed。

修正准备状态后的实际 run `20260930T082712Z-3b64ed5e` 曾在构建中返回 PREPARING / OPERATION_IN_PROGRESS，日志实时增长。它因上述代理 tag 问题终止后为 FAILED、resource_state=ABSENT、preparation_complete=false、failing_stage=prepare；随后公开 run 命令以 exit 2 拒绝启动，没有创建 provider 资源。失败输入和构建日志保留，修正后的材料另行冻结。


## E2B 五轮完成及资源终态

云端运行在 15:48 启动，工作中停止/恢复后于 17:03 完成，17:04 自动收集并释放 sandbox。五轮均有唯一已完成的用户 session 和 seal，R1–R4 需求阶段完成，R5 仅执行用户试用；controller exit code 0、cleanup_complete=true、residual_processes=0。五轮 sealed SHA 都为 `d208bac3a5a3caff5981db83af7195db30b58288`，没有反馈 issue、准入票或代码交付；这是合法的空需求闭环，但并未覆盖实际修改 Harness 或重启交付中的去重。

| 轮次 | 用户 session | 分数 | 反馈 issue 数 | 验收记录 |
| --- | --- | --- | --- | --- |
| R1 | op-468c1b45b1a88d950c1fd90a17294cd5 | 3 | 0 | valid / completed / accepted / unverified_accept |
| R2 | op-71e82f90cdc33f78a84b817238c485e7 | 3 | 0 | valid / completed / accepted / unverified_accept |
| R3 | op-154335b33a36ec2b8ff47c6b604af2a2 | 3 | 0 | valid / completed / accepted / unverified_accept |
| R4 | op-c823fbd34022d97a90835ce71ebb58de | 3 | 0 | valid / completed / accepted / unverified_accept |
| R5 | op-9fe899507eefd22166516406623f9bb0 | 4 | 0 | valid / completed / accepted / unverified_accept |

自动终态归档为 COMPLETE / consistent=true，SHA-256 `377d1e9052dd973c36679a7220d63a400f4b165807bd467173bb5849e7b18484`，已逐字节重算；资源状态 DESTROYED，Gitea repository ID 145360 保留。销毁后从持久 snapshot 再次公开 collect 成功，新归档 SHA-256 `170235d6326dab3122cceef56a787b78b27f70ab51caa68de65381ea6a4a2733` 也重验一致。归档包含本次收集时间和状态，因此重复收集可产生不同 hash，分别按对应 receipt 校验。

本次从启动至自动释放约 76 分钟（含停止/恢复），实际 sandbox 4 CPU / 8192 MB。usage.jsonl 记录 354 次成功调用、7,906,872 total tokens：Harness 196 次 / 6,729,521 tokens，User 154 次 / 1,156,712 tokens，Synthesizer 4 次 / 20,639 tokens。没有 delivery 调用。这是程序记录的调用用量，包含本次中断/续跑，不是供应商账单或价格估计；其他账户和任务的耗时、费用会变化。

成功收集后曾仍显示旧的“Automatic collection failed”错误，尽管资源已释放。现已修正：成功 collect 只清除已恢复的采集错误，其他启动错误仍保留，三种恢复/保留回归用例通过。修正后的公开 collect 实测清除该旧错误，不改实验冻结输入。

## 本地启动、中断及恢复问题

实际本地运行为 `20260930T084214Z-10f53992`，16:47 prepare 完成、16:49 启动。controller source archive SHA-256 `eaf717f6f2ac5697cf5edc277cfdb32f938f6f938113c0b91b85df73605e6fee`，manifest SHA-256 `f3f61a88441758682c51af1308b0f54bacb6dfbc50820164447cc43c18692b33`，任务使用已修正 pytest-mock 的锁文件。启动时 Vigil ready=true，controller 与资源均 RUNNING；Compose project 为 `adx-20260930t084214z-10f53992-9cc5b93e`，自动创建的 Gitea repository ID 为 1，初始地址为 `http://127.0.0.1:55451`。

实际 OpenAgents reader 的 gzip/direct 探针完成验证，解码后 SHA-256 `5c0647eed9d3e69bf20404db3a142c4355e4f2bfe9595c59c94261ffab524dde`；探针使用独立仓库并已删除，不污染用户反馈。

16:52 在 R1 用户阶段公开 stop，controller exit -9、STOPPED、cleanup_complete=true、残留进程 0。所属容器停止/移除，用户原有 auto-designer-gitea 容器保留。停止后公开 collect 无需重新启动 Gitea，COMPLETE 归档另存并重验 SHA-256 `87aa1221db16287b4bae9a1d6a6d8a6738516f1b482550e43ee28f67a38c2f6e`。

恢复前补齐了仓库身份校验：缺失或 ID 改变的已有仓库不得被重新建仓替代；resources.json 采用 canonical repository_id，同时识别已有 repo_id。首次公开 resume 仍失败：Compose 的随机 host port 在重新启动后改变，冻结的 observation transport profile 保留初始 55451 端口，controller 因 `invalid or mismatched observation transport profile` 在 Vigil 启动前退出。保留原 manifest、transport profile 和任务材料；修复方向是持久化初次分配的端口，并在恢复时重新绑定原地址，而非放宽 profile 身份校验。


端口修复后再次公开 resume 成功：canonical_url 和 host_port 恢复为 `http://127.0.0.1:55451` / 55451，repository_id 仍为 1，Vigil ready=true，实验与资源 RUNNING、采集 PARTIAL，新 controller nonce 为 `d1cc19b3634346d381c49e2ab7c49268`。manifest SHA-256 保持不变；与停止归档逐字节比较，冻结 transport profile 没有改动（SHA-256 `d437d4c0efa06331c34e4160dffac689d0ddcf223e0011cc84aacbfcf8152bd4`）。恢复只重设所属容器的端口绑定，保留原数据卷和仓库身份。端口恢复、占用、换仓库和跨服务 profile 等新增检查后完整 pytest 为 1289 passed、2 skipped；随后补充成功重试清除已解决的启动错误，29 个生命周期测试通过。

进入 R3 后再次公开 resume，返回 action=attach，controller nonce 与 runner PID 83651 都保持不变，没有新建第二个 controller。另补充读取旧版本成功恢复状态时清除遗留启动错误、保留当前采集错误的用例，生命周期测试合计 31 passed；实际公开 status 的 last_error 已恢复为空。启动/采集历史仍在 journal 中保留。


## 本地 R4 实际反馈与交付

R1–R3 均 valid / completed / accepted，零反馈；R4 用户 session `op-725ddecc2696800fb9dec8a486e174d4` 为 valid / completed / accepted、score=3，产生一条用户 issue。Issue #1 经 Triage、Synthesizer 和 Owner 处理后准入，进入 OpenAgents 交付；内容涉及用户明确要求先说明计划时，Harness 直接编辑。交付 worker 已在容器中读取 `.openagents/observation-evidence/issue-1-…` 的真实证据包并检查 Harness 代码，说明实际反馈到交付 reader 的链路也被本地运行覆盖。R4 已完成交付和封口，进入 R5；交付中 stop/resume 去重尚未验证。

实施阶段提交了 Spec-0001 的 prompt、complete_task 契约、帮助文档、结构测试和真实模型验收脚本。首次验收指出证据文件没有 Task ownership，以及两类脚本负例缺少实证，返回 REWORK；实现端返工后重新验收，未跳过验收直接封口。验收同时确认 12 个真实模型用例通过、T1 回滚两次均失败，以及 17 项 Harness 自测中一个缺 `.env.example` 的失败在原冻结基线上也存在。

回看 seed 打包规则，确认 `.env.example` 被错误当成私有 env 排除，这是统一材料编译的问题，不是用户填写凭证的错误。现已保留公开 `.env.example`，仍排除 `.env`、`.env.local`、`.env.example.local`、credentials.env 和私有 env 目录；归档回归检查确认这些私有文件内容不进入包，材料/本地/云端后端测试合计 83 passed。另从真实当前 seed 重新打包、解压，在全新目录执行其 13 项自测，全部通过，归档 SHA-256 `38f75dff424dc7136c1ce5ec16db8a30472fd08a29ed24f953b5f182ed656c23`。既有 local/E2B 实验仍使用各自原冻结材料，没有补文件或改 manifest 来隐藏基线失败；后续 prepare 才使用修正的打包规则。


第二次验收仍要求补回公开 `.env.example`，随后完整 Harness 检查通过。最终 reviewer 与 architect 均 PASS，merger 以批准 head `309013dae006a093d46ddfdc26343afa7fc2bb99` 合并 PR #2，merge commit 和 R4 sealed SHA 均为 `edf1406288ab715b910c79399a69dc812f6e7310`。Issue #1 已关闭。R5 的 recovery 记录中 user_sha 等于这一封口 SHA，实际 `data/harness_runs/edf1406288ab715b910c79399a69dc812f6e7310-edf1406288ab/` 已包含修复后的 prompt、工具描述、公开配置模板和验收证据；不是只根据合并消息推断新版本已被使用。

交付验证包括四类真实模型行为各三次，共 12/12 通过，证据固定在 `7a3643d19e12cb07e33cafde8850c7a1078ccd33`，后续不再修改产品 prompt 或验收脚本。回退 T1 后 BC1 两次均失败，注入未跟踪 PLAN.md、修改后提交、修改/提交/撤回三个负例均触发失败；缺少模型配置时脚本 BLOCKED / exit 2。最终候选 unittest 17/17、pytest 20 passed，并行重复也通过。这些是本次单模型、单夹具下的检查点行为证据，不证明所有任务措辞都已覆盖，也未把仅检查规则文字的结构测试当作行为验收。

归档收集也已修正 `.env.example` 误排除：允许公开模板，但仍排除私有 env 文件和目录，回归测试通过。浏览器试用还发现本地随机账户密码未持久化，现改为新建账户后立即保存 `secrets/local-gitea-login.env`（0600，父目录 0700），PAT 失败或恢复不丢失密码；已有账户无记录时不伪造或重置密码。创建、失败重试、旧账户和权限等六项新增回归通过，本地与旧基础设施检查合计 59 passed。该登录修复供后续新建实验使用，没有修改当前运行的账户或冻结输入。


## 本地五轮完成及资源终态

本地运行于 18:55（Asia/Shanghai）完成五轮；controller exit code 0、cleanup_complete=true、residual_processes=0，recovery 和 invocation manifest 的五个封口完全对应。R1–R3 与 R4 的试用输入是 seed `d533063bb0e347119eaad34d27ac027c16420a94`，R4 交付后 sealed SHA 变为 `edf1406288ab715b910c79399a69dc812f6e7310`，R5 实际使用该新版本并以同一 SHA 封口。

| 轮次 | 用户 session | 分数 | 反馈 issue 数 | 最终验收记录 |
| --- | --- | --- | --- | --- |
| R1 | op-a4c484c55a7e73ae5b6f10d73b8de21a | 3 | 0 | valid / completed / accepted / unverified_accept |
| R2 | op-e0314e8d332e0ce1d22bca374357545e | 3 | 0 | valid / completed / accepted / unverified_accept |
| R3 | op-1b99186271187f1818804c1e22c4b3ed | 3 | 0 | valid / completed / accepted / unverified_accept |
| R4 | op-725ddecc2696800fb9dec8a486e174d4 | 3 | 1 | valid / completed / accepted / unverified_accept |
| R5 | op-4e639bf10ca5b6e3771e77ea74a32fda | 3 | 0 | valid / completed / accepted / unverified_accept |

R5 用户本轮明确表示无需停下来给计划，因此它验证的是合并后版本仍能自主完成任务，没有再次独立覆盖显式检查点措辞；显式检查点行为由上述交付的 12 次真实模型用例覆盖。各轮 objective evaluation 均 skipped、passed 为空，不能把 accepted 或完成五轮解释为官方 SWE-bench 通过。

自动终态收集 COMPLETE / consistent=true，归档 37,593,524 bytes、SHA-256 `32ff7f4cde3b9bc936900a8d177d9f020a8012341db619d084c127d4bb2da1d0`，已重算归档及其中全部文件 hash。该次由原冻结收集代码执行，仍排除公开模板；使用当前已修正 CLI 在资源销毁后再次 collect，得到 COMPLETE / consistent=true，SHA-256 `026c3a0628cdbabf8d601f7b83c8cab97fc86c4fb15f88d2858b535a27491c71`，归档及全部文件 hash 再验一致，包含最终 Harness 的 `.env.example`。针对本次已知模型/provider 凭证扫描，两次归档均未发现原文；这不是对未知敏感信息的通用保证。

终态 experiment_state=COMPLETED、resource_state=DESTROYED。所属 Compose 项目已无容器，`adx-20260930t084214z-10f53992-9cc5b93e_gitea_data` 数据卷保留；原有 `auto-designer-gitea` 容器仍运行。本地网页登录地址此时不再服务，这是释放所属容器后的预期行为；仓库数据和宿主归档保留。

从首次启动到完成约 126 分钟，包括停止/恢复、真实代码交付和验收返工。主控制器 usage.jsonl 记录 215 次成功调用、3,388,262 total tokens：Harness 113 次 / 2,631,909，User 93 次 / 587,092，Synthesizer 4 次 / 21,473，Triager 5 次 / 147,788。OpenAgents 的外部 Claude Code 和模型 e2e 调用不在这一汇总内，所以不是完整实验总用量，也不是供应商账单。

## 本次验证范围

两份示例均以公开统一 CLI 完成五轮、R1 中断/恢复、实际 transport reader 预检、完整收集与资源释放。本地还覆盖真实反馈准入、交付返工/验收/合并及下一轮使用新 SHA；云端没有准入票，因此仅覆盖空需求闭环和 ZIP/R2 技术自检。尚未验证在交付执行期间停止再恢复的去重，未执行官方任务评分。

根据用户“先不 commit”的要求，本次 prepare 冻结的是基线提交加未提交实现的源码快照，源码归档 hash 已逐一记录，尚未进行发布后的干净 clone 复测。运行中发现的修正没有回写冻结源码或任务材料；它们由相应自动化检查和另行材料打包验证，两个实际运行仍保留各自准备时的 source archive。完整 pytest 最终为 1299 passed、2 skipped；Ruff check/format、spec validate、生成视图和 whitespace 检查通过。67 个变更文件均位于 Spec-0069 的 Task 分配或其 spec/生成视图中，未提交、未推送。
