# Spec-0007/T3：一次性迁移脚本——把 harness 仓从 main+release 收敛到纯 trunk（单 main）。
"""把演化成果从 release 收敛到 main 且不丢东西：

`git checkout main && git reset --hard release`（main 移到 release tip，保留全部 release 历史与内容）→
删除除 main 外所有本地分支（release + 孤儿 fix/issue-* + 已合并）→ 可选：push main、删远端 release、
确认 Gitea 默认分支为 main。

幂等：已迁移（无 release 分支）→ no-op、不报错。对意外仓状态（无 release、main 非 release 祖先）安全退出
并提示，绝不执行破坏性的 `-f`/删除。
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

# 可选回调：确认/切换远端（Gitea）默认分支为给定分支名；None 则跳过（纯本地迁移）。
SetDefaultBranch = Callable[[str], None]


def _git(repo: Path, *args: str) -> str:
    """在 repo 内跑 git（check=True，失败抛 CalledProcessError），返回 stdout。"""
    out = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


def _branches(repo: Path) -> list[str]:
    """列出本地分支名。"""
    out = _git(repo, "branch", "--format=%(refname:short)")
    return [b for b in out.split("\n") if b]


def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    """ancestor 是否为 descendant 的祖先（相等视为真）。"""
    return (
        subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", ancestor, descendant],
            capture_output=True,
        ).returncode
        == 0
    )


def migrate_trunk_main(
    *,
    repo: Path,
    push_remote: bool,
    set_default_branch: SetDefaultBranch | None,
) -> int:
    """执行迁移，返回退出码：0=迁移成功 / 已迁移(no-op)；1=意外仓状态，安全跳过、未改动。"""
    repo = Path(repo)
    branches = _branches(repo)

    # 幂等：无 release（已迁移或本就 trunk）→ no-op，不报错、不触碰任何分支。
    if "release" not in branches:
        print("[migrate-trunk] 无 release 分支 → 视为已迁移，跳过")
        return 0

    # 安全闸：main 必须是 release 的祖先（release ⊃ main）才允许把 main 快进到 release tip。
    # 否则（main 领先/已分叉）属意外状态，绝不强行 -f/删除，交人工处置。
    if "main" not in branches or not _is_ancestor(repo, "main", "release"):
        print(
            "[migrate-trunk] main 非 release 祖先（或缺 main）→ 安全退出，不执行 -f/删除",
            file=sys.stderr,
        )
        return 1

    # 迁移：main 移到 release tip（reset --hard 到 release，release ⊃ main 故保留全部历史与内容）。
    _git(repo, "checkout", "main")
    _git(repo, "reset", "--hard", "release")

    # 删除除 main 外所有本地分支（release + 孤儿 fix/issue-* + 已合并），本地仅剩 main 一条线。
    for branch in _branches(repo):
        if branch != "main":
            _git(repo, "branch", "-D", branch)

    if push_remote:
        _git(repo, "push", "origin", "main")
        # 删远端 release（已不存在则忽略，保持幂等）。
        subprocess.run(
            ["git", "-C", str(repo), "push", "origin", "--delete", "release"],
            capture_output=True,
        )

    # 确认远端默认分支为 main（默认展示真正在进化的版本）。
    if set_default_branch is not None:
        set_default_branch("main")

    print("[migrate-trunk] 完成：本地仅 main（release/孤儿/已合并分支已删除）")
    return 0


def _gitea_default_branch_setter(*, session, api: str, owner: str, repo: str) -> SetDefaultBranch:
    """构造把 Gitea 仓默认分支切到给定分支的回调（PATCH /repos/{owner}/{repo}）。"""

    def _set(branch: str) -> None:
        resp = session.patch(f"{api}/repos/{owner}/{repo}", json={"default_branch": branch})
        if resp.status_code not in (200, 201):
            print(
                f"[migrate-trunk] 切默认分支为 {branch} 失败：HTTP {resp.status_code}",
                file=sys.stderr,
            )

    return _set


def main() -> int:
    import requests

    from bootstrap_harness import HARNESS_REPO, _read_env  # 复用 .env 解析与仓名

    repo_root = Path(__file__).resolve().parents[1]  # backend/
    harness_repo = repo_root / "data" / "harness_repo"
    if not (harness_repo / ".git").is_dir():
        print(f"[migrate-trunk] 前置缺失：{harness_repo} 不是 git 仓", file=sys.stderr)
        return 2

    env = _read_env(repo_root / "deploy" / "gitea" / ".env")
    session = requests.Session()
    session.headers.update(
        {"Authorization": f"token {env['TOKEN']}", "Content-Type": "application/json"}
    )
    api = f"{env['GITEA_URL'].rstrip('/')}/api/v1"
    setter = _gitea_default_branch_setter(
        session=session, api=api, owner=env["OWNER"], repo=HARNESS_REPO
    )
    return migrate_trunk_main(repo=harness_repo, push_remote=True, set_default_branch=setter)


if __name__ == "__main__":
    raise SystemExit(main())
