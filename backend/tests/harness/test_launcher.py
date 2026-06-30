"""spec-0003/T1：HarnessLauncher 单测，用最小假 entry（不依赖真 nexau）。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from auto_designer.harness.launcher import HarnessLauncher

# 计数器式假 entry：逐行回 "<count>:<message>"，count 随进程重启归零（验证 reset）。
_COUNTER_ENTRY = """\
import json, sys
count = 0
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)["message"]
    count += 1
    sys.stdout.write(json.dumps({"reply": f"{count}:{msg}"}) + "\\n")
    sys.stdout.flush()
"""
_BAD_JSON_ENTRY = (
    'import sys\nfor _ in sys.stdin:\n    sys.stdout.write("garbage\\n"); sys.stdout.flush()\n'
)
_NO_REPLY_ENTRY = (
    "import json, sys\nfor _ in sys.stdin:\n"
    '    sys.stdout.write(json.dumps({"x": 1}) + "\\n"); sys.stdout.flush()\n'
)
_EARLY_EXIT_ENTRY = "import sys\nsys.exit(0)\n"
# 固定回 "v2:<message>" 的 entry：用于验证同 ref 改内容后跑的是新代码而非陈旧缓存。
_V2_ENTRY = (
    "import json, sys\nfor line in sys.stdin:\n"
    "    line = line.strip()\n    if not line:\n        continue\n"
    '    msg = json.loads(line)["message"]\n'
    '    sys.stdout.write(json.dumps({"reply": f"v2:{msg}"}) + "\\n"); sys.stdout.flush()\n'
)
# 回 SANDBOX_WORK_DIR 当前值的 entry：验证 launch(workspace_dir=) 把它注入子进程 env。
_ENV_ECHO_ENTRY = (
    "import json, os, sys\nfor line in sys.stdin:\n"
    "    line = line.strip()\n    if not line:\n        continue\n"
    '    sys.stdout.write(json.dumps({"reply": os.environ.get("SANDBOX_WORK_DIR", "(unset)")})'
    ' + "\\n"); sys.stdout.flush()\n'
)


def _commit_all(repo: str, message: str) -> None:
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", message],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _make_repo(tmp_path: Path, entry_src: str, entry_argv: list[str]) -> str:
    repo = tmp_path / "harness_repo"
    repo.mkdir()
    (repo / "fake_entry.py").write_text(entry_src, encoding="utf-8")
    argv_yaml = "\n".join(f"  - {a}" for a in entry_argv)
    (repo / "params.yaml").write_text(f"entry:\n{argv_yaml}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "seed"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return str(repo)


def _launcher(
    tmp_path: Path, entry_src: str, entry_argv: list[str] | None = None
) -> HarnessLauncher:
    argv = entry_argv if entry_argv is not None else [sys.executable, "fake_entry.py"]
    repo = _make_repo(tmp_path, entry_src, argv)
    return HarnessLauncher(harness_repo=repo, runs_root=tmp_path / "runs")


def test_multi_turn_send(tmp_path) -> None:
    h = _launcher(tmp_path, _COUNTER_ENTRY).launch("main")
    try:
        assert h.send("a") == "1:a"
        assert h.send("b") == "2:b"
    finally:
        h.close()


def test_reset_restarts_and_clears_state(tmp_path) -> None:
    h = _launcher(tmp_path, _COUNTER_ENTRY).launch("main")
    try:
        assert h.send("a") == "1:a"
        h.reset()
        assert h.send("b") == "1:b"  # 计数器随重启归零
    finally:
        h.close()


def test_close_idempotent_and_send_after_close(tmp_path) -> None:
    h = _launcher(tmp_path, _COUNTER_ENTRY).launch("main")
    h.close()
    h.close()  # 幂等
    with pytest.raises(RuntimeError):
        h.send("x")


def test_checkout_writes_and_reuses(tmp_path) -> None:
    launcher = _launcher(tmp_path, _COUNTER_ENTRY)
    h1 = launcher.launch("main")
    h1.close()
    runs = tmp_path / "runs"
    dests = list(runs.iterdir())
    assert len(dests) == 1  # 单一 checkout 目录（名含 SHA）
    dest = dests[0]
    assert (dest / "params.yaml").exists()
    marker = dest / "_reuse_marker"
    marker.write_text("x")  # 若二次 launch 复用该目录，marker 应仍在
    h2 = launcher.launch("main")
    h2.close()
    assert marker.exists()  # 同 ref 同 SHA → 复用同目录
    assert list(runs.iterdir()) == dests  # 未新建目录


def test_checkout_invalidates_on_content_change(tmp_path) -> None:
    """根因回归：同一分支(main)内容变更后，必须跑新代码而非陈旧 checkout 缓存。"""
    launcher = _launcher(tmp_path, _COUNTER_ENTRY)
    launcher.launch("main").close()  # 先缓存旧内容

    repo = launcher._harness_repo  # 改 entry → main 指向新 SHA
    (Path(repo) / "fake_entry.py").write_text(_V2_ENTRY, encoding="utf-8")
    _commit_all(repo, "change entry")

    h = launcher.launch("main")
    try:
        assert h.send("a") == "v2:a"  # 跑的是新内容，不是旧缓存的计数器 entry
    finally:
        h.close()
    assert len(list((tmp_path / "runs").iterdir())) == 2  # 两个不同 SHA 的 checkout 并存


def test_entry_command_not_found_raises(tmp_path) -> None:
    launcher = _launcher(tmp_path, _COUNTER_ENTRY, entry_argv=["no_such_cmd_xyz_42"])
    with pytest.raises(FileNotFoundError):
        launcher.launch("main")


def test_ref_not_found_raises(tmp_path) -> None:
    with pytest.raises(RuntimeError):
        _launcher(tmp_path, _COUNTER_ENTRY).launch("nope-ref")


def test_bad_json_output_raises(tmp_path) -> None:
    h = _launcher(tmp_path, _BAD_JSON_ENTRY).launch("main")
    try:
        with pytest.raises(RuntimeError):
            h.send("a")
    finally:
        h.close()


def test_missing_reply_key_raises(tmp_path) -> None:
    h = _launcher(tmp_path, _NO_REPLY_ENTRY).launch("main")
    try:
        with pytest.raises(RuntimeError):
            h.send("a")
    finally:
        h.close()


def test_early_exit_eof_raises(tmp_path) -> None:
    h = _launcher(tmp_path, _EARLY_EXIT_ENTRY).launch("main")
    try:
        with pytest.raises(RuntimeError):
            h.send("a")
    finally:
        h.close()


# Spec-0008/T1 v2：共享工作区——launch(workspace_dir=) 把目录注入 harness 子进程 SANDBOX_WORK_DIR。
def test_launch_injects_workspace_dir_as_sandbox_work_dir(tmp_path) -> None:
    h = _launcher(tmp_path, _ENV_ECHO_ENTRY).launch("main", workspace_dir="/shared/ws")
    try:
        assert h.send("x") == "/shared/ws"  # 子进程看到注入的 SANDBOX_WORK_DIR
    finally:
        h.close()


def test_launch_without_workspace_dir_leaves_sandbox_work_dir_unset(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SANDBOX_WORK_DIR", raising=False)  # 隔离宿主环境可能的残留
    h = _launcher(tmp_path, _ENV_ECHO_ENTRY).launch("main")  # 不传 → 不注入（退化）
    try:
        assert h.send("x") == "(unset)"
    finally:
        h.close()
