"""Real process lifetimes at the frozen Harness boundary; no model calls."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from evaluation.harness.stdio import HarnessStdioSession

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux process ownership")


def _wait_for(path: Path) -> None:
    deadline = time.monotonic() + 5
    while not path.exists():
        if time.monotonic() >= deadline:
            raise AssertionError(f"Fixture did not become ready: {path}")
        time.sleep(0.01)


def _kill_recorded(directory: Path) -> None:
    for path in directory.glob("*.pid"):
        try:
            os.kill(int(path.read_text()), signal.SIGKILL)
        except ProcessLookupError:
            pass


def _fixture(directory: Path, reply: bool) -> Path:
    directory.mkdir()
    writer = directory / "writer.py"
    writer.write_text(
        "import os,time\nfrom pathlib import Path\n"
        f"Path({str(directory / 'writer.pid')!r}).write_text(str(os.getpid()))\n"
        "counter=0\nwhile True:\n"
        f" Path({str(directory / 'pulse')!r}).write_text(str(counter))\n"
        " counter+=1\n time.sleep(0.02)\n"
    )
    intermediary = directory / "intermediary.py"
    intermediary.write_text(
        "import subprocess,sys\n"
        f"subprocess.Popen([sys.executable,{str(writer)!r}],start_new_session=True,"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
    )
    fixture = directory / "fixture.py"
    fixture.write_text(
        "import subprocess,sys,os,time,json\nfrom pathlib import Path\n"
        f"Path({str(directory / 'harness.pid')!r}).write_text(str(os.getpid()))\n"
        f"subprocess.Popen([sys.executable,{str(intermediary)!r}],start_new_session=True,"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).wait()\n"
        "sys.stdin.readline()\n"
        + ("print(json.dumps({'type':'reply','text':'done'}),flush=True)\n" if reply else "")
        + "time.sleep(30)\n"
    )
    return fixture


@pytest.mark.parametrize("reply", [False, True])
def test_close_reaps_detached_orphan_and_preserves_other_process(tmp_path, reply):
    owned = tmp_path / "owned"
    fake = _fixture(owned, reply)
    other = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
    session = HarnessStdioSession([sys.executable, str(fake)], cwd=tmp_path)
    try:
        session.start()
        _wait_for(owned / "pulse")
        if reply:
            assert session.request("test", timeout=5).text == "done"
        else:
            with pytest.raises(TimeoutError):
                session.request("test", timeout=0.1)
        session.close(grace_seconds=0.05)
        pulse = (owned / "pulse").read_text()
        time.sleep(0.15)
        assert (owned / "pulse").read_text() == pulse
        assert not Path(f"/proc/{int((owned / 'writer.pid').read_text())}").exists()
        assert other.poll() is None
    finally:
        session.close(grace_seconds=0.05)
        _kill_recorded(owned)
        other.kill()
        other.wait()


def test_controller_death_stops_owned_harness_and_detached_children(tmp_path):
    owned = tmp_path / "owned"
    fake = _fixture(owned, False)
    controller = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from evaluation.harness.stdio import HarnessStdioSession;"
            f"s=HarnessStdioSession([{sys.executable!r},{str(fake)!r}],cwd={str(tmp_path)!r});"
            "s.request('test',timeout=30)",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for(owned / "pulse")
        controller.kill()
        controller.wait()
        deadline = time.monotonic() + 5
        while Path(f"/proc/{int((owned / 'writer.pid').read_text())}").exists():
            if time.monotonic() >= deadline:
                raise AssertionError("Detached writer survived controller death")
            time.sleep(0.01)
        pulse = (owned / "pulse").read_text()
        time.sleep(0.15)
        assert (owned / "pulse").read_text() == pulse
    finally:
        if controller.poll() is None:
            controller.kill()
            controller.wait()
        _kill_recorded(owned)
