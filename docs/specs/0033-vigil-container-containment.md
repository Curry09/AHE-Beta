---
number: "0033"
title: 交付面容器化围堵：vigil 专用容器（零宿主挂载、容器内自 clone）+ 出口代理 allowlist + 观测游标改跟 origin/main
issue: 0
slug: vigil-container-containment
summary: spec-0032 换轨后交付面的 coding agent 是进程外的 claude CLI（bypassPermissions），nexau 时代的进程内 workspace_jail 够不着它——WSL/宿主裸跑时嵌套 agent 可读整个文件系统（编排仓、data/sessions 过拟合信道）且出网无限制，现存兜底（凭证隔离/boundary 钩子/repo_guard 绊线）只管「改了什么、推到哪」，不管「看了什么」。本 spec 把 spec-0021/0022 定下的「进程内 jail 靠不住 → 环境级围堵（无凭证 + 网络出口 allowlist）」完整落地：vigil 跑进专用容器（openagents + claude CLI + git），工作目录为**容器内自 clone 的 harness 仓**——零宿主挂载，「只能看到 harness 仓」从软件承诺变成文件系统边界；网络上 vigil 容器只挂 internal 网络（可达 gitea），外网经 egress 代理 allowlist（仅放行 Anthropic API 域）。可行性关键：两面（需求面/交付面）的唯一交互媒介本来就是 Gitea（issue 标签 + push/merge + main SHA），vigil 不需要宿主文件系统的任何东西；容器每 run 重建 = clone 与 .openagents 运行态自动归零（原 rmtree 重置语义保留）。连带修一个现存 bug：spec-0032 后推进 main 的是 Gitea 上的 server-side merge，而 orchestrator c 步与 launcher 读的是**本地** harness 仓的 main——本地永远停在 seed，游标不前进、用户永远跑 v0；_resolve_head 改为先 fetch origin 再解析 origin/main（无 origin 时退化本地，兼容既有测试与 Fake 场景）。宿主 subprocess 直跑模式保留为显式 opt-in（VIGIL_MODE=subprocess，仅限盯屏联调），容器为缺省。
tasks:
  - id: T1
    title: vigil 容器与网络基建：Dockerfile/entrypoint/build + internal 网络 + egress 代理 allowlist
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: true
    files:
      - backend/deploy/vigil/Dockerfile
      - backend/deploy/vigil/entrypoint.sh
      - backend/deploy/vigil/build.sh
      - backend/deploy/gitea/docker-compose.yml
      - backend/deploy/gitea/egress-proxy.conf
    scope: 新建 deploy/vigil/——Dockerfile（基底 python 3.12 bookworm 含 git；native 安装 claude CLI；以本地 OpenAgents checkout 为 build context 装 openagents，pin 由 checkout 决定）、entrypoint.sh（从 env 取内网 Gitea 地址与 token clone harness 仓到容器私有工作目录 → 把只读挂载的 /config/openagents.yml 拷入 .openagents/ → exec openagents vigil --parallel $K）、build.sh <openagents-path>（构建入口，校验路径存在）。docker-compose.yml：新增 internal 网络 vigil-net（internal true，挂 gitea 与 egress-proxy）；新增 egress-proxy 服务（tinyproxy/squid 任一，配置文件 egress-proxy.conf 只放行 Anthropic API 域（含 ANTHROPIC_BASE_URL 自定义域的注释指引），同时挂 vigil-net 与可出网的默认网络）。gitea 服务加挂 vigil-net（host 端口映射照旧走原网络，不受 internal 影响）。vigil 容器本身不进 compose（生命周期随 run，由 run.py docker run 拉起，见 T2），但其网络/代理依赖在此就位。
    acceptance: build.sh 在带 OpenAgents checkout 的机器上构建成功；容器内 openagents/claude/git 可执行；vigil-net 上 vigil 容器可达 gitea 3000、直连外网被拒、经代理仅 allowlist 域可达（生产机实证）；compose config 校验通过。
  - id: T2
    title: run.py 双模式接线：容器缺省（docker run 生命周期/日志/env 注入）+ subprocess 显式 opt-in
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/run.py
      - backend/tests/test_run_vigil.py
    scope: VIGIL_MODE env（container 缺省 / subprocess 显式 opt-in 且打醒目告警「无围堵，仅限盯屏联调」）。container 模式：start_vigil 改为 docker run -d --rm --name auto-designer-vigil --network vigil-net、只读挂载 staging 配置目录到 /config、env 注入 GITEA_TOKEN + claude 凭证二选一（ANTHROPIC_API_KEY（API 计费，可配 ANTHROPIC_BASE_URL——须为 Anthropic 协议端点）或 CLAUDE_CODE_OAUTH_TOKEN（订阅计费，宿主 claude setup-token 生成的长效 headless token））+ HTTPS_PROXY=egress-proxy + 并发 K + 内网仓地址；两者皆缺时预检 fail-loud；日志经 docker logs -f 子进程落 data/vigil.log；stop_vigil = docker rm -f（--rm 兜底自清理）。write_openagents_config 改写到 staging 目录（不再写进 HARNESS_REPO——容器内自 clone，宿主仓与交付面脱钩），gitea.base_url 用内网地址（VIGIL_GITEA_INTERNAL_URL 缺省 http gitea 3000），host 侧 .env 的 localhost 地址仅编排面自用。预检从「PATH 有 openagents」按模式分叉：container 模式改查 docker 可用 + 镜像存在（缺镜像给 build.sh 提示）。subprocess 模式保留既有行为（含写配置进 HARNESS_REPO）。
    acceptance: 两模式的 start/stop/config 落点/预检各有单测（mock subprocess/docker，不触真容器）；container 模式下 HARNESS_REPO 内不再出现 .openagents/；token/key 只经 env 不落盘断言保留；生产机容器模式端到端跑通一轮（承接 spec-0032/T5 的冒烟验收）。
  - id: T3
    title: 观测游标改跟 origin/main：_resolve_head 先 fetch（无 origin 退化本地）
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: true
    files:
      - backend/auto_designer/loop/orchestrator.py
      - backend/tests/loop/test_orchestrator.py
    scope: 修 spec-0032 引入的现存 bug——推进 main 的是 Gitea server-side merge，本地 harness 仓的 main 停在 seed，c 步游标与 launcher 的会话快照永远解析到 v0（老模型 dev 在本地仓 commit+push、本地即真身，故无此问题；换轨后真身在 Gitea）。_resolve_head：先 git fetch origin <ref>（把远端对象与游标取回本地，launcher 按 SHA checkout 因此可解析），解析优先 refs/remotes/origin/<ref>、无 origin/fetch 失败时退化本地 <ref>（容忍离线/Fake/单仓测试场景，行为与今天等价）。fetch 失败不抛——观测游标宁可停滞也不废轮，失败打印告警。
    acceptance: 新增测试：本地仓 + bare origin，外部向 origin 推进 main（模拟 vigil merge）→ run_round 回灌 SHA 前进且 launcher 收到的 launch ref 为新 SHA；无 origin 的既有测试全部不回归（退化路径）；fetch 失败（origin 不可达）不抛、返回本地 SHA。
  - id: T4
    title: 文档与 spec 制品：CLAUDE.md 围堵段收口 + render/graph
    status: done
    priority: P2
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: true
    files:
      - CLAUDE.md
    scope: CLAUDE.md 交付面描述补围堵形态（vigil 容器化、零挂载自 clone、egress allowlist、VIGIL_MODE 双模式与使用纪律「subprocess 仅限盯屏联调」）；OVERVIEW/ARCHITECTURE 随 render/graph 再生成。
    acceptance: CLAUDE.md 与实况一致；spec validate/render/graph 全绿。
---

# 0033: 交付面容器化围堵：vigil 专用容器 + 出口代理 allowlist + 观测游标改跟 origin/main

## Summary

把交付面（OpenAgents vigil + 嵌套 claude CLI）关进专用容器：**零宿主挂载、容器内自 clone harness 仓**，「只能看到 harness 仓」从软件承诺变成文件系统边界；网络上只挂 internal 网络（可达本地 Gitea），外网经 egress 代理 allowlist（仅 Anthropic API）。这是 spec-0021/0022「进程内 jail 靠不住 → 环境级围堵」的完整落地。连带修一个现存 bug：观测游标与 launcher 改跟 `origin/main`（server-side merge 后本地 main 不再是真身）。

## Motivation

spec-0032 换轨后，交付面 coding agent 是进程外的 `claude -p`（headless 需 `bypassPermissions`），nexau 时代挂在工具层的 `workspace_jail` 中间件够不着它：宿主/WSL 裸跑时，嵌套 agent 可读整个文件系统——编排仓、`data/sessions/`（体感与会话全量，**过拟合信道**：spec-0015 沉下 sandbox 目录防的正是这个）——且出网无任何限制。现存三层兜底（凭证隔离 / boundary 钩子 + CI 边界 / repo_guard 绊线）都作用在「改了什么、推到哪」，对「看了什么」零约束。

进程内软闸不是出路：0021 事故已实证 dev 能用 python heredoc 隧道绕过路径扫描；0022 因此把围堵需求定为**环境级**——无凭证 + 网络出口 allowlist。换轨没有制造这个需求，只是把它从「建议」变成「必须」。

## Guide-level explanation

### 为什么「零挂载」可行——媒介本来就是 Gitea

疑问「harness 仓每轮在变，容器只挂它够吗」的答案是：**连挂都不用挂**。两面的全部交互都经 Gitea：

```
需求面（宿主进程）                     交付面（vigil 容器）
 Owner 打 openagents 标签 ──issue──►  _intake 发现、盖 ready
 c 步 fetch origin/main   ◄──merge──  PR 合并落 Gitea main
 launcher 按 SHA checkout（本地仓=编排面自己的观测/种子副本）
```

vigil 需要的只是「一个 harness 仓的 git 工作目录」——容器 entrypoint 自己从 `http://gitea:3000` clone 一份即可，宿主的 `HARNESS_REPO` 与交付面彻底脱钩（退化为编排面的种子推送源 + 观测副本）。挂载方案反而有害：每 run 的 rmtree 重置会拆掉容器的工作目录、宿主路径耦合进容器。零挂载还白送一个性质：**容器每 run 重建 = clone 和 `.openagents/` 运行态（队列 db/claims）自动归零**，原「rmtree 重置世界」语义原样保留。

### 围堵形态

```
宿主：run.py（需求面照旧）─ docker run ─► vigil 容器（openagents+claude+git）
                                            │ 文件系统：只有容器私有 clone —— 编排仓/sessions 物理不存在
                                            │ 网络：仅 vigil-net（internal）
                                            ├──► gitea:3000（issue/push/merge）
                                            └──► egress-proxy ──allowlist──► api.anthropic.com（仅此）
```

`bypassPermissions` 在这个盒子里开着也无所谓——能读的只有它本来就该改的仓，能连的只有它本来就该连的两个端点。凭证面：容器内只有 harness 仓的 Gitea token + claude 凭证（`ANTHROPIC_API_KEY`（API 计费）或 `CLAUDE_CODE_OAUTH_TOKEN`（订阅计费，宿主 `claude setup-token` 生成）二选一，皆 env 注入不落盘、专用可轮换），宿主的 `~/.claude` 登录态与 gh 凭证不进容器。

### 使用纪律

容器模式为缺省；`VIGIL_MODE=subprocess` 保留宿主直跑（带醒目告警），**仅限人盯着日志的一次性联调**——长跑闭环必须容器模式。

## Reference-level explanation

- **镜像**（T1）：python 3.12 bookworm（自带 git）+ claude CLI（native 安装器）+ openagents（以本地 OpenAgents checkout 为 build context 安装，版本 pin 由 checkout 决定，与「uv tool 钉版本」同一纪律）。构建入口 `build.sh <openagents-path>`。
- **配置注入**（T2）：`write_openagents_config` 改写到宿主 staging 目录、只读挂载到容器 `/config`，entrypoint clone 后拷入 `.openagents/`；`gitea.base_url` 用容器内网地址（`VIGIL_GITEA_INTERNAL_URL` 缺省 `http://gitea:3000`），宿主 `.env` 的 localhost 地址仅编排面自用。这是「同一份配置、两个可达性域」的唯一分叉点。
- **出口 allowlist**（T1）：vigil-net 置 `internal: true`（无 NAT，直连外网物理不通）；egress-proxy 双网络（vigil-net + 可出网默认网络），allowlist 仅 Anthropic API 域；vigil 容器经 `HTTPS_PROXY` 走代理（claude CLI 尊重代理变量）。自定义 `ANTHROPIC_BASE_URL` 时 allowlist 需同步（配置文件注释给出指引）。
- **生命周期**（T2）：`docker run -d --rm --name auto-designer-vigil` 随 run 起、`docker rm -f` 随 run 收，日志经 `docker logs -f` 落 `data/vigil.log`（观测面不变）。
- **游标修复**（T3）：`_resolve_head` 先 `git fetch origin <ref>`（同时取回对象，launcher 按 SHA checkout 得以解析），解析优先 `origin/<ref>`、失败退化本地（离线/Fake/单仓测试等价于今天）。fetch 失败告警不抛——游标宁可停滞不废轮。

## Drawbacks

1. 多一个镜像要构建维护（OpenAgents 升级需重 build）；首次构建拉 claude CLI 需外网。
2. egress 代理是新的单点：代理挂了交付面全停（needs-human/看门狗兜不到这层，靠日志观测）。
3. Anthropic API key 进入被围堵容器——盒内 agent 理论上可滥用该 key（调 API 本身）；爆炸半径限于 API 费用与该 key，可单独发放/限额/轮换。
4. Windows 原生仍不能跑交付面（不变）；容器模式要求宿主有 docker。

## Rationale and alternatives

- **零挂载 vs 挂载宿主仓**：见 Guide——媒介是 Gitea，挂载徒增 rmtree 竞态与路径耦合，且围堵上挂载点就是逃逸面。
- **弃案：`.claude/settings.json` 软闸（allow/deny 工具白名单）**：便宜但仍是 claude 自我执行的进程内约束，与被 0021 实证击穿的 jail 同一信任模型；用户裁决直接做硬闸。容器就位后如仍想叠加纵深，可作后续可选层。
- **弃案：给 vigil-net 直接开外网、跳过代理**：allowlist 就没了——出口白名单正是 0022 两条硬需求之一，不可省。
- **弃案：挂载宿主 `~/.claude` 解决 claude 登录**：把整个个人账号登录态交进围堵盒——egress 拦得住外传，却拦不住 agent 把读到的 token 写进 commit/PR 正文经 Gitea「抄」出盒；且 claude 需写该目录（token 刷新），容器与宿主登录态互相污染。围堵原则：只给非给不可的、且每样可单独作废——env 注入的专用 key/长效 token 满足，个人登录态不满足。
- **fetch 放 orchestrator 而非 launcher**：游标解析是 c 步唯一入口（launcher 只按给定 SHA checkout），在源头取回对象一处修完两个消费者。

## Prior art

- spec-0021（dev 逃逸事故与三层兜底）/ spec-0022（围堵硬需求=无凭证+出口 allowlist）：本 spec 是其环境级结论在换轨后的落地。
- spec-0032 §4.5：换轨时明记「jail 变弱需正视、网络出口 allowlist 仍是环境级建议」——本 spec 收掉这笔债。
- deploy/gitea 既有形态（Gitea + act_runner 容器化、命名网络）：vigil 只是同一基建里的第三类容器。

## Unresolved questions

1. egress-proxy 选型（tinyproxy 够用/squid 更可控）与 allowlist 的域名通配细节——T1 实施时按最小可用定，生产实证后固化。
2. claude CLI 在容器内的首跑体验（native 安装器的更新自检、telemetry 出网点是否需要加白）——生产实证清单。
3. act_runner 的 job 容器（CI 冒烟）是否也应迁到 internal 网络——checkout 经 gitea 内网已可达，但 catthehacker 镜像内 action 生态可能有出网期待；观察后定。

## Future possibilities

- 多 vigil 容器横向扩（--parallel 之外的仓级并行）；
- egress 代理日志作为交付面行为审计面（谁在什么时候连了什么）；
- 需求面（user sim/生成器）同法容器化，编排仓最终只剩编排本体。
