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
    dest = tmp_path / "runs" / "main"
    assert (dest / "params.yaml").exists()
    marker = dest / "_reuse_marker"
    marker.write_text("x")  # 若二次 launch 复用该目录，marker 应仍在
    h2 = launcher.launch("main")
    h2.close()
    assert marker.exists()


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
