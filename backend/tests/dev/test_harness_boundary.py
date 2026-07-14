"""harness 提交边界闸单测：violations 判定 + 安装后的 pre-commit 钩子真拦越界提交/放行合法提交。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from auto_designer.dev.harness_boundary import (
    ALLOWED_TOP,
    install_pre_commit,
    render_hook,
    violations,
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@x", "-c", "user.name=t", *args],
        capture_output=True,
        text=True,
    )


def _seed_repo(tmp_path: Path) -> Path:
    """建一个装了边界钩子的 harness 仓（entry.py 作 v0 本体）。"""
    repo = tmp_path / "harness"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    install_pre_commit(repo)
    (repo / "entry.py").write_text("print('v0')\n", encoding="utf-8")
    assert _git(repo, "add", ".").returncode == 0
    assert _git(repo, "commit", "-m", "seed").returncode == 0  # 本体文件 → 钩子放行
    return repo


def test_violations_flags_only_out_of_bounds() -> None:
    staged = [
        "entry.py",  # 本体
        "agents/main.md",  # 本体子路径
        "tools/x.tool.yaml",
        "MANUAL.md",
        ".gitignore",
        "tests/test_entry.py",  # 合法：harness 自身的回归测试
        "__pycache__/entry.cpython-312.pyc",  # 噪声 → 忽略
        "unicode_ascii/core.py",  # 越界：任务代码
        "pyproject.toml",  # 越界：项目脚手架
        "test_toplevel.py",  # 越界：顶层散落测试（须进 tests/）
    ]
    assert violations(staged) == ["unicode_ascii/core.py", "pyproject.toml", "test_toplevel.py"]


def test_violations_empty_for_pure_harness() -> None:
    assert violations(["entry.py", "agents/main.md", "params.yaml", "agent.yaml"]) == []
    assert violations(["tests/test_smoke.py", "tests/helpers/util.py"]) == []  # harness 自测放行
    assert violations([]) == []
    assert violations(["  ", ""]) == []  # 空/空白路径不算


def test_allowed_top_is_harness_skeleton() -> None:
    assert ALLOWED_TOP == {
        "MANUAL.md",
        "RUNTIME.md",
        "agent.yaml",
        "params.yaml",
        "entry.py",
        "agents",
        "tools",
        "tests",
        ".gitignore",
    }


def test_violations_allows_runtime_md() -> None:
    assert violations(["RUNTIME.md"]) == []


def test_render_hook_is_executable_python() -> None:
    src = render_hook()
    assert src.startswith("#!/usr/bin/env python3")
    compile(src, "<hook>", "exec")  # 生成的钩子须是合法 python


def test_hook_blocks_out_of_bounds_commit(tmp_path: Path) -> None:
    # 机制硬门：dev 把被测项目代码写进 harness 仓 → git commit 被 pre-commit 钩子拒绝。
    repo = _seed_repo(tmp_path)
    (repo / "unicode_ascii").mkdir()
    (repo / "unicode_ascii" / "core.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname='u'\n", encoding="utf-8")
    _git(repo, "add", "-A")
    res = _git(repo, "commit", "-m", "fix: build unidecode")
    assert res.returncode != 0  # 越界 → 拒绝
    assert "harness-boundary" in res.stderr
    assert "unicode_ascii/core.py" in res.stderr and "pyproject.toml" in res.stderr
    # 提交确实没落下（HEAD 仍是 seed，工作区脏文件仍在）
    assert _git(repo, "log", "--oneline").stdout.count("\n") == 1


def test_hook_allows_harness_only_commit(tmp_path: Path) -> None:
    # 合法：只改 harness 本体（新增 agents/ 定义、改 entry.py）→ 放行。
    repo = _seed_repo(tmp_path)
    (repo / "agents").mkdir()
    (repo / "agents" / "main.md").write_text("# harness\n", encoding="utf-8")
    (repo / "entry.py").write_text("print('v1')\n", encoding="utf-8")
    _git(repo, "add", "-A")
    res = _git(repo, "commit", "-m", "feat: improve harness scaffolding")
    assert res.returncode == 0
    assert _git(repo, "log", "--oneline").stdout.count("\n") == 2


def test_hook_allows_harness_self_test(tmp_path: Path) -> None:
    # 合法：harness 自身的回归测试放 tests/ → 放行（区别于被测任务的项目代码）。
    repo = _seed_repo(tmp_path)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_smoke.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    _git(repo, "add", "-A")
    res = _git(repo, "commit", "-m", "test: add harness smoke")
    assert res.returncode == 0
    assert _git(repo, "log", "--oneline").stdout.count("\n") == 2


def test_hook_blocks_toplevel_test_file(tmp_path: Path) -> None:
    # 顶层散落 test_*.py 仍拒——逼测试统一进 tests/（顶层段不在白名单）。
    repo = _seed_repo(tmp_path)
    (repo / "test_toplevel.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    _git(repo, "add", "-A")
    res = _git(repo, "commit", "-m", "test: stray toplevel test")
    assert res.returncode != 0
    assert "test_toplevel.py" in res.stderr


def test_hook_ignores_pyc_noise(tmp_path: Path) -> None:
    # 字节码缓存混进暂存区不该拖垮合法提交（钩子跳过 pyc/__pycache__）。
    repo = _seed_repo(tmp_path)
    cache = repo / "__pycache__"
    cache.mkdir()
    (cache / "entry.cpython-312.pyc").write_bytes(b"\x00")
    (repo / "entry.py").write_text("print('v2')\n", encoding="utf-8")
    _git(repo, "add", "-A", "-f")  # -f 越过 .gitignore 强塞 pyc 进暂存
    res = _git(repo, "commit", "-m", "feat: tweak")
    assert res.returncode == 0  # pyc 被忽略、entry.py 合法 → 放行
