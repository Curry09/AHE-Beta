"""spec-0003/T1：HarnessLauncher 单测，用最小假 entry（不依赖真 nexau）。"""

from __future__ import annotations

import json
import os
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
    msg = json.loads(line)["text"]
    count += 1
    sys.stdout.write(json.dumps({"type": "reply", "text": f"{count}:{msg}"}) + "\\n")
    sys.stdout.flush()
"""
_BAD_JSON_ENTRY = (
    'import sys\nfor _ in sys.stdin:\n    sys.stdout.write("garbage\\n"); sys.stdout.flush()\n'
)
_NO_REPLY_ENTRY = (
    "import json, sys\nfor _ in sys.stdin:\n"
    '    sys.stdout.write(json.dumps({"type": "custom", "x": 1}) + "\\n"); sys.stdout.flush()\n'
)
_EARLY_EXIT_ENTRY = "import sys\nsys.exit(0)\n"
# 读一行后长睡不回：让读线程卡在 stdout.readline() 里（在途），用于收尾竞态回归。
_BLOCKING_ENTRY = "import sys, time\nsys.stdin.readline()\ntime.sleep(300)\n"
# 固定回 "v2:<message>" 的 entry：用于验证同 ref 改内容后跑的是新代码而非陈旧缓存。
_V2_ENTRY = (
    "import json, sys\nfor line in sys.stdin:\n"
    "    line = line.strip()\n    if not line:\n        continue\n"
    '    msg = json.loads(line)["text"]\n'
    '    sys.stdout.write(json.dumps({"type": "reply", "text": f"v2:{msg}"}) + "\\n"); sys.stdout.flush()\n'
)
# 回 SANDBOX_WORK_DIR 当前值的 entry：验证 launch(workspace_dir=) 把它注入子进程 env。
_ENV_ECHO_ENTRY = (
    "import json, os, sys\nfor line in sys.stdin:\n"
    "    line = line.strip()\n    if not line:\n        continue\n"
    '    sys.stdout.write(json.dumps({"type": "reply", "text": os.environ.get("SANDBOX_WORK_DIR", "(unset)")})'
    ' + "\\n"); sys.stdout.flush()\n'
)
_TYPED_ENTRY = """\
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    obj = json.loads(line)
    if obj.get("type") == "message":
        sys.stdout.write(json.dumps({"type": "progress", "kind": "tool", "text": "typed-progress"}) + "\\n")
        sys.stdout.write(json.dumps({"type": "reply", "text": "typed:" + obj["text"], "steps": [{"kind": "tool", "text": "typed"}]}) + "\\n")
        sys.stdout.flush()
    elif obj.get("type") == "interrupt":
        sys.stdout.write(json.dumps({"type": "reply", "text": "[interrupted]"}) + "\\n")
        sys.stdout.flush()
"""
_TYPED_ERROR_ENTRY = """\
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    json.loads(line)
    sys.stdout.write(json.dumps({"type": "error", "message": "boom", "recoverable": False}) + "\\n")
    sys.stdout.flush()
"""
_TYPED_TIMEOUT_STATUS_ENTRY = """\
import json, sys
for line in sys.stdin:
    obj = json.loads(line)
    if obj.get("type") == "message":
        sys.stdout.write(json.dumps({"type": "reply", "text": "timed out", "status": "timed_out", "termination_reason": "task_budget_exhausted"}) + "\\n")
        sys.stdout.flush()
"""
_TYPED_USAGE_ENTRY = """\
import json, sys
for line in sys.stdin:
    obj = json.loads(line)
    if obj.get("type") == "message":
        sys.stdout.write(json.dumps({"type": "usage", "provider": "nexau", "model": "m", "input_tokens": 7, "output_tokens": 3, "total_tokens": 10, "usage_source": "reported", "agent_run_id": "h1"}) + "\\n")
        sys.stdout.write(json.dumps({"type": "reply", "text": "done"}) + "\\n")
        sys.stdout.flush()
"""
_TYPED_POST_REPLY_USAGE_ENTRY = """\
import json, sys, time
for line in sys.stdin:
    obj = json.loads(line)
    if obj.get("type") == "message":
        sys.stdout.write(json.dumps({"type": "reply", "text": "done"}) + "\\n")
        sys.stdout.flush()
        time.sleep(0.05)
        sys.stdout.write(json.dumps({"type": "usage", "total_tokens": 12, "usage_source": "reported"}) + "\\n")
        sys.stdout.flush()
"""
_TYPED_INTERRUPT_ENTRY = """\
import json, sys, threading, time
busy = {"on": False}

def work():
    while busy["on"]:
        sys.stdout.write(json.dumps({"type": "progress", "kind": "tool", "text": "working"}) + "\\n")
        sys.stdout.flush()
        time.sleep(0.15)

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    obj = json.loads(line)
    if obj.get("type") == "message":
        busy["on"] = True
        threading.Thread(target=work, daemon=True).start()
    elif obj.get("type") == "interrupt":
        busy["on"] = False
        sys.stdout.write(json.dumps({"type": "reply", "text": "[interrupted]"}) + "\\n")
        sys.stdout.flush()
"""


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


def test_managed_local_launcher_and_real_tools_inherit_independent_session_env(
    tmp_path, monkeypatch
):
    from auto_designer.user.sim.runtime import LocalWorkspaceRuntime

    # Exercise Git checkout, native Harness startup and its real Python tool;
    # no launcher/Popen mocks or process-global task environment switching.
    entry = """import json,os,pathlib,subprocess,sys
for line in sys.stdin:
    json.loads(line)
    keys=['HOME','VIRTUAL_ENV','AUTO_DESIGNER_ATTEMPT_NONCE','UV_LINK_MODE','UV_CACHE_DIR','HARNESS_ONLY']
    values={key:os.environ.get(key) for key in keys}
    values['entry_interpreter']=sys.executable
    tool="import json,os,pathlib,sys;pathlib.Path(os.environ['HOME'],'tool-written').write_text(os.environ['AUTO_DESIGNER_ATTEMPT_NONCE']);print(json.dumps({'home':os.environ['HOME'],'prefix':sys.prefix,'nonce':os.environ['AUTO_DESIGNER_ATTEMPT_NONCE'],'cache':os.environ['UV_CACHE_DIR'],'link_mode':os.environ['UV_LINK_MODE']}))"
    values['tool']=json.loads(subprocess.check_output(['python','-c',tool],cwd=os.environ['SANDBOX_WORK_DIR'],text=True))
    print(json.dumps({'type':'reply','text':json.dumps(values)}),flush=True)
"""
    repo = _make_repo(tmp_path, entry, ["python", "fake_entry.py"])
    defaults = {
        "HOME": "/shared-harness-home",
        "UV_CACHE_DIR": "/shared-harness-cache",
        "AUTO_DESIGNER_ATTEMPT_NONCE": "wrong-harness-nonce",
        "UV_LINK_MODE": "hardlink",
        "HARNESS_ONLY": "kept",
    }
    Path(repo, "params.yaml").write_text(
        "entry: [python, fake_entry.py]\nenv: " + json.dumps(defaults) + "\n"
    )
    _commit_all(repo, "configure default harness environment")
    controller_home = tmp_path / "controller-home"
    controller_home.mkdir()
    monkeypatch.setenv("HOME", str(controller_home))
    monkeypatch.setenv("AUTO_DESIGNER_ATTEMPT_NONCE", "controller-nonce")
    before = dict(os.environ)
    launcher = HarnessLauncher(harness_repo=repo, runs_root=tmp_path / "runs")
    handles = []
    try:
        for user in ("a", "b"):
            attempt = tmp_path / ("attempt-" + user)
            workspace, home, cache = attempt / "repo", attempt / "home", attempt / "cache"
            workspace.mkdir(parents=True)
            home.mkdir()
            cache.mkdir()
            venv = workspace / ".venv"
            subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True)
            runtime = LocalWorkspaceRuntime(
                str(workspace),
                environment={
                    "HOME": str(home),
                    "VIRTUAL_ENV": str(venv),
                    "UV_CACHE_DIR": str(cache),
                    "UV_LINK_MODE": "copy",
                    "AUTO_DESIGNER_ATTEMPT_NONCE": "attempt-" + user,
                    "PATH": "/usr/bin:/bin",
                },
                evidence={"task_virtual_env": str(venv), "harness_python": sys.executable},
            )
            handles.append((launcher.launch("main", runtime), runtime))
        for handle, runtime in handles:
            observed = json.loads(handle.send("check environment"))
            assert observed["entry_interpreter"] == sys.executable
            assert observed["HARNESS_ONLY"] == "kept"
            for key in (
                "HOME",
                "VIRTUAL_ENV",
                "AUTO_DESIGNER_ATTEMPT_NONCE",
                "UV_LINK_MODE",
                "UV_CACHE_DIR",
            ):
                assert observed[key] == runtime.environment[key]
            assert observed["tool"] == {
                "home": runtime.environment["HOME"],
                "prefix": runtime.evidence["task_virtual_env"],
                "nonce": runtime.environment["AUTO_DESIGNER_ATTEMPT_NONCE"],
                "cache": runtime.environment["UV_CACHE_DIR"],
                "link_mode": "copy",
            }
            assert (
                Path(runtime.environment["HOME"], "tool-written").read_text()
                == runtime.environment["AUTO_DESIGNER_ATTEMPT_NONCE"]
            )
        assert not (controller_home / "tool-written").exists()
        assert dict(os.environ) == before
    finally:
        for handle, runtime in handles:
            handle.close()
            runtime.close()


def test_usage_sideband_is_isolated_and_drained_once(tmp_path) -> None:
    h = _launcher(tmp_path, _TYPED_USAGE_ENTRY).launch("main")
    try:
        assert h.send("a") == "done"
        assert h.last_progress == []
        assert h.last_visible_events[-1]["type"] == "reply"
        assert [event["type"] for event in h.last_visible_events] == ["reply"]
        events = h.drain_usage_events()
        assert len(events) == 1
        assert events[0]["total_tokens"] == 10
        assert h.drain_usage_events() == []
    finally:
        h.close()


def test_reply_status_is_recorded_as_request_outcome(tmp_path) -> None:
    launcher = _launcher(tmp_path, _TYPED_TIMEOUT_STATUS_ENTRY)
    repo = Path(launcher._harness_repo)
    (repo / "params.yaml").write_text(
        "entry:\n  - python\n  - fake_entry.py\nprotocol: stdio-jsonl-v1\n", encoding="utf-8"
    )
    _commit_all(repo, "enable v1 timeout status")
    h = launcher.launch("main")
    try:
        assert h.send("a") == "timed out"
        assert h.request_outcomes[-1]["status"] == "timed_out"
        assert h.request_outcomes[-1]["started_at"]
        assert h.request_outcomes[-1]["finished_at"]
        assert h.last_request_status == "timed_out"
    finally:
        h.close()


def test_usage_arriving_shortly_after_reply_is_captured(tmp_path) -> None:
    h = _launcher(tmp_path, _TYPED_POST_REPLY_USAGE_ENTRY).launch("main")
    try:
        assert h.send("a") == "done"
        assert h.drain_usage_events() == [
            {"type": "usage", "total_tokens": 12, "usage_source": "reported"}
        ]
        assert h.drain_usage_events() == []
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


def test_unknown_sideband_is_accepted_without_protocol_error(tmp_path) -> None:
    """非 reply 的未知 JSON 旁路应被收下，不再报「既无 reply 也无 progress」。"""
    h = _launcher(tmp_path, _NO_REPLY_ENTRY).launch("main")
    try:
        h.begin("a")
        kind, _ = h.poll(1.0)
        assert kind == "pending"
        assert h.last_sideband and h.last_sideband[0].get("x") == 1
        assert any(p.get("kind") == "sideband" for p in h.last_progress)
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


def test_typed_protocol_sends_type_message_and_reads_type_reply_progress(tmp_path) -> None:
    launcher = _launcher(tmp_path, _TYPED_ENTRY)
    repo = Path(launcher._harness_repo)
    (repo / "params.yaml").write_text(
        "entry:\n  - python\n  - fake_entry.py\nprotocol: stdio-jsonl-v1\n", encoding="utf-8"
    )
    _commit_all(repo, "declare typed protocol")
    h = launcher.launch("main")
    try:
        assert h.send("hello") == "typed:hello"
        assert h.last_progress == [{"kind": "tool", "text": "typed-progress"}]
        assert h.last_steps == [{"kind": "tool", "text": "typed"}]
        events = h.drain_visible_events()
        assert [e["type"] for e in events] == ["progress", "reply"]
        assert [e["text"] for e in events] == ["typed-progress", "typed:hello"]
        assert all(e["source"] == "harness_stdout" for e in events)
        assert h.drain_visible_events() == []
    finally:
        h.close()


_POST_REPLY_STATUS_ENTRY = """\
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    sys.stdout.write(json.dumps({"type": "reply", "text": "done"}) + "\\n")
    sys.stdout.flush()
    sys.stdout.write(json.dumps({"type": "status", "text": "handling queued"}) + "\\n")
    sys.stdout.flush()
"""


def test_post_reply_status_is_drained_as_visible_event(tmp_path) -> None:
    h = _launcher(tmp_path, _POST_REPLY_STATUS_ENTRY).launch("main")
    try:
        assert h.send("a") == "done"
        events = h.drain_visible_events()
        assert [e["type"] for e in events] == ["reply", "status"]
        assert "handling queued" in events[1]["text"]
    finally:
        h.close()


_FOLLOWUP_REPLY_ENTRY = """\
import json, sys, time
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    sys.stdout.write(json.dumps({"type": "reply", "text": "first"}) + "\\n")
    sys.stdout.flush()
    time.sleep(0.05)
    sys.stdout.write(json.dumps({"type": "status", "text": "handling queued"}) + "\\n")
    sys.stdout.flush()
    time.sleep(0.05)
    sys.stdout.write(json.dumps({"type": "reply", "text": "second-queued"}) + "\\n")
    sys.stdout.flush()
"""


def test_poll_after_reply_gets_followup(tmp_path) -> None:
    """reply 后仍能 poll 到后续 queued 工作的 reply（主 loop keep_waiting；Spec-0036）。"""
    h = _launcher(tmp_path, _FOLLOWUP_REPLY_ENTRY).launch("main")
    try:
        h.write_message("a")
        kind, val = h.poll(2.0)
        assert kind == "reply"
        assert val == "first"
        assert h.in_flight is False
        kind2, val2 = h.poll(2.0)
        assert kind2 == "reply"
        assert val2 == "second-queued"
        assert h.in_flight is False
    finally:
        h.close()


def test_poll_timeout_when_idle(tmp_path) -> None:
    h = _launcher(tmp_path, _POST_REPLY_STATUS_ENTRY).launch("main")
    try:
        assert h.send("a") == "done"
        assert h.in_flight is False
        kind, _ = h.poll(0.3)
        assert kind == "pending"
    finally:
        h.close()


def test_typed_protocol_interrupt_uses_type_interrupt(tmp_path) -> None:
    launcher = _launcher(tmp_path, _TYPED_INTERRUPT_ENTRY)
    repo = Path(launcher._harness_repo)
    (repo / "params.yaml").write_text(
        "entry:\n  - python\n  - fake_entry.py\nprotocol: stdio-jsonl-v1\n", encoding="utf-8"
    )
    _commit_all(repo, "declare typed protocol")
    h = launcher.launch("main")
    try:
        h.begin("long")
        assert h.control("interrupt") == "[interrupted]"
    finally:
        h.close()


def test_typed_protocol_error_raises(tmp_path) -> None:
    launcher = _launcher(tmp_path, _TYPED_ERROR_ENTRY)
    repo = Path(launcher._harness_repo)
    (repo / "params.yaml").write_text(
        "entry:\n  - python\n  - fake_entry.py\nprotocol: stdio-jsonl-v1\n", encoding="utf-8"
    )
    _commit_all(repo, "declare typed protocol")
    h = launcher.launch("main")
    try:
        with pytest.raises(RuntimeError, match="boom"):
            h.send("x")
    finally:
        h.close()


def test_unknown_protocol_raises(tmp_path) -> None:
    launcher = _launcher(tmp_path, _COUNTER_ENTRY)
    repo = Path(launcher._harness_repo)
    (repo / "params.yaml").write_text(
        "entry:\n  - python\n  - fake_entry.py\nprotocol: nope\n", encoding="utf-8"
    )
    _commit_all(repo, "unsupported protocol")
    with pytest.raises(ValueError, match="protocol"):
        launcher.launch("main")


# 帮助文本：checkout 时只读 HELP.md 全文挂到句柄。
def test_launch_exposes_help_md_from_repo(tmp_path) -> None:
    launcher = _launcher(tmp_path, _COUNTER_ENTRY)
    repo = launcher._harness_repo
    (Path(repo) / "HELP.md").write_text("# Help\nlive progress supported.\n", encoding="utf-8")
    _commit_all(repo, "add help")
    h = launcher.launch("main")
    try:
        assert "live progress supported" in h.help_text
    finally:
        h.close()


def test_launch_help_text_empty_when_help_absent(tmp_path) -> None:
    launcher = _launcher(tmp_path, _COUNTER_ENTRY)
    repo = launcher._harness_repo
    (Path(repo) / "USER.md").write_text("# User\nlegacy only.\n", encoding="utf-8")
    (Path(repo) / "MANUAL.md").write_text("# Retired\nlegacy only.\n", encoding="utf-8")
    _commit_all(repo, "add retired docs")
    h = launcher.launch("main")
    try:
        assert h.help_text == ""
    finally:
        h.close()


# 进度旁路：reply 前可多行 type=progress；poll pending 期间 last_progress 可见。
_PROGRESS_ENTRY = """\
import json, sys, time
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    obj = json.loads(line)
    if obj.get("type") == "interrupt":
        sys.stdout.write(json.dumps({"type": "reply", "text": "[interrupted]"}) + "\\n")
        sys.stdout.flush()
        continue
    for text in ("read core.py", "run pytest"):
        sys.stdout.write(json.dumps({"type": "progress", "kind": "tool", "text": text}) + "\\n")
        sys.stdout.flush()
        time.sleep(0.15)
    sys.stdout.write(json.dumps({"type": "reply", "text": "all done", "steps": [{"kind": "tool", "text": "x"}]}) + "\\n")
    sys.stdout.flush()
"""


def test_progress_lines_accumulate_before_reply(tmp_path) -> None:
    h = _launcher(tmp_path, _PROGRESS_ENTRY).launch("main")
    try:
        h.begin("go")
        # 第一次短 poll 多半还在跑 → pending，但可能已读到部分 progress
        kind, val = h.poll(0.05)
        # 等到终态
        while kind == "pending":
            kind, val = h.poll(2.0)
        assert kind == "reply"
        assert val == "all done"
        texts = [p.get("text") for p in h.last_progress]
        assert "read core.py" in texts
        assert "run pytest" in texts
        assert h.last_steps == [{"kind": "tool", "text": "x"}]
    finally:
        h.close()


# status/peek 旁路型 control：吐 status、不结束本轮；夹杂的 progress 不算应答。
_STATUS_PEEK_ENTRY = """\
import json, sys, threading, time
busy = {"on": False}

def work():
    n = 0
    while busy["on"]:
        n += 1
        sys.stdout.write(json.dumps({"type": "progress", "kind": "tool", "text": f"step-{n}"}) + "\\n")
        sys.stdout.flush()
        time.sleep(0.15)

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    obj = json.loads(line)
    if obj.get("type") in ("status", "peek"):
        sys.stdout.write(json.dumps({
            "type": "status", "status": {"phase": "running", "elapsed": 0.4, "completed": False,
                       "current_step": {"kind": "tool", "text": "pytest"}}
        }) + "\\n")
        sys.stdout.flush()
        continue
    if obj.get("type") == "interrupt":
        busy["on"] = False
        time.sleep(0.05)
        sys.stdout.write(json.dumps({"type": "reply", "text": "[interrupted]"}) + "\\n")
        sys.stdout.flush()
        continue
    if obj.get("type") == "message":
        busy["on"] = True
        threading.Thread(target=work, daemon=True).start()
"""


def test_status_control_returns_sideband_and_keeps_inflight(tmp_path) -> None:
    h = _launcher(tmp_path, _STATUS_PEEK_ENTRY).launch("main")
    try:
        h.begin("go")
        h.poll(0.25)
        out = h.control("status")
        assert "phase=running" in out
        assert h.in_flight is True  # 旁路型控制不结束本轮
        # 本轮仍可用终结型 control 收尾
        assert h.control("interrupt") == "[interrupted]"
        assert h.in_flight is False
    finally:
        h.close()


def test_interrupt_control_still_ends_with_reply(tmp_path) -> None:
    h = _launcher(tmp_path, _STATUS_PEEK_ENTRY).launch("main")
    try:
        h.begin("go")
        h.poll(0.2)
        out = h.control("interrupt")
        assert out == "[interrupted]"
        assert h.in_flight is False
    finally:
        h.close()


# in-flight 再塞 message：框架允许写入；本桩忽略第二条 message，仍跑到 interrupt 才结束。
_MIDFLIGHT_MSG_ENTRY = """\
import json, sys, threading, time
busy = {"on": False}
seen = []

def work():
    while busy["on"]:
        sys.stdout.write(json.dumps({"type": "progress", "kind": "tool", "text": "working"}) + "\\n")
        sys.stdout.flush()
        time.sleep(0.12)

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    obj = json.loads(line)
    if obj.get("type") == "interrupt":
        busy["on"] = False
        time.sleep(0.05)
        sys.stdout.write(json.dumps({"type": "reply", "text": "[interrupted] saw=" + ",".join(seen)}) + "\\n")
        sys.stdout.flush()
        continue
    if obj.get("type") == "message":
        seen.append(obj["text"])
        if not busy["on"]:
            busy["on"] = True
            threading.Thread(target=work, daemon=True).start()
"""


def test_write_message_while_awaiting_keeps_soft_flag(tmp_path) -> None:
    """统一写：等待中再写仍合法；软 awaiting 旗标保持（Spec-0036）。"""
    h = _launcher(tmp_path, _MIDFLIGHT_MSG_ENTRY).launch("main")
    try:
        h.write_message("first")
        h.poll(0.2)
        assert h.in_flight is True
        h.write_message("/btw still going?")
        assert h.in_flight is True
        kind, _ = h.poll(0.2)
        assert kind == "pending"
        assert h.control("interrupt").startswith("[interrupted]")
        assert h.in_flight is False
    finally:
        h.close()


def test_double_write_message_allowed(tmp_path) -> None:
    """连续两次写 message 无需中间虚构轮次锁（Spec-0036）。"""
    h = _launcher(tmp_path, _MIDFLIGHT_MSG_ENTRY).launch("main")
    try:
        h.write_message("first")
        h.write_message("second")  # 不再要求中间 reply
        assert h.in_flight is True
        assert h.control("interrupt").startswith("[interrupted]")
    finally:
        h.close()


def test_write_message_alias_begin_and_emit(tmp_path) -> None:
    """begin/emit_message 为 write_message 的 deprecated 别名。"""
    h = _launcher(tmp_path, _COUNTER_ENTRY).launch("main")
    try:
        h.begin("a")
        assert h.poll(2.0)[0] == "reply"
        h.emit_message("b")
        kind, val = h.poll(2.0)
        assert kind == "reply"
        assert val == "2:b"
    finally:
        h.close()


@pytest.mark.parametrize("receive", ["poll", "try_reply"])
def test_untyped_reply_is_rejected(tmp_path, receive):
    entry = 'import json,sys\nfor line in sys.stdin:\n    print(json.dumps({"reply":"done"}),flush=True)\n'
    h = _launcher(tmp_path, entry).launch("main")
    try:
        h.write_message("hello")
        if receive == "try_reply":
            h._reader.join(timeout=0.05)
            # Synchronize with the stdout reader without imposing a product timeout.
            import time

            deadline = time.monotonic() + 2
            while h._line_q.empty() and time.monotonic() < deadline:
                time.sleep(0.01)
        with pytest.raises(RuntimeError, match="type"):
            h.poll(2) if receive == "poll" else h.try_reply()
        assert h.last_request_status == "crashed"
        assert h.request_outcomes[-1]["termination_source"] == "protocol"
    finally:
        h.close()
