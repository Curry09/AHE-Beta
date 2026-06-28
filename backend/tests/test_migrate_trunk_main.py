# Spec-0005/T3：migrate_trunk_main 一次性迁移单测（真临时 git 仓，不触远端）。
"""验证 main←release 收敛：

- main 指向旧 release tip（内容与历史全保留、git log 见 release 历史），release/孤儿/已合并分支全删，
  本地仅剩 main；
- 重复运行幂等无副作用、不报错；
- release 不存在 / main 非 release 祖先 → 安全跳过、打印原因、不执行 -f/删除、仓状态不变。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from migrate_trunk_main import migrate_trunk_main


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@x", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _branches(repo: Path) -> list[str]:
    return sorted(b for b in _git(repo, "branch", "--format=%(refname:short)").split("\n") if b)


def _seed_main_plus_release(tmp_path: Path) -> Path:
    """种 main(空种子) + release(领先若干提交) + 孤儿 fix/issue-* + 一条已合并分支。"""
    repo = tmp_path / "harness"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    (repo / "main.md").write_text("v0 seed\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "seed: harness v0")  # main 空种子
    # release 从 main 起、领先多个演化提交
    _git(repo, "branch", "release")
    _git(repo, "checkout", "release")
    for i in (1, 2, 3):
        (repo / "main.md").write_text(f"v0 seed\n# evo {i}\n", encoding="utf-8")
        _git(repo, "commit", "-am", f"release: evo {i}")
    # 孤儿 fix/issue-* 分支（从 release 切，残留）
    for n in (7, 8):
        _git(repo, "branch", f"fix/issue-{n}")
    # 一条已合并进 release 的分支
    _git(repo, "branch", "merged-feat")
    _git(repo, "checkout", "main")
    return repo


def test_migrates_main_to_release_tip_and_prunes(tmp_path) -> None:
    repo = _seed_main_plus_release(tmp_path)
    release_tip = _git(repo, "rev-parse", "release")
    release_log = _git(repo, "log", "release", "--oneline")

    rc = migrate_trunk_main(repo=repo, push_remote=False, set_default_branch=None)
    assert rc == 0
    # main 指向旧 release tip，内容与全部 release 历史保留
    assert _git(repo, "rev-parse", "main") == release_tip
    assert (repo / "main.md").read_text(encoding="utf-8") == "v0 seed\n# evo 3\n"
    assert _git(repo, "log", "main", "--oneline") == release_log
    assert "release: evo 3" in release_log
    # 本地仅剩 main 一条线（release/孤儿/已合并全删）
    assert _branches(repo) == ["main"]


def test_idempotent_second_run_noop(tmp_path) -> None:
    repo = _seed_main_plus_release(tmp_path)
    assert migrate_trunk_main(repo=repo, push_remote=False, set_default_branch=None) == 0
    head_after_first = _git(repo, "rev-parse", "main")
    # 二次运行：无 release → no-op，不报错、不改动
    assert migrate_trunk_main(repo=repo, push_remote=False, set_default_branch=None) == 0
    assert _git(repo, "rev-parse", "main") == head_after_first
    assert _branches(repo) == ["main"]


def test_no_release_safe_skip(tmp_path) -> None:
    """本就无 release（纯 trunk）→ 视为已迁移，no-op 返回 0、分支不变。"""
    repo = tmp_path / "h"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    (repo / "f").write_text("x\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "seed")
    assert migrate_trunk_main(repo=repo, push_remote=False, set_default_branch=None) == 0
    assert _branches(repo) == ["main"]


def test_main_not_ancestor_of_release_safe_exit(tmp_path) -> None:
    """main 已分叉（非 release 祖先）→ 安全退出 rc=1，不执行 -f/删除，分支与 HEAD 不变。"""
    repo = _seed_main_plus_release(tmp_path)
    # 让 main 领先一个 release 没有的提交 → main 不再是 release 祖先
    (repo / "main.md").write_text("v0 seed\n# main-only divergence\n", encoding="utf-8")
    _git(repo, "commit", "-am", "main: diverge")
    main_before = _git(repo, "rev-parse", "main")
    branches_before = _branches(repo)

    rc = migrate_trunk_main(repo=repo, push_remote=False, set_default_branch=None)
    assert rc == 1
    assert _git(repo, "rev-parse", "main") == main_before  # 未改动
    assert _branches(repo) == branches_before  # release/孤儿仍在，未删
