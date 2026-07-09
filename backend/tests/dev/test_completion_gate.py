"""CompletionGateMiddleware 单测：收尾闸门保证"完整提交（含手册）+ 尽量落测试"。

用 tmp git 仓自建各状态，验证：
- 改了 entry.py 没同步 MANUAL.md → 拦（手册闸）；报告声明"无对外可见变化"→ 豁免；
- 手册已同步、仅缺测试 → 软闸（预算紧则让路）；
- 工作区有未提交/未跟踪改动 → 拦（完整提交闸）；
- after_model：不达标时剔除 complete_task 调用 + force_continue + 注入反馈；
- 预算兜底：remaining<=1 放行，不空转到超时。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from nexau.archs.main_sub.execution.hooks import AfterModelHookInput
from nexau.archs.main_sub.execution.parse_structures import ParsedResponse, ToolCall

from auto_designer.dev.completion_gate import CompletionGateMiddleware


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@x", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _seed_repo(tmp_path: Path) -> tuple[Path, str]:
    """种一个 harness 仓（含 entry.py + MANUAL.md 的 v0），返回 (仓, seed_sha)。"""
    repo = tmp_path / "harness"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    (repo / "entry.py").write_text("print('v0')\n", encoding="utf-8")
    (repo / "MANUAL.md").write_text("# manual v0\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "seed: harness v0")
    return repo, _git(repo, "rev-parse", "HEAD")


def _gate(repo: Path, seed: str) -> CompletionGateMiddleware:
    g = CompletionGateMiddleware()
    g._repo = str(repo)
    g._start_sha = seed  # 模拟"本轮从 seed 开工"
    return g


def _commit_entry_only(repo: Path) -> None:
    (repo / "entry.py").write_text("print('v1 with progress events')\n", encoding="utf-8")
    _git(repo, "add", "entry.py")
    _git(repo, "commit", "-m", "feat: progress")


def _tags(problems: list[str]) -> list[str]:
    return [p.split("]")[0] + "]" for p in problems]


def test_manual_not_synced_blocks(tmp_path: Path) -> None:
    repo, seed = _seed_repo(tmp_path)
    _commit_entry_only(repo)  # 改了 entry.py，没动 MANUAL.md
    tags = _tags(_gate(repo, seed)._check(report="", drop_soft=False))
    assert "[手册同步]" in tags
    assert "[落地测试]" in tags


def test_no_visible_change_declaration_bypasses_manual(tmp_path: Path) -> None:
    repo, seed = _seed_repo(tmp_path)
    _commit_entry_only(repo)
    tags = _tags(_gate(repo, seed)._check(report="本次无对外可见变化", drop_soft=False))
    assert "[手册同步]" not in tags  # 豁免
    assert "[落地测试]" in tags  # 测试软闸仍在


def test_manual_synced_only_soft_test_gate(tmp_path: Path) -> None:
    repo, seed = _seed_repo(tmp_path)
    (repo / "entry.py").write_text("print('v1')\n", encoding="utf-8")
    (repo / "MANUAL.md").write_text("# manual v1\n- progress events\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "feat: progress + manual")
    gate = _gate(repo, seed)
    assert _tags(gate._check(report="", drop_soft=False)) == ["[落地测试]"]
    assert gate._check(report="", drop_soft=True) == []  # 预算紧 → 软闸让路，放行


def test_committed_test_passes(tmp_path: Path) -> None:
    repo, seed = _seed_repo(tmp_path)
    (repo / "entry.py").write_text("print('v1')\n", encoding="utf-8")
    (repo / "MANUAL.md").write_text("# manual v1\n", encoding="utf-8")
    (repo / "test_entry.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "feat: progress + manual + test")
    assert _gate(repo, seed)._check(report="", drop_soft=False) == []  # 全齐 → 放行


def test_dirty_worktree_blocks(tmp_path: Path) -> None:
    repo, seed = _seed_repo(tmp_path)
    (repo / "scratch.tmp").write_text("uncommitted\n", encoding="utf-8")  # 未跟踪
    tags = _tags(_gate(repo, seed)._check(report="本次无对外可见变化", drop_soft=True))
    assert "[完整提交]" in tags


def test_after_model_strips_complete_task_and_continues(tmp_path: Path) -> None:
    repo, seed = _seed_repo(tmp_path)
    _commit_entry_only(repo)  # 会命中手册闸
    gate = _gate(repo, seed)
    parsed = ParsedResponse(
        original_response="",
        tool_calls=[ToolCall(tool_name="complete_task", parameters={"report": "done"})],
    )
    hi = AfterModelHookInput(
        agent_state=None,
        max_iterations=34,
        current_iteration=10,  # remaining=24
        messages=[],
        parsed_response=parsed,
    )
    res = gate.after_model(hi)
    assert res.parsed_response is not None
    assert not res.parsed_response.has_calls()  # complete_task 被剔除
    assert res.force_continue is True
    assert res.messages and len(res.messages) == 1  # 注入了反馈


def test_after_model_budget_backstop_relents(tmp_path: Path) -> None:
    repo, seed = _seed_repo(tmp_path)
    _commit_entry_only(repo)
    gate = _gate(repo, seed)
    hi = AfterModelHookInput(
        agent_state=None,
        max_iterations=34,
        current_iteration=33,  # remaining=1 → 兜底放行
        messages=[],
        parsed_response=ParsedResponse(
            original_response="",
            tool_calls=[ToolCall(tool_name="complete_task", parameters={})],
        ),
    )
    res = gate.after_model(hi)
    assert not res.has_modifications()  # 放行，不拦


def test_non_completing_call_ignored(tmp_path: Path) -> None:
    repo, seed = _seed_repo(tmp_path)
    _commit_entry_only(repo)
    gate = _gate(repo, seed)
    hi = AfterModelHookInput(
        agent_state=None,
        max_iterations=34,
        current_iteration=5,
        messages=[],
        parsed_response=ParsedResponse(
            original_response="",
            tool_calls=[ToolCall(tool_name="run_shell_command", parameters={"command": "ls"})],
        ),
    )
    assert not gate.after_model(hi).has_modifications()  # 不是收尾调用 → 不干预
