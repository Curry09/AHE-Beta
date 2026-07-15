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
# 读一行后长睡不回：让读线程卡在 stdout.readline() 里（在途），用于收尾竞态回归。
_BLOCKING_ENTRY = "import sys, time\nsys.stdin.readline()\ntime.sleep(300)\n"
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


def test_checkout_concurrent_same_sha_yields_single_intact_copy(tmp_path) -> None:
    """Spec-0017/T5 竞态回归：并行会话同 SHA 同时 checkout，params.yaml 绝不被交错写坏。

    加锁 + 临时目录原子 rename 前：多线程同时通过存在性检查 → 并发 extractall 同一目录
    （params.yaml 被叠写出重复 entry 键/乱字节，生产实跑踩中），或复用他人半解压目录。
    屏障齐射逼出竞态窗口；重复键会让 safe YAML 抛 DuplicateKeyError，即断言失败。
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from ruamel.yaml import YAML

    launcher = _launcher(tmp_path, _COUNTER_ENTRY)
    n = 8
    barrier = threading.Barrier(n)

    def checkout(_: int) -> str:
        barrier.wait()  # 齐射：全员同时冲 check-then-extract
        return str(launcher._checkout(ref="main"))

    with ThreadPoolExecutor(max_workers=n) as pool:
        dests = list(pool.map(checkout, range(n)))

    assert len(set(dests)) == 1  # 全部落到同一 checkout 目录
    runs = tmp_path / "runs"
    assert [d.name for d in runs.iterdir()] == [Path(dests[0]).name]  # 无 tmp 残留、无重复目录
    params = YAML(typ="safe").load((Path(dests[0]) / "params.yaml").read_text(encoding="utf-8"))
    assert isinstance(params["entry"], list) and params["entry"]  # 结构完好、单一 entry 键
    assert (Path(dests[0]) / "fake_entry.py").is_file()  # 副本内容完整


def test_read_params_concurrent_parses_cleanly(tmp_path) -> None:
    """Spec-0017/T5 追加：ruamel YAML 实例非线程安全 → 每次解析新建实例。

    旧实现共享模块级单例 _yaml，并行 launch 并发 load 会搅乱解析器内部状态（生产实跑踩中）。
    屏障齐射并发解析同一 params.yaml，断言全部结果完好一致。
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "params.yaml").write_text(
        "entry:\n  - python\n  - entry.py\nenv:\n  K: v\n", encoding="utf-8"
    )
    launcher = HarnessLauncher(harness_repo="unused", runs_root=tmp_path / "runs")
    n = 16
    barrier = threading.Barrier(n)

    def read(_: int) -> dict:
        barrier.wait()  # 齐射：并发进解析器
        return launcher._read_params(dest)

    with ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(read, range(n)))
    assert all(r == {"entry": ["python", "entry.py"], "env": {"K": "v"}} for r in results)


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


def test_terminate_while_reader_blocked_leaves_no_thread_error(tmp_path) -> None:
    """收尾竞态回归：一轮 send 在途（读线程正卡在 stdout.readline()）时 close()，
    不得让读线程抛 ValueError: I/O operation on closed file / AttributeError。

    _terminate 必须先杀进程、让读线程靠 EOF 收场并 join，之后再关流 / 置空 _proc；反序会与
    仍卡在 readline() 的读线程抢同一 stdout / _proc。用 threading.excepthook 捕获后台线程异常。
    """
    import threading

    errors: list = []
    prev_hook = threading.excepthook
    threading.excepthook = errors.append  # 任何后台线程未捕获异常都会落进 errors
    try:
        h = _launcher(tmp_path, _BLOCKING_ENTRY).launch("main")
        h.begin("x")
        kind, _ = h.poll(0.5)
        assert kind == "pending"  # 确认读线程正卡在 readline()（在途）
        reader = h._reader
        assert reader is not None
        h.close()  # 收尾：必须干净——读线程靠 EOF 退出，主线程随后关流才无并发
        reader.join(timeout=5)
        assert not reader.is_alive()  # 读线程已因 EOF 自然退出，未泄漏
    finally:
        threading.excepthook = prev_hook
    assert errors == []  # 后台读线程全程未抛异常（反序实现会在此落进 I/O closed file）


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


# 用户手册：checkout 时读 MANUAL.md 全文挂到句柄，供用户 agent 形成能力预期。
def test_launch_exposes_manual_from_repo(tmp_path) -> None:
    launcher = _launcher(tmp_path, _COUNTER_ENTRY)
    repo = launcher._harness_repo
    (Path(repo) / "MANUAL.md").write_text("# Manual\nno live progress.\n", encoding="utf-8")
    _commit_all(repo, "add manual")
    h = launcher.launch("main")
    try:
        assert "no live progress" in h.manual
    finally:
        h.close()


def test_launch_manual_empty_when_absent(tmp_path) -> None:
    h = _launcher(tmp_path, _COUNTER_ENTRY).launch("main")  # repo 无 MANUAL.md
    try:
        assert h.manual == ""
    finally:
        h.close()
