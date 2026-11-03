---
number: "0070"
title: 兼容 Gitea.com 的证据发布与联合预检
issue: 0
slug: gitea-com-evidence-transport
summary: 保留自建 Gitea 的 gzip 行为，增加 ZIP 发布、受限签名下载和读取端能力验证，保证旧证据与恢复兼容。
tasks:
  - id: T1
    title: 附件能力解析与受限下载
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/tracker/gitea.py
      - backend/ahe_beta/tracker/attachment_transport.py
      - backend/tests/tracker/test_gitea_evidence_transport.py
      - backend/tests/tracker/test_gitea.py
      - backend/tests/tracker/test_gitea_observe.py
      - backend/tests/tracker/test_gitea_timeline.py
    scope: 解析实际上传类型与站点规则，保留同源下载并增加固定 Gitea.com/R2 策略及有界无认证外部请求。
    acceptance: 自建 200 与托管单跳通过；Gitea.com 规则选 ZIP；API/恶意域/二次跳转/超时/认证泄漏负例拒绝。
  - id: T2
    title: 双格式发布与冻结传输记录
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/delivery_evidence.py
      - backend/ahe_beta/observations/transport.py
      - backend/tests/demand/test_delivery_evidence.py
      - backend/tests/observations/test_transport_profile.py
    scope: 默认 gzip 字节/句柄保持，增加确定性单文件 ZIP 和独立 profile；旧目录按 gzip 恢复，不改 framework contract。
    acceptance: 旧 gzip 字节与句柄不变；ZIP 回读摘要、重试复用、授权范围、超限与旧 profile 恢复测试通过。
  - id: T3
    title: 实际交付运行时能力预检
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/controllers/ordinary.py
      - backend/ahe_beta/loop/sim_user.py
      - backend/ahe_beta/observations/preflight.py
      - backend/tests/test_run_vigil.py
      - backend/tests/loop/test_sim_user.py
      - backend/tests/observations/test_transport_preflight.py
    scope: 在实际 executable/image 及复用容器检查新路径能力并关闭自更新，先冻结 profile 再启动模型或派单；接线容器公网地址。
    acceptance: 旧 gzip 不要求新命令；旧 reader/坏能力/错误镜像/冻结配置漂移在模型和派单前阻断，两个 sim_user 入口与恢复均通过。
  - id: T4
    title: 按需公网出口与镜像接线
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/deploy/gitea/docker-compose.yml
      - backend/deploy/gitea/egress-proxy.conf
      - backend/deploy/gitea/egress-gitea-com.conf
      - backend/deploy/experiment/docker-compose.yml
      - backend/deploy/experiment/egress-proxy.conf
      - backend/deploy/experiment/egress-gitea-com.conf
      - backend/deploy/vigil/entrypoint.sh
      - backend/deploy/vigil/build.sh
      - backend/deploy/vigil/observation-runtime.json
      - backend/tests/test_vigil_build.py
      - backend/tests/experiment/test_evidence_egress.py
    scope: 为托管 profile 显式启用受限代理规则，保留旧出口默认；构建并验证实际新 reader 镜像，记录真实版本。
    acceptance: 默认网络权限不扩张；显式托管路径通过代理到 Gitea.com/R2；伪装目标拒绝，最终镜像能力与记录一致。
  - id: T5
    title: 跨仓验收与联合发布
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
      - T3
      - T4
    relates-to: []
    parallel: false
    files:
      - backend/scripts/check_observation_contract.py
      - backend/scripts/check_gitea_evidence_transport.py
      - backend/tests/test_observation_contract.py
      - .github/workflows/ci.yml
      - release/compatibility.json
      - docs/QUICKSTART.md
      - docs/CONFIGURATION.md
      - docs/RELEASING.md
      - backend/deploy/README.md
    scope: 增加真实 producer/reader 离线契约与显式现场探针，更新 reader 先行的配套 SHA/部署记录和使用说明。
    acceptance: 两仓固定版本离线契约通过；自建/Gitea.com、E2B/容器实际 prepare 得到只读授权证据；现场结果脱敏且无模型调用。
---

# 0070 · 兼容 Gitea.com 的证据发布与联合预检

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

状态：用户已批准，两仓候选实现及离线/真实传输验收完成，正式发行尚未执行。任务 done 表示本版实现和候选验证完成；正式 reader SHA/digest 必须在 reader 先行合并、构建和复测后填写，不能将本地 dirty 工作树构建的候选镜像当作已发布版本。

为 AHE-Beta 增加 Gitea.com 的证据发布支持，同时保留自建 Gitea 的现有 gzip 行为、历史句柄和实验恢复。对应读取端为 OpenAgents `0092-gitea-com-evidence-reader.md`；两仓以本文件明确的传输契约和联合测试对齐，不互相 vendor 业务代码，不新增附件托管服务。

本组交付范围是“授权证据能上传、回读校验、被实际 OpenAgents 读取”；不以实验进程继续运行为成功，不把新功能验收混入当前仍在运行的固定版本 N1 实验。

## Motivation

2026-09-29 新用户试跑发现：内部 Gitea 1.22.6 的附件规则允许 .gz，直接下载返回 200；Gitea.com 当前拒绝实际 gzip 上传（422），允许合法 ZIP（201），附件下载则返回 303 到 R2 签名地址。内部实例及 E2B 到内部实例的真实 gzip 往返均已通过。

当前发布端在 `demand/delivery_evidence.py` 固定 gzip 压缩和 .json.gz 命名，`tracker/gitea.py` 在预检中要求白名单含 .gz，上传固定 MIME，下载禁止重定向。Owner 在证据发布并回读校验后才添加交付标签，这个顺序必须保持。现有本地观测和授权结构不依赖托管商，无需改变。

OpenAgents 旧读取端固定 gzip；即使发布端上传 ZIP 成功，读取端仍会降级为“证据不可用”并继续工作。因此需要真实读取端能力检查和读到文件的联合验收，不能只修上传扩展名或忽略预检。

## Guide-level explanation

使用已有自建 Gitea 的用户继续使用原凭证和启动方式：服务器允许 gzip 时优先选择原 gzip，原附件和 Issue 无需迁移；旧 OpenAgents 可继续读取这条路径。

使用 Gitea.com 的用户仍只提供自己的站点账号/token 及既有 E2B/模型配置。新运行根据站点规则选择 ZIP，并在实际交付环境确认读取能力。错误应指出阶段与可执行的修复方向，例如“当前 OpenAgents 不支持 ZIP，请升级交付运行时”，不得表现为“实验已启动但开发者没有证据”。网络或权限故障不能解释成格式不支持。

本组不重写 E2B 启动器、不自动部署公网 Gitea、不落实尚未完成的可选实验后端设计（0069）。只接入现有可运行的 subprocess/E2B 与容器证据链路；新用户完整 Quick Start 的其他问题另行处理。

## Reference-level explanation

### 两仓共同的传输契约（本段须保持一致）

- 内层 JSON 的 `format` 保持 `auto-designer:observation-evidence-v1`，issue、sessions、manifest、文件路径及摘要语义保持不变；不让 Agent 解析传输协议。
- Issue 机器句柄沿用 `asset_id/name/sha256/bytes`。旧 gzip 发布的句柄不新增字段；缺少 `encoding` 按 gzip。新增 ZIP 句柄必须带 `encoding: "zip"`；读取端也允许显式 `encoding: "gzip"`。未知值或声明与实际魔数不符必须拒绝，不自动猜测或回退。
- `sha256` 和 `bytes` 始终校验实际下载的压缩附件。传输上限 4,000,000 字节、解压后上限 24,000,000 字节；上限在真实读取过程中执行，不能只信服务器或 ZIP 元数据。
- ZIP 仅含一个普通文件 `evidence.json`，UTF-8、DEFLATE；拒绝额外或重复条目、目录、链接、加密和其他压缩算法。只在内存中有界读取该条目，不使用 extract/extractall。发布端固定条目时间戳为 1980-01-01 00:00:00、文件元数据及压缩级别 6，保证同一固定发布运行时重试得到相同字节；内部 JSON 序列化规则沿用原规则。
- `same-origin-v1` 保持现有自建 Gitea HTTP/HTTPS 直接 200 路径。新增 `gitea-com-r2-v1` 只适用于配置 origin 恰为 `https://gitea.com`、默认 443 且无子路径的实例；不得用后缀匹配放行伪装站点。
- 始终先从认证 Gitea API 验证附件属于当前 issue，再请求同源 `/attachments/{uuid}`，不采用正文外链或 `browser_download_url`。仅该已认证附件响应的 302/303/307/308 可进入一次受限跳转；目标必须为 HTTPS、默认 443、无 userinfo/fragment，hostname 精确满足 `^[a-f0-9]{32}\.r2\.cloudflarestorage\.com$` 的完整规则。其他存储域、IP 字面量、端口或二次跳转均拒绝。该边界是固定托管域名策略，依赖正常 DNS/TLS 与部署代理，不提供任意 URL 的通用下载能力。
- 对象存储使用新的无 Gitea Authorization、无 Cookie 请求，不继承 session 或 .netrc 认证；保留明确配置的网络代理。签名 query 仅用于本次请求，不写日志、异常正文或持久化状态。跨跳转共用单次附件下载 15 秒总预算，最终只接受 200，并继续验证字节数和摘要；API 请求仍禁止重定向。
- 能力命令为 `openagents observation-capabilities --json`，返回单个 JSON：`schema=openagents-observation-reader-capabilities-v1`、`marker=auto-designer:observation-evidence-v1`、`encodings=[gzip,zip]`、`zip_profile=single-evidence-json-v1`、`download_policies=[same-origin-v1,gitea-com-r2-v1]`、上述两项字节上限。调用不需要项目、凭证或网络，不自更新、不创建文件、不调用模型。
- 能力命令须在实际交付 executable/image 内执行；查询时设置已有开关 `OPENAGENTS_NO_SELF_UPDATE=1`，使尚不认识该命令的旧版本也不能先自更新。新路径的正式交付进程同样关闭运行期间自更新，记录实际 executable/image 身份。纯 gzip + same-origin 旧路径不强制要求新命令；ZIP 或 R2 路径能力缺失、未知、超时、预算不匹配均在派单/模型调用前明确阻断。

### 发布、选择和恢复

新增传输选择使用正确解析的附件配置：逗号分隔扩展名大小写归一、MIME 去参数后匹配，处理 application/gzip、application/x-gzip、application/zip、空值及 */* 的允许语义；仅出现 application/octet-stream 不能推断允许实际以 application/gzip 上传的 .gz（Gitea.com 已实测拒绝）。gzip 有效允许时优先 gzip，否则 ZIP，均不支持则明确失败。不得把 401/403、超时或 5xx 当作选择 ZIP 的依据。后续实际上传和回读是最终判断，站点声明与实测冲突应报告差异，不自动放宽校验。

保持 `build_package` 原调用默认 gzip，并保证原输入在相同发布运行时得到原 gzip 字节。ZIP 只更换外层压缩，随后按实际附件摘要确定性命名。重复发布优先复用同名资产，读取并验证后才更新机器句柄和交付标签；传输失败保持原提案、授权和证据归档，重试不制造重复交付。

既有 `preflight_observations()` 返回的 repository/format/max_transfer_bytes 对象保持原形，因为两个 sim_user 入口会把它与 `.framework-contract.json` 完整比较。新增 `.transport-profile.json` 独立持久化 schema、仓库身份、encoding、download_policy、预算，不存 token 或签名 URL。先确定并持久化 profile，再开始本轮用户或开发模型调用；同一实验恢复沿用已选 profile，不因站点配置变化静默换格式。

已有观测目录存在旧 framework contract 而缺少 profile 时，按旧 gzip + same-origin 解释；验证仍可用后可原子补写 profile，不重写旧 contract/附件。若站点已不支持旧路径，明确停止恢复并建议新实验身份，不混用旧新证据。格式选择信息通过显式配置传给 tracker/publisher，不让裸 `publish_delivery_evidence` 自动开启未经能力检查的 ZIP。

### 实际运行时预检与代理

纯 gzip 旧路径继续现有行为。新路径在启动/复用 vigil 之前检查实际 reader：subprocess/E2B 调用将要使用的 openagents 可执行文件；新容器用固定 image ID 覆盖 entrypoint 执行离线能力命令；复用容器检查其实际安装版本，不用宿主源码代替。能力进程限时 10 秒、stdout 上限 16 KiB；命令不存在或输出不符合 schema 时明确失败。

容器访问 Gitea.com 时，只有该 profile 才在未提供显式覆盖的情况下令容器端 Gitea URL 使用公网 https://gitea.com；原 localhost→http://gitea:3000 映射保持。两个 egress-proxy 模板需要可显式启用的 Gitea.com/R2 扩展 allowlist；原模式默认不扩大出口。扩展仅限 443，精确 gitea.com 和规定的 R2 hostname，不放行整个 cloudflare.com。代理放行不替代客户端目标验证。预检失败不能启动开发派单。

### Task DAG 与文件分配

| Task | 职责 | 文件归属 | 依赖 |
|---|---|---|---|
| T1 | Gitea 能力解析、MIME、受限下载 | tracker/gitea.py、新附件传输模块及专门 tracker 测试 | 无 |
| T2 | 双编码发布、profile 持久化与旧恢复 | demand/delivery_evidence.py、新 observations/transport.py、发布/profile 测试 | T1 |
| T3 | 实际 reader 能力预检、生命周期接线 | backend/ahe_beta/experiment/controllers/ordinary.py、loop/sim_user.py、新 observations/preflight.py、生命周期测试 | T1、T2 |
| T4 | 容器公网接线与按需出口 | 两套部署代理/Compose、vigil 构建/入口/镜像记录、部署测试 | T3 |
| T5 | 跨仓 CI、真实探针、联合版本与文档 | 联合检查脚本、集成测试、CI、release/compatibility.json、使用/发布文档 | T2、T3、T4 |

跨仓发布依赖不能写成误指本仓的 Task ID：OpenAgents 0092 先完成并发布兼容 reader → 本仓 T5 用真实提交 SHA/镜像验收 → 本仓启用新路径。不得在 spec 中填造未来 commit 或 image digest；实施时记录验证后的真实 pin。

本版保留 `openagents.integration_commit` 的旧配置基线，增加 `observation_transport.reader_release_commit`（当前 null）。CI 支持手动传入真实完整 reader SHA 运行新契约；填写正式 reader pin 后，普通 PR CI 自动启用双编码检查。在此之前 CI 明确报告仅覆盖旧配置基线，不能把它当成 ZIP 发行验收。镜像记录已保存实际构建的 `hosted_candidate`、原 HEAD + dirty + 源码摘要和 immutable image ID，并明确标为评审候选。

### 验收与端到端入口

实现 `backend/scripts/check_observation_contract.py --openagents <checkout>`，在无凭证无网络的 CI 里将真实生产者输出交给真实读取器，验证 gzip/ZIP、旧句柄、错误预算、摘要、issue、路径、ZIP 负例、重试复用和旧目录恢复；脚本不得调用 LLM。现有配置契约检查继续保留。

实现 `backend/scripts/check_gitea_evidence_transport.py` 作为显式真人环境探针：凭证只从 env/私密文件读取，只创建带探针标记的独立私有仓库/Issue，上传合成授权证据，调用真实 publisher 和 OpenAgents prepare，检查 session scope、digest、历史文件及只读权限；结束关闭探针 Issue，并输出不含凭证或签名 URL 的结果。探针不占用真实实验反馈，不在普通每次启动中默默创建仓库。

必须分别在自建 Gitea、Gitea.com、E2B 和实际容器/代理环境验证；公开 CI 不依赖私人 token，真人验证单独保存脱敏结果。负例包括摘要不符、错误 issue、未授权范围、多条目/路径/加密 ZIP、大小与时间超限、伪装域名、API 重定向、二次跳转、对象存储收到认证头、旧 reader 和漂移的冻结 profile。正向必须断言实际 evidence scope 与文件，不能只断言无异常。

2026-09-29 候选验收已完成：真实 producer → reader 离线验证 gzip/ZIP 各 7 个文件、14 类拒绝、重试复用和旧恢复；两站实际上传/回读及宿主、E2B、新镜像内 `prepare` 均得到唯一授权 session 的两轮历史共 7 个文件，摘要、内容和 `0400` 权限一致，没有模型调用。托管容器置于 internal 网络，真实通过 Squid 到 Gitea.com/R2；默认拒绝托管站、伪装域/端口/IP 拒绝均实测。额外实测了新 image ID 能力命令，以及本地 tag 不存在时仍能查询同一 run 的复用容器。临时容器/代理网络和 E2B 探针已清理，合成私有探针仓和已关闭 Issue 保留供审计。旧单实例 Gitea 代理保留既有开发机 cache_peer，实际托管联网验收使用每实验模板。

## Drawbacks

两仓会暂时同时维护 gzip/ZIP 和同源/托管下载两种路径，需要共同的契约用例防止实现漂移。Gitea.com 的对象存储域名属于外部部署事实，若未来变化，客户端应明确拒绝并更新支持策略，不能追求“永远成功”而任意跟随外链。

能力查询增加一次有界启动检查；它只能证明本地代码声明及已验证的支持，不能替代实际网络、权限和文件往返验收。

## Rationale and alternatives

选择在原传输边界增量扩展：保留 gzip 默认与 v1 内容结构，只对新托管路径增加 ZIP、受限下载和 reader 检查。不改变证据授权和角色职责，也不把模型事件格式耦合进框架。

备选一是要求所有用户自建 Gitea；这保留现状但违背无需租服务器的开源体验。备选二是全部改 ZIP 或升级到新的内层 schema；这会让原自建实例与旧 reader 产生不必要迁移。备选三是改扩展名、跳过预检或全局自动跟随重定向；分别无法生成合法 ZIP、掩盖真实失败或扩大凭证/下载边界。新增统一对象存储服务则引入新的账号、权限与运维，超出此次范围。

## Prior art

现有按 issue 授权的证据流程已经具备版本匹配、内容摘要、上传回读和 Owner 准入顺序；本组延续这些已验证行为。2026-09-29 的相关基线为 AHE-Beta 35 项、OpenAgents 64 项测试通过，真实函数跨仓 gzip 成功、相同 JSON 的 ZIP 被旧 reader 拒绝；这些仅是设计依据，不算新功能通过。

[Gitea 1.22 配置说明](https://docs.gitea.com/1.22/administration/config-cheat-sheet/) 描述附件 ALLOWED_TYPES、存储类型和 SERVE_DIRECT；[Python zipfile 文档](https://docs.python.org/3/library/zipfile.html) 描述 ZIP 成员与有界读取所需接口。两者用于说明外部能力，当前站点兼容性仍以真实附件探针为准。

## Unresolved questions

无待用户补充的设计问题。双编码、严格托管下载策略、实际 reader 检查和读取端先发布顺序已批准并实施。后续提交/联合发布需把真实已合并 reader SHA 和正式镜像 digest 写入兼容清单后复测；目前保留明确标注的本地候选记录，不伪造远程 pin。

## Future possibilities

其他托管实例/S3/CDN 支持可作为独立能力 profile 增量加入；本组不提供任意域名重定向配置。完整本地/E2B 统一启动体验及官方 benchmark 评分仍属于独立工作，不因附件链路通过而宣称完成。
