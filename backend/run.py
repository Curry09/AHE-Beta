"""真实端到端跑一轮闭环（a→b→c）。

接线：用户侧 = spec-0005 控制信封 sim（内层 tool-use AgenticPersonaClient，LLM 由
     ApiPersonaClient.complete 供给，模型走 backend/.env 的 LLM_*），场景携带 workspace
     （billing-split fixture），orchestrator 每局 materialize 共享工作区并注入 harness（488c170）；
     开发者侧 = 真 nexau dev agent + 真 Gitea（issue，走 backend/deploy/gitea/.env）
     + 本地 git 仓承载 harness 代码。
本地规模：仅 P-0991(expert) 1 个 user agent × 2 dev agent，默认跑 3 轮；跑前复位到最初状态。
Spec-0007：纯 trunk（单 main），dev 直推 main、无门禁；每局解析 main HEAD SHA 作会话级快照。

前置：
  1) backend/.env 有 LLM_MODEL/LLM_BASE_URL/LLM_API_KEY
  2) Gitea 已起并 bootstrap，backend/deploy/gitea/.env 有 GITEA_URL/OWNER/REPO/TOKEN
运行：PYTHONPATH=backend .venv/bin/python backend/run.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent  # backend/
DATA = ROOT / "data"
HARNESS_REPO = DATA / "harness_repo"


def _load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"')
    return out


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
    _git(HARNESS_REPO, "add", ".")
    _git(HARNESS_REPO, "commit", "-m", "seed: harness v0")
    return HARNESS_REPO


def _reset_to_initial(repo: Path, tracker) -> None:
    """跑测试前复位到最初状态：Gitea harness 仓回 v0 + 关闭遗留 issue + 清空看板数据。

    - Gitea: 强推本地 v0 seed 到 origin/main、删除所有远端 vK tag —— harness 回到 v0 起点
      (dev agent 在同一本地仓工作、push 同一 origin，故此处强推与其后续推进 fast-forward 兼容)。
    - issue: 关闭所有遗留 open issue (issue 编号/历史无法经 API 抹除，仅复位 open 集)。
    - 看板: 清空 data/sessions/*.json 与 data/live/agents.json (体感曲线/活动注册表归零)。
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
    (DATA / "live" / "agents.json").unlink(missing_ok=True)


def main() -> int:
    import os
    from urllib.parse import urlparse

    llm_env = _load_env(ROOT / ".env")  # LLM_*
    os.environ.update(llm_env)
    gitea = _load_env(ROOT / "deploy" / "gitea" / ".env")  # GITEA_URL/OWNER/REPO/TOKEN

    # 环境里的 HTTP(S)_PROXY 抽风（实测代理连不上，直连网关稳定 200）：放行本地 Gitea + 模型网关，
    # 让 nexau/openai 调用绕过烂代理直连，根除偶发 APIConnectionError。
    bypass = ["localhost", "127.0.0.1"]
    for url in (llm_env.get("LLM_BASE_URL"), gitea.get("GITEA_URL")):
        host = urlparse(url).hostname if url else None
        if host and host not in bypass:
            bypass.append(host)
    no_proxy = ",".join(bypass)
    os.environ["NO_PROXY"] = no_proxy
    os.environ["no_proxy"] = no_proxy

    from auto_designer.dev.agentic_developer import AgenticDeveloper
    from auto_designer.harness.launcher import HarnessLauncher
    from auto_designer.loop.metrics import Metrics
    from auto_designer.loop.orchestrator import Orchestrator
    from auto_designer.loop.sim_user import make_sim_run_session_fn, result_to_turns
    from auto_designer.models import Persona, SeedScenario, WorkspaceSpec
    from auto_designer.tracker.gitea import GiteaTracker
    from auto_designer.user.session_store import SessionStore
    from auto_designer.user.sim.dimensions import Persona as SimPersona
    from auto_designer.user.sim.persona_client import AgenticPersonaClient, ApiPersonaClient
    from auto_designer.user.sim.run_live import TASK, expert

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

    # 用户侧 = spec-0005 控制信封 sim：9 维 sim persona 为权威画像，反向派生展示用 models.Persona。
    # 场景用 run_live.TASK（split_bill「加进仓库并证明可用」）——需 harness 真正动文件/跑测试（工具调用），
    # 而非纯文本咨询；shallow/expert 同一任务上做能力分叉。
    # 内层 tool-use 用户 agent：ApiPersonaClient.complete 作 LLM，AgenticPersonaClient 提供
    # bind_session（sim_user 据此绑定共享工作区，令用户 agent 在 harness 同目录核实）。
    api = ApiPersonaClient()
    client = AgenticPersonaClient(api.complete)
    # 场景携带 billing-split fixture：orchestrator 每局 materialize 共享工作区并注入 harness。
    scenarios = [
        SeedScenario(description=TASK, workspace=WorkspaceSpec(fixture="billing-split"))
    ]  # 仅测 P-0991(expert)
    fixed_set: list[tuple[Persona, SeedScenario]] = []
    sim_personas: dict[str, SimPersona] = {}  # 展示用 identity -> 9 维 sim persona（权威画像）
    for build, scenario in zip([expert], scenarios, strict=True):
        sp = build()
        mp = Persona(
            identity=sp.persona_id,
            level=sp.d1.value,
            domain="/".join(sp.d2.stack) or "general",
            goal=scenario.description[:120],
            speaking_style=f"delegation={sp.d41.value}; autonomy={sp.d5.value}",
        )
        fixed_set.append((mp, scenario))
        sim_personas[mp.identity] = sp

    from auto_designer.loop.live import clear_agents, update_agent

    clear_agents(data_dir=DATA)  # 一轮 run 开始清空 agent 活动注册表

    def on_sim_turn(identity, sim_persona, res, running):
        """sim 逐轮（含终止轮）+ 收尾回调 -> 写该用户 agent 的活动槽，看板实时展示。"""
        turns = [t.to_dict() for t in result_to_turns(res)]
        last = res.turns[-1] if res.turns else None
        if running:
            status = f"对话中… 第 {last.turn + 1} 轮 · {last.verdict}" if last else "启动中…"
        else:
            feel = res.feeling or res.feeling_derived
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
        )

    user_run_session_fn = make_sim_run_session_fn(
        client=client,
        tracker=tracker,
        store=store,
        sim_personas=sim_personas,
        on_turn=on_sim_turn,
    )

    def make_dev_status(agent_id, label):  # 开发者 agent 活动回调
        def cb(*, running, status, issue_number=None, branch=None, detail=None):
            update_agent(
                data_dir=DATA,
                agent_id=agent_id,
                role="developer",
                label=label,
                running=running,
                status=status,
                detail=detail,
            )

        return cb

    developers = [  # 2 个工具型 dev agent：同轮各领一条不同 issue，自主改 harness + git 发版
        AgenticDeveloper(
            tracker, str(repo), dev_agent_def, on_status=make_dev_status("dev-0", "dev#1")
        ),
        AgenticDeveloper(
            tracker, str(repo), dev_agent_def, on_status=make_dev_status("dev-1", "dev#2")
        ),
    ]

    orch = Orchestrator(
        launcher=launcher,
        harness_repo=str(repo),  # Spec-0007/T4：每局解析 main HEAD SHA 用
        fixed_set=fixed_set,
        developer_agents=developers,
        run_session_fn=user_run_session_fn,
        initial_ref="main",  # Spec-0007/T4：纯 trunk，跟踪 main 分支
    )

    print("④ 跑 3 轮闭环（仅 P-0991 expert × 2 dev agent，dev 直推 main，真模型）...")
    refs = orch.run(3)

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
