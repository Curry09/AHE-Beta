"""真实端到端跑闭环（需求面 round-based + 交付面常驻 vigil）。

接线：用户侧 = spec-0005 控制信封 sim（内层 tool-use AgenticPersonaClient，LLM 由
     ApiPersonaClient.complete 供给，模型走 backend/.env 的 USER_LLM_*）；
     交付面 = OpenAgents vigil（Spec-0032：独立 CLI 常驻子进程，本进程托管生命周期）——
     Owner 准入打 `openagents` 交接令牌，vigil 发现→盖 ready→分支/PR→评审→合并进 main；
     issue/PR 全在真 Gitea（backend/deploy/gitea/.env），harness 代码承载于本地 git 仓 + Gitea origin。
本地规模：persona 从 distill 卡库(persona_library.json)注入、场景从种子卡库(seeds.json)经
     distill seed_adapter 注入（held-out 判分制品在注入边界剥离）；跑前复位到最初状态。
Spec-0007/0032：纯 trunk（单 main）语义不变；每局解析 main HEAD SHA 作会话级快照；回灌 = live main
     纯观测游标（推进者现在是 vigil 的 merge）。vK tag 体系退役（观测锚点 = merge commit）。

前置：
  1) backend/.env 有三组独立配置 {USER,DESIGNER,HARNESS}_LLM_{MODEL,BASE_URL,API_KEY}
     （前二=编排角色，HARNESS=被进化的产品本体，run.py 据其导出 harness 子进程读的 plain LLM_*）
  2) Gitea 已起并 bootstrap，backend/deploy/gitea/.env 有 GITEA_URL/OWNER/REPO/TOKEN
  3) 交付面 CLI：`openagents` 在 PATH（uv tool install --from <OpenAgents 仓>@<pin> openagents，
     含 forge/Gitea driver 的版本）+ 已登录的 `claude` CLI（vigil 的 coding 后端）。
     平台注记：vigil 依赖 fcntl.flock，交付面仅 Linux/macOS 可跑（Windows 本地只跑单测）。
运行：./run.sh  （或直接 PYTHONPATH=backend .venv/bin/python backend/run.py）
  persona / 种子卡库两个「给定输入」经 CLI 参数注入，默认指向 backend/persona_library.json
  与 backend/seeds.json：
    ./run.sh --persona-library <path> --seed-cards <path>
  或经 run.sh 的 PERSONA_LIBRARY / SEED_CARDS 环境变量覆盖。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent  # backend/
DATA = ROOT / "data"
# dev/designer 的 sandbox 工作目录 = harness 仓。把它下沉到一个**只含它自己**的独立父目录
# （data/harness_sandbox/harness_repo），使 trace 目录（data/sessions 体感+会话、data/harness_runs
# harness 运行副本）不再是它的 `../` 同级——`../sessions/*.json`、`../harness_runs/**` 这类相对路径
# 直接够不着。堵住「dev/designer 回看任务轨迹 → 把该任务专属产物（某库 API/某类文件/预期输出）带进
# harness」的过拟合泄漏（与提交边界闸同源之患；见 agent_defs/designer/systemprompt.md 硬禁区）。
# 注：bash 仍可走绝对路径，但相对导航（ls ..）已看不到 trace，堵住了唯一的现实发现路径。
_SANDBOX_ROOT = DATA / "harness_sandbox"
HARNESS_REPO = _SANDBOX_ROOT / "harness_repo"
# 两个「给定输入」的默认卡库路径；均可经 CLI 参数（见 _parse_args）/ run.sh 覆盖注入。
DEFAULT_PERSONA_LIBRARY = (
    ROOT / "persona_library.json"
)  # distill 合并库（sr-* + gh-*）；分库见 persona_library_{selfreport,github}.json
DEFAULT_SEED_CARDS = ROOT / "seeds.json"  # distill 种子卡库（原始卡；经 seed_adapter 注入）
GITEA_ENV_FILE = ROOT / "deploy" / "gitea" / ".env"

# 每轮跑几个 persona（None=用满卡库全部）。默认由 roster（编制）的用户数决定，与前端房间容量一致；
# 仍可设为具体整数手动覆盖。用户会话数≈persona 数，耗时按此线性放大，按需下调。
PERSONA_LIMIT: int | None = None

# 闭环轮数：run.json 运行态与看板「按轮分组」以此为总轮数。
# 默认 2（截图 demo 用），可用环境变量 TOTAL_ROUNDS 覆盖（如端到端跑 5 轮）。
TOTAL_ROUNDS = int(os.environ.get("TOTAL_ROUNDS", "2") or "2")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """解析 CLI 参数：persona 卡库 / 种子卡库两个「给定输入」文件路径（其余默认）。"""
    parser = argparse.ArgumentParser(description="真实端到端跑一轮闭环（a→b→c）")
    parser.add_argument(
        "--persona-library",
        type=Path,
        default=DEFAULT_PERSONA_LIBRARY,
        help="persona distill 卡库 JSON（默认 backend/persona_library.json）",
    )
    parser.add_argument(
        "--seed-cards",
        type=Path,
        default=DEFAULT_SEED_CARDS,
        help="种子卡库 JSON（原始卡，经 seed_adapter 注入；默认 backend/seeds.json）",
    )
    return parser.parse_args(argv)


def _load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"')
    return out


def _apply_env_defaults(values: dict[str, str]) -> None:
    """Apply repository defaults without overriding explicit process configuration."""
    for key, value in values.items():
        os.environ.setdefault(key, value)


def _load_seeds(path: Path) -> list:
    """从种子卡库(seeds.json)经 distill seed_adapter 注入为 SeedScenario 列表。

    与 persona 侧对称：SeedLibrary 读原始卡 → card_to_seed 逐卡注入（契约校验 + held-out
    判分制品 oracle/test_cmd/gates 在注入边界剥离，绝不进 SeedScenario / 训练环）。
    """
    from auto_designer.distill.seed_adapter import card_to_seed
    from auto_designer.distill.seed_library import SeedLibrary

    return [card_to_seed(record) for record in SeedLibrary(path).load()]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=seed@x", "-c", "user.name=seed", *args],
        check=True,
        capture_output=True,
    )


def _gitea_remote_url(gitea: dict[str, str]) -> str:
    """构造带 token 的 Gitea git 远程地址：http://OWNER:TOKEN@host/OWNER/REPO.git。"""
    from urllib.parse import urlparse, urlunparse

    u = urlparse(gitea["GITEA_URL"])
    netloc = f"{gitea['OWNER']}:{gitea['TOKEN']}@{u.netloc}"
    return urlunparse((u.scheme, netloc, f"/{gitea['OWNER']}/{gitea['REPO']}.git", "", "", ""))


def _isolate_git_credentials() -> None:
    """进程级 git 凭证隔离（Spec-0021/T2）：dev agent 逃逸后不得推到 GitHub。

    实测逃逸链：dev agent 用 python heredoc 隧道绕过 workspace-jail 的路径扫描、`os.chdir` 到编排仓
    并 `git push`。凭证泄漏有**多条静默信道**，单关一条不够：
    - **ssh 传输**（GitHub `git@…`）：`GIT_SSH_COMMAND=false` 让 ssh 调用失败。
    - **终端交互提示**：`GIT_TERMINAL_PROMPT=0`。
    - **askpass 静默信道**：`GIT_ASKPASS`/`SSH_ASKPASS` 指向一个能直接吐凭证的程序（实测 VS Code +
      WSL 环境注入 `GIT_ASKPASS`，git 走 HTTPS 时静默拿到 GitHub token——`GIT_TERMINAL_PROMPT=0`
      **管不到它**）。连同 VS Code 的 `VSCODE_GIT_ASKPASS_*`/IPC 一并清除。
    - **credential.helper 静默信道**：store/manager/keychain 也会静默交出凭证。用空值经 GIT_CONFIG_*
      注入重置 helper 列表（追加而非覆盖既有注入）——git ≥2.31 支持。

    对合法流程无影响：dev/harness 推 Gitea 走 `http://OWNER:TOKEN@host/…`（凭证在 URL，不经
    askpass/helper），本地无传输 git 操作也不涉及凭证。`GIT_SSH_COMMAND` 用 setdefault 留运维覆盖余地。
    """
    os.environ.setdefault("GIT_SSH_COMMAND", "false")
    os.environ["GIT_TERMINAL_PROMPT"] = "0"
    for _k in (
        "GIT_ASKPASS",
        "SSH_ASKPASS",
        "SSH_AUTH_SOCK",
        "VSCODE_GIT_ASKPASS_NODE",
        "VSCODE_GIT_ASKPASS_MAIN",
        "VSCODE_GIT_ASKPASS_EXTRA_ARGS",
        "VSCODE_GIT_IPC_HANDLE",
    ):
        os.environ.pop(_k, None)
    try:
        _n = int(os.environ.get("GIT_CONFIG_COUNT", "0") or "0")
    except ValueError:
        _n = 0
    os.environ["GIT_CONFIG_COUNT"] = str(_n + 1)
    os.environ[f"GIT_CONFIG_KEY_{_n}"] = "credential.helper"
    os.environ[f"GIT_CONFIG_VALUE_{_n}"] = ""


def _set_gitea_remote(repo: Path, gitea: dict[str, str]) -> None:
    """仅给本地 harness 仓配好 Gitea origin（带 token）。推送由开发者 agent 用 git 工具自己做，不在此 push。"""
    url = _gitea_remote_url(gitea)
    remotes = subprocess.run(
        ["git", "-C", str(repo), "remote"], capture_output=True, text=True
    ).stdout.split()
    if "origin" in remotes:
        _git(repo, "remote", "set-url", "origin", url)
    else:
        _git(repo, "remote", "add", "origin", url)


def _seed_harness_repo() -> Path:
    """从 harness_template 种一个本地 git 仓：仅 main（Spec-0007/T4：纯 trunk，不再建 release）。"""
    if HARNESS_REPO.exists():
        shutil.rmtree(HARNESS_REPO)
    HARNESS_REPO.mkdir(parents=True)
    archive_raw = os.environ.get("AUTO_DESIGNER_HARNESS_ARCHIVE", "").strip()
    if archive_raw:
        archive = Path(archive_raw).expanduser().resolve()
        if not archive.is_file():
            raise SystemExit(f"冻结 Harness archive 不存在：{archive}")
        try:
            with tarfile.open(archive, "r:gz") as bundle:
                bundle.extractall(HARNESS_REPO, filter="data")
        except (tarfile.TarError, OSError) as exc:
            raise SystemExit(f"冻结 Harness archive 解包失败：{archive}: {exc}") from exc
    else:
        template = ROOT / "harness_template"
        for item in template.iterdir():
            dest = HARNESS_REPO / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
    subprocess.run(
        ["git", "init", "-b", "main", str(HARNESS_REPO)], check=True, capture_output=True
    )
    # 清掉模板复制带来的字节码缓存、写 .gitignore，让 v0 seed 只含 harness 制品。
    # Spec-0032/T5：.openagents/ 是 vigil 的本地运行态（队列 db/claims/配置），随 rmtree 每 run 归零，
    # 且永不入库。
    from auto_designer.dev.harness_boundary import install_pre_commit  # noqa: PLC0415

    for pyc in HARNESS_REPO.rglob("__pycache__"):
        shutil.rmtree(pyc, ignore_errors=True)
    (HARNESS_REPO / ".gitignore").write_text(
        "__pycache__/\n*.pyc\n.openagents/\n", encoding="utf-8"
    )
    _git(HARNESS_REPO, "add", ".")
    _git(HARNESS_REPO, "commit", "-m", "seed: harness v0")
    # 提交边界硬闸：装 pre-commit 钩子。容器围堵后改为拒绝清单（密钥 / .openagents），不再用顶层
    # 白名单锁死产品形状（docs/specs、结构性演进要放行）。git worktree 共享 hooks。
    # 钩子装在 seed 提交之后。服务端兜底见 smoke.yml 的边界检查步（--no-verify 也绕不开）。
    install_pre_commit(HARNESS_REPO)
    return HARNESS_REPO


def _remote_tag_refs(ls_output: str) -> list[str]:
    """`git ls-remote --tags` 输出 → 可删除的真 tag ref 列表。

    Spec-0032 实证修复#2：附注 tag 会输出两行——`refs/tags/v1` 与 peeled 行 `refs/tags/v1^{}`；
    后者是解引用展示、不是真 ref，`push origin :refs/tags/v1^{}` 会以 128 崩掉复位流程，须跳过。
    """
    refs: list[str] = []
    for line in ls_output.splitlines():
        ref = line.split("\t")[-1]
        if ref.startswith("refs/tags/") and not ref.endswith("^{}"):
            refs.append(ref)
    return refs


def _reset_to_initial(repo: Path, tracker) -> None:
    """跑测试前复位到最初状态：Gitea harness 仓回 v0 + 关闭遗留 issue + 清空看板数据。

    - Gitea: 强推本地 v0 seed 到 origin/main、删除所有远端 vK tag —— harness 回到 v0 起点
      (dev agent 在同一本地仓工作、push 同一 origin，故此处强推与其后续推进 fast-forward 兼容)。
    - issue: 关闭所有遗留 open issue (issue 编号/历史无法经 API 抹除，仅复位 open 集)。
    - 看板: 清空 data/live/ 投影。Spec-0049/T4：不得删除 role_runs（含其中 sessions）；
      会话已迁入 ROLE_RUNS_DIR/sessions，也不再按共享 DATA/sessions/*.json 抹盘。
    """
    _git(repo, "push", "-f", "origin", "main")  # 远端 main 覆盖回 v0 seed
    ls = subprocess.run(
        ["git", "-C", str(repo), "ls-remote", "--tags", "origin"],
        capture_output=True,
        text=True,
    ).stdout
    for ref in _remote_tag_refs(ls):
        _git(repo, "push", "origin", f":{ref}")  # 删远端 tag（legacy vK 清扫）
    for issue in tracker.list_open_issues():
        try:
            tracker.set_state(issue.number, "closed", "reset to initial before clean run")
        except Exception:  # noqa: BLE001  关 issue 失败不阻塞复位
            pass
    from auto_designer.loop.live import clear_live  # noqa: PLC0415  与 main() 同风格延迟导入

    clear_live(data_dir=DATA)


# Spec-0032/T5：交付面 stages 定稿（写进 harness 仓 .openagents/openagents.yml 的单一出处）。
# Spec-0040/T1：rfc 从 skip 改为 agent——solve 先 drafter 落 docs/specs，再 implement
# （spec CLI 在 vigil 镜像内，不进 harness 仓）。triage=skip：准入已由 Owner 完成；
# ci 缺省 skip、经 VIGIL_CI_STAGE=agent 开启——vigil 判定表「零 check=永等 CI」，须先验证
# act_runner 真在跑再开 ci 闸，否则全部票卡到看门狗；e2e=skip 二期；
# review/merge=agent：工程质量闸全自动（review 在，不触 OpenAgents「不许零闸」守卫）。
_VIGIL_STAGES: dict[str, str] = {
    "triage": "skip",
    "rfc": "agent",
    "conflict": "agent",
    "ci": "skip",  # write_openagents_config 按 VIGIL_CI_STAGE 覆盖
    "e2e": "skip",
    "review": "agent",
    "merge": "agent",
}
# vigil 轮询间隔（秒）：比 OpenAgents 默认 60s 更紧凑——本地 Gitea 无速率压力，缩短准入→领活时延。
_VIGIL_INTERVAL = 30


def install_role_runs(*, data_root: Path) -> Path:
    """Nail AUTO_DESIGNER_RUN_ID / ROLE_RUNS_DIR / usage path for this process.

    Spec-0049/T4：一次闭环进程一份切片；看板 data/sessions 只是指向当前 sessions 的别名。
    """
    run_id = os.environ.get("AUTO_DESIGNER_RUN_ID", "").strip() or uuid.uuid4().hex
    os.environ["AUTO_DESIGNER_RUN_ID"] = run_id
    root = data_root / "role_runs" / run_id
    (root / "demand").mkdir(parents=True, exist_ok=True)
    (root / "delivery").mkdir(parents=True, exist_ok=True)
    (root / "sessions").mkdir(parents=True, exist_ok=True)
    os.environ["ROLE_RUNS_DIR"] = str(root)
    os.environ["AUTO_DESIGNER_USAGE_PATH"] = str(root / "usage.jsonl")
    _alias_current_sessions(data_root=data_root, sessions_root=root / "sessions")
    return root


def experiment_run_mode() -> str:
    """Return the explicit lifecycle mode used by recoverable experiment runs."""
    mode = os.environ.get("AUTO_DESIGNER_RUN_MODE", "fresh").strip().lower() or "fresh"
    if mode not in {"fresh", "resume"}:
        raise SystemExit(f"AUTO_DESIGNER_RUN_MODE 必须为 fresh 或 resume：{mode!r}")
    return mode


def load_recovery_store(*, mode: str):
    """Create/open the shared recovery ledger when an experiment identity is present."""
    root_raw = os.environ.get("AUTO_DESIGNER_RECOVERY_ROOT", "").strip()
    identity_names = {
        "experiment_id": "AUTO_DESIGNER_EXPERIMENT_ID",
        "run_id": "AUTO_DESIGNER_RUN_ID",
        "config_hash": "AUTO_DESIGNER_CONFIG_HASH",
        "controller_sha": "AUTO_DESIGNER_CONTROLLER_SHA",
        "plan_hash": "AUTO_DESIGNER_PLAN_HASH",
    }
    values = {field: os.environ.get(name, "").strip() for field, name in identity_names.items()}
    configured = bool(root_raw or any(values.values()))
    if not configured:
        return None
    missing = [name for field, name in identity_names.items() if not values[field]]
    if not root_raw:
        missing.append("AUTO_DESIGNER_RECOVERY_ROOT")
    if missing:
        raise SystemExit("恢复身份环境变量不完整：" + ", ".join(missing))
    from auto_designer.loop.recovery import RecoveryIdentity, RecoveryStore  # noqa: PLC0415

    identity = RecoveryIdentity(**values)
    root = Path(root_raw).expanduser().resolve()
    if mode == "fresh":
        return RecoveryStore.initialize(root=root, identity=identity)
    return RecoveryStore.open(root=root, identity=identity)


def existing_harness_repo() -> Path:
    """Return the preserved harness repo required by resume without mutating it."""
    if not (HARNESS_REPO / ".git").is_dir():
        raise SystemExit(f"resume 缺少已初始化 harness 仓：{HARNESS_REPO}")
    return HARNESS_REPO


def _alias_current_sessions(*, data_root: Path, sessions_root: Path) -> None:
    """Point data/sessions at this run's sessions without deleting prior role_runs."""
    alias = data_root / "sessions"
    sessions_root.mkdir(parents=True, exist_ok=True)
    try:
        if alias.is_symlink() or alias.is_file():
            alias.unlink()
        elif alias.is_dir():
            leftover = data_root / "sessions_pre_0049"
            if not leftover.exists():
                alias.rename(leftover)
            else:
                return
        alias.symlink_to(sessions_root, target_is_directory=True)
    except OSError:
        return


def current_role_runs_dir() -> Path | None:
    raw = os.environ.get("ROLE_RUNS_DIR", "").strip()
    return Path(raw) if raw else None


def apply_experiment_context(*, ctx: object) -> None:
    """Spec-0047/T4：用 ExperimentContext 覆盖单例 DATA/HARNESS/vigil 资源名。"""
    global \
        DATA, \
        HARNESS_REPO, \
        _SANDBOX_ROOT, \
        _VIGIL_CONTAINER, \
        _VIGIL_NETWORK, \
        _VIGIL_CONFIG_STAGING, \
        GITEA_ENV_FILE
    experiment_id = str(ctx.experiment_id)  # type: ignore[attr-defined]
    os.environ["AUTO_DESIGNER_EXPERIMENT_ID"] = experiment_id
    DATA = Path(ctx.data_root)  # type: ignore[attr-defined]
    _SANDBOX_ROOT = DATA / "harness_sandbox"
    HARNESS_REPO = Path(ctx.harness_repo)  # type: ignore[attr-defined]
    _VIGIL_CONTAINER = str(ctx.vigil_container)  # type: ignore[attr-defined]
    _VIGIL_NETWORK = str(ctx.vigil_network)  # type: ignore[attr-defined]
    _VIGIL_CONFIG_STAGING = Path(ctx.vigil_config_root)  # type: ignore[attr-defined]
    GITEA_ENV_FILE = DATA.parent / "secrets" / "demand-gitea.env"


def write_openagents_config(*, repo: Path, gitea: dict[str, str]) -> Path:
    """把交付面声明式配置写进 harness 仓 `.openagents/openagents.yml`（Spec-0032/T5）。

    forge=gitea + 连接四元组（token 本体不落盘，只声明 token_env=GITEA_TOKEN，由 vigil 子进程
    env 提供）；stages 见 _VIGIL_STAGES；labels=[openagents]（Owner 准入的交接令牌 = vigil 发现标签）。
    """
    config_dir = repo / ".openagents"
    config_dir.mkdir(parents=True, exist_ok=True)
    # Spec-0032/T6：ci 闸随基建就位切换——act_runner 验证在跑后置 VIGIL_CI_STAGE=agent 开启。
    effective = dict(_VIGIL_STAGES)
    ci_stage = os.environ.get("VIGIL_CI_STAGE", "").strip().lower()
    if ci_stage in ("agent", "human", "skip"):
        effective["ci"] = ci_stage
    coordination = os.environ.get("VIGIL_COORDINATION", "soft").strip().lower()
    if coordination not in {"soft", "off", "dependencies"}:
        raise ValueError("VIGIL_COORDINATION must be soft, off, or dependencies")
    stages = "\n".join(f"  {stage}: {owner}" for stage, owner in effective.items())
    text = (
        "# 由 backend/run.py 每次 run 生成（Spec-0032/T5），勿手工编辑——改 run.py 的定稿常量。\n"
        "version: 1\n"
        "forge: gitea\n"
        f"coordination: {coordination}\n"
        "gitea:\n"
        f"  base_url: {gitea['GITEA_URL']}\n"
        f"  owner: {gitea['OWNER']}\n"
        f"  repo: {gitea['REPO']}\n"
        "  token_env: GITEA_TOKEN\n"
        f"stages:\n{stages}\n"
        "release: manual\n"
        "defaults:\n"
        f"  interval: {_VIGIL_INTERVAL}\n"
        "  base: main\n"
        "  labels: [openagents]\n"
    )
    path = config_dir / "openagents.yml"
    path.write_text(text, encoding="utf-8")
    return path


def ensure_openagents_cli() -> None:
    """交付面 CLI 预检（subprocess 模式）：`openagents` 必须在 PATH。"""
    if shutil.which("openagents") is None:
        raise SystemExit(
            "PATH 上找不到 `openagents`（交付面 CLI）——"
            "uv tool install --from <OpenAgents 仓>@<含 forge/Gitea driver 的版本> openagents"
        )


# Spec-0033/T2：交付面运行形态。container（缺省）= 围堵盒：零宿主挂载自 clone、internal 网络 +
# egress 代理 allowlist；subprocess = 宿主直跑，无任何围堵，仅限人盯着日志的一次性联调。
_VIGIL_IMAGE = (
    os.environ.get("AUTO_DESIGNER_VIGIL_IMAGE", "").strip() or "auto-designer-vigil:latest"
)
_VIGIL_CONTAINER = "auto-designer-vigil"
_VIGIL_NETWORK = "auto-designer-vigil-net"  # deploy/gitea compose 里的 internal 网络（按名引用）
_VIGIL_PROXY_URL = "http://egress-proxy:3128"  # 盒内唯一外网通道（allowlist 见 egress-proxy.conf）
_VIGIL_CONFIG_STAGING = DATA / "vigil_config"  # 容器模式的配置 staging（只读挂载进 /config）
# claude 凭证三选一（Spec-0033）：API key / 网关 Bearer token（配 ANTHROPIC_BASE_URL，须为
# Anthropic 协议端点，且网关域要加进 egress-proxy.conf 白名单）/ 订阅长效 token（claude setup-token）。
_CLAUDE_CRED_ENVS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
# claude 非凭证配置 env（存在才透传进容器）：base_url（自建/第三方 Anthropic 协议网关）+ 模型覆盖。
# 接非官方网关（如 OpenAI 兼容网关的 Anthropic 端点）时，模型名不是 claude-* 而是网关自己的 model id，
# 必须经 ANTHROPIC_MODEL 覆盖；claude 有一档"小/快模型"轻调用（缺省 haiku），网关无此模型时也要用
# ANTHROPIC_SMALL_FAST_MODEL 指到同一个，否则那档调用会 404。
_CLAUDE_CONFIG_ENVS = (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
)
# The product harness is a separate OpenAI-compatible client.  Pass its explicitly scoped GLM
# configuration into the delivery container under the plain names consumed by scripts/run.sh.
_HARNESS_LLM_SUFFIXES = ("MODEL", "BASE_URL", "API_KEY")


class VigilHandle:
    """交付面运行句柄：mode + 托管进程（subprocess=vigil 本体；container=docker logs 跟随器）+ 日志句柄。

    keep_alive：需求面收尾是否拆掉 vigil。Spec-0050/T4：缺省拆；显式 VIGIL_KEEP_ALIVE=1 或
    卡死时 handle.keep_alive=True 才留盒。
    """

    def __init__(
        self, *, mode: str, proc: subprocess.Popen, log_handle: object, keep_alive: bool
    ) -> None:
        self.mode = mode
        self.proc = proc
        self.log_handle = log_handle
        self.keep_alive = keep_alive


def vigil_mode() -> str:
    """VIGIL_MODE 解析：container（缺省）/ subprocess（显式 opt-in）；其余值 fail-loud。"""
    raw = os.environ.get("VIGIL_MODE", "").strip().lower() or "container"
    if raw not in ("container", "subprocess"):
        raise SystemExit(f"VIGIL_MODE 非法：{raw!r}（可选 container / subprocess）")
    return raw


def vigil_keep_alive() -> bool:
    """Return whether vigil should survive the demand-side finally.

    Spec-0050/T4：缺省拆盒（非末轮已等交付封口）。仅显式 1/true/yes/on 才常驻调试。
    卡死路径由调用方把 handle.keep_alive 置 True，不走本函数。
    """
    raw = os.environ.get("VIGIL_KEEP_ALIVE", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _vigil_internal_gitea_url() -> str:
    """容器视角的 Gitea 地址（同网络服务名）；宿主 .env 的 localhost 地址仅编排面自用。"""
    return os.environ.get("VIGIL_GITEA_INTERNAL_URL", "").strip() or "http://gitea:3000"


def _ensure_vigil_container_prereqs() -> None:
    """container 模式预检（fail-loud）：docker 可用 + 镜像已构建 + claude 凭证就位。"""
    if shutil.which("docker") is None:
        raise SystemExit(
            "PATH 上找不到 docker（VIGIL_MODE=container 需要；或 VIGIL_MODE=subprocess 联调）"
        )
    inspect = subprocess.run(
        ["docker", "image", "inspect", _VIGIL_IMAGE], capture_output=True, text=True
    )
    if inspect.returncode != 0:
        raise SystemExit(
            f"缺 vigil 镜像 {_VIGIL_IMAGE}——先构建：backend/deploy/vigil/build.sh "
            "<OpenAgents 仓路径> <NexAU 仓路径>"
        )
    if not any(os.environ.get(key, "").strip() for key in _CLAUDE_CRED_ENVS):
        raise SystemExit(
            "缺 claude 凭证：设 ANTHROPIC_API_KEY（API 计费）/ ANTHROPIC_AUTH_TOKEN（网关 Bearer，"
            "配 ANTHROPIC_BASE_URL，网关域需加进 egress-proxy.conf 白名单）/ CLAUDE_CODE_OAUTH_TOKEN"
            "（订阅计费，宿主 `claude setup-token` 生成）之一（Spec-0033）"
        )


def start_vigil(*, repo: Path, parallel: int, gitea: dict[str, str], log_path: Path) -> VigilHandle:
    """按 VIGIL_MODE 起交付面（含各模式预检与配置落盘），返回句柄供 finally stop_vigil 收尾。

    container（缺省）：配置写 staging 只读挂载进盒，harness 仓由容器 entrypoint 自 clone（零宿主
    挂载——两面唯一媒介是 Gitea，宿主仓与交付面脱钩）；凭证只经容器 env。subprocess：既有行为
    （配置写进宿主仓、Popen 直跑），无围堵、带醒目告警。
    """
    mode = vigil_mode()
    keep_alive = vigil_keep_alive()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if mode == "subprocess":
        print(
            "[vigil] ⚠ subprocess 模式无围堵（嵌套 agent 可读宿主全文件系统、出网无限制）——"
            "仅限盯屏联调，长跑闭环用 container 模式（Spec-0033）"
        )
        ensure_openagents_cli()
        write_openagents_config(repo=repo, gitea=gitea)
        return _start_vigil_subprocess(
            repo=repo,
            parallel=parallel,
            gitea_token=gitea["TOKEN"],
            log_path=log_path,
            keep_alive=keep_alive,
        )
    _ensure_vigil_container_prereqs()
    staging = _VIGIL_CONFIG_STAGING
    # 同一份配置、两个可达性域的唯一分叉点：容器内 base_url 用内网服务名地址。
    write_openagents_config(repo=staging, gitea={**gitea, "GITEA_URL": _vigil_internal_gitea_url()})
    return _start_vigil_container(
        parallel=parallel,
        gitea=gitea,
        staging=staging,
        log_path=log_path,
        keep_alive=keep_alive,
    )


def _start_vigil_subprocess(
    *, repo: Path, parallel: int, gitea_token: str, log_path: Path, keep_alive: bool
) -> VigilHandle:
    """宿主直跑：`openagents vigil --parallel K`（cwd=harness 仓，日志落 log_path）。

    GITEA_TOKEN 只经子进程 env 传递（配置文件不落 token）。level-triggered：票何时出现何时接。
    """
    log_handle = open(log_path, "a", encoding="utf-8")  # noqa: SIM115  生命周期随 vigil 进程，stop 时关闭
    env = {**os.environ, "GITEA_TOKEN": gitea_token}
    proc = subprocess.Popen(
        ["openagents", "vigil", "--parallel", str(max(1, parallel))],
        cwd=str(repo),
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    return VigilHandle(mode="subprocess", proc=proc, log_handle=log_handle, keep_alive=keep_alive)


def _container_is_running(*, name: str) -> bool:
    running, _run_id, _experiment = _container_state(name=name)
    return running


def _container_state(*, name: str) -> tuple[bool, str, str]:
    """Return (running, run_id label, experiment_id label)."""
    inspect = subprocess.run(
        [
            "docker",
            "inspect",
            "-f",
            '{{.State.Running}}|{{index .Config.Labels "io.auto-designer.run_id"}}|{{index .Config.Labels "io.openagents.experiment_id"}}',
            name,
        ],
        capture_output=True,
        text=True,
    )
    if inspect.returncode != 0:
        return False, "", ""
    parts = inspect.stdout.strip().split("|", 2)
    running_s = parts[0] if parts else ""
    run_label = parts[1] if len(parts) > 1 else ""
    exp_label = parts[2] if len(parts) > 2 else ""
    return running_s.lower() == "true", run_label, exp_label


def _attach_container_logs(*, log_path: Path, keep_alive: bool) -> VigilHandle:
    """把 `docker logs -f` 接到 log_path；不负责 docker run（新建与复用共用）。"""
    log_handle = open(log_path, "a", encoding="utf-8")  # noqa: SIM115  生命周期随跟随器，stop 时关闭
    logs = subprocess.Popen(
        ["docker", "logs", "-f", _VIGIL_CONTAINER], stdout=log_handle, stderr=subprocess.STDOUT
    )
    return VigilHandle(mode="container", proc=logs, log_handle=log_handle, keep_alive=keep_alive)


def _start_vigil_container(
    *, parallel: int, gitea: dict[str, str], staging: Path, log_path: Path, keep_alive: bool
) -> VigilHandle:
    """围堵盒：docker run -d --rm 起 vigil 容器，日志经 `docker logs -f` 跟随进 log_path。

    挂载面只有两处只读：staging 配置（/config）与 entrypoint 脚本；凭证（Gitea token / claude
    凭证）只经容器 env 注入（宿主侧 docker inspect 可见——宿主本就是信任边界内侧）。clone 地址
    与代理均为盒内网络名（vigil-net internal，直连外网物理不通）。

    容器已在跑（需求面上一轮 keep-alive 留下的）→ 只挂日志跟随器，不 docker run（同名会撞车）。
    Spec-0049/T4：keep-alive 且 AUTO_DESIGNER_RUN_ID 变化则拆旧盒重建，避免 delivery 挂错 run。
    """
    run_id = os.environ.get("AUTO_DESIGNER_RUN_ID", "").strip()
    running, existing_run, experiment_id = _container_state(name=_VIGIL_CONTAINER)
    ours = os.environ.get("AUTO_DESIGNER_EXPERIMENT_ID", "").strip()
    if running and experiment_id and experiment_id != ours:
        raise SystemExit(
            f"拒绝 attach 实验 {experiment_id} 的 vigil 容器 {_VIGIL_CONTAINER}；"
            "请用 backend/scripts/experiment.py"
        )
    if running and (not run_id or existing_run == run_id):
        print(f"[vigil] 容器 {_VIGIL_CONTAINER} 已在跑，复用（不 docker run）")
        return _attach_container_logs(log_path=log_path, keep_alive=keep_alive)
    if running:
        print(f"[vigil] 容器 {_VIGIL_CONTAINER} run_id 已变（{existing_run}→{run_id}），重建")
        subprocess.run(["docker", "rm", "-f", _VIGIL_CONTAINER], capture_output=True, text=True)
    repo_url = _gitea_remote_url({**gitea, "GITEA_URL": _vigil_internal_gitea_url()})
    args = [
        "docker", "run", "-d", "--rm",
        "--name", _VIGIL_CONTAINER,
        "--network", _VIGIL_NETWORK,
        "-v", f"{(staging / '.openagents').resolve()}:/config:ro",
        "-v", f"{(ROOT / 'deploy' / 'vigil' / 'entrypoint.sh').resolve()}:/entrypoint.sh:ro",
        "-e", f"GITEA_TOKEN={gitea['TOKEN']}",
        "-e", f"GITEA_USER={gitea['OWNER']}",
        "-e", f"VIGIL_REPO_URL={repo_url}",
        "-e", f"VIGIL_PARALLEL={max(1, parallel)}",
        "-e", f"HTTPS_PROXY={_VIGIL_PROXY_URL}",
        "-e", f"HTTP_PROXY={_VIGIL_PROXY_URL}",
        "-e", f"https_proxy={_VIGIL_PROXY_URL}",
        "-e", f"http_proxy={_VIGIL_PROXY_URL}",
        "-e", "NO_PROXY=gitea,localhost,127.0.0.1",
        "-e", "no_proxy=gitea,localhost,127.0.0.1",
        # 容器即 jail（实证修复）：claude 缺省 acceptEdits 只放行文件编辑，headless 下 git commit/push
        # 被拒 → deliver 卡死挂 needs-human。盒内用 bypassPermissions（围堵由容器承担，见 spec-0033
        # §Guide）；宿主同名 env 可覆盖。注意 claude 拒绝 root 下 bypass——镜像以非 root 用户 vigil 跑。
        "-e",
        (
            "OPENAGENTS_PERMISSION_MODE="
            f"{os.environ.get('OPENAGENTS_PERMISSION_MODE', '').strip() or 'bypassPermissions'}"
        ),
    ]  # fmt: skip
    if run_id:
        args += [
            "--label",
            f"io.auto-designer.run_id={run_id}",
            "-e",
            f"AUTO_DESIGNER_RUN_ID={run_id}",
        ]
    if ours:
        args += ["--label", f"io.openagents.experiment_id={ours}"]
    delivery = _vigil_delivery_mount()
    if delivery is not None:
        args += [
            "--user",
            "root",
            "-v",
            f"{delivery}:/role_runs",
            "-e",
            "ROLE_RUNS_DIR=/role_runs",
        ]
    for key in (*_CLAUDE_CRED_ENVS, *_CLAUDE_CONFIG_ENVS):
        value = os.environ.get(key, "").strip()
        if value:
            args += ["-e", f"{key}={value}"]
    for suffix in _HARNESS_LLM_SUFFIXES:
        value = os.environ.get(f"HARNESS_LLM_{suffix}", "").strip()
        if value:
            args += ["-e", f"LLM_{suffix}={value}"]
    args += [_VIGIL_IMAGE, "bash", "/entrypoint.sh"]
    started = subprocess.run(args, capture_output=True, text=True)
    if started.returncode != 0:
        raise SystemExit(f"vigil 容器启动失败：{started.stderr.strip()[:300]}")
    return _attach_container_logs(log_path=log_path, keep_alive=keep_alive)


def _vigil_delivery_mount() -> str | None:
    """Host path of this run's delivery/ directory, or None when ROLE_RUNS_DIR is unset."""
    root = current_role_runs_dir()
    if root is None:
        return None
    delivery = root / "delivery"
    delivery.mkdir(parents=True, exist_ok=True)
    return str(delivery.resolve())


def _stop_managed_proc(*, proc: subprocess.Popen) -> None:
    """停托管进程（container=日志跟随器；subprocess=vigil 本体）。超时则 kill。"""
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def stop_vigil(handle: VigilHandle) -> None:
    """Stop the delivery-plane process according to keep_alive.

    Spec-0040/T1：keep_alive 时 container 只拆日志跟随器、不 docker rm；subprocess 不杀 vigil 本体。
    """
    try:
        if handle.keep_alive:
            if handle.mode == "container":
                _stop_managed_proc(proc=handle.proc)
            return
        if handle.mode == "container":
            subprocess.run(["docker", "rm", "-f", _VIGIL_CONTAINER], capture_output=True, text=True)
        _stop_managed_proc(proc=handle.proc)
    finally:
        try:
            handle.log_handle.close()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001  关日志失败不影响收尾
            pass


def main() -> int:
    from urllib.parse import urlparse

    args = _parse_args(argv=sys.argv[1:])
    if not os.environ.get("AUTO_DESIGNER_EXPERIMENT_ID", "").strip():
        print(
            "[run.py] 单例 ./run.sh 已弃用：并行隔离实验请用 backend/scripts/experiment.py",
            file=sys.stderr,
        )

    _isolate_git_credentials()  # Spec-0021/T2：进程级 git 凭证隔离（多信道封堵，见函数注释）

    llm_env = _load_env(
        ROOT / ".env"
    )  # {USER,DESIGNER,HARNESS}_LLM_*（DEV_LLM_* 随 dev 退役不再消费）
    # 启动命令显式注入的配置优先于仓内 .env，便于临时切换网关/模型且不把密钥写盘。
    _apply_env_defaults(llm_env)
    # 分角色 LLM 配置：编排角色各用 {USER,DESIGNER}_LLM_{MODEL,API_KEY,BASE_URL}，彼此独立、无公共
    # 回落——agent.yaml 的 ${env.DESIGNER_LLM_*} 与 user 侧 ApiPersonaClient 直接读各自角色变量。
    # 交付面（vigil）的 coding 后端是 claude CLI，凭证走宿主 claude 登录态，不经 .env。
    # 被进化的产品本体 harness 是第 4 个独立实体：其（可移植的）agent.yaml 只认 plain LLM_*，不知我们
    # 的角色命名。在此把 HARNESS_LLM_* 写实到 plain LLM_*，让 launcher 起的 harness 子进程（继承
    # os.environ）拿到自己的模型凭证。缺 HARNESS_LLM_* 即报错，绝不静默回落到别的角色。
    for _suffix in ("MODEL", "BASE_URL", "API_KEY"):
        _val = os.environ.get(f"HARNESS_LLM_{_suffix}")
        if not _val:
            raise SystemExit(
                f"backend/.env 缺 HARNESS_LLM_{_suffix}（harness 本体的独立 LLM 配置）；"
                "见 backend/.env.example"
            )
        os.environ[f"LLM_{_suffix}"] = _val
    gitea = _load_env(GITEA_ENV_FILE)  # GITEA_URL/OWNER/REPO/TOKEN

    from auto_designer.loop.roster import load_roster

    # 编制（单一真源）：用户/设计师/开发者数量，前端房间容量经 /api/config 读同一份。
    roster = load_roster()
    user_limit = PERSONA_LIMIT if PERSONA_LIMIT is not None else roster["user"]
    print(
        f"⓪.5 编制 roster：用户×{roster['user']} · 设计师×{roster['designer']} · "
        f"交付面并发×{roster['developer']}（vigil --parallel；前端房间容量与此一致）"
    )

    # 环境里的 HTTP(S)_PROXY 抽风（实测代理连不上，直连网关稳定 200）：放行本地 Gitea + 模型网关，
    # 让 nexau/openai 调用绕过烂代理直连，根除偶发 APIConnectionError。
    bypass = ["localhost", "127.0.0.1"]
    for url in (
        os.environ.get("USER_LLM_BASE_URL"),
        os.environ.get("DESIGNER_LLM_BASE_URL"),
        gitea.get("GITEA_URL"),
    ):
        host = urlparse(url).hostname if url else None
        if host and host not in bypass:
            bypass.append(host)
    no_proxy = ",".join(bypass)
    os.environ["NO_PROXY"] = no_proxy
    os.environ["no_proxy"] = no_proxy

    from auto_designer.designer.designer import Designer
    from auto_designer.designer.triage import Triager
    from auto_designer.distill.library import PersonaLibrary
    from auto_designer.harness.launcher import HarnessLauncher
    from auto_designer.loop.metrics import Metrics
    from auto_designer.loop.orchestrator import Orchestrator
    from auto_designer.loop.round_gate import RoundDeliveryBlocked
    from auto_designer.loop.sim_user import make_sim_run_session_fn, result_to_turns
    from auto_designer.models import Persona, SeedScenario
    from auto_designer.tracker.gitea import GiteaTracker
    from auto_designer.user.session_store import SessionStore
    from auto_designer.user.sim.dimensions import Persona as SimPersona
    from auto_designer.user.sim.persona_client import AgenticPersonaClient, ApiPersonaClient
    from auto_designer.user.sim.persona_io import card_to_personas

    print(f"⓪ 输入：persona 卡库={args.persona_library} | 种子卡库={args.seed_cards}")
    run_mode = experiment_run_mode()
    role_runs = install_role_runs(data_root=DATA)
    recovery = load_recovery_store(mode=run_mode)
    from auto_designer.invocation import append_round, init_manifest  # noqa: PLC0415

    if run_mode == "fresh":
        init_manifest(
            roster=roster,
            models={
                "user": os.environ.get("USER_LLM_MODEL", ""),
                "designer": os.environ.get("DESIGNER_LLM_MODEL", ""),
                "harness": os.environ.get("HARNESS_LLM_MODEL", ""),
                "delivery": os.environ.get("ANTHROPIC_MODEL", ""),
            },
        )
    print(f"⓪.6 实验切片 ROLE_RUNS_DIR={role_runs}")
    if run_mode == "fresh":
        print("① fresh：种 harness 本地仓 ...")
        repo = _seed_harness_repo()
    else:
        print("① resume：复用现有 harness 本地仓 ...")
        repo = existing_harness_repo()

    print("② 接 Gitea + 本地存储 + launcher ...")
    tracker = GiteaTracker(
        base_url=gitea["GITEA_URL"], owner=gitea["OWNER"], repo=gitea["REPO"], token=gitea["TOKEN"]
    )
    tracker.ensure_labels(["bug", "feature"])
    _set_gitea_remote(repo, gitea)  # 配 origin；推送由开发者 agent 用 git 工具自己做
    if run_mode == "fresh":
        print("②.5 fresh：复位 Gitea harness、issue 与 live 投影 ...")
        _reset_to_initial(repo, tracker)
    else:
        print("②.5 resume：保留 Gitea、session、harness 与 live 历史 ...")
    store = SessionStore(role_runs / "sessions")
    # A resume may contain authoritative session files whose derived index was
    # not published before an interruption.  Rebuild it before any role can
    # resolve issue -> session evidence.
    store.rebuild_index()
    launcher = HarnessLauncher(harness_repo=str(repo), runs_root=DATA / "harness_runs")

    print("③ 装配 sim 用户 agent（spec-0005 控制信封）+ 生成/准入角色 ...")
    designer_agent_def = str(
        ROOT / "agent_defs" / "designer"
    )  # synthesize agent 定义目录（只读工具）
    triager_agent_def = str(
        ROOT / "agent_defs" / "triage_agent"
    )  # Spec-0025：triage agent 定义目录
    divergent_agent_def = str(
        ROOT / "agent_defs" / "divergent_pm"
    )  # divergent PM（discovery 轨，产出经 Owner 准入）
    owner_agent_def = str(ROOT / "agent_defs" / "owner")  # Spec-0029：唯一准入评审

    # 用户侧 = spec-0005 控制信封 sim：9 维 sim persona 为权威画像，反向派生展示用 models.Persona。
    # persona 从 distill 卡库（persona_library.json）注入、场景从种子卡库（seeds.json）经
    # distill seed_adapter 注入——两个「给定输入」皆走 distill 卡库，替代此前硬编码的 expert × TASK。
    # 用户 agent 用 AgenticPersonaClient 走内层 tool-use，ApiPersonaClient.complete 作内层 LLM
    # （sim_user 据此 bind_session 绑定共享工作区，令用户 agent 在 harness 同目录核实）。
    # Spec-0017/T2：client 每局一实例（bind_session 是会话级状态，并发下复用单实例必串台）；
    # 底层 ApiPersonaClient 无会话态、跨会话共享同一实例，工厂只新建外壳。
    api = ApiPersonaClient()

    def client_factory() -> AgenticPersonaClient:
        return AgenticPersonaClient(api.complete)

    sim_persona_list = card_to_personas(
        PersonaLibrary(args.persona_library)
    )  # persona 卡库 → sim persona
    sim_persona_list = sim_persona_list[
        :user_limit
    ]  # 用户会话数 = roster 用户数（或 PERSONA_LIMIT）
    seeds = _load_seeds(args.seed_cards)
    # 配对：persona[i] × seed[i % len(seeds)]，每轮 = len(personas) 局用户会话，覆盖全部锚点 persona。
    fixed_set: list[tuple[Persona, SeedScenario]] = []
    sim_personas: dict[str, SimPersona] = {}  # 展示用 identity -> 9 维 sim persona（权威画像）
    persona_meta: dict[
        str, dict[str, str]
    ] = {}  # Spec-0026/T1：identity -> persona 摘要（看板展示用）
    for i, sp in enumerate(sim_persona_list):
        scenario = seeds[i % len(seeds)]
        mp = Persona(
            identity=sp.persona_id,
            level=sp.d1.value,
            domain="/".join(sp.d2.stack) or "general",
            goal=scenario.description[:120],
            speaking_style=f"delegation={sp.d41.value}; autonomy={sp.d5.value}",
        )
        fixed_set.append((mp, scenario))
        sim_personas[mp.identity] = sp
        persona_meta[mp.identity] = {
            "identity": mp.identity,
            "level": mp.level,
            "domain": mp.domain,
            "goal": mp.goal,
        }

    from auto_designer.loop.live import (
        append_agent_log,
        archive_agent,
        clear_live,
        prepare_live_resume,
        update_agent,
        update_live_run,
    )

    if run_mode == "fresh":
        clear_live(data_dir=DATA)
    elif recovery is not None:
        prepare_live_resume(data_dir=DATA, phase="reconcile")

    # 当前轮游标：orchestrator 轮次回调写入，各 agent 活动/归档据此标轮。round_shas 逐轮累计。
    current = {"round": 0}
    round_shas: list[str] = []

    def on_round_start(k):
        current["round"] = k
        update_live_run(
            data_dir=DATA,
            running=True,
            round_no=k,
            total_rounds=TOTAL_ROUNDS,
            phase=orch.recovery_phase(round_no=k) if recovery is not None else "users",
        )

    # Spec-0029/T8：背压阈值（proposal/ready 队列深度）。超阈值只告警、不自动扩容——这是
    # CLAUDE.md「issue 长期不降=退化」观测指标的可执行化，处置（调轮次/加 dev/收紧准入）由人定。
    def _alarm_threshold(env_key: str) -> int:
        raw = os.environ.get(env_key, "").strip()
        return int(raw) if raw.isdigit() and int(raw) > 0 else 20

    proposal_alarm = _alarm_threshold("PROPOSAL_DEPTH_ALARM")
    ready_alarm = _alarm_threshold("READY_DEPTH_ALARM")

    def _check_backpressure(round_no):
        from auto_designer.designer.issue_schema import PROPOSAL, READY, plane  # noqa: PLC0415

        try:
            open_issues = tracker.list_open_issues()
        except Exception:  # noqa: BLE001  读失败不拦轮次
            return
        p_depth = sum(1 for i in open_issues if plane(i.labels) == PROPOSAL)
        r_depth = sum(1 for i in open_issues if plane(i.labels) == READY)
        if p_depth > proposal_alarm:
            print(
                f"[背压告警] 第 {round_no} 轮末 proposal 深度 {p_depth} > {proposal_alarm}："
                "准入太严或生成太滥，请人工介入（调 hold 口径 / 减生成器）。"
            )
        if r_depth > ready_alarm:
            print(
                f"[背压告警] 第 {round_no} 轮末 ready 深度 {r_depth} > {ready_alarm}："
                "dev 消化不动（积压不降=退化信号），请人工介入（加 dev / 收紧准入）。"
            )

    def on_round_end(k, sha):
        round_shas.append(sha)
        append_round(round_no=k, user_sha=None, sealed_sha=sha)
        update_live_run(
            data_dir=DATA,
            running=True,
            round_no=k,
            total_rounds=TOTAL_ROUNDS,
            round_shas=round_shas,
        )
        _check_backpressure(k)

    def make_event_logger(
        agent_id,
    ):  # 过程流（assistant 发言/工具调用/结果）→ 该 agent 的看板时间线
        return lambda kind, text: append_agent_log(
            data_dir=DATA, agent_id=agent_id, text=text, kind=kind
        )

    def on_sim_turn(identity, sim_persona, res, running, *, session_id=None):
        """sim 逐轮（含终止轮）+ 收尾回调 -> 写该用户 agent 的活动槽；收尾再按轮归档。"""
        turns = [t.to_dict() for t in result_to_turns(res)]
        last = res.turns[-1] if res.turns else None
        feel = res.feeling or res.feeling_derived
        if running:
            # TurnLog.turn 已是 1-based（apply_verdict 先自增再落日志），直接用，勿再 +1
            status = f"对话中… 第 {last.turn} 轮 · {last.verdict}" if last else "启动中…"
        else:
            score = feel.score if feel else "?"
            status = f"已完成 · {res.end_reason} · 体感 {score}"
        update_agent(
            data_dir=DATA,
            agent_id=f"user-{identity}",
            role="user",
            label=identity,
            running=running,
            status=status,
            turns=turns,
            round_no=current["round"],
            meta=persona_meta.get(identity),
        )
        if not running:
            archive_agent(
                data_dir=DATA,
                agent_id=f"user-{identity}",
                round_no=current["round"],
                extra={
                    "kind": "user_session",
                    "session_id": session_id,
                    "score": feel.score if feel else None,
                    "end_reason": res.end_reason,
                },
            )

    user_run_session_fn = make_sim_run_session_fn(
        client_factory=client_factory,
        tracker=tracker,
        store=store,
        sim_personas=sim_personas,
        on_turn=on_sim_turn,
        # Spec-0025/T6：给每条 raw issue 盖当前轮号（供增量 triage 与观测曲线）。current 由 on_round_start 更新。
        round_provider=lambda: current["round"] or None,
    )

    def make_triager_status(agent_id, label):  # triage agent 活动回调（收尾按轮归档）
        def cb(*, running, status, detail=None, **kw):
            update_agent(
                data_dir=DATA,
                agent_id=agent_id,
                role="triager",
                label=label,
                running=running,
                status=status,
                detail=detail,
                round_no=current["round"],
            )
            if not running:
                archive_agent(
                    data_dir=DATA,
                    agent_id=agent_id,
                    round_no=current["round"],
                    extra={"kind": "triager_run"},
                )

        return cb

    triagers = [  # Spec-0025/T6：roster 个 triage agent——规范化本轮新 raw issue，跑在 synthesize 之前
        Triager(
            tracker,
            store,
            str(repo),
            triager_agent_def,
            on_status=make_triager_status(
                f"triager-{i}", "triager" if roster["triager"] == 1 else f"triager#{i + 1}"
            ),
            on_event=make_event_logger(f"triager-{i}"),
        )
        for i in range(roster["triager"])
    ]

    def make_designer_status(agent_id, label):  # 创新者 agent 活动回调（收尾时按轮归档）
        def cb(*, running, status, detail=None, proposals=None):
            update_agent(
                data_dir=DATA,
                agent_id=agent_id,
                role="designer",
                label=label,
                running=running,
                status=status,
                detail=detail,
                round_no=current["round"],
            )
            if not running:
                archive_agent(
                    data_dir=DATA,
                    agent_id=agent_id,
                    round_no=current["round"],
                    extra={"kind": "designer_run", "proposals": proposals or []},
                )

        return cb

    designers = [
        Designer(
            tracker,
            store,
            str(repo),
            designer_agent_def,
            on_status=make_designer_status(
                f"designer-{i}", "designer" if roster["designer"] == 1 else f"designer#{i + 1}"
            ),
            on_event=make_event_logger(f"designer-{i}"),
            round_provider=lambda: current["round"] or None,
        )
        for i in range(roster["designer"])
    ]
    from auto_designer.designer.grouped_designer import group_designer_stage

    designers = group_designer_stage(designers, artifact_root=role_runs / "designer_grouping")

    def make_divergent_status(agent_id, label):
        def cb(*, running, status, detail=None, proposals=None):
            update_agent(
                data_dir=DATA,
                agent_id=agent_id,
                role="divergent",
                label=label,
                running=running,
                status=status,
                detail=detail,
                round_no=current["round"],
            )
            if not running:
                archive_agent(
                    data_dir=DATA,
                    agent_id=agent_id,
                    round_no=current["round"],
                    extra={"kind": "divergent_run", "proposals": proposals or []},
                )

        return cb

    from auto_designer.designer.divergent import Divergent  # noqa: PLC0415

    divergents = [
        Divergent(
            tracker,
            store,
            str(repo),
            divergent_agent_def,
            on_status=make_divergent_status(
                f"divergent-{i}",
                "divergent" if roster["divergent"] == 1 else f"divergent#{i + 1}",
            ),
            on_event=make_event_logger(f"divergent-{i}"),
            round_provider=lambda: current["round"] or None,
        )
        for i in range(roster["divergent"])
    ]

    def make_owner_status(agent_id, label):  # Spec-0029：准入评审活动回调（收尾按轮归档）
        def cb(*, running, status, detail=None, proposals=None):
            update_agent(
                data_dir=DATA,
                agent_id=agent_id,
                role="owner",
                label=label,
                running=running,
                status=status,
                detail=detail,
                round_no=current["round"],
            )
            if not running:
                archive_agent(
                    data_dir=DATA,
                    agent_id=agent_id,
                    round_no=current["round"],
                    extra={"kind": "owner_run", "proposals": proposals or []},
                )

        return cb

    from auto_designer.designer.owner import Owner  # noqa: PLC0415

    # Owner 恒 1 个路由实例；默认 roster owner=0 使用零 LLM 机械交接，N_OWNERS=1 才启用模型评审。
    owner = Owner(
        tracker,
        store,
        str(repo),
        owner_agent_def,
        on_status=make_owner_status("owner-0", "owner"),
        on_event=make_event_logger("owner-0"),
        review=roster["owner"] >= 1,
    )

    # Spec-0017/T3：a 段并发度。默认 = roster 用户数（全并行），MAX_PARALLEL_USERS 环境变量
    # 可下调（设 1 即回到串行）。覆盖面（每轮跑几个 persona，PERSONA_LIMIT/roster）与并发度
    # （同时跑几个）是两个独立旋钮。
    raw_parallel = os.environ.get("MAX_PARALLEL_USERS", "").strip()
    max_parallel_users = int(raw_parallel) if raw_parallel.isdigit() else (len(fixed_set) or 1)
    max_parallel_users = max(1, max_parallel_users)  # 0/负值/非数字一律回落（1=串行）

    # Spec-0021/T2：编排仓完整性绊线。run 期间编排仓（ROOT=auto-designer 检出）应全程冻结——只该动
    # harness 沙盒与 data/。开跑前拍一张 (HEAD, porcelain) 快照，每轮 b 段后校验未变；被 dev agent
    # 逃逸改动即抛 RepoIntegrityError 中止（凭证隔离已掐推送，这是第二道独立信道兜底）。
    from auto_designer.dev.repo_guard import snapshot_repo, verify_unchanged  # noqa: PLC0415

    _repo_baseline = snapshot_repo(repo=str(ROOT))

    def integrity_guard() -> None:
        verify_unchanged(repo=str(ROOT), before=_repo_baseline)

    orch = Orchestrator(
        launcher=launcher,
        harness_repo=str(repo),  # Spec-0007/T4：每局解析 main HEAD SHA 用
        fixed_set=fixed_set,
        run_session_fn=user_run_session_fn,
        initial_ref="main",  # Spec-0007/T4：纯 trunk，跟踪 main 分支
        triagers=triagers,  # Spec-0029：第一拍分片并行（第 k 个处理 pending[k::n]）
        designers=designers,  # 第二拍 synthesize（吃本轮新升提案）
        divergents=divergents,  # 第一拍与 triage 并行（discovery 轨，吃会话证据）
        owner=owner,  # Spec-0029：唯一准入（proposal → ready/merged/declined/hold）
        on_round_start=on_round_start,  # 轮次运行态 → data/live/run.json（看板 /api/state）
        on_round_end=on_round_end,
        max_parallel_users=max_parallel_users,  # Spec-0017/T3
        integrity_guard=integrity_guard,  # Spec-0021/T2
        fetch_issue=lambda number: tracker.get_issue(number=number),
        recovery=recovery,
    )

    # Spec-0050/T4：TOTAL_ROUNDS=1 只测用户，不启交付面。
    vigil = None
    if TOTAL_ROUNDS > 1:
        print(f"③.5 起交付面 vigil（OpenAgents，mode={vigil_mode()}）...")
        vigil = start_vigil(
            repo=repo,
            parallel=roster["developer"],
            gitea=gitea,
            log_path=DATA / "vigil.log",
        )

    print(
        f"④ 跑 {TOTAL_ROUNDS} 轮闭环（{len(fixed_set)} 个 persona（distill 卡库）× "
        f"{len(triagers)} triager 分片 ∥ {len(divergents)} divergent → {roster['designer']} synthesize "
        f"→ owner({'评审' if roster['owner'] >= 1 else '零 LLM 机械交接'})；交付面 vigil --parallel "
        f"{roster['developer']}（末轮只用户；非末轮封口后切轮），"
        f"a 段并发 {max_parallel_users}，背压阈值 proposal>{proposal_alarm}/ready>{ready_alarm}，"
        "真模型）..."
    )
    refs: list[str] = []
    exit_code = 0
    try:
        refs = orch.run(TOTAL_ROUNDS)
    except RoundDeliveryBlocked as exc:
        # Spec-0050/T4：卡死留 vigil 容器等人；进程非 0 退出。
        exit_code = 1
        if vigil is not None:
            vigil.keep_alive = True
        update_live_run(
            data_dir=DATA,
            running=False,
            round_no=current["round"],
            total_rounds=TOTAL_ROUNDS,
            round_shas=round_shas,
            phase="blocked",
            blocked_issues=list(exc.numbers),
        )
        print(f"[orchestrator] 本轮交付卡死，实验停止：{exc}")
    finally:
        if vigil is not None:
            stop_vigil(vigil)
        update_live_run(
            data_dir=DATA,
            running=False,
            round_no=current["round"],
            total_rounds=TOTAL_ROUNDS,
            round_shas=round_shas,
            phase="blocked" if exit_code else "done",
        )

    print("\n=== 结果 ===")
    print("各轮 main HEAD SHA:", refs)  # Spec-0007/T4：观测游标（main 最新 SHA）
    m = Metrics(tracker, store)
    print("当前 open issue 数:", m.open_issue_count())
    print("体感趋势:", m.feeling_trend())
    print("issue 曲线 (t, opened, net_open):", m.issue_curve())
    print("本地仓分支:", end=" ")
    subprocess.run(["git", "-C", str(repo), "branch", "--format=%(refname:short)"])
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
