# Spec 0061 · 实施与闭环验证

2026-09-08。结论：制品自有日志、框架收集、跨容器读取、两侧补强请求及跨版本保留的工程机制已接通。
本次使用脚本化角色决策和受控交互，不能据此声称真实模型已主动、有效地运用观测，或完整 vigil
工程质量闸已经重新实测。此前 spec0059 两会话实验也不被冒充为新机制的测试。

## 实现边界

| 部分 | 已实现 |
|---|---|
| NexAU 种子 | entry 自己调用 observability；元数据日志、随版 READING、进程/尝试/span/中断/重建记录；队列、单进程及重启总预算；失败不改任务结果 |
| 固定迭代框架 | 启动前存储与 Gitea 能力预检；仓库绑定；清理前有界收集；原子发布、摘要、真实 harness SHA/镜像及收集器指纹；partial/unavailable 显式状态 |
| 失败恢复 | 导出失败停止并保留原现场，写恢复回执；使用原运行 ID 重试；不覆盖历史，不无限重试，不创建 harness 交付票 |
| 交接 | 框架保存的来源授权决定包范围；先上传并回读校验附件，再发交付令牌；开发容器按当前 issue 下载，不用外链或宿主 session 挂载 |
| 开发职责 | 公共 engine 覆盖 Spec Writer/Drafter、Architect、Developer/Implementer/Executor、Reviewer/Acceptance；维护观测影响、说明及测试，不以日志存在代替行为验收 |
| 补强 | 四个需求角色的非终结工具；开发角色的显式请求文件与认证回传；普通 proposal、稳定请求 ID、durable outbox、评论分页去重、重启/空闲补交 |
| 路线隔离 | PM 及其后续缺口保留来源；Designer 的原始证据权限来自可信授权，不从模型正文扩权；Owner 无原始日志工具 |

阅读/记录事件格式属于 harness；框架只解释传输外壳。更换为非 NexAU 起点不要求修改事件解析器。

## 最终受控实测

- [完整结果](/root/src/auto-designer-experiments/spec0061-observation-validation/spec0061-lifecycle-0rsw87jo/result.json)
- [隔离私有测试仓](http://localhost:3000/designer/observation-lifecycle-20260908-170125)
- [需求侧补强 #1](http://localhost:3000/designer/observation-lifecycle-20260908-170125/issues/1)
- [开发侧补强 #2](http://localhost:3000/designer/observation-lifecycle-20260908-170125/issues/2)
- [实际合并 PR #3](http://localhost:3000/designer/observation-lifecycle-20260908-170125/pulls/3)

v1 为 `f068a75fdd5b5a7dde2604dabc809ddf67448672`，合并封口 v2 为
`1a2840e8e9f24a645beea7d4eb51a3f774e18399`。

两版都执行「start A → cancel → start B → inspect」。行为回复独立验证为
`active=A → active=none → active=B → active=B`。
v1 的 transitions.log 只有四条 transition，不能判别请求归属；v2 改为 ownership.tsv
及新版说明，可辨别 `start A / cancel A / start B / inspect B`。
两张补强票通过普通 Owner 交接，实际合并后关闭；新会话绑定新的 sealed SHA，旧文件字节不变。

最终开发镜像 `auto-designer-vigil:observability-spec61-1dda04a` 的不可变 ID 为
`sha256:efdce28072a5640d6e30ecfa7622f809ae83f0f5ad4d21785e5881c12426ad1c`。
容器没有宿主 bind mount，使用 `http://gitea:3000` 获取私有附件；服务端的浏览器 URL 为
localhost 并未被用于下载。实际加载模块位于已安装的 site-packages，而不是宿主源码挂载。
此次临时执行容器已删除；测试仓、历史证据与结果保留在上列位置。

## 回归结果

- auto-designer 全量：846 passed（25.27s）。
- harness 种子独立测试：16 passed（0.26s）。
- OpenAgents 全量：1196 passed（16.47s）。
- 两仓 Ruff、spec validate、派生文档检查通过。

负例覆盖路径越界、符号/硬链接、特殊文件、字节与时间预算、持续慢速传输、摘要损坏、跨 issue
或 session 引用、未认证评论、同 ID 重试、响应丢失后已关闭票去重、PM 后续来源、离线补交，
以及没有 .gitignore 的制品不会因运行器证据缓存触发工作树污染。
全量回归曾暴露种子单文件加载测试漏掉同目录模块路径，已修正测试启动语义并全量复跑通过。
本机 HTTP 测试需具备环回端口权限；沙箱内未完成的全量运行不计作通过。

## 使用和恢复

新实验应选择本次固定开发镜像，并使用声明了 `observations: artifact-observations-v1` 的新版
种子/制品。运行中的旧实验、旧种子归档及 latest 镜像标签没有被替换。
直接启动 backend/run.py 时设置 `AUTO_DESIGNER_VIGIL_IMAGE=auto-designer-vigil:observability-spec61-1dda04a`；
实验管理入口的冻结配置则将 `images.vigil` 指向该固定镜像。
精确构建 pin 见 [observation-runtime.json](../../backend/deploy/vigil/observation-runtime.json)。
overlay 构建不更新依赖；依赖改变时应使用完整构建，不能把本次基底当成永久实现约束。

复跑真实基础设施验证（会创建新的独立私有测试仓，不调用模型）：

```bash
.venv/bin/python backend/scripts/replay_observation_lifecycle.py \
  --env-file backend/deploy/gitea/.env \
  --openagents-source /root/src/OpenAgents \
  --delivery-image auto-designer-vigil:observability-spec61-1dda04a \
  --output-root /root/src/auto-designer-experiments/spec0061-observation-validation
```

恢复单份失败导出：

```bash
PYTHONPATH=backend .venv/bin/python -m auto_designer.observations \
  --root /具体实验/observations \
  --receipt /具体实验/observations/collection-failures/具体回执.json
```

恢复复用原版本与运行 ID；不自动删除保留容器，确认归档后再维护清理。
正常路径自动发布，失败现场不得被误认为完整日志；积压达到上限会在新实验启动前要求维护。

## 不扩大结论

complete 是收集校验与制品声明，不是全知记录或功能成功。日志量不是优化分数；benchmark
未参与提案、开发或本测试。通用脱敏不是全面隐私识别，制品最小化记录与工程验收仍有责任。
已实现按票分发和摘要检查，不等于在同一个持有仓库 token 的终端上建成多租户权限沙箱。
取回记录也不等于模型实际阅读或理解；真实模型是否提出恰当补强，仍需下一次多轮实验观察。
历史票没有可信授权时不从正文回补权限；源码与镜像的更新也不追溯改写旧实验。

## 当前版本调用（Spec-0071）

上面的命令、源码路径、时间和结果记录保留当时的验证事实。当前工具已迁移到
`tools/dev/replay/`，需显式指定一个已有的 v2 run 目录、凭证文件与 OpenAgents 源码：

```bash
PYTHONPATH=backend uv run --locked --extra experiments python -m tools.dev.replay.replay_observation_lifecycle \
  --run-dir .experiments/RUN_ID \
  --secrets-file /path/to/experiment.env \
  --openagents-source /path/to/OpenAgents \
  --output-root /path/to/validation-output
```

此工具会创建独立测试仓库并运行 Docker；它不是新的实验启动入口。可选的
`--delivery-image` 验证须提供 run 中的网络或显式 `--delivery-network`；容器访问地址可用
`--internal-url` 指定。运行前请查看 `--help` 和 [开发工具说明](../../tools/dev/README.md)。
此次目录清理未重新执行上面的在线验证，原验收记录仍属于原冻结版本。
