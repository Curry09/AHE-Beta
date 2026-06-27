"""真实端到端跑一轮闭环（a→b→c）。

接线：真 nexau（user/developer/harness agent，模型走 backend/.env 的 LLM_*）
     + 真 Gitea（issue，走 backend/deploy/gitea/.env）+ 本地 git 仓承载 harness 代码。
本地多轮规模：2 persona（2 user agent）× 2 dev agent，max_turns=2，体感门禁 n=1 抽样，跑 2 轮。

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


def _seed_harness_repo() -> Path:
    """从 harness_template 种一个本地 git 仓：main 初始提交 + release 分支。"""
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
    _git(HARNESS_REPO, "branch", "release")
    return HARNESS_REPO


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

    from auto_designer import nexau_runtime
    from auto_designer.dev.developer_agent import DeveloperAgent
    from auto_designer.dev.release import release
    from auto_designer.dev.test_agent import TestAgent
    from auto_designer.harness.launcher import HarnessLauncher
    from auto_designer.loop.metrics import Metrics
    from auto_designer.loop.orchestrator import Orchestrator
    from auto_designer.models import Persona, SeedScenario
    from auto_designer.tracker.gitea import GiteaTracker
    from auto_designer.user.session import run_session
    from auto_designer.user.session_store import SessionStore
    from auto_designer.user.user_agent import UserAgent

    print("① 种 harness 本地仓 ...")
    repo = _seed_harness_repo()

    print("② 接 Gitea + 本地存储 + launcher ...")
    tracker = GiteaTracker(
        base_url=gitea["GITEA_URL"], owner=gitea["OWNER"], repo=gitea["REPO"], token=gitea["TOKEN"]
    )
    tracker.ensure_labels(["bug", "feature"])
    store = SessionStore(DATA / "sessions")
    launcher = HarnessLauncher(harness_repo=str(repo), runs_root=DATA / "harness_runs")

    print("③ 装配真 nexau 角色 ...")
    user_nexau = nexau_runtime.load(str(ROOT / "agent_defs" / "user_agent"))
    dev_nexau = nexau_runtime.load(str(ROOT / "agent_defs" / "developer_agent"))

    personas = [
        Persona(
            identity="独立开发者",
            level="中级",
            domain="Python 后端",
            goal="让一段慢 SQL 查询快起来",
            speaking_style="口语、偏急",
        ),
        Persona(
            identity="创业公司全栈",
            level="高级",
            domain="Node.js/TypeScript",
            goal="把一个 Express API 的 p99 延迟降下来",
            speaking_style="简洁、爱追问细节",
        ),
    ]
    scenarios = [
        SeedScenario(
            description="我有个 Django 接口很慢，怀疑是 ORM 查询，帮我看看怎么排查和优化。"
        ),
        SeedScenario(
            description="我的 Express 接口 p99 到 800ms，想定位是中间件、DB 还是序列化的问题，给排查思路。"
        ),
    ]
    fixed_set = list(zip(personas, scenarios, strict=True))  # 2 user agent

    def user_llm(*, kind: str, prompt: str) -> str:
        return user_nexau.run(prompt)

    from auto_designer.loop.live import clear_agents, update_agent

    clear_agents(data_dir=DATA)  # 一轮 run 开始清空 agent 活动注册表

    def _session_with_emit(persona, scenario, harness, agent_id, role, label, prefix):
        """跑一局会话，逐轮把 transcript 写进该 agent 的活动槽（流式），收尾标 running=False。"""

        def on_progress(transcript):
            turns = [t.to_dict() for t in transcript.turns]
            waiting = bool(turns) and turns[-1]["role"] == "user"
            update_agent(
                data_dir=DATA,
                agent_id=agent_id,
                role=role,
                label=label,
                running=True,
                status=f"{prefix}harness 回复中…" if waiting else f"{prefix}对话中…",
                turns=turns,
            )

        ua = UserAgent(llm=user_llm, persona=persona, max_turns=2, on_progress=on_progress)
        session = run_session(persona, scenario, harness, ua, tracker, store)
        update_agent(
            data_dir=DATA,
            agent_id=agent_id,
            role=role,
            label=label,
            running=False,
            status=f"{prefix}已完成 · 体感 {session.feeling.score}",
            turns=[t.to_dict() for t in session.transcript.turns],
        )
        return session

    def user_run_session_fn(persona, scenario, harness):  # a 段：用户 agent
        return _session_with_emit(
            persona, scenario, harness, f"user-{persona.identity}", "user", persona.identity, ""
        )

    def test_run_session_fn(persona, scenario, harness):  # 体感门禁：测试 agent（归开发者侧）
        return _session_with_emit(
            persona, scenario, harness, "test", "developer", "测试 agent", "门禁会话 · "
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

    developers = [  # 2 dev agent：共用同一 nexau 定义，同轮各领一条不同 issue
        DeveloperAgent(tracker, str(repo), dev_nexau, on_status=make_dev_status("dev-0", "dev#1")),
        DeveloperAgent(tracker, str(repo), dev_nexau, on_status=make_dev_status("dev-1", "dev#2")),
    ]
    tester = TestAgent(
        launcher=launcher,
        fixed_set=fixed_set[:1],  # 体感门禁取 1 个 persona 抽样，控制每次评测成本
        baseline=None,
        n=1,
        tol=0.5,
        run_session_fn=test_run_session_fn,
    )

    def release_fn(branch, verdict, issue_number):
        return release(str(repo), branch, verdict, tracker, issue_number)

    orch = Orchestrator(
        launcher=launcher,
        fixed_set=fixed_set,
        tracker=tracker,
        store=store,
        developer_agents=developers,
        test_agent=tester,
        release_fn=release_fn,
        run_session_fn=user_run_session_fn,
        initial_ref="release",
    )

    print("④ 跑 2 轮闭环（2 user agent × 2 dev agent，真模型，较慢，请稍候）...")
    refs = orch.run(2)

    print("\n=== 结果 ===")
    print("release_ref 链:", refs)
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
