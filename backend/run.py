"""真实端到端跑一轮闭环（a→b→c）。

接线：用户侧 = spec-0005 控制信封 sim（内层 tool-use AgenticPersonaClient，LLM 由
     ApiPersonaClient.complete 供给，模型走 backend/.env 的 USER_LLM_*）；
     开发者侧 = 真 nexau dev agent + 真 Gitea（issue，走 backend/deploy/gitea/.env）
     + 本地 git 仓承载 harness 代码。
本地规模：persona 从 distill 卡库(persona_library.json)注入、场景从种子卡库(seeds.json)经
     distill seed_adapter 注入（held-out 判分制品在注入边界剥离），
     × 2 dev agent，跑 5 轮；跑前复位到最初状态。
Spec-0007：纯 trunk（单 main），dev 直推 main、无门禁；每局解析 main HEAD SHA 作会话级快照。

前置：
  1) backend/.env 有四组独立配置 {USER,DEV,DESIGNER,HARNESS}_LLM_{MODEL,BASE_URL,API_KEY}
     （前三=编排角色，HARNESS=被进化的产品本体，run.py 据其导出 harness 子进程读的 plain LLM_*）
  2) Gitea 已起并 bootstrap，backend/deploy/gitea/.env 有 GITEA_URL/OWNER/REPO/TOKEN
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
DEFAULT_PERSONA_LIBRARY = ROOT / "persona_library.json"  # distill 产物：6 张锚卡
DEFAULT_SEED_CARDS = ROOT / "seeds.json"  # distill 种子卡库（原始卡；经 seed_adapter 注入）

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
    # 提交边界硬闸：装 pre-commit 钩子，dev 之后想把 harness 本体外的任务代码提交进来会被直接拒。
    # 顺手清掉模板复制带来的字节码缓存、写 .gitignore，让 v0 seed 只含 harness 制品（钩子放行）。
    from auto_designer.dev.harness_boundary import install_pre_commit  # noqa: PLC0415

    for pyc in HARNESS_REPO.rglob("__pycache__"):
        shutil.rmtree(pyc, ignore_errors=True)
    (HARNESS_REPO / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    install_pre_commit(HARNESS_REPO)
    _git(HARNESS_REPO, "add", ".")
    _git(HARNESS_REPO, "commit", "-m", "seed: harness v0")
    return HARNESS_REPO


def _reset_to_initial(repo: Path, tracker) -> None:
    """跑测试前复位到最初状态：Gitea harness 仓回 v0 + 关闭遗留 issue + 清空看板数据。

    - Gitea: 强推本地 v0 seed 到 origin/main、删除所有远端 vK tag —— harness 回到 v0 起点
      (dev agent 在同一本地仓工作、push 同一 origin，故此处强推与其后续推进 fast-forward 兼容)。
    - issue: 关闭所有遗留 open issue (issue 编号/历史无法经 API 抹除，仅复位 open 集)。
    - 看板: 清空 data/sessions/*.json 与 data/live/ 全部投影 (体感曲线/活动注册表/轮次归档归零)。
    """
    _git(repo, "push", "-f", "origin", "main")  # 远端 main 覆盖回 v0 seed
    ls = subprocess.run(
        ["git", "-C", str(repo), "ls-remote", "--tags", "origin"],
        capture_output=True,
        text=True,
    ).stdout
    for line in ls.splitlines():
        ref = line.split("\t")[-1]
        if ref.startswith("refs/tags/"):
            _git(repo, "push", "origin", f":{ref}")  # 删远端 tag
    for issue in tracker.list_open_issues():
        try:
            tracker.set_state(issue.number, "closed", "reset to initial before clean run")
        except Exception:  # noqa: BLE001  关 issue 失败不阻塞复位
            pass
    for f in (DATA / "sessions").glob("*.json"):
        f.unlink()
    from auto_designer.loop.live import clear_live  # noqa: PLC0415  与 main() 同风格延迟导入

    clear_live(data_dir=DATA)


def main() -> int:
    from urllib.parse import urlparse

    args = _parse_args(argv=sys.argv[1:])

    _isolate_git_credentials()  # Spec-0021/T2：进程级 git 凭证隔离（多信道封堵，见函数注释）

    llm_env = _load_env(ROOT / ".env")  # {USER,DEV,DESIGNER,HARNESS}_LLM_*
    os.environ.update(llm_env)
    # 分角色 LLM 配置：三种编排角色各用 {USER,DEV,DESIGNER}_LLM_{MODEL,API_KEY,BASE_URL}，彼此独立、
    # 无公共回落——agent.yaml 的 ${env.DEV_LLM_*} / ${env.DESIGNER_LLM_*} 与 user 侧 ApiPersonaClient
    # 直接读各自角色变量（.env 各组均已填全）。
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
    gitea = _load_env(ROOT / "deploy" / "gitea" / ".env")  # GITEA_URL/OWNER/REPO/TOKEN

    from auto_designer.loop.roster import load_roster

    # 编制（单一真源）：用户/设计师/开发者数量，前端房间容量经 /api/config 读同一份。
    roster = load_roster()
    user_limit = PERSONA_LIMIT if PERSONA_LIMIT is not None else roster["user"]
    print(
        f"⓪.5 编制 roster：用户×{roster['user']} · 设计师×{roster['designer']} · "
        f"开发者×{roster['developer']}（前端房间容量与此一致）"
    )

    # 环境里的 HTTP(S)_PROXY 抽风（实测代理连不上，直连网关稳定 200）：放行本地 Gitea + 模型网关，
    # 让 nexau/openai 调用绕过烂代理直连，根除偶发 APIConnectionError。
    bypass = ["localhost", "127.0.0.1"]
    for url in (
        os.environ.get("USER_LLM_BASE_URL"),
        os.environ.get("DEV_LLM_BASE_URL"),
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
    from auto_designer.dev.agentic_developer import AgenticDeveloper
    from auto_designer.distill.library import PersonaLibrary
    from auto_designer.harness.launcher import HarnessLauncher
    from auto_designer.loop.metrics import Metrics
    from auto_designer.loop.orchestrator import Orchestrator
    from auto_designer.loop.sim_user import make_sim_run_session_fn, result_to_turns
    from auto_designer.models import Persona, SeedScenario
    from auto_designer.tracker.gitea import GiteaTracker
    from auto_designer.user.session_store import SessionStore
    from auto_designer.user.sim.dimensions import Persona as SimPersona
    from auto_designer.user.sim.persona_client import AgenticPersonaClient, ApiPersonaClient
    from auto_designer.user.sim.persona_io import card_to_personas

    print(f"⓪ 输入：persona 卡库={args.persona_library} | 种子卡库={args.seed_cards}")
    print("① 种 harness 本地仓 ...")
    repo = _seed_harness_repo()

    print("② 接 Gitea + 本地存储 + launcher ...")
    tracker = GiteaTracker(
        base_url=gitea["GITEA_URL"], owner=gitea["OWNER"], repo=gitea["REPO"], token=gitea["TOKEN"]
    )
    tracker.ensure_labels(["bug", "feature"])
    _set_gitea_remote(repo, gitea)  # 配 origin；推送由开发者 agent 用 git 工具自己做
    print("②.5 复位到最初状态（Gitea harness→v0 + 关闭遗留 issue + 清空看板）...")
    _reset_to_initial(repo, tracker)
    store = SessionStore(DATA / "sessions")
    launcher = HarnessLauncher(harness_repo=str(repo), runs_root=DATA / "harness_runs")

    print("③ 装配 sim 用户 agent（spec-0005 控制信封）+ 开发者角色 ...")
    dev_agent_def = str(ROOT / "agent_defs" / "developer_agent")  # 工具型 dev agent 定义目录
    designer_agent_def = str(
        ROOT / "agent_defs" / "designer"
    )  # synthesize agent 定义目录（只读工具）
    triager_agent_def = str(
        ROOT / "agent_defs" / "triage_agent"
    )  # Spec-0025：triage agent 定义目录
    divergent_agent_def = str(
        ROOT / "agent_defs" / "divergent_pm"
    )  # divergent PM（产品候选，经 gate 晋升）

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
        update_agent,
        update_live_run,
    )

    clear_live(data_dir=DATA)  # 一轮 run 开始清空 live 观测投影（agents/run/history）

    # 当前轮游标：orchestrator 轮次回调写入，各 agent 活动/归档据此标轮。round_shas 逐轮累计。
    current = {"round": 0}
    round_shas: list[str] = []

    def on_round_start(k):
        current["round"] = k
        update_live_run(data_dir=DATA, running=True, round_no=k, total_rounds=TOTAL_ROUNDS)

    def on_round_end(k, sha):
        round_shas.append(sha)
        update_live_run(
            data_dir=DATA,
            running=True,
            round_no=k,
            total_rounds=TOTAL_ROUNDS,
            round_shas=round_shas,
        )

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

    def make_dev_status(agent_id, label):  # 开发者 agent 活动回调（收尾时按轮归档）
        def cb(*, running, status, issue_number=None, detail=None, tag=None, committed=False):
            update_agent(
                data_dir=DATA,
                agent_id=agent_id,
                role="developer",
                label=label,
                running=running,
                status=status,
                detail=detail,
                round_no=current["round"],
            )
            if not running and issue_number is not None:  # 「无可领 issue」不算工作项，不归档
                archive_agent(
                    data_dir=DATA,
                    agent_id=agent_id,
                    round_no=current["round"],
                    extra={
                        "kind": "dev_run",
                        "issue_number": issue_number,
                        "tag": tag,
                        "committed": committed,
                    },
                )

        return cb

    # Spec-0025/T6：dev 预算按 kind 分档（RFC 最高），env 覆盖各档；无分池/重试（见 T5）。
    from auto_designer.dev.agentic_developer import DEFAULT_BUDGETS  # noqa: PLC0415

    def _budget(kind: str) -> int:
        raw = os.environ.get(f"DEV_BUDGET_{kind.upper()}", "").strip()
        return int(raw) if raw.isdigit() and int(raw) > 0 else DEFAULT_BUDGETS[kind]

    budgets = {k: _budget(k) for k in DEFAULT_BUDGETS}

    developers = [  # roster 个工具型 dev agent：同轮各领一条不同 issue，自主改 harness + git 发版
        AgenticDeveloper(
            tracker,
            str(repo),
            dev_agent_def,
            on_status=make_dev_status(f"dev-{i}", f"dev#{i + 1}"),
            on_event=make_event_logger(f"dev-{i}"),
            budgets=budgets,
        )
        for i in range(roster["developer"])
    ]

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

    designers = [  # roster 个创新者 agent：a 之后综合全局 backlog+体感产结构性提案（design 标签），供 dev 领取
        Designer(
            tracker,
            store,
            str(repo),
            designer_agent_def,
            on_status=make_designer_status(
                f"designer-{i}", "designer" if roster["designer"] == 1 else f"designer#{i + 1}"
            ),
            on_event=make_event_logger(f"designer-{i}"),
        )
        for i in range(roster["designer"])
    ]

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
        developer_agents=developers,
        run_session_fn=user_run_session_fn,
        initial_ref="main",  # Spec-0007/T4：纯 trunk，跟踪 main 分支
        triagers=triagers,  # Spec-0025/T6：d1 triage（规范化）跑在 synthesize 之前
        designers=designers,  # synthesize + gate
        divergents=divergents,  # 与 synthesize 并行落候选
        on_round_start=on_round_start,  # 轮次运行态 → data/live/run.json（看板 /api/state）
        on_round_end=on_round_end,
        max_parallel_users=max_parallel_users,  # Spec-0017/T3
        integrity_guard=integrity_guard,  # Spec-0021/T2
    )

    print(
        f"④ 跑 {TOTAL_ROUNDS} 轮闭环（{len(fixed_set)} 个 persona（distill 卡库）× "
        f"{len(triagers)} triager × {len(designers)} synthesize × {len(divergents)} divergent × "
        f"{len(developers)} dev，"
        f"a 段并发 {max_parallel_users}，dev 预算 "
        f"bug={budgets['bug']}/feature={budgets['feature']}/rfc={budgets['rfc']}，"
        f"dev 直推 main，真模型）..."
    )
    try:
        refs = orch.run(TOTAL_ROUNDS)
    finally:
        # 无论正常结束还是中途炸掉，运行态都落 running=False，看板不悬挂「运行中」。
        update_live_run(
            data_dir=DATA,
            running=False,
            round_no=current["round"],
            total_rounds=TOTAL_ROUNDS,
            round_shas=round_shas,
        )

    print("\n=== 结果 ===")
    print("各轮 main HEAD SHA:", refs)  # Spec-0007/T4：观测游标（main 最新 SHA），非 release 链
    m = Metrics(tracker, store)
    print("当前 open issue 数:", m.open_issue_count())
    print("体感趋势:", m.feeling_trend())
    print("issue 曲线 (t, opened, net_open):", m.issue_curve())
    print("本地仓分支:", end=" ")
    subprocess.run(["git", "-C", str(repo), "branch", "--format=%(refname:short)"])
    print("tags:", end=" ")
    subprocess.run(["git", "-C", str(repo), "tag"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
