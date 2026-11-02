# 部署资源

本目录保存实验基础设施的 Compose 模板、镜像构建文件和维护脚本。运行实验时，使用统一入口 `backend/scripts/experiment.py`；不需要先手动启动这里的 Gitea 服务。完整步骤见[快速开始](../../docs/QUICKSTART.zh-CN.md)。本文中的命令均从仓库根目录执行。

## 目录用途

| 目录 | 用途 |
| --- | --- |
| [`experiment/`](experiment/) | local 后端使用的基础设施模板。每个 run 独立创建 Gitea、网络、存储和出口代理；启用本地工程 CI 时，由后端补充专属 runner 和 CI 服务。 |
| [`gitea/`](gitea/) | 手动联调使用的单实例 Gitea、Actions runner 和出口代理。使用固定容器名、网络名和端口，适合维护，不用于并行实验。 |
| [`vigil/`](vigil/) | OpenAgents 交付环境的镜像构建文件、容器入口和证据读取能力记录。统一入口根据冻结的源码与运行配方准备交付环境。 |
| [`swebench-seed/`](swebench-seed/) | SWE-bench 任务工作区的存储镜像和运行环境配方；不是初始 Harness 源码。构建脚本需要已准备的 `workspace/` 和 `build-state.json`。 |

独立 Harness 基准评测使用仓库根目录的 `evaluation.yaml`，操作见[评测指南](../../evaluation/docs/harbor.zh-CN.md)。

## 实验部署

local 后端自动准备本地 Gitea，生成账号和凭证，并保存到该 run 的私有 `secrets/` 目录。需要访问网页时，从运行记录读取实际地址；端口由实验管理，不固定为 3000。

E2B 后端使用自己的 Gitea.com 账户托管仓库，不启动本地 Gitea。模型凭证、`E2B_API_KEY` 和 `GITEA_TOKEN` 通过实验凭证文件提供。配置字段见[实验配置](../../docs/CONFIGURATION.zh-CN.md)。

本地工程 CI 是可选项，通过 `runtime.local.ci_enabled` 开启。统一入口为每个 run 准备并核验独立的 runner；它不复用下面手动部署的共享 runner。具体配置见[本地工程 CI](../../docs/CONFIGURATION.zh-CN.md#本地工程-ci)。

## 模型出口与证据访问

local 实验的交付环境通过出口代理访问模型服务。后端根据配置中的模型端点生成目标主机和端口规则，无需修改仓库中的静态代理模板。

手动部署使用的静态模板默认允许 Anthropic 和 Claude 服务。使用其他模型网关时，需要显式修改对应的出口规则。自建 Gitea 使用 gzip 证据附件；Gitea.com 使用 ZIP 附件及其 R2 下载地址，交付环境必须支持对应的读取协议，统一入口会在模型调用前预检实际运行环境。

手动部署需要访问 Gitea.com 证据时，在启动 Compose 前设置：

```bash
export AHE_BETA_EGRESS_CONFIG=./egress-gitea-com.conf
```

该配置在基础出口规则上增加 `gitea.com:443` 和匹配规则的 R2 主机访问权限，不会放开任意外网地址。

## 手动启动 Gitea

以下步骤仅用于基础设施联调。需要 Docker Engine、Compose、Bash 和 curl。服务使用 SQLite 和命名数据卷，HTTP 与 SSH 端口只绑定本机；这份模板不包含 TLS 或高可用部署配置。

先启动 Gitea 和出口代理，再初始化账号、仓库及 runner：

```bash
export GITEA_ADMIN_USER=aheadmin
export GITEA_ADMIN_EMAIL=aheadmin@example.com
read -rs -p "Gitea admin password: " GITEA_ADMIN_PASS
printf '\n'
export GITEA_ADMIN_PASS

(
  cd backend/deploy/gitea
  docker compose up -d gitea egress-proxy
  bash ./bootstrap.sh
)
unset GITEA_ADMIN_PASS
```

Gitea 地址为 `http://localhost:3000`，SSH 端口为 `2222`。初始化脚本等待服务就绪，创建管理员、私有工作仓库和标签，生成访问 Token，并在取得 runner 注册 Token 后启动 Actions runner。

脚本把连接信息写入 `backend/deploy/gitea/.env`，文件权限为 `0600`，且已被 Git 忽略：

| 字段 | 含义 |
| --- | --- |
| `GITEA_URL` | 服务根地址，不带尾斜杠或 `/api/v1` 后缀 |
| `OWNER` | 初始化的管理员用户名 |
| `REPO` | 工作仓库名，默认 `ahe-beta-work` |
| `TOKEN` | 包含 `write:user`、`write:issue` 和 `write:repository` 权限的访问 Token |
| `RUNNER_TOKEN` | Actions runner 注册 Token |

重复执行时，脚本保留已有账号和仓库，复用 `.env` 中的 Token；不会更新已有账号的密码。可通过 `GITEA_WORK_REPO` 和 `GITEA_TOKEN_NAME` 设置仓库名及 Token 名称。

### 检查连接

服务版本接口返回 HTTP 200 表示 Gitea 已就绪：

```bash
curl -fsS http://localhost:3000/api/v1/version
```

需要检查仓库写入权限时，可以创建一条测试 Issue：

```bash
(
  source backend/deploy/gitea/.env
  curl --fail-with-body -sS \
    -H "Authorization: token $TOKEN" \
    -H 'Content-Type: application/json' \
    -X POST "$GITEA_URL/api/v1/repos/$OWNER/$REPO/issues" \
    -d '{"title":"Connection check","body":"Manual deployment verification."}'
)
```

### 停止与清理

停止服务并保留数据：

```bash
docker compose -f backend/deploy/gitea/docker-compose.yml down
```

如果需要重新初始化，下面的命令会同时删除 Gitea 与 runner 的数据卷，包括账号、仓库、Issue 和 runner 注册信息：

```bash
docker compose -f backend/deploy/gitea/docker-compose.yml down -v
rm -f backend/deploy/gitea/.env
```

这些命令只管理手动部署的单实例。统一入口创建的实验应通过 `experiment.py` 的 `stop` 和 `destroy` 命令管理，详见[快速开始](../../docs/QUICKSTART.zh-CN.md)。
