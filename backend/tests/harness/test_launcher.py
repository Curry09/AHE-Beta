"""spec-0003/T1: HarnessLauncher unit tests, using a minimal fake entry (no dependency on the real nexau)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ahe_beta.harness.launcher import HarnessLauncher

# Counter-style fake entry: replies line by line with "<count>:<message>", count resets to zero on process restart (verifies reset).
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
# After reading one line, sleeps long and never responds: keeps the reader thread stuck in stdout.readline() (in flight), used for teardown race regression.
_BLOCKING_ENTRY = "import sys, time\nsys.stdin.readline()\ntime.sleep(300)\n"
# Entry that always replies "v2:<message>": used to verify that after the content changes under the same ref, the new code runs rather than a stale cache.
_V2_ENTRY = (
    "import json, sys\nfor line in sys.stdin:\n"
    "    line = line.strip()\n    if not line:\n        continue\n"
    '    msg = json.loads(line)["text"]\n'
    '    sys.stdout.write(json.dumps({"type": "reply", "text": f"v2:{msg}"}) + "\\n"); sys.stdout.flush()\n'
)
# Entry that replies with the current value of SANDBOX_WORK_DIR: verifies that launch(workspace_dir=) injects it into the subprocess env.
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
    from ahe_beta.user.sim.runtime import LocalWorkspaceRuntime

    # Exercise Git checkout, native Harness startup and its real Python tool;
    # no launcher/Popen mocks or process-global task environment switching.
    entry = """import json,os,pathlib,subprocess,sys
for line in sys.stdin:
    json.loads(line)
    keys=['HOME','VIRTUAL_ENV','AHE_BETA_ATTEMPT_NONCE','UV_LINK_MODE','UV_CACHE_DIR','HARNESS_ONLY']
    values={key:os.environ.get(key) for key in keys}
    values['entry_interpreter']=sys.executable
    tool="import json,os,pathlib,sys;pathlib.Path(os.environ['HOME'],'tool-written').write_text(os.environ['AHE_BETA_ATTEMPT_NONCE']);print(json.dumps({'home':os.environ['HOME'],'prefix':sys.prefix,'nonce':os.environ['AHE_BETA_ATTEMPT_NONCE'],'cache':os.environ['UV_CACHE_DIR'],'link_mode':os.environ['UV_LINK_MODE']}))"
    values['tool']=json.loads(subprocess.check_output(['python','-c',tool],cwd=os.environ['SANDBOX_WORK_DIR'],text=True))
    print(json.dumps({'type':'reply','text':json.dumps(values)}),flush=True)
"""
    repo = _make_repo(tmp_path, entry, ["python", "fake_entry.py"])
    defaults = {
        "HOME": "/shared-harness-home",
        "UV_CACHE_DIR": "/shared-harness-cache",
        "AHE_BETA_ATTEMPT_NONCE": "wrong-harness-nonce",
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
    monkeypatch.setenv("AHE_BETA_ATTEMPT_NONCE", "controller-nonce")
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
                    "AHE_BETA_ATTEMPT_NONCE": "attempt-" + user,
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
                "AHE_BETA_ATTEMPT_NONCE",
                "UV_LINK_MODE",
                "UV_CACHE_DIR",
            ):
                assert observed[key] == runtime.environment[key]
            assert observed["tool"] == {
                "home": runtime.environment["HOME"],
                "prefix": runtime.evidence["task_virtual_env"],
                "nonce": runtime.environment["AHE_BETA_ATTEMPT_NONCE"],
                "cache": runtime.environment["UV_CACHE_DIR"],
                "link_mode": "copy",
            }
            assert (
                Path(runtime.environment["HOME"], "tool-written").read_text()
                == runtime.environment["AHE_BETA_ATTEMPT_NONCE"]
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
        assert h.send("b") == "1:b"  # Counter resets to zero on restart
    finally:
        h.close()


def test_close_idempotent_and_send_after_close(tmp_path) -> None:
    h = _launcher(tmp_path, _COUNTER_ENTRY).launch("main")
    h.close()
    h.close()  # Idempotent
    with pytest.raises(RuntimeError):
        h.send("x")


def test_checkout_writes_and_reuses(tmp_path) -> None:
    launcher = _launcher(tmp_path, _COUNTER_ENTRY)
    h1 = launcher.launch("main")
    h1.close()
    runs = tmp_path / "runs"
    dests = list(runs.iterdir())
    assert len(dests) == 1  # Single checkout directory (name contains the SHA)
    dest = dests[0]
    assert (dest / "params.yaml").exists()
    marker = dest / "_reuse_marker"
    # If a second launch reuses this directory, the marker should still be there
    marker.write_text("x")
    h2 = launcher.launch("main")
    h2.close()
    assert marker.exists()  # Same ref, same SHA → reuses the same directory
    assert list(runs.iterdir()) == dests  # No new directory created


def test_checkout_invalidates_on_content_change(tmp_path) -> None:
    """Root-cause regression: after content changes on the same branch (main), the new code must run rather than a stale checkout cache."""
    launcher = _launcher(tmp_path, _COUNTER_ENTRY)
    launcher.launch("main").close()  # Cache the old content first

    repo = launcher._harness_repo  # Change the entry → main points to the new SHA
    (Path(repo) / "fake_entry.py").write_text(_V2_ENTRY, encoding="utf-8")
    _commit_all(repo, "change entry")

    h = launcher.launch("main")
    try:
        assert h.send("a") == "v2:a"  # The new content runs, not the old cached counter entry
    finally:
        h.close()
    # Two checkouts with different SHAs coexist
    assert len(list((tmp_path / "runs").iterdir())) == 2


def test_checkout_concurrent_same_sha_yields_single_intact_copy(tmp_path) -> None:
    """Spec-0017/T5 race regression: parallel sessions checkout the same SHA simultaneously; params.yaml must never be corrupted by interleaved writes.

    Before locking + atomic rename of a temp directory: multiple threads pass the existence check at the same time → concurrent extractall into the same directory
    (params.yaml gets overlaid writes producing duplicate entry keys/garbled bytes — hit in a real production run), or another session's half-extracted directory gets reused.
    A barrier salvo forces out the race window; duplicate keys make safe YAML raise DuplicateKeyError, which means the assertion fails.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from ruamel.yaml import YAML

    launcher = _launcher(tmp_path, _COUNTER_ENTRY)
    n = 8
    barrier = threading.Barrier(n)

    def checkout(_: int) -> str:
        barrier.wait()  # Salvo: all threads rush check-then-extract at the same time
        return str(launcher._checkout(ref="main"))

    with ThreadPoolExecutor(max_workers=n) as pool:
        dests = list(pool.map(checkout, range(n)))

    assert len(set(dests)) == 1  # All land in the same checkout directory
    runs = tmp_path / "runs"
    # No tmp leftovers, no duplicate directories
    assert [d.name for d in runs.iterdir()] == [Path(dests[0]).name]
    params = YAML(typ="safe").load((Path(dests[0]) / "params.yaml").read_text(encoding="utf-8"))
    # Structure intact, single entry key
    assert isinstance(params["entry"], list) and params["entry"]
    assert (Path(dests[0]) / "fake_entry.py").is_file()  # The copy's content is complete


def test_read_params_concurrent_parses_cleanly(tmp_path) -> None:
    """Spec-0017/T5 addition: the ruamel YAML instance is not thread-safe → create a new instance for every parse.

    The old implementation shared a module-level singleton _yaml; concurrent load from parallel launches would scramble the parser's internal state (hit in a real production run).
    Barrier-synchronized volley: parse the same params.yaml concurrently and assert that all results come back intact and identical.
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
        barrier.wait()  # Volley: concurrent calls into the parser
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
    """Unknown JSON bypasses that are not reply should be accepted, instead of reporting "neither reply nor progress"."""
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
    """Teardown race regression: calling close() while a round of send is in flight (the reader thread is stuck in stdout.readline()) must not make the reader thread raise ValueError: I/O operation on closed file / AttributeError.

    _terminate must first kill the process, let the reader thread wind down via EOF and join it, and only then close the streams / clear _proc; the reversed order would race with the reader thread still stuck in readline() over the same stdout / _proc. Capture background thread exceptions with threading.excepthook.
    """
    import threading

    errors: list = []
    prev_hook = threading.excepthook
    # Any uncaught exception from a background thread lands in errors
    threading.excepthook = errors.append
    try:
        h = _launcher(tmp_path, _BLOCKING_ENTRY).launch("main")
        h.begin("x")
        kind, _ = h.poll(0.5)
        assert kind == "pending"  # Confirm the reader thread is stuck in readline() (in flight)
        reader = h._reader
        assert reader is not None
        # Teardown: must be clean — the reader thread exits via EOF, and the main thread closes the streams afterwards, so there is no concurrent access
        h.close()
        reader.join(timeout=5)
        assert not reader.is_alive()  # The reader thread exited naturally on EOF; no leak
    finally:
        threading.excepthook = prev_hook
    # The background reader thread never raised an exception throughout (a reversed-order implementation would land in the I/O closed file error here)
    assert errors == []


def test_early_exit_eof_raises(tmp_path) -> None:
    h = _launcher(tmp_path, _EARLY_EXIT_ENTRY).launch("main")
    try:
        with pytest.raises(RuntimeError):
            h.send("a")
    finally:
        h.close()


# Spec-0008/T1 v2: shared workspace — launch(workspace_dir=) injects the directory into the harness subprocess's SANDBOX_WORK_DIR.
def test_launch_injects_workspace_dir_as_sandbox_work_dir(tmp_path) -> None:
    h = _launcher(tmp_path, _ENV_ECHO_ENTRY).launch("main", workspace_dir="/shared/ws")
    try:
        assert h.send("x") == "/shared/ws"  # The subprocess sees the injected SANDBOX_WORK_DIR
    finally:
        h.close()


def test_launch_without_workspace_dir_leaves_sandbox_work_dir_unset(tmp_path, monkeypatch) -> None:
    # Isolate any possible leftovers from the host environment
    monkeypatch.delenv("SANDBOX_WORK_DIR", raising=False)
    # Not passed → not injected (degenerate case)
    h = _launcher(tmp_path, _ENV_ECHO_ENTRY).launch("main")
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
    """After a reply, poll can still reach the reply of subsequent queued work (main loop keep_waiting; Spec-0036)."""
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


# Help text: at checkout, read the full HELP.md and attach it to the handle.
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


# Progress bypass: multiple type=progress lines may precede the reply; last_progress is visible while poll is pending.
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
        # The first short poll is most likely still running → pending, but some progress may already have been read
        kind, val = h.poll(0.05)
        # Wait until the terminal state
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


# status/peek bypass-style control: emits status without ending the round; interleaved progress does not count as a reply.
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
        assert h.in_flight is True  # Bypass-style control does not end the round
        # The round can still be finished with a terminal-style control
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


# Pushing another message while in flight: the framework allows the write; this stub ignores the second message and still runs until the interrupt before ending.
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
    """Unified write: writing again while waiting is still legal; the soft awaiting flag is preserved (Spec-0036)."""
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
    """Two consecutive message writes require no intermediate fabricated round lock (Spec-0036)."""
    h = _launcher(tmp_path, _MIDFLIGHT_MSG_ENTRY).launch("main")
    try:
        h.write_message("first")
        h.write_message("second")  # No longer requires an intermediate reply
        assert h.in_flight is True
        assert h.control("interrupt").startswith("[interrupted]")
    finally:
        h.close()


def test_write_message_alias_begin_and_emit(tmp_path) -> None:
    """begin/emit_message are deprecated aliases of write_message."""
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
