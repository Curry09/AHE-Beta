"""harness 提交边界闸单测：violations 判定 + 安装后的 pre-commit 钩子真拦密钥/放行结构演进。

Spec-0040/T2: 拒绝清单放行 docs/specs 与结构性演进，拒绝 .env 与 .openagents。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ahe_beta.guards.harness_boundary import (
    DENIED_TOP,
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
    assert _git(repo, "commit", "-m", "seed").returncode == 0
    return repo


def test_violations_flags_only_secrets_and_runtime() -> None:
    staged = [
        "entry.py",
        "agents/main.md",
        "docs/specs/0001-version-command.md",  # RFC 施工规格：放行
        "docs/specs/OVERVIEW.md",
        "pyproject.toml",  # 结构性演进：放行
        "README.md",
        "src/harness/cli.py",
        "unicode_ascii/core.py",  # 容器围堵后不再当越界（agent 看不见宿主任务仓）
        "test_toplevel.py",
        ".gitea/workflows/smoke.yml",
        "__pycache__/entry.cpython-312.pyc",
        ".env",
        ".env.local",
        "secrets/.env.production",
        ".env.example",  # 模板：放行
        ".openagents/vigil-queue.db",
    ]
    assert violations(staged) == [
        ".env",
        ".env.local",
        "secrets/.env.production",
        ".openagents/vigil-queue.db",
    ]


def test_violations_empty_for_product_and_rfc() -> None:
    assert violations(["entry.py", "agents/main.md", "params.yaml", "agent.yaml"]) == []
    assert violations(["tests/test_smoke.py", "docs/specs/0001-x.md", "HELP.md"]) == []
    assert violations([]) == []
    assert violations(["  ", ""]) == []


def test_denied_top_is_runtime_only() -> None:
    assert DENIED_TOP == {".openagents"}


def test_gitea_ci_dir_is_allowed() -> None:
    """CI 定义随仓演进（rfc/结构改动可能要改 smoke）；存在性由 runner 跑，不再预提交拒写。"""
    assert violations([".gitea/workflows/smoke.yml"]) == []


def test_render_hook_is_executable_python() -> None:
    src = render_hook()
    assert src.startswith("#!/usr/bin/env python3")
    compile(src, "<hook>", "exec")


def test_hook_blocks_env_secret(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path)
    (repo / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    _git(repo, "add", "-A", "-f")
    res = _git(repo, "commit", "-m", "chore: leak env")
    assert res.returncode != 0
    assert "harness-boundary" in res.stderr
    assert ".env" in res.stderr
    assert _git(repo, "log", "--oneline").stdout.count("\n") == 1


def test_hook_blocks_openagents_runtime(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path)
    runtime = repo / ".openagents"
    runtime.mkdir()
    (runtime / "vigil-queue.db").write_text("x", encoding="utf-8")
    _git(repo, "add", "-A", "-f")
    res = _git(repo, "commit", "-m", "chore: commit vigil state")
    assert res.returncode != 0
    assert ".openagents/vigil-queue.db" in res.stderr


def test_hook_allows_rfc_docs_and_structural_dirs(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path)
    specs = repo / "docs" / "specs"
    specs.mkdir(parents=True)
    (specs / "0001-version-command.md").write_text("# spec\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname='harness'\n", encoding="utf-8")
    (repo / "README.md").write_text("# harness\n", encoding="utf-8")
    _git(repo, "add", "-A")
    res = _git(repo, "commit", "-m", "spec: add rfc docs")
    assert res.returncode == 0
    assert _git(repo, "log", "--oneline").stdout.count("\n") == 2


def test_hook_allows_harness_only_commit(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path)
    (repo / "agents").mkdir()
    (repo / "agents" / "main.md").write_text("# harness\n", encoding="utf-8")
    (repo / "HELP.md").write_text("# help\n", encoding="utf-8")
    (repo / "entry.py").write_text("print('v1')\n", encoding="utf-8")
    _git(repo, "add", "-A")
    res = _git(repo, "commit", "-m", "feat: improve harness scaffolding")
    assert res.returncode == 0
    assert _git(repo, "log", "--oneline").stdout.count("\n") == 2


def test_hook_allows_env_example(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path)
    (repo / ".env.example").write_text("TOKEN=\n", encoding="utf-8")
    _git(repo, "add", "-A")
    res = _git(repo, "commit", "-m", "docs: env template")
    assert res.returncode == 0


def test_hook_ignores_pyc_noise(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path)
    cache = repo / "__pycache__"
    cache.mkdir()
    (cache / "entry.cpython-312.pyc").write_bytes(b"\x00")
    (repo / "entry.py").write_text("print('v2')\n", encoding="utf-8")
    _git(repo, "add", "-A", "-f")
    res = _git(repo, "commit", "-m", "feat: tweak")
    assert res.returncode == 0
