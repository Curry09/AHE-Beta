# 联合发布流程与待办

本轮为源码整理，尚未发布 tag、Release、镜像或变更仓库可见性。两仓独立版本化，使用兼容清单把一组版本连接起来，不要求版本号相同。

## 基线与冻结

`release/compatibility.json` 的 `baseline_commit` 保留整理前的审计来源，`openagents.integration_commit` 则记录已合入 main 的跨仓基线完整 SHA；当前跨仓 CI 优先采用 `execution_evidence.reader_release_commit`，未发布时采用 `reader_candidate_commit`，**两者都不是整理完成后的正式发行版本**。整理 PR 合并并通过检查后，从双方目标分支取最终提交，生成发布资产中的完整 manifest，填写两仓 SHA/tag、NexAU、seed Harness tree、容器 digest、配置 profile、平台及验证结果。避免在提交内部记录自身 commit hash。

两仓最终均从 main 发布。OpenAgents 的功能和开源整理已分别通过 [PR #185](https://github.com/Curry09/OpenAgents/pull/185) 与 [PR #186](https://github.com/Curry09/OpenAgents/pull/186) 合入 main；已合入 main 的配置基线为 `ee87df3acab036213cecbc35cdea01339a5dd988`；当前 PR CI 的配套执行证据 reader 为 `release/compatibility.json` 中的不可变候选提交。这仍是提交 pin，尚未发布正式 tag。项目/前端/桌面组件版本可以不同，Release notes 解释各自范围。NexAU 从 hzhua/nexau 的固定 Git 提交获取；pyproject.toml、uv.lock 与 release/compatibility.json 必须一致。OpenAgents wheel 的 nexau extra 也直接携带固定 Git 依赖，安装时需能读取上游仓库；当前发布方式为源码/GitHub wheel，PyPI 发行前另行确认 direct-reference 依赖政策。

## 已纳入本轮代码的检查

- 锁定依赖安装、Python lint/format/test。
- auto-designer 的 evaluation 测试、前端测试/构建和实际两仓配置契约。
- OpenAgents 基础 wheel 仓外安装、可选 NexAU 导入、desktop typecheck/test/bundle。
- 公开快照的敏感哨兵回归测试；离线演示显式使用脚本客户端。

GitHub CI 的跨仓 checkout 要求对方仓库可读；首次公开前若仍是私仓，需要维护者设置只读仓库 secret `OPENAGENTS_READ_TOKEN`（workflow 不持久化该 checkout 凭证）或在受信任本地完成该项，不能把个人 token 写进 workflow。先公开可被读取的 OpenAgents，再公开/启用依赖它的 auto-designer CI。

## 正式公开前仍需完成

- [ ] 合成用户 + 自有任务的两轮真实闭环 demo，以及未参与开发者按文档完成一次安装/试用。
- [ ] Docker/Gitea/模型 canary：R1 反馈→需求→PR→合并，R2 users-only；另测停止/恢复及终态失败不误放行。
- [ ] 复测旧消息归属、子 Agent 停滞、撤回、反馈证据被驳回后不被 PM 重新当作事实等研究回归案例。
- [ ] 完整 Git 历史和 release 资产的秘密扫描；逐项处理，不无证据地重写历史。
- [ ] THIRD_PARTY.md 中人物画像、任务数据、vendored 来源的逐项许可与分发决定。
- [ ] 两侧 `npm audit` 告警评估和修复/书面处置，升级后重新验证。
- [ ] 固定并验证容器 digest；镜像构建/真实运行不能用 Python 测试结果代替。
- [ ] 检查分支保护必需状态、私密漏洞报告、仓库描述与双方链接。

## 发布顺序

1. OpenAgents 功能与整理已合入 main；auto-designer 已更新 pin 并复测契约，继续将本整理 PR 合入 main，完成离线与真实验收。
2. 构建 OpenAgents wheel、源码包，以及约定的镜像；auto-designer 保持源码发行。使用不可变版本名，生成校验和、manifest、Release notes 和已知限制。
3. 先准备依赖方可引用的 OpenAgents 版本，再冻结 auto-designer 指向该版本；先以 draft/prerelease 验证安装与下载。
4. 维护者确认上述待办与资产后，执行正式 tag、Release 和可见性变更；双方 Release 互相链接。
5. 若验收失败，修复后发新的候选版本，不移动已有正式 tag。旧版本兼容组合继续保留。

## 更新联合版本时需要同步的引用

- auto-designer 的 `.github/workflows/ci.yml` 中 `integration` 从清单选择已验证的 OpenAgents 完整 SHA，不写移动的 `main`。
- 两仓 `release/compatibility.json` 的 `openagents.integration_commit`：保持配置基线一致；启用新证据发行时再固定 `observation_transport.reader_release_commit`，CI 优先使用该新 reader SHA；保留历史 `baseline_commit` 供追溯。
- Quickstart 的 clone/checkout 示例：采用同一兼容组合；正式发布后补版本 tag 与对应 SHA。
- 构建镜像时使用该 OpenAgents checkout；发行资产记录实际镜像 digest，不能仅更新 Git ref 就宣称旧镜像含有新代码。

流程为：合并整理改动 → 更新包版本与发布说明 → 固定候选提交并验证 → 打不可变 tag、构建和验收 Release 资产。候选提交到正式 tag 若有变化，应重新验证；已有正式 tag 不移动。

## Gitea.com 配套升级门禁

<!-- Spec-0070/T5 -->

OpenAgents 0092 必须先于新发布端上线：旧 reader 不理解 ZIP，不能靠 publisher 上传成功判断交付成功。当前实现是配套工作树候选，`observation_transport.reader_release_commit` 保持 `null`，没有捏造尚未发布的提交。`observation-runtime.json` 中历史 runtime pin 仍属于 gzip 基线，`hosted_candidate` 只记录本次实际构建的评审镜像。

1. 审阅并合并 OpenAgents reader，取得真实完整 SHA，并更新候选 pin；用它构建新镜像并通过镜像内能力检查。
2. 普通 PR CI 按清单选择配套 execution evidence reader 的 release pin 或候选 pin，同时运行配置及真实 producer/reader 的 gzip/ZIP 离线契约；也可手动触发 `workflow_dispatch`，输入完整 SHA 验证另一提交。离线契约通过不代表镜像或模型 canary 已通过。
3. 对新容器/代理及 E2B 分别执行显式真人探针，确认真实 `prepare` 返回授权 session，历史文件和摘要一致且权限为 `0400`。记录环境、版本与结果，脱敏后保存；不调用模型。
4. 把已验证 SHA 填入 `observation_transport.reader_release_commit`，同步 Quickstart 与镜像发行记录。普通 PR CI 继续自动运行新编码契约。运行时使用实际镜像 digest，而不是仅更新宿主 checkout。
5. 保留旧 gzip/direct 兼容组合。旧实验恢复继续原冻结 profile；新实验才使用新托管路径。

附件链路验收与完整闭环 canary 分开记录；前者不代替 R1 交付、R2 复测和停止/恢复的模型实验。

手动构建经典 Vigil 或 SWE 运行时镜像时，另备 SDK checkout：`git clone https://github.com/hzhua/nexau.git /path/to/nexau` 后执行 `git -C /path/to/nexau checkout --detach 28511d9f0362191a6c378fd441b2be55309a9e32`。Vigil 的 `backend/deploy/vigil/build.sh` 显式接收 OpenAgents 与 SDK 两个源码路径；SWE 镜像构建设置 `NEXAU_SOURCE=/path/to/nexau`。统一实验入口的 local/E2B 引导直接按冻结 uv.lock 安装 Git 依赖，无需内置或额外打包 SDK 源码。
