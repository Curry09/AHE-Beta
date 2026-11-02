---
number: "0002"
title: Gitea 接入与基建
issue: 0
slug: gitea-tracker-and-infra
summary: 本组补齐 **a 段的真实后端与基建**：0001 用 Fake 把接口立了起来，本组把「桩」换成「真」——起一个本地 Gitea（issue 与 harness 仓的家），并实现 0001/T5 `IssueTracker` 接口的真后端 `GiteaTracker`。
tasks:
  - id: T1
    title: Gitea 本地基建与标签方案
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/deploy/gitea/docker-compose.yml
      - backend/deploy/README.md
      - backend/deploy/gitea/bootstrap.sh
    scope: "做什么：\n- 提供 `docker-compose.yml`：单 Gitea 服务、sqlite 后端、数据挂命名卷、暴露固定 HTTP 端口。\n- 提供 `bootstrap.sh`：等待就绪 → 建 admin → 生成带 `write:issue,write:repository` scope 的 access token → 建工作仓 → ensure 标签集 {bug, feature}。\n- 产出 `backend/deploy/gitea/.env`(GITEA_URL/OWNER/REPO/TOKEN)，gitignore，作为 T2/T3 的配置契约。\n- 提供 `README.md`：启动、拿 token、重置数据卷的步骤。\n不做什么：\n- 不做生产化部署（无 TLS、无外部 DB、无反向代理、无高可用）。\n- 不实现 IssueTracker 客户端逻辑（归 T2）、不推 harness 种子内容（归 T3）。\n- 不管理 token 轮换/过期策略、不做多用户/多组织权限模型。\n- 不在脚本内编排 T2/T3；本任务仅产出连接信息，消费方自行读取。"
    acceptance: "- `docker compose up -d` 后 Gitea 在固定端口可访问，`GET /api/v1/version` 返回 200。\n- `bootstrap.sh` 首次运行产出 `backend/deploy/gitea/.env`，含 GITEA_URL/OWNER/REPO/TOKEN 四键且值非空。\n- `bootstrap.sh` 二次运行不报错、不重复建 admin/仓/标签（幂等），TOKEN 维持有效。\n- 工作仓存在，标签集含且仅初始含 {bug, feature}。\n- 用产出 TOKEN `curl` 调 `POST /repos/{OWNER}/{REPO}/issues` 建一条 issue 返回 201。\n- GITEA_URL 不含尾斜杠与 /api/v1 后缀；.env 被 gitignore 不入库。\n- README 记录启动、拿 token、重置数据卷三条路径。"
  - id: T2
    title: GiteaTracker
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/tracker/gitea.py
      - backend/tests/tracker/test_gitea.py
    scope: "做什么：\n- 实现 spec-0001/T5 的 IssueTracker 接口四方法：ensure_labels / create_issue / add_comment / set_state。\n- 薄 REST 客户端(requests)打 `/api/v1`，鉴权 `Authorization: token <token>`。\n- ensure_labels：建/查 label 并维护 name→id 映射缓存；create_issue 返回解析后的 IssueRef。\n- 配置(base_url/owner/repo/token)由构造注入，来源是 T1 产出的 .env。\n不做什么：\n- 不读环境变量、不读 .env、不起服务（注入由调用方负责，保持纯客户端）。\n- 不实现 issue 列表/搜索/里程碑/指派等接口外端点（奥卡姆，dev 侧需要再扩）。\n- 不做本地缓存 issue 内容、不做离线队列/重试编排（失败即抛，由调用方决定）。\n- 不负责标签的语义定义（标签集 {bug,feature} 由 T1 预置）。"
    acceptance: "- 实现 IssueTracker 协议四方法且带类型标注，可作为 GiteaTracker 注入 run_session 替换 FakeTracker。\n- create_issue 向 `/repos/{owner}/{repo}/issues` 发出含 title/body/label-id 的 POST，解析响应回带号 IssueRef(number/url/state)。\n- ensure_labels 对已存在 label 复用 id、对缺失 label 新建，并幂等（重复调不重复建）。\n- add_comment、set_state 命中对应端点；token 进 `Authorization: token <token>` 头。\n- 非 2xx 响应（401/403/404/422）抛出含状态码与端点的异常，不返回空回执。\n- 单测全程 mock HTTP，不依赖运行中的 Gitea。"
  - id: T3
    title: harness 仓初始化
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/scripts/bootstrap_harness.py
      - backend/tests/test_bootstrap_harness.py
    scope: "做什么：\n- 读 T1 产出的 `backend/deploy/gitea/.env` 连接信息。\n- 经 Gitea API 建 harness 仓（仓名独立于工作仓，缺则建，幂等）。\n- 用 git 把本仓 `backend/harness_template/` 内容作为初始提交推到该仓默认分支(main)。\n- 建 release 分支指向 main。\n不做什么：\n- 不创建 feature 分支（由开发者 agent 按需创建，归 spec-0003）。\n- 不含任何 harness 演化逻辑、不跑 harness、不接 developer_agent（归 spec-0003）。\n- 不定义 harness_template 内容/布局本身（归 spec-0003，本任务只搬运）。\n- 不管理 Gitea 服务生命周期、不生成 token（归 T1）。"
    acceptance: "- 脚本在 Gitea 建出独立 harness 仓，默认分支 main 含 harness_template 全部内容（单条初始提交）。\n- 仓附 release 分支，指向初始 main。\n- 幂等：连跑两次退出码均 0，第二次不重复建仓、不强推覆盖、不报错。\n- 仓已存在且 main 已演化时，第二次运行不回退历史，仅确保 release 分支存在。\n- harness_template 缺失/为空时非零退出，不推空仓。\n- token 经 remote URL 注入，不落入 harness 仓内容。\n- 单测以 mock Gitea API + 临时 git 覆盖建仓/推送/建分支调用，不依赖真服务。"
---

# 0002 · Gitea 接入与基建

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

本组补齐 **a 段的真实后端与基建**：0001 用 Fake 把接口立了起来，本组把「桩」换成「真」——起一个本地 Gitea（issue 与 harness 仓的家），并实现 0001/T5 `IssueTracker` 接口的真后端 `GiteaTracker`。

与 0001 的接力关系：

```
0001：IssueTracker 接口 + FakeTracker（桩，仅供测试）
        └─► 0002/T2 GiteaTracker（真后端，运行时注入 run_session）
0002/T1 本地 Gitea（docker + sqlite，bootstrap 产出 URL/owner/repo/token）
        ├─► T2 GiteaTracker 读连接信息，打 /api/v1
        └─► T3 把 harness_template 推成独立 harness 仓（供 0003 开发者 agent 走真实分支/合并）
```

**T1** 是一切前置（没有 Gitea 就没有 issue 去向、也没有 harness 仓）；**T2** 让用户 agent 产的 issue 真正进 Gitea；**T3** 把 v0 种子变成可演化的 harness 仓。本组完成后，a 段即可脱离 Fake 真跑。

## Motivation

issue 与 harness 仓都需要落地于 Gitea，而在 0001 阶段两者都只存在于接口与 Fake 之中，尚无真实去处。首要缺口是一个可复现、低运维的本地 Gitea 实例（T1）：sqlite 单文件、单二进制，配合一条把「空服务」变成「可用工作区（有 token、有仓、有标签）」的幂等初始化路径——把初始化固化为脚本，避免手点 UI 带来的不可复现与配置漂移，幂等则是 CI 与多次本地启动能够安全重跑的前提。

有了 Gitea 之后，用户侧此前已用 IssueTracker 接口与 FakeTracker 解耦，缺的只是真实后端：T2 的 GiteaTracker 只做薄封装——Gitea 本身已负责发号、状态机、comment 存储，客户端只需把接口调用翻译为 HTTP 请求并解析响应，不在客户端重建任何状态，避免与远端产生双写漂移。

与此同时，CLAUDE.md 已将 harness 定为独立 git 仓、托管于 Gitea、走真实分支/合并；T3 负责「从种子到可用仓」的一次性初始化，是 dev 侧（spec-0003）launcher 与 developer_agent 的前置条件。把这一步脚本化保证可复现，幂等保证重跑（CI、重置后重建）安全。

## Guide-level explanation

本组三个任务依次搭出一条链路：T1 用 docker-compose（Gitea + sqlite）起一个本地服务，配一份 bootstrap 脚本完成建 admin、生成 access token、建工作仓、ensure 标签方案的一键初始化，最终产出连接信息文件 `backend/deploy/gitea/.env`（URL/owner/repo/token），作为下游任务唯一的配置入口。

T2 在此之上实现 GiteaTracker：spec-0001/T5 IssueTracker 接口的真实后端，是一个打 Gitea `/api/v1` 的薄 REST 客户端。运行时把它注入 run_session，用户 agent 产出的 issue 草稿就能真正提交到 Gitea 并拿到带号 IssueRef；对 run_session 而言它与 FakeTracker 行为等价、可互换，替换不影响上层逻辑。

T3 则把 `backend/harness_template/` 作为 v0 种子推送到 Gitea，建立一个独立的 harness 仓，供 dev 侧（spec-0003）开发者 agent 在其上走真实分支与合并；harness 自身的演化历史从此存在于该仓，不污染 AHE-Beta 本仓。三者共同完成后，a 段的 issue 落地与 harness 演化载体便都脱离 Fake，可以真实运行。

## Reference-level explanation

本组三个任务分别对应三块可独立测试的产物，彼此以文件与接口衔接：T1 产出本地 Gitea 服务与一份连接信息契约文件 `backend/deploy/gitea/.env`；T2 在此之上实现 GiteaTracker 客户端；T3 在此之上把 harness 种子推成独立仓。依赖方向为 `T1 → T2`、`T1 → T3`，T2 与 T3 互不依赖，可并行推进。

### 组件与职责

T1 由两个文件构成：`docker-compose.yml` 起单个 `gitea` 服务（`GITEA__database__DB_TYPE=sqlite3`），数据目录挂命名卷持久化，暴露 HTTP 端口（默认 3000）与可选 SSH 端口，端口由 .env 或 compose 内常量固定给定，禁止随机分配（T2/T3 需稳定 URL）；`bootstrap.sh` 是纯 shell 脚本，靠 `docker compose exec` 调 gitea CLI 加 `curl` 调 REST 完成初始化，不引入额外语言运行时依赖。

T2 的 GiteaTracker 是 spec-0001/T5 IssueTracker 接口的真实后端，构造签名为 `GiteaTracker(base_url: str, owner: str, repo: str, token: str)`；输入 IssueDraft(title/body/labels)、输出 IssueRef(number/url/state) 复用 spec-0001/T1 的定义，本任务不新增数据类；内部只维护一个 `_label_ids: dict[str, int]`（name→id 缓存），仅 ensure_labels 写入、create_issue 读取。

T3 的入口是 `backend/scripts/bootstrap_harness.py`，读取 T1 产出 .env 中的 {GITEA_URL, OWNER, TOKEN}；harness 仓名为固定常量，独立于 T1 的工作仓，避免 issue 仓与 harness 仓混用。

### 配置契约

T1 产出的 `backend/deploy/gitea/.env` 是 T1 与 T2/T3 之间唯一的配置面，KEY=VALUE 行格式，键集固定为四个：

| 键 | 含义 |
| --- | --- |
| GITEA_URL | Gitea 根 URL，无尾斜杠、无 `/api/v1` 后缀（如 `http://localhost:3000`） |
| OWNER | 工作仓 owner（admin 用户名） |
| REPO | 工作仓名 |
| TOKEN | 带 `write:issue,write:repository` scope 的 access token |

GiteaTracker(T2) 消费全部四键，bootstrap_harness(T3) 只消费其中 {GITEA_URL, OWNER, TOKEN}；本组其它任务不得依赖未列入的键，键名与语义不得在未同步 T2/T3 的情况下变更。

### 初始化与调用时序

T1 的 bootstrap 脚本共五步、每步均设计为幂等：① 就绪探测——轮询 `GET /api/v1/version` 直至 200 或超时，超时非零退出并打印诊断；② 建 admin——`gitea admin user create --admin --username --password --email`，已存在时 CLI 报错，脚本捕获视为成功；③ 生成 token——`gitea admin user generate-access-token --username <admin> --scopes write:issue,write:repository --raw`，token 仅在生成时可见故写入 .env，重跑若 token 名已存在则复用既有 .env、不重复生成；④ 建工作仓——`POST /api/v1/admin/users/{owner}/repos` 或 `/user/repos`(auto_init=true)，仓已存在(409)视为成功；⑤ ensure 标签——`GET /repos/{owner}/{repo}/labels` 取现有、缺失项 `POST` 建之，标签集固定为 {bug, feature} 且颜色固定。

T2 的四个方法映射到 Gitea `/api/v1` 端点（路径相对 `{base_url}/api/v1`）：`ensure_labels(names)` 先 `GET /repos/{owner}/{repo}/labels` 取现有 name→id，缺失项 `POST /repos/{owner}/{repo}/labels`(name + 默认 color) 建之并合并进缓存；`create_issue(draft)` 先确保 draft.labels 已在缓存中（未缓存则自动触发 ensure_labels，保证 issue 一次提交即带正确 label id、不依赖调用方先手动 ensure），再 `POST /repos/{owner}/{repo}/issues`（body={title, body, labels:[id...]}），从响应取 {number, html_url, state} 构造 IssueRef；`add_comment(number, body)` 对应 `POST /repos/{owner}/{repo}/issues/{number}/comments`；`set_state(number, state, reason)` 对应 `PATCH /repos/{owner}/{repo}/issues/{number}`(state ∈ {open, closed})，reason 若给定因 Gitea PATCH 不收该字段而追加为一条 comment。

T3 的初始化同样是三步幂等流程：① 建仓——`POST /api/v1/user/repos`(name=harness, auto_init=false, private 可选)，已存在(409)视为成功；② 推种子——在临时工作目录初始化 git 仓、复制本仓 `backend/harness_template/` 全部内容、`git add` 加单条初始提交、以 `https://{token}@{host}/{owner}/{repo}.git` 为 remote push 到 main；③ 建 release 分支——经 API `POST /repos/{owner}/{repo}/branches`(new_branch_name=release, old_branch_name=main) 或等价 push 一条 release ref，分支已存在视为成功。

### 边界与错误处理

三任务遵循同一原则——失败不静默、不伪造成功，已完成的初始化保持幂等：

T1：服务不可达/就绪超时时①步非零退出并提示检查 compose 状态，不进行后续步骤；admin/仓/标签已存在分别按「捕获 CLI 错误」「409」「按名去重」处理为幂等成功，不报错中断；token 生成失败或 scope 不足非零退出，脚本不静默写入空 token，避免 T2 拿到无效凭证后才暴露；.env 已存在时默认复用其中 TOKEN（不可二次读取），其余键按脚本探测结果对齐，并提供显式重置入口（删卷 + 删 .env）。

T2：Gitea 不可达（连接异常/超时）时 requests 异常原样上抛，GiteaTracker 不吞、由调用方处理（run_session 记录失败、不伪造 IssueRef）；token 失效/权限不足对应响应 401/403，客户端把所有非 2xx 响应统一转为带状态码与端点的显式异常，不静默返回空 IssueRef；标签竞态（并发下重复建）时 POST label 返回 409/422 即回退为 GET 重新读取该 name 的 id，保证 ensure_labels 幂等；响应缺字段时（number/html_url/state 任一缺失）即抛解析异常，避免下游拿到半成品回执；「重复建 issue」不在本客户端语义内——去重语义不存在于 IssueTracker 契约，每次 create_issue 即新建一条，防重复由用户侧产出逻辑(spec-0001/T3)负责，客户端保持无状态翻译。

T3：Gitea 不可达/token 失效时建仓 API 抛 4xx/连接异常，脚本非零退出并打印端点与状态码，不进行后续 push；仓已存在但内容已演化时默认不强推覆盖——若远端 main 已有额外提交、push 非 fast-forward，脚本报告「仓已初始化」并跳过推种子，仅确保 release 分支存在，以保护开发者 agent 已产生的演化历史；建仓 409、push 已最新、release 已存在三种情况均视为幂等成功（退出码 0）；harness_template 缺失/为空时前置校验拦截，非零退出，避免推空仓。

### 关键决策

- T1：数据库选 sqlite + 单服务——最小运维面，契合自用单实例（奥卡姆）；token 生成用 CLI `generate-access-token --raw` 而非 Web UI 手点——可脚本化、可幂等、输出干净便于写 .env；端口固定而非随机——T2/T3 的连接信息契约要求稳定 URL；标签集固定为 {bug, feature}，是驱动 dev 侧分流的最小集（bug→release 快修，feature→feature 分支），不预置更多标签。
- T2：客户端用薄 requests 而非 py-gitea SDK 或自研异步客户端——仅需 4 个端点，零额外重依赖、请求形状完全可控、便于 mock（奥卡姆）；label 用 name→id 缓存而非每次现查——Gitea 建 issue 收 label id 而非名，缓存避免每局重复 GET，也不把 Gitea 细节泄露到用户侧；错误处理统一抛异常而非返回可空回执——鉴权失败/不可达是不可恢复的环境问题，需在调用点显式暴露；set_state 的 reason 落为 comment——Gitea PATCH 不收该字段，落 comment 保留可追溯的关闭理由。
- T3：seed 推送用 git push 而非 API 逐文件上传或 tar 上传——保留真实 git 历史与单条初始提交，契合开发者 agent「走真实分支/合并」；重跑策略取「存在即跳过」而非强推覆盖——保护演化历史、保证幂等；harness 仓与 issue 工作仓保持独立——关注点分离、权限与历史互不干扰；配置复用 T1 的 .env——OWNER/TOKEN 单一来源，不重复造配置面。

### 接口

T1：产出文件契约 `backend/deploy/gitea/.env`（四键见上）；脚本入口 `bash backend/deploy/gitea/bootstrap.sh`（幂等），服务入口 `docker compose -f backend/deploy/gitea/docker-compose.yml up -d`（宿主 HTTP/SSH 仅绑定 loopback；bootstrap 必须显式传入 `GITEA_ADMIN_PASS`，以 umask 077 写凭证）；消费方为 GiteaTracker(T2) 与 bootstrap_harness(T3)。

T2：类 `GiteaTracker(base_url: str, owner: str, repo: str, token: str)`，实现 spec-0001/T5 `IssueTracker` 协议：
- `ensure_labels(names: list[str]) -> None`
- `create_issue(draft: IssueDraft) -> IssueRef`
- `add_comment(number: int, body: str) -> None`
- `set_state(number: int, state: str, reason: str | None) -> None`
所有方法在非 2xx 响应时抛出带状态码与端点的异常；不返回 None 掩盖失败。

T3：`python backend/scripts/bootstrap_harness.py`——输入 `backend/deploy/gitea/.env`(GITEA_URL/OWNER/TOKEN) + 本仓 `backend/harness_template/` 目录；行为是在 Gitea 建出 harness 仓，默认分支 main 含 harness_template 内容，附 release 分支；退出码成功(含幂等重跑)为 0，连接/鉴权失败或 harness_template 缺失为非 0；副作用边界仅写 Gitea 远端与临时工作目录，不修改本仓、不修改 .env。

### 测试

T1 产物为基建脚本，以 README 记录的手动/CI 验证为主：就绪与建 issue（compose up → bootstrap → 用产出 token curl 建一条 issue 成功 201）；幂等（连跑两次 bootstrap，第二次退出码 0、不新增重复 admin/仓/标签）；失败路径（Gitea 未起时跑 bootstrap，①步就绪超时后非零退出并打印诊断，不写入半成品 .env）；鉴权 scope（用产出 token 调超出 scope 的端点应被拒 403，证明 token scope 收敛到 write:issue,write:repository）；契约校验（.env 恰含四键，GITEA_URL 无尾斜杠/无 /api/v1 后缀）。细粒度自动化测试随 T2/T3 的 mock 覆盖，本任务不重复构造 Gitea mock。

T2 单测全程 mock HTTP（responses/respx）：create_issue 发对 URL、`Authorization: token` 头与 body(title/body/labels=[id])，并从响应解析出 IssueRef(number/url/state)；ensure_labels 缺失则 POST 建、已存在则复用 id，连续两次调用不重复 POST（幂等）；create_issue 遇 draft.labels 含未缓存名时自动触发 ensure_labels 后再建 issue（一次成功带正确 id）；add_comment/set_state 命中对应端点与方法(POST/PATCH)，set_state 带 reason 时额外发一条 comment；失败路径覆盖 mock 返回 401（token 失效）与 404（仓不存在）时抛带状态码的异常，mock 连接异常（不可达）时异常上抛不被吞；标签竞态覆盖 mock POST label 返回 409 时回退 GET 取既有 id，ensure_labels 仍成功。

T3 单测 mock Gitea API + 临时 git：建仓调用命中 `POST /user/repos`、参数含 harness 仓名，harness_template 内容进单条初始提交并 push 到 main；release 分支经 API/ref 建出，指向初始 main；幂等覆盖建仓 mock 返回 409、push 已最新、release 已存在三种情况下脚本退出码均 0、不重复建；保护历史覆盖 mock 远端 main 已有额外提交（非 fast-forward）时脚本不 `--force`，报告已初始化并仅确保 release 分支；失败路径覆盖 mock 建仓返回 401（token 失效）/连接异常（Gitea 不可达）时脚本非零退出、不进行 push；前置校验覆盖本仓 harness_template 缺失/为空时脚本非零退出，不发起任何远端写。

### 文件归属与依赖 DAG

| Task | 文件（单一 writer 所有权） |
| --- | --- |
| T1 | `backend/deploy/gitea/docker-compose.yml`、`backend/deploy/README.md`、`backend/deploy/gitea/bootstrap.sh` |
| T2 | `backend/ahe_beta/tracker/gitea.py`、`backend/tests/tracker/test_gitea.py` |
| T3 | `backend/scripts/bootstrap_harness.py`、`backend/tests/test_bootstrap_harness.py` |

依赖 DAG：`T1 → T2`，`T1 → T3`（T2 与 T3 互不依赖，可并行）。

## Drawbacks

<!-- 待填 -->

## Rationale and alternatives

T1 在数据库、token 生成方式、端口分配、连接信息载体四处做了选择：数据库选 sqlite 而非 postgres/mysql——单文件、随 Gitea 进程零额外服务，运维面最小（奥卡姆），代价是并发写能力弱、不利横向扩展，自用单实例场景可接受，高并发写场景再换 postgres；token 生成选 CLI `generate-access-token --raw` 而非 Web UI 手点或 API 用户名密码换——可脚本化、可幂等、输出干净便于写 .env，UI 手点不可复现，API 换 token 需先有凭证、引入鸡生蛋问题；端口选固定分配而非随机——T2/T3 的连接信息契约要求稳定 URL，随机端口需额外回写发现机制、增加复杂度；连接信息选 .env 文件而非环境变量或配置中心——落盘可被多个消费方(T2/T3)读取、可 gitignore、零依赖，纯环境变量在多进程/多次启动间不持久，配置中心对单实例是过度设计。

T2 在客户端形态、缓存策略、错误处理、reason 落地四处做了选择：客户端选薄 requests 而非 py-gitea SDK 或自研异步客户端——仅需 4 个端点，零额外重依赖、请求形状完全可控、便于 mock（奥卡姆），SDK 引入版本耦合与多余表面，异步对单局会话无收益；label 选 name→id 缓存而非每次现查或要求调用方传 id——Gitea 建 issue 收 label id 而非名，缓存避免每局重复 GET，现查浪费请求，要求调用方传 id 会把 Gitea 细节泄露到用户侧；错误处理选统一抛异常而非返回 Result/可空回执——鉴权失败/不可达是不可恢复的环境问题，显式抛出使失败在调用点暴露，可空回执易被下游忽略导致静默丢 issue；set_state 的 reason 选落为 comment 而非丢弃或自定义字段——Gitea PATCH issue 不收 reason 字段，以 comment 保留关闭理由可追溯，丢弃会损失信息，自定义字段 Gitea 不支持。

T3 在 seed 推送方式、重跑策略、仓拆分、配置来源四处做了选择：seed 推送选 git push 而非 API 逐文件上传或 tar 上传——保留真实 git 历史与提交对象，契合开发者 agent「走真实分支/合并」，逐文件上传无统一提交、丢历史语义，tar 上传 Gitea 无对应原子接口；重跑策略选「存在即跳过」而非强推覆盖或报错退出——保护演化历史、保证幂等，强推会丢开发者 agent 产出，报错退出会让 CI/重置流程脆弱；harness 仓选与 issue 工作仓独立而非同仓——issue 与 harness 演化关注点分离、权限与历史互不干扰，同仓会让 issue 流与代码演化混杂；配置选复用 T1 的 .env 而非脚本自带参数或独立配置——OWNER/TOKEN 单一来源、与 T2 一致，不重复造配置面。

## Prior art

三个任务共享 Gitea 官方文档体系：T1 依据 Docker 安装指南（https://docs.gitea.com/installation/install-with-docker）与命令行文档（含 admin user create / generate-access-token，https://docs.gitea.com/administration/command-line）落地本地服务与初始化脚本；T2、T3 分别依据 Gitea API 文档中 issues/labels/comments 端点与 repos/branches 端点（均见 https://docs.gitea.com/api/）实现客户端调用与仓初始化。CLAUDE.md 架构中「状态去向：issue → Gitea」「被进化对象：harness 作为可启动程序」「dev 侧走真实分支/合并」三处约定分别是 T1、T3 的直接依据。T2 的接口与数据结构定义承接自 spec-0001（IssueTracker/FakeTracker 见 T5，IssueDraft/IssueRef 见 T1），T3 的 harness_template 布局、launcher 与开发者 agent 承接自 spec-0003；两者的 Gitea 连接信息均来自本组 T1 产出的 `backend/deploy/gitea/.env`。

## Unresolved questions

<!-- 待填 -->

## Future possibilities

<!-- 待填 -->

