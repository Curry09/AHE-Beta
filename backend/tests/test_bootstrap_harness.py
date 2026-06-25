"""spec-0002/T3：bootstrap_harness 单测，mock Gitea API + 临时 git（不触网、不真跑 git）。"""

from __future__ import annotations

from pathlib import Path

import requests

from bootstrap_harness import HARNESS_REPO, bootstrap_harness


class _Resp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeSession:
    """按 url 路由返回固定状态码；可设连接异常。记录 POST 调用供断言。"""

    def __init__(
        self, repo_status: int, branch_status: int, raise_exc: Exception | None = None
    ) -> None:
        self._repo_status = repo_status
        self._branch_status = branch_status
        self._raise = raise_exc
        self.calls: list[tuple[str, dict]] = []

    def post(self, url: str, json: dict) -> _Resp:
        if self._raise is not None:
            raise self._raise
        self.calls.append((url, json))
        if url.endswith("/user/repos"):
            return _Resp(self._repo_status)
        if url.endswith("/branches"):
            return _Resp(self._branch_status)
        raise AssertionError(f"unexpected url {url}")


class _GitRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    def __call__(self, args: list[str], cwd: str) -> None:
        self.calls.append((args, cwd))


def _repo_root_with_template(tmp_path: Path) -> Path:
    (tmp_path / "harness_template").mkdir()
    (tmp_path / "harness_template" / "entry.py").write_text("print('v0')\n", encoding="utf-8")
    return tmp_path


def _run(session: _FakeSession, git: _GitRecorder, repo_root: Path) -> int:
    return bootstrap_harness(
        session=session,
        run_git=git,
        repo_root=repo_root,
        gitea_url="http://gitea:3000",
        owner="o",
        token="T",
        harness_repo=HARNESS_REPO,
    )


def test_create_pushes_seed_and_branch(tmp_path) -> None:
    session = _FakeSession(repo_status=201, branch_status=201)
    git = _GitRecorder()
    rc = _run(session, git, _repo_root_with_template(tmp_path))
    assert rc == 0
    # 建仓命中 /user/repos 且参数含 harness 仓名
    repo_call = [c for c in session.calls if c[0].endswith("/user/repos")][0]
    assert repo_call[1]["name"] == HARNESS_REPO
    # 种子进单条初始提交并 push 到 main
    git_args = [a for a, _ in git.calls]
    assert ["init", "-b", "main"] in git_args
    assert any(a[:2] == ["push", "-u"] and a[-1] == "HEAD:main" for a in git_args)
    # release 分支经 API 建出，指向 main
    branch_call = [c for c in session.calls if c[0].endswith("/branches")][0]
    assert branch_call[1] == {"new_branch_name": "release", "old_branch_name": "main"}


def test_idempotent_existing_repo_skips_push(tmp_path) -> None:
    session = _FakeSession(repo_status=409, branch_status=409)
    git = _GitRecorder()
    rc = _run(session, git, _repo_root_with_template(tmp_path))
    assert rc == 0
    assert git.calls == []  # 仓已存在 → 不强推覆盖（保护演化历史）
    assert any(c[0].endswith("/branches") for c in session.calls)  # 仍确保 release 分支


def test_auth_failure_returns_nonzero_no_push(tmp_path) -> None:
    session = _FakeSession(repo_status=401, branch_status=201)
    git = _GitRecorder()
    rc = _run(session, git, _repo_root_with_template(tmp_path))
    assert rc == 1
    assert git.calls == []


def test_connection_error_returns_nonzero(tmp_path) -> None:
    session = _FakeSession(
        repo_status=201, branch_status=201, raise_exc=requests.ConnectionError("down")
    )
    git = _GitRecorder()
    rc = _run(session, git, _repo_root_with_template(tmp_path))
    assert rc == 1
    assert git.calls == []


def test_missing_template_returns_2_no_remote_write(tmp_path) -> None:
    session = _FakeSession(repo_status=201, branch_status=201)
    git = _GitRecorder()
    rc = _run(session, git, tmp_path)  # 无 harness_template
    assert rc == 2
    assert session.calls == []  # 前置失败，不发起任何远端写
    assert git.calls == []


def test_empty_template_returns_2(tmp_path) -> None:
    (tmp_path / "harness_template").mkdir()  # 存在但为空
    session = _FakeSession(repo_status=201, branch_status=201)
    rc = _run(session, _GitRecorder(), tmp_path)
    assert rc == 2
    assert session.calls == []
