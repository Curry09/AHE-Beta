"""CommitCheckpointMiddleware 单测：未提交且（预算过线 / 改动过大）时注入前置提交升级指令。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from nexau.archs.main_sub.execution.hooks import BeforeModelHookInput
from nexau.core.messages import Message, Role, TextBlock

from auto_designer.dev.commit_checkpoint import CommitCheckpointMiddleware


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@x", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _seed_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "harness"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    (repo / "entry.py").write_text("print('v0')\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "seed")
    return repo, _git(repo, "rev-parse", "HEAD")


def _gate(repo: Path, seed: str) -> CommitCheckpointMiddleware:
    g = CommitCheckpointMiddleware(first_commit_by_frac=0.34, big_diff_lines=150)
    g._repo = str(repo)
    g._start_sha = seed
    return g


def _hi(repo: Path, seed: str, *, cur: int, mx: int = 34) -> BeforeModelHookInput:
    return BeforeModelHookInput(
        agent_state=None,
        max_iterations=mx,
        current_iteration=cur,
        messages=[Message(role=Role.USER, content=[TextBlock(text="go")])],
    )


def test_no_nudge_early_and_small(tmp_path: Path) -> None:
    repo, seed = _seed_repo(tmp_path)
    # 预算才 10%、无改动 → 不施压
    assert not _gate(repo, seed).before_model(_hi(repo, seed, cur=3)).has_modifications()


def test_nudge_past_budget_without_commit(tmp_path: Path) -> None:
    repo, seed = _seed_repo(tmp_path)
    # 预算过半、仍零 commit → 施压
    res = _gate(repo, seed).before_model(_hi(repo, seed, cur=20))
    assert res.has_modifications()
    assert "COMMIT CHECKPOINT" in res.messages[-1].get_text_content()


def test_silent_after_commit(tmp_path: Path) -> None:
    repo, seed = _seed_repo(tmp_path)
    (repo / "entry.py").write_text("print('v1')\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "feat: step1")  # 本轮已提交
    # 即便预算过线，已提交 → 闭嘴
    assert not _gate(repo, seed).before_model(_hi(repo, seed, cur=30)).has_modifications()


def test_nudge_on_big_uncommitted_diff_even_if_early(tmp_path: Path) -> None:
    repo, seed = _seed_repo(tmp_path)
    (repo / "entry.py").write_text(
        "\n".join(f"x{i} = {i}" for i in range(200)) + "\n", encoding="utf-8"
    )
    # 预算才 10% 但未提交改动已 >150 行 → 提前施压（正在贪大）
    res = _gate(repo, seed).before_model(_hi(repo, seed, cur=3))
    assert res.has_modifications()


def test_hard_landing_directive_in_final_stretch(tmp_path: Path) -> None:
    repo, seed = _seed_repo(tmp_path)
    # 只剩 2 轮预算（cur=32/34）、仍零提交 → 升级为硬落地指令（不同于普通/严重档措辞）
    res = _gate(repo, seed).before_model(_hi(repo, seed, cur=32))
    assert res.has_modifications()
    text = res.messages[-1].get_text_content()
    assert "最后" in text and "下一次工具调用就应该是提交" in text


def test_final_stretch_silent_after_commit(tmp_path: Path) -> None:
    repo, seed = _seed_repo(tmp_path)
    (repo / "entry.py").write_text("print('v1')\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "feat: step1")  # 本轮已提交
    # 即便到最后窗口，已提交 → 依然闭嘴（不误催已达标的轮）
    assert not _gate(repo, seed).before_model(_hi(repo, seed, cur=33)).has_modifications()
